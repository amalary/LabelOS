"""Database guards also installed for metadata-created test databases."""

from sqlalchemy import DDL, event


def guard_statements(dialect, *, versioning=True, collection_tracking=True):
    immutable = (
        "datasets",
        "dataset_versions",
        "dataset_documentation",
        "dataset_transformations",
        "dataset_lineage",
        "governance_activity",
    )
    checks = {table: {"UPDATE": "1 = 1", "DELETE": "1 = 1"} for table in immutable}
    distinct = "IS DISTINCT FROM" if dialect == "postgresql" else "IS NOT"
    fixed = (
        "id",
        "organization_id",
        "documentation_id",
        "run_key",
        "production",
        "created_at",
    )
    changed = " OR ".join(f"OLD.{c} {distinct} NEW.{c}" for c in fixed)
    checks["collection_runs"] = {
        "INSERT": "NEW.status != 'queued'",
        "UPDATE": f"({changed}) OR NOT ((OLD.status = 'queued' AND NEW.status IN ('running', 'cancelled')) OR (OLD.status = 'running' AND NEW.status IN ('succeeded', 'failed', 'cancelled'))) OR (OLD.started_at IS NOT NULL AND OLD.started_at {distinct} NEW.started_at)",
        "DELETE": "1 = 1",
    }
    if collection_tracking:
        checks["collection_runs"].update(collection_run_guards(dialect))
    # Ordering versions makes the lineage graph acyclic, including direct SQL writes.
    checks["dataset_lineage"][
        "INSERT"
    ] = "NOT EXISTS (SELECT 1 FROM dataset_transformations t JOIN dataset_versions o ON o.id = t.output_version_id JOIN dataset_versions i ON i.id = NEW.input_version_id WHERE t.id = NEW.transformation_id AND i.created_at < o.created_at)"
    locks = {}
    if versioning:
        version_checks, locks = version_guards(dialect)
        for table, operations in version_checks.items():
            checks[table].update(operations)
    statements = []
    for table, operations in checks.items():
        for operation, condition in operations.items():
            name = f"{table}_{operation.lower()}_governance_guard"
            if dialect == "postgresql":
                prelude = locks.get((table, operation), "")
                prelude = prelude + " " if prelude else ""
                statements.extend(
                    [
                        f"CREATE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {prelude}IF {condition} THEN RAISE EXCEPTION 'Invalid or immutable governance history'; END IF; RETURN NEW; END $$",
                        f"CREATE TRIGGER {name} BEFORE {operation} ON {table} FOR EACH ROW EXECUTE FUNCTION {name}()",
                    ]
                )
            else:
                statements.append(
                    f"CREATE TRIGGER {name} BEFORE {operation} ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT, 'Invalid or immutable governance history'); END"
                )
    return statements


def collection_run_guards(dialect):
    distinct = "IS DISTINCT FROM" if dialect == "postgresql" else "IS NOT"
    fixed = (
        "id",
        "organization_id",
        "documentation_id",
        "run_key",
        "production",
        "created_at",
        "job_id",
        "retry_of_id",
        "attempt",
        "max_attempts",
        "not_before",
    )
    changed = " OR ".join(f"OLD.{c} {distinct} NEW.{c}" for c in fixed)
    checkpoint_changed = (
        f"CAST(OLD.checkpoint AS TEXT) {distinct} CAST(NEW.checkpoint AS TEXT)"
    )
    monotonic = " OR ".join(
        f"NEW.{c} < OLD.{c}"
        for c in ("records_seen", "records_written", "records_rejected")
    )
    invalid_error = (
        "NEW.error_code IS NOT NULL AND NEW.error_code NOT IN "
        "('provider_unavailable', 'rate_limited', 'access_denied', 'invalid_data', "
        "'terms_changed', 'internal_error')"
    )
    return {
        "INSERT": (
            "NEW.status != 'queued' OR NEW.progress_revision != 0 "
            "OR NEW.records_seen != 0 OR NEW.records_written != 0 OR NEW.records_rejected != 0 "
            "OR (NEW.retry_of_id IS NULL AND (NEW.attempt != 1 OR NEW.checkpoint IS NOT NULL)) "
            "OR (NEW.retry_of_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM collection_runs p "
            "WHERE p.id = NEW.retry_of_id AND p.organization_id = NEW.organization_id "
            "AND p.documentation_id = NEW.documentation_id AND p.production = NEW.production "
            "AND p.status IN ('failed', 'partially_completed') AND NEW.attempt = p.attempt + 1 "
            "AND NEW.max_attempts = p.max_attempts "
            f"AND NOT (CAST(p.checkpoint AS TEXT) {distinct} CAST(NEW.checkpoint AS TEXT))))"
        ),
        "UPDATE": (
            f"({changed}) OR ({monotonic}) OR ({invalid_error}) "
            "OR (NEW.status = 'partially_completed' AND NEW.records_written = 0) "
            f"OR (OLD.started_at IS NOT NULL AND OLD.started_at {distinct} NEW.started_at) "
            "OR NOT ((OLD.status = 'queued' AND NEW.status IN ('running', 'cancelled') "
            "AND NEW.records_seen = 0 AND NEW.progress_revision = OLD.progress_revision "
            f"AND NOT ({checkpoint_changed}) "
            "AND (NEW.status != 'running' OR NEW.not_before IS NULL OR NEW.started_at >= NEW.not_before)) "
            "OR (OLD.status = 'running' AND NEW.status = 'running' "
            "AND NEW.progress_revision = OLD.progress_revision + 1) "
            "OR (OLD.status = 'running' AND NEW.status IN "
            "('completed', 'succeeded', 'partially_completed', 'failed', 'cancelled') "
            f"AND NEW.progress_revision = OLD.progress_revision AND NOT ({checkpoint_changed})))"
        ),
    }


def version_guards(dialect):
    """Freeze identity/content from creation; only lifecycle timestamps may advance.

    Lock the output version before appending provenance so finalization and direct
    SQL inserts serialize on PostgreSQL. SQLite serializes writers itself.
    """
    distinct = "IS DISTINCT FROM" if dialect == "postgresql" else "IS NOT"
    fixed = (
        "id",
        "organization_id",
        "dataset_id",
        "version_key",
        "created_at",
        "schema_version",
        "data_fingerprint",
        "collection_start",
        "collection_end",
        "source_references",
        "parent_version_id",
    )
    changed = " OR ".join(
        (
            f"CAST(OLD.{c} AS TEXT) {distinct} CAST(NEW.{c} AS TEXT)"
            if c == "source_references"
            else f"OLD.{c} {distinct} NEW.{c}"
        )
        for c in fixed
    )
    if dialect == "postgresql":
        bad_digest = "NEW.data_fingerprint !~ '^[a-f0-9]{64}$'"
        bad_sources = (
            "json_typeof(NEW.source_references) != 'array' "
            "OR json_array_length(NEW.source_references) NOT BETWEEN 1 AND 100 "
            "OR EXISTS (SELECT 1 FROM json_array_elements(NEW.source_references) e "
            "WHERE json_typeof(e) != 'string' OR length(trim(e #>> '{}')) NOT BETWEEN 1 AND 2000) "
            "OR (SELECT count(DISTINCT e #>> '{}') FROM json_array_elements(NEW.source_references) e) "
            "!= json_array_length(NEW.source_references)"
        )
    else:
        bad_digest = "length(NEW.data_fingerprint) != 64 OR NEW.data_fingerprint GLOB '*[^a-f0-9]*'"
        bad_sources = (
            "json_type(NEW.source_references) != 'array' "
            "OR json_array_length(NEW.source_references) NOT BETWEEN 1 AND 100 "
            "OR EXISTS (SELECT 1 FROM json_each(NEW.source_references) e "
            "WHERE e.type != 'text' OR length(trim(e.value)) NOT BETWEEN 1 AND 2000) "
            "OR (SELECT count(DISTINCT e.value) FROM json_each(NEW.source_references) e) "
            "!= json_array_length(NEW.source_references)"
        )
    invalid_metadata = (
        f"(NEW.schema_version IS NOT NULL AND length(trim(NEW.schema_version)) = 0) "
        f"OR (NEW.data_fingerprint IS NOT NULL AND ({bad_digest})) "
        "OR ((NEW.collection_start IS NULL) != (NEW.collection_end IS NULL)) "
        "OR NEW.collection_end < NEW.collection_start "
        f"OR (NEW.source_references IS NOT NULL AND ({bad_sources}))"
    )
    incomplete = " OR ".join(
        f"NEW.{c} IS NULL"
        for c in (
            "schema_version",
            "data_fingerprint",
            "collection_start",
            "collection_end",
            "source_references",
        )
    )
    checks = {
        "dataset_versions": {
            "INSERT": (
                "NEW.state != 'draft' OR NEW.finalized_at IS NOT NULL OR NEW.archived_at IS NOT NULL "
                f"OR ({invalid_metadata}) OR (NEW.parent_version_id IS NOT NULL AND NOT EXISTS "
                "(SELECT 1 FROM dataset_versions p WHERE p.id = NEW.parent_version_id "
                "AND p.dataset_id = NEW.dataset_id AND p.organization_id = NEW.organization_id "
                "AND p.state IN ('finalized', 'archived') AND p.created_at < NEW.created_at))"
            ),
            "UPDATE": (
                f"({changed}) OR NOT ((OLD.state = 'draft' AND NEW.state = 'finalized' "
                f"AND NOT ({incomplete}) AND NEW.finalized_at IS NOT NULL "
                "AND NEW.finalized_at >= NEW.created_at AND NEW.archived_at IS NULL) "
                "OR (OLD.state = 'finalized' AND NEW.state = 'archived' "
                f"AND NOT (OLD.finalized_at {distinct} NEW.finalized_at) "
                "AND NEW.archived_at IS NOT NULL AND NEW.archived_at >= NEW.finalized_at))"
            ),
        }
    }
    locks = {}
    for table, query in (
        (
            "dataset_documentation",
            "SELECT v.state FROM dataset_versions v WHERE v.id = NEW.version_id",
        ),
        (
            "dataset_transformations",
            "SELECT v.state FROM dataset_versions v WHERE v.id = NEW.output_version_id",
        ),
        (
            "dataset_lineage",
            "SELECT v.state FROM dataset_versions v JOIN dataset_transformations t ON t.output_version_id = v.id WHERE t.id = NEW.transformation_id",
        ),
    ):
        condition = f"NOT EXISTS ({query} AND v.organization_id = NEW.organization_id AND v.state = 'draft')"
        if table == "dataset_lineage":
            condition += " OR NOT EXISTS (SELECT 1 FROM dataset_transformations t JOIN dataset_versions o ON o.id = t.output_version_id JOIN dataset_versions i ON i.id = NEW.input_version_id WHERE t.id = NEW.transformation_id AND i.created_at < o.created_at)"
        checks[table] = {"INSERT": condition}
        locks[(table, "INSERT")] = (
            query.replace("SELECT v.state", "PERFORM v.id") + " FOR UPDATE OF v;"
        )
    return checks, locks


def register_governance_guards(*tables):
    for dialect in ("postgresql", "sqlite"):
        for statement in guard_statements(dialect):
            table = next(
                table
                for table in tables
                if statement.startswith(
                    (f"CREATE FUNCTION {table.name}_", f"CREATE TRIGGER {table.name}_")
                )
            )
            event.listen(
                table, "after_create", DDL(statement).execute_if(dialect=dialect)
            )
    for table in tables:
        for operation in ("insert", "update", "delete"):
            event.listen(
                table,
                "after_drop",
                DDL(
                    f"DROP FUNCTION IF EXISTS {table.name}_{operation}_governance_guard()"
                ).execute_if(dialect="postgresql"),
            )
