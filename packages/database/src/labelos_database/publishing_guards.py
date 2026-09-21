"""Database enforcement for immutable delivery facts and serialized attempt starts.

Revisions freeze these statements; metadata-created tests use the same guards.
"""

from sqlalchemy import DDL, event

IMMUTABLE = (
    "id",
    "workspace_id",
    "scheduling_job_id",
    "marketing_content_item_id",
    "marketing_content_item_channel_id",
    "social_account_connection_id",
    "approval_request_id",
    "authorized_content_revision",
    "schedule_generation",
    "provider",
    "destination_identity",
    "receipt_id",
    "idempotency_key",
    "payload_schema_version",
    "payload_fingerprint",
    "canonical_envelope",
    "correlation_id",
    "created_at",
)


def guard_statements(dialect):
    distinct = "IS DISTINCT FROM" if dialect == "postgresql" else "IS NOT"
    changed = " OR ".join(f"OLD.{c} {distinct} NEW.{c}" for c in IMMUTABLE)
    checks = {
        "publications": {
            "INSERT": "NEW.status != 'pending' OR NEW.transition_version != 0 OR NEW.updated_at != NEW.created_at",
            "UPDATE": f"({changed}) OR OLD.status IN ('published', 'permanent_failure', 'cancelled') OR NEW.transition_version != OLD.transition_version + 1 OR NEW.updated_at < OLD.updated_at OR NOT ((OLD.status = 'pending' AND NEW.status IN ('processing', 'cancelled')) OR (OLD.status = 'retryable_failure' AND NEW.status IN ('retrying', 'cancelled')) OR (OLD.status IN ('processing', 'retrying') AND NEW.status IN ('published', 'retryable_failure', 'permanent_failure', 'manual_action_required')) OR (OLD.status = 'manual_action_required' AND NEW.status IN ('published', 'retryable_failure', 'permanent_failure')))",
            "DELETE": "1 = 1",
        },
        "publication_attempts": {
            "UPDATE": "1 = 1",
            "DELETE": "1 = 1",
            "INSERT": "NOT EXISTS (SELECT 1 FROM publications p WHERE p.id = NEW.publication_id AND p.workspace_id = NEW.workspace_id AND p.status IN ('pending', 'retryable_failure') AND NEW.started_at >= p.updated_at AND (p.status = 'pending' OR (p.retry_policy_version = 1 AND p.retry_disposition IN ('automatic', 'provider_delay') AND p.next_retry_at <= NEW.started_at AND p.retry_deadline_at > NEW.started_at AND NEW.number <= 5))) OR NEW.number != (SELECT count(*) + 1 FROM publication_attempts a WHERE a.publication_id = NEW.publication_id AND a.workspace_id = NEW.workspace_id) OR (NEW.number > 1 AND NOT EXISTS (SELECT 1 FROM publication_transitions t JOIN publication_attempts a ON a.id = t.attempt_id WHERE a.publication_id = NEW.publication_id AND a.workspace_id = NEW.workspace_id AND a.number = NEW.number - 1 AND t.outcome = 'retryable_failure' AND t.version = (SELECT max(x.version) FROM publication_transitions x WHERE x.publication_id = NEW.publication_id AND x.workspace_id = NEW.workspace_id)))",
        },
        "publication_transitions": {
            "UPDATE": "1 = 1",
            "DELETE": "1 = 1",
            "INSERT": "NOT EXISTS (SELECT 1 FROM publications p WHERE p.id = NEW.publication_id AND p.workspace_id = NEW.workspace_id AND p.transition_version = NEW.version AND p.status = NEW.to_status AND p.updated_at = NEW.occurred_at) OR NEW.version != (SELECT count(*) + 1 FROM publication_transitions t WHERE t.publication_id = NEW.publication_id AND t.workspace_id = NEW.workspace_id) OR (NEW.version = 1 AND NEW.from_status != 'pending') OR (NEW.version > 1 AND NOT EXISTS (SELECT 1 FROM publication_transitions t WHERE t.publication_id = NEW.publication_id AND t.workspace_id = NEW.workspace_id AND t.version = NEW.version - 1 AND t.to_status = NEW.from_status AND t.occurred_at <= NEW.occurred_at)) OR (NEW.attempt_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM publication_attempts a WHERE a.id = NEW.attempt_id AND a.publication_id = NEW.publication_id AND a.workspace_id = NEW.workspace_id AND a.number = (SELECT max(x.number) FROM publication_attempts x WHERE x.publication_id = NEW.publication_id AND x.workspace_id = NEW.workspace_id) AND ((NEW.operation IN ('start', 'retry') AND a.started_at = NEW.occurred_at) OR (NEW.outcome IS NOT NULL AND a.started_at <= NEW.observed_at)))) OR (NEW.observed_at IS NOT NULL AND NEW.version > 1 AND NEW.observed_at < (SELECT t.occurred_at FROM publication_transitions t WHERE t.publication_id = NEW.publication_id AND t.workspace_id = NEW.workspace_id AND t.version = NEW.version - 1))",
        },
    }
    # Human reservations exclude all future starts. Recovery grants are bound to
    # one failed transition and retain the original attempt/time budget.
    reserved = "EXISTS (SELECT 1 FROM publication_actions h WHERE h.publication_id = NEW.publication_id AND h.operation IN ('begin_manual', 'complete_manual') AND h.version = (SELECT max(x.version) FROM publication_actions x WHERE x.publication_id = h.publication_id))"
    grant = "EXISTS (SELECT 1 FROM publication_actions h WHERE h.publication_id = p.id AND h.publication_version = p.transition_version AND h.operation = 'authorize_retry' AND h.retry_until > NEW.started_at)"
    condition = checks["publication_attempts"]["INSERT"]
    condition = condition.replace(
        "p.retry_policy_version = 1 AND", "(p.retry_policy_version = 1 AND"
    )
    condition = condition.replace(
        "AND NEW.number <= 5)", f" OR {grant}) AND NEW.number <= 5)"
    )
    checks["publication_attempts"]["INSERT"] = f"({condition}) OR {reserved}"
    statements = []
    for table, operations in checks.items():
        for operation, condition in operations.items():
            name = f"{table}_{operation.lower()}_guard"
            if dialect == "postgresql":
                # Lock the aggregate before checking attempt order, even for direct SQL inserts.
                lock = (
                    "PERFORM 1 FROM publications WHERE id = NEW.publication_id AND workspace_id = NEW.workspace_id FOR UPDATE;"
                    if table != "publications" and operation == "INSERT"
                    else ""
                )
                statements.extend(
                    [
                        f"CREATE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {lock} IF {condition} THEN RAISE EXCEPTION 'Invalid or immutable publishing history'; END IF; RETURN NEW; END $$",
                        f"CREATE TRIGGER {name} BEFORE {operation} ON {table} FOR EACH ROW EXECUTE FUNCTION {name}()",
                    ]
                )
            else:
                statements.append(
                    f"CREATE TRIGGER {name} BEFORE {operation} ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT, 'Invalid or immutable publishing history'); END"
                )
    if dialect == "postgresql":
        statements.extend(
            [
                """CREATE FUNCTION publication_projection_guard() RETURNS trigger
            LANGUAGE plpgsql AS $$
            DECLARE p publications%ROWTYPE; t publication_transitions%ROWTYPE;
            BEGIN
              IF TG_TABLE_NAME = 'publications' THEN
                SELECT * INTO p FROM publications WHERE id = NEW.id;
              ELSE
                SELECT * INTO p FROM publications WHERE id = NEW.publication_id;
              END IF;
              IF p.transition_version != (SELECT count(*) FROM publication_transitions
                  WHERE publication_id = p.id AND workspace_id = p.workspace_id) THEN
                RAISE EXCEPTION 'Publication projection requires complete history';
              END IF;
              IF p.transition_version > 0 THEN
                SELECT * INTO t FROM publication_transitions
                  WHERE publication_id = p.id AND workspace_id = p.workspace_id
                  AND version = p.transition_version;
                IF t.id IS NULL OR t.to_status != p.status OR t.occurred_at != p.updated_at
                  OR p.failure_category IS DISTINCT FROM t.failure_category
                  OR p.retry_disposition IS DISTINCT FROM t.retry_disposition
                  OR p.next_retry_at IS DISTINCT FROM t.next_retry_at
                  OR p.retry_deadline_at IS DISTINCT FROM t.retry_deadline_at
                  OR p.retry_policy_version IS DISTINCT FROM t.retry_policy_version
                  OR (p.status = 'published' AND
                    (p.external_post_id IS DISTINCT FROM t.external_post_id
                     OR p.published_at IS DISTINCT FROM t.observed_at)) THEN
                  RAISE EXCEPTION 'Publication projection differs from history';
                END IF;
              END IF;
              IF EXISTS (SELECT 1 FROM publication_attempts a
                WHERE a.publication_id = p.id AND NOT EXISTS
                (SELECT 1 FROM publication_transitions h WHERE h.attempt_id = a.id
                 AND h.operation IN ('start', 'retry'))) THEN
                RAISE EXCEPTION 'Attempt requires committed start history';
              END IF;
              RETURN NULL;
            END $$""",
                *[
                    f"CREATE CONSTRAINT TRIGGER {table}_projection_guard AFTER INSERT OR UPDATE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION publication_projection_guard()"
                    for table in (
                        "publications",
                        "publication_attempts",
                        "publication_transitions",
                    )
                ],
            ]
        )
    return statements


def register_publishing_guards(*tables):
    # Every referenced table exists before installing the cross-table guards.
    for dialect in ("postgresql", "sqlite"):
        for statement in guard_statements(dialect):
            event.listen(
                tables[-1],
                "after_create",
                DDL(statement.replace("%", "%%")).execute_if(dialect=dialect),
            )
    for table in tables:
        for operation in ("insert", "update", "delete"):
            event.listen(
                table,
                "after_drop",
                DDL(
                    f"DROP FUNCTION IF EXISTS {table.name}_{operation}_guard()"
                ).execute_if(dialect="postgresql"),
            )

    event.listen(
        tables[0],
        "after_drop",
        DDL("DROP FUNCTION IF EXISTS publication_projection_guard()").execute_if(
            dialect="postgresql"
        ),
    )
