"""Reusable collection attempts, checkpoints and terminal outcomes.

Revision ID: 202610120400
Revises: 202610120300
"""

import sqlalchemy as sa
from alembic import op

revision = "202610120400"
down_revision = "202610120300"
branch_labels = None
depends_on = None

OLD_GUARDS = {
    "postgresql": [
        "CREATE FUNCTION collection_runs_insert_governance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.status != 'queued' THEN RAISE EXCEPTION 'Invalid or immutable governance history'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER collection_runs_insert_governance_guard BEFORE INSERT ON collection_runs FOR EACH ROW EXECUTE FUNCTION collection_runs_insert_governance_guard()",
        "CREATE FUNCTION collection_runs_update_governance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF (OLD.id IS DISTINCT FROM NEW.id OR OLD.organization_id IS DISTINCT FROM NEW.organization_id OR OLD.documentation_id IS DISTINCT FROM NEW.documentation_id OR OLD.run_key IS DISTINCT FROM NEW.run_key OR OLD.production IS DISTINCT FROM NEW.production OR OLD.created_at IS DISTINCT FROM NEW.created_at) OR NOT ((OLD.status = 'queued' AND NEW.status IN ('running', 'cancelled')) OR (OLD.status = 'running' AND NEW.status IN ('succeeded', 'failed', 'cancelled'))) OR (OLD.started_at IS NOT NULL AND OLD.started_at IS DISTINCT FROM NEW.started_at) THEN RAISE EXCEPTION 'Invalid or immutable governance history'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER collection_runs_update_governance_guard BEFORE UPDATE ON collection_runs FOR EACH ROW EXECUTE FUNCTION collection_runs_update_governance_guard()",
        "CREATE FUNCTION collection_runs_delete_governance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF 1 = 1 THEN RAISE EXCEPTION 'Invalid or immutable governance history'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER collection_runs_delete_governance_guard BEFORE DELETE ON collection_runs FOR EACH ROW EXECUTE FUNCTION collection_runs_delete_governance_guard()",
    ],
    "sqlite": [
        "CREATE TRIGGER collection_runs_insert_governance_guard BEFORE INSERT ON collection_runs WHEN NEW.status != 'queued' BEGIN SELECT RAISE(ABORT, 'Invalid or immutable governance history'); END",
        "CREATE TRIGGER collection_runs_update_governance_guard BEFORE UPDATE ON collection_runs WHEN (OLD.id IS NOT NEW.id OR OLD.organization_id IS NOT NEW.organization_id OR OLD.documentation_id IS NOT NEW.documentation_id OR OLD.run_key IS NOT NEW.run_key OR OLD.production IS NOT NEW.production OR OLD.created_at IS NOT NEW.created_at) OR NOT ((OLD.status = 'queued' AND NEW.status IN ('running', 'cancelled')) OR (OLD.status = 'running' AND NEW.status IN ('succeeded', 'failed', 'cancelled'))) OR (OLD.started_at IS NOT NULL AND OLD.started_at IS NOT NEW.started_at) BEGIN SELECT RAISE(ABORT, 'Invalid or immutable governance history'); END",
        "CREATE TRIGGER collection_runs_delete_governance_guard BEFORE DELETE ON collection_runs WHEN 1 = 1 BEGIN SELECT RAISE(ABORT, 'Invalid or immutable governance history'); END",
    ],
}

NEW_GUARDS = {
    "postgresql": [
        "CREATE FUNCTION collection_runs_insert_governance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.status != 'queued' OR NEW.progress_revision != 0 OR NEW.records_seen != 0 OR NEW.records_written != 0 OR NEW.records_rejected != 0 OR (NEW.retry_of_id IS NULL AND (NEW.attempt != 1 OR NEW.checkpoint IS NOT NULL)) OR (NEW.retry_of_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM collection_runs p WHERE p.id = NEW.retry_of_id AND p.organization_id = NEW.organization_id AND p.documentation_id = NEW.documentation_id AND p.production = NEW.production AND p.status IN ('failed', 'partially_completed') AND NEW.attempt = p.attempt + 1 AND NEW.max_attempts = p.max_attempts AND NOT (CAST(p.checkpoint AS TEXT) IS DISTINCT FROM CAST(NEW.checkpoint AS TEXT)))) THEN RAISE EXCEPTION 'Invalid or immutable governance history'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER collection_runs_insert_governance_guard BEFORE INSERT ON collection_runs FOR EACH ROW EXECUTE FUNCTION collection_runs_insert_governance_guard()",
        "CREATE FUNCTION collection_runs_update_governance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF (OLD.id IS DISTINCT FROM NEW.id OR OLD.organization_id IS DISTINCT FROM NEW.organization_id OR OLD.documentation_id IS DISTINCT FROM NEW.documentation_id OR OLD.run_key IS DISTINCT FROM NEW.run_key OR OLD.production IS DISTINCT FROM NEW.production OR OLD.created_at IS DISTINCT FROM NEW.created_at OR OLD.job_id IS DISTINCT FROM NEW.job_id OR OLD.retry_of_id IS DISTINCT FROM NEW.retry_of_id OR OLD.attempt IS DISTINCT FROM NEW.attempt OR OLD.max_attempts IS DISTINCT FROM NEW.max_attempts OR OLD.not_before IS DISTINCT FROM NEW.not_before) OR (NEW.records_seen < OLD.records_seen OR NEW.records_written < OLD.records_written OR NEW.records_rejected < OLD.records_rejected) OR (NEW.error_code IS NOT NULL AND NEW.error_code NOT IN ('provider_unavailable', 'rate_limited', 'access_denied', 'invalid_data', 'terms_changed', 'internal_error')) OR (NEW.status = 'partially_completed' AND NEW.records_written = 0) OR (OLD.started_at IS NOT NULL AND OLD.started_at IS DISTINCT FROM NEW.started_at) OR NOT ((OLD.status = 'queued' AND NEW.status IN ('running', 'cancelled') AND NEW.records_seen = 0 AND NEW.progress_revision = OLD.progress_revision AND NOT (CAST(OLD.checkpoint AS TEXT) IS DISTINCT FROM CAST(NEW.checkpoint AS TEXT)) AND (NEW.status != 'running' OR NEW.not_before IS NULL OR NEW.started_at >= NEW.not_before)) OR (OLD.status = 'running' AND NEW.status = 'running' AND NEW.progress_revision = OLD.progress_revision + 1) OR (OLD.status = 'running' AND NEW.status IN ('completed', 'succeeded', 'partially_completed', 'failed', 'cancelled') AND NEW.progress_revision = OLD.progress_revision AND NOT (CAST(OLD.checkpoint AS TEXT) IS DISTINCT FROM CAST(NEW.checkpoint AS TEXT)))) THEN RAISE EXCEPTION 'Invalid or immutable governance history'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER collection_runs_update_governance_guard BEFORE UPDATE ON collection_runs FOR EACH ROW EXECUTE FUNCTION collection_runs_update_governance_guard()",
        "CREATE FUNCTION collection_runs_delete_governance_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF 1 = 1 THEN RAISE EXCEPTION 'Invalid or immutable governance history'; END IF; RETURN NEW; END $$",
        "CREATE TRIGGER collection_runs_delete_governance_guard BEFORE DELETE ON collection_runs FOR EACH ROW EXECUTE FUNCTION collection_runs_delete_governance_guard()",
    ],
    "sqlite": [
        "CREATE TRIGGER collection_runs_insert_governance_guard BEFORE INSERT ON collection_runs WHEN NEW.status != 'queued' OR NEW.progress_revision != 0 OR NEW.records_seen != 0 OR NEW.records_written != 0 OR NEW.records_rejected != 0 OR (NEW.retry_of_id IS NULL AND (NEW.attempt != 1 OR NEW.checkpoint IS NOT NULL)) OR (NEW.retry_of_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM collection_runs p WHERE p.id = NEW.retry_of_id AND p.organization_id = NEW.organization_id AND p.documentation_id = NEW.documentation_id AND p.production = NEW.production AND p.status IN ('failed', 'partially_completed') AND NEW.attempt = p.attempt + 1 AND NEW.max_attempts = p.max_attempts AND NOT (CAST(p.checkpoint AS TEXT) IS NOT CAST(NEW.checkpoint AS TEXT)))) BEGIN SELECT RAISE(ABORT, 'Invalid or immutable governance history'); END",
        "CREATE TRIGGER collection_runs_update_governance_guard BEFORE UPDATE ON collection_runs WHEN (OLD.id IS NOT NEW.id OR OLD.organization_id IS NOT NEW.organization_id OR OLD.documentation_id IS NOT NEW.documentation_id OR OLD.run_key IS NOT NEW.run_key OR OLD.production IS NOT NEW.production OR OLD.created_at IS NOT NEW.created_at OR OLD.job_id IS NOT NEW.job_id OR OLD.retry_of_id IS NOT NEW.retry_of_id OR OLD.attempt IS NOT NEW.attempt OR OLD.max_attempts IS NOT NEW.max_attempts OR OLD.not_before IS NOT NEW.not_before) OR (NEW.records_seen < OLD.records_seen OR NEW.records_written < OLD.records_written OR NEW.records_rejected < OLD.records_rejected) OR (NEW.error_code IS NOT NULL AND NEW.error_code NOT IN ('provider_unavailable', 'rate_limited', 'access_denied', 'invalid_data', 'terms_changed', 'internal_error')) OR (NEW.status = 'partially_completed' AND NEW.records_written = 0) OR (OLD.started_at IS NOT NULL AND OLD.started_at IS NOT NEW.started_at) OR NOT ((OLD.status = 'queued' AND NEW.status IN ('running', 'cancelled') AND NEW.records_seen = 0 AND NEW.progress_revision = OLD.progress_revision AND NOT (CAST(OLD.checkpoint AS TEXT) IS NOT CAST(NEW.checkpoint AS TEXT)) AND (NEW.status != 'running' OR NEW.not_before IS NULL OR NEW.started_at >= NEW.not_before)) OR (OLD.status = 'running' AND NEW.status = 'running' AND NEW.progress_revision = OLD.progress_revision + 1) OR (OLD.status = 'running' AND NEW.status IN ('completed', 'succeeded', 'partially_completed', 'failed', 'cancelled') AND NEW.progress_revision = OLD.progress_revision AND NOT (CAST(OLD.checkpoint AS TEXT) IS NOT CAST(NEW.checkpoint AS TEXT)))) BEGIN SELECT RAISE(ABORT, 'Invalid or immutable governance history'); END",
        "CREATE TRIGGER collection_runs_delete_governance_guard BEFORE DELETE ON collection_runs WHEN 1 = 1 BEGIN SELECT RAISE(ABORT, 'Invalid or immutable governance history'); END",
    ],
}


def _guards(drop=False, *, old=False):
    dialect = op.get_bind().dialect.name
    if drop:
        for operation in ("insert", "update", "delete"):
            name = f"collection_runs_{operation}_governance_guard"
            suffix = " ON collection_runs" if dialect == "postgresql" else ""
            op.execute(f"DROP TRIGGER IF EXISTS {name}{suffix}")
            if dialect == "postgresql":
                op.execute(f"DROP FUNCTION IF EXISTS {name}()")
    else:
        for statement in (OLD_GUARDS if old else NEW_GUARDS)[dialect]:
            op.execute(statement)


def _constraints(batch, *, old=False):
    statuses = "'succeeded', 'failed', 'cancelled'"
    failure = "status = 'failed'"
    success = "status != 'failed'"
    if not old:
        statuses += ", 'completed', 'partially_completed'"
        failure = "status IN ('failed', 'partially_completed')"
        success = "status NOT IN ('failed', 'partially_completed')"
    for name in ("status", "status_timestamps", "failure_error"):
        batch.drop_constraint(op.f(f"ck_collection_runs_{name}"), type_="check")
    batch.create_check_constraint(
        op.f("ck_collection_runs_status"),
        f"status IN ('queued', 'running', {statuses})",
    )
    batch.create_check_constraint(
        op.f("ck_collection_runs_status_timestamps"),
        "(status = 'queued' AND started_at IS NULL AND completed_at IS NULL) "
        "OR (status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL) "
        f"OR (status IN ({statuses}) AND completed_at IS NOT NULL)",
    )
    batch.create_check_constraint(
        op.f("ck_collection_runs_failure_error"),
        f"({failure} AND error_code IS NOT NULL) OR ({success} AND error_code IS NULL)",
    )


def _defer_foreign_keys():
    if op.get_bind().dialect.name == "sqlite":
        # sqlite3 legacy transaction mode does not BEGIN for DDL. Keep the
        # deferral active across reflection, table copy, drop and rename.
        op.execute("SAVEPOINT collection_run_tracking")
        previous = op.get_bind().exec_driver_sql("PRAGMA defer_foreign_keys").scalar()
        op.execute("PRAGMA defer_foreign_keys=ON")
        return previous
    return None


def _restore_foreign_keys(previous):
    if previous is not None:
        if op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Collection migration violated foreign keys")
        op.execute(f"PRAGMA defer_foreign_keys={int(previous)}")
        op.execute("RELEASE SAVEPOINT collection_run_tracking")


def upgrade():
    deferred = _defer_foreign_keys()
    _guards(drop=True)
    with op.batch_alter_table("collection_runs") as batch:
        for column in (
            sa.Column("job_id", sa.Uuid(), nullable=True),
            sa.Column("retry_of_id", sa.Uuid(), nullable=True),
            sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("not_before", sa.DateTime(timezone=True), nullable=True),
            sa.Column("checkpoint", sa.JSON(none_as_null=True), nullable=True),
            sa.Column(
                "progress_revision", sa.Integer(), nullable=False, server_default="0"
            ),
        ):
            batch.add_column(column)
        batch.create_unique_constraint(
            "uq_collection_runs_retry_of_id", ["retry_of_id"]
        )
        batch.create_foreign_key(
            "fk_collection_runs_retry_of_id_collection_runs",
            "collection_runs",
            ["retry_of_id", "organization_id"],
            ["id", "organization_id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            op.f("ck_collection_runs_retry_metadata"),
            "attempt >= 1 AND attempt <= max_attempts AND max_attempts <= 20 AND progress_revision >= 0",
        )
        _constraints(batch)
    _guards()
    _restore_foreign_keys(deferred)


def downgrade():
    # Never silently discard attempt history or checkpoints on rollback.
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM collection_runs WHERE status IN ('completed', 'partially_completed') "
                "OR job_id IS NOT NULL OR retry_of_id IS NOT NULL OR checkpoint IS NOT NULL "
                "OR not_before IS NOT NULL OR attempt != 1 OR max_attempts != 3 OR progress_revision != 0 LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("Collection tracking history prevents downgrade")
    deferred = _defer_foreign_keys()
    _guards(drop=True)
    with op.batch_alter_table("collection_runs") as batch:
        batch.drop_constraint(
            "fk_collection_runs_retry_of_id_collection_runs", type_="foreignkey"
        )
        batch.drop_constraint("uq_collection_runs_retry_of_id", type_="unique")
        batch.drop_constraint(op.f("ck_collection_runs_retry_metadata"), type_="check")
        _constraints(batch, old=True)
        for column in (
            "job_id",
            "retry_of_id",
            "attempt",
            "max_attempts",
            "not_before",
            "checkpoint",
            "progress_revision",
        ):
            batch.drop_column(column)
    _guards(old=True)
    _restore_foreign_keys(deferred)
