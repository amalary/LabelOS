"""Keep provenance immutable and acyclic even for direct SQL writers."""

from sqlalchemy import DDL, event


def guard_statements(dialect):
    conditions = {
        "provenance_transformations": (
            "NEW.collection_run_id IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM collection_runs r WHERE r.id = NEW.collection_run_id "
            "AND r.organization_id = NEW.organization_id "
            "AND r.status IN ('running', 'completed', 'succeeded', 'partially_completed'))"
        ),
        "provenance_records": (
            "(NEW.collection_run_id IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM collection_runs r JOIN dataset_documentation d ON d.id = r.documentation_id "
            "WHERE r.id = NEW.collection_run_id AND r.organization_id = NEW.organization_id "
            "AND d.version_id = NEW.version_id "
            "AND r.status IN ('running', 'completed', 'succeeded', 'partially_completed'))) "
            "OR (NEW.transformation_id IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM provenance_transformations t WHERE t.id = NEW.transformation_id "
            "AND t.organization_id = NEW.organization_id AND t.version_id = NEW.version_id "
            "AND ((NEW.kind = 'normalized_artist' AND t.transformation_type IN ('normalize', 'merge')) "
            "OR (NEW.kind = 'observation' AND t.transformation_type = 'transform') "
            "OR (NEW.kind = 'derived_output' AND t.transformation_type = 'derive')))) "
            "OR (NEW.artist_id IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM artists a WHERE a.id = NEW.artist_id AND a.organization_id = NEW.organization_id)) "
            "OR (NEW.observation_id IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM analytics_observations a WHERE a.id = NEW.observation_id AND a.organization_id = NEW.organization_id))"
        ),
        # Strictly increasing immutable generations prohibit cycles, including
        # concurrent inserts. This does not depend on wall-clock ordering.
        "provenance_edges": (
            "NOT EXISTS (SELECT 1 FROM provenance_records i JOIN provenance_records o ON o.id = NEW.output_id "
            "WHERE i.id = NEW.input_id AND i.organization_id = NEW.organization_id "
            "AND o.organization_id = NEW.organization_id AND i.generation < o.generation)"
        ),
    }
    for table, condition in conditions.items():
        version_query = (
            "SELECT v.id FROM dataset_versions v JOIN provenance_records r "
            "ON r.version_id = v.id WHERE r.id = NEW.output_id"
            if table == "provenance_edges"
            else "SELECT v.id FROM dataset_versions v WHERE v.id = NEW.version_id"
        )
        condition = (
            f"({condition}) OR NOT EXISTS ({version_query} "
            "AND v.organization_id = NEW.organization_id AND v.state = 'draft')"
        )
        for operation, check in (
            ("insert", condition),
            ("update", "1 = 1"),
            ("delete", "1 = 1"),
        ):
            name = f"{table}_{operation}_provenance_guard"
            if dialect == "postgresql":
                lock = (
                    version_query.replace("SELECT v.id", "PERFORM v.id")
                    + " FOR UPDATE OF v; "
                    if operation == "insert"
                    else ""
                )
                yield f"CREATE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {lock}IF {check} THEN RAISE EXCEPTION 'Invalid or immutable provenance'; END IF; RETURN NEW; END $$"
                yield f"CREATE TRIGGER {name} BEFORE {operation.upper()} ON {table} FOR EACH ROW EXECUTE FUNCTION {name}()"
            else:
                yield f"CREATE TRIGGER {name} BEFORE {operation.upper()} ON {table} WHEN {check} BEGIN SELECT RAISE(ABORT, 'Invalid or immutable provenance'); END"


def register_provenance_guards(*tables):
    for dialect in ("sqlite", "postgresql"):
        for statement in guard_statements(dialect):
            table = next(
                t
                for t in tables
                if statement.startswith(
                    (f"CREATE FUNCTION {t.name}_", f"CREATE TRIGGER {t.name}_")
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
                    f"DROP FUNCTION IF EXISTS {table.name}_{operation}_provenance_guard()"
                ).execute_if(dialect="postgresql"),
            )
