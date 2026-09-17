"""Immutable human history and legal resolution edges, serialized on publication."""

from sqlalchemy import DDL, event


def action_guard_statements(dialect):
    previous = "(SELECT h.operation FROM publication_actions h WHERE h.publication_id = NEW.publication_id ORDER BY h.version DESC LIMIT 1)"
    deadline = (
        "NEW.retry_until <= a.started_at + interval '24 hours'"
        if dialect == "postgresql"
        else "julianday(NEW.retry_until) <= julianday(a.started_at, '+24 hours')"
    )
    invalid = f"""
      NEW.version != (SELECT count(*) + 1 FROM publication_actions WHERE publication_id = NEW.publication_id)
      OR NOT EXISTS (SELECT 1 FROM publications p WHERE p.id = NEW.publication_id
        AND p.workspace_id = NEW.workspace_id AND p.transition_version = NEW.publication_version
        AND p.status IN ('retryable_failure', 'permanent_failure') AND p.updated_at <= NEW.occurred_at)
      OR EXISTS (SELECT 1 FROM publication_leases l WHERE l.publication_id = NEW.publication_id
        AND (l.owner_id IS NOT NULL OR l.interrupted))
      OR EXISTS (SELECT 1 FROM publication_actions h WHERE h.publication_id = NEW.publication_id
        AND (h.operation = 'complete_manual' OR h.occurred_at > NEW.occurred_at))
      OR (NEW.operation = 'begin_manual' AND {previous} = 'begin_manual')
      OR (NEW.operation = 'complete_manual' AND COALESCE({previous}, '') != 'begin_manual')
      OR (NEW.operation = 'authorize_retry' AND (
        {previous} = 'begin_manual' OR
        EXISTS (SELECT 1 FROM publication_actions h WHERE h.publication_id = NEW.publication_id
          AND h.publication_version = NEW.publication_version AND h.operation = 'authorize_retry')
        OR NOT EXISTS (SELECT 1 FROM publications p WHERE p.id = NEW.publication_id
          AND p.status = 'retryable_failure' AND p.retry_disposition IN ('blocked_reconnection', 'manual_action'))
        OR (SELECT count(*) FROM publication_attempts WHERE publication_id = NEW.publication_id) >= 5
        OR NOT EXISTS (SELECT 1 FROM publication_attempts a WHERE a.publication_id = NEW.publication_id
          AND a.number = 1 AND {deadline})))
    """
    statements = []
    for operation, condition in (
        ("insert", invalid),
        ("update", "1 = 1"),
        ("delete", "1 = 1"),
    ):
        name = f"publication_actions_{operation}_guard"
        if dialect == "postgresql":
            lock = (
                "PERFORM 1 FROM publications WHERE id = NEW.publication_id FOR UPDATE;"
                if operation == "insert"
                else ""
            )
            statements.extend(
                [
                    f"CREATE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {lock} IF {condition} THEN RAISE EXCEPTION 'Invalid or immutable publication action'; END IF; RETURN NEW; END $$",
                    f"CREATE TRIGGER {name} BEFORE {operation.upper()} ON publication_actions FOR EACH ROW EXECUTE FUNCTION {name}()",
                ]
            )
        else:
            statements.append(
                f"CREATE TRIGGER {name} BEFORE {operation.upper()} ON publication_actions WHEN {condition} BEGIN SELECT RAISE(ABORT, 'Invalid or immutable publication action'); END"
            )
    return statements


def register_action_guards(table):
    for dialect in ("postgresql", "sqlite"):
        for statement in action_guard_statements(dialect):
            event.listen(
                table,
                "after_create",
                DDL(statement.replace("%", "%%")).execute_if(dialect=dialect),
            )
    for operation in ("insert", "update", "delete"):
        event.listen(
            table,
            "after_drop",
            DDL(
                f"DROP FUNCTION IF EXISTS publication_actions_{operation}_guard()"
            ).execute_if(dialect="postgresql"),
        )
