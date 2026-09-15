"""DDL guards shared by metadata-created test databases; revisions freeze the SQL."""

from sqlalchemy import DDL, event

SNAPSHOT_COLUMNS = (
    "id",
    "workspace_id",
    "marketing_content_item_id",
    "marketing_content_item_channel_id",
    "social_account_connection_id",
    "approval_request_id",
    "approval_resource_type",
    "authorized_content_revision",
    "schedule_generation",
    "scheduled_for",
    "schedule_timezone",
    "effective_artist_id",
    "idempotency_key",
    "activation_operation_id",
    "supersedes_job_id",
    "lineage_root_job_id",
    "created_by_user_id",
    "created_at",
)


def guard_statements(dialect: str) -> list[str]:
    if dialect == "postgresql":
        changed = " OR ".join(
            f"OLD.{c} IS DISTINCT FROM NEW.{c}" for c in SNAPSHOT_COLUMNS
        )
        return [
            f"""CREATE FUNCTION scheduling_job_guard() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Scheduling history cannot be deleted';
              END IF;
              IF OLD.status IN ('cancelled', 'superseded', 'handed_off') OR {changed} THEN
                RAISE EXCEPTION 'Scheduling snapshot or terminal history is immutable';
              END IF;
              IF NEW.fencing_token < OLD.fencing_token OR NEW.transition_version < OLD.transition_version THEN
                RAISE EXCEPTION 'Scheduling counters cannot decrease';
              END IF;
              RETURN NEW;
            END $$""",
            "CREATE TRIGGER scheduling_job_guard BEFORE UPDATE OR DELETE ON scheduling_jobs "
            "FOR EACH ROW EXECUTE FUNCTION scheduling_job_guard()",
            """CREATE FUNCTION scheduling_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'Scheduling transitions are append-only'; END $$""",
            "CREATE TRIGGER scheduling_history_guard BEFORE UPDATE OR DELETE ON scheduling_job_transitions "
            "FOR EACH ROW EXECUTE FUNCTION scheduling_history_guard()",
        ]
    changed = " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in SNAPSHOT_COLUMNS)
    return [
        "CREATE TRIGGER scheduling_job_no_delete BEFORE DELETE ON scheduling_jobs "
        "BEGIN SELECT RAISE(ABORT, 'Scheduling history cannot be deleted'); END",
        f"CREATE TRIGGER scheduling_job_guard BEFORE UPDATE ON scheduling_jobs "
        f"WHEN OLD.status IN ('cancelled', 'superseded', 'handed_off') OR {changed} "
        "OR NEW.fencing_token < OLD.fencing_token OR NEW.transition_version < OLD.transition_version "
        "BEGIN SELECT RAISE(ABORT, 'Scheduling snapshot, history or counters are immutable'); END",
        *[
            f"CREATE TRIGGER scheduling_history_no_{operation.lower()} BEFORE {operation} "
            "ON scheduling_job_transitions BEGIN "
            "SELECT RAISE(ABORT, 'Scheduling transitions are append-only'); END"
            for operation in ("UPDATE", "DELETE")
        ],
    ]


def register_scheduling_guards(job_table, transition_table) -> None:
    for dialect in ("postgresql", "sqlite"):
        statements = guard_statements(dialect)
        for statement in statements[:2]:
            event.listen(
                job_table, "after_create", DDL(statement).execute_if(dialect=dialect)
            )
        for statement in statements[2:]:
            event.listen(
                transition_table,
                "after_create",
                DDL(statement).execute_if(dialect=dialect),
            )
    event.listen(
        job_table,
        "after_drop",
        DDL("DROP FUNCTION IF EXISTS scheduling_job_guard()").execute_if(
            dialect="postgresql"
        ),
    )
    event.listen(
        transition_table,
        "after_drop",
        DDL("DROP FUNCTION IF EXISTS scheduling_history_guard()").execute_if(
            dialect="postgresql"
        ),
    )
