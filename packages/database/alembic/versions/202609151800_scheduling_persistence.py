"""Workspace-owned channel scheduling snapshots and retained transition history.

The actual head was rechecked as 202609151000 immediately before creation.
No historical scheduling intent is activated.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202609151800"
down_revision = "202609151000"
branch_labels = None
depends_on = None

_status = postgresql.ENUM(
    *("pending", "claimed", "blocked", "cancelled", "superseded", "handed_off"),
    name="scheduling_job_status",
    create_type=False,
    create_constraint=True,
)
_reason = postgresql.ENUM(
    *(
        "connection_unavailable",
        "reconnect_required",
        "capability_unavailable",
        "destination_mismatch",
        "manual_delivery_required",
        "stale_content_revision",
        "stale_approval",
        "changed_schedule_generation",
        "missing_durable_delivery_receiver",
        "missed_schedule_window",
        "ineligible_parent_state",
        "missing_schedule_intent",
        "handoff_contract_violation",
    ),
    name="scheduling_blocked_reason",
    create_type=False,
    create_constraint=True,
)


# Frozen guards: this revision never imports mutable application schema code.
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


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        _status.create(op.get_bind(), checkfirst=True)
        _reason.create(op.get_bind(), checkfirst=True)
    op.create_index(
        "uq_approval_requests_schedule_scope",
        "approval_requests",
        ["id", "organization_id", "resource_type", "resource_id", "resource_revision"],
        unique=True,
    )
    op.create_index(
        "uq_marketing_channels_schedule_scope",
        "marketing_content_item_channels",
        ["id", "marketing_content_item_id"],
        unique=True,
    )
    op.create_index(
        "uq_marketing_content_items_schedule_scope",
        "marketing_content_items",
        ["id", "organization_id"],
        unique=True,
    )
    op.create_index(
        "uq_social_accounts_schedule_scope",
        "social_account_connections",
        ["id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "scheduling_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("marketing_content_item_id", sa.Uuid(), nullable=False),
        sa.Column("marketing_content_item_channel_id", sa.Uuid(), nullable=False),
        sa.Column("social_account_connection_id", sa.Uuid(), nullable=True),
        sa.Column("approval_request_id", sa.Uuid(), nullable=False),
        sa.Column(
            "approval_resource_type",
            sa.String(length=120),
            server_default="marketing_content_item",
            nullable=False,
        ),
        sa.Column("authorized_content_revision", sa.Integer(), nullable=False),
        sa.Column("schedule_generation", sa.Integer(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schedule_timezone", sa.String(length=255), nullable=False),
        sa.Column("effective_artist_id", sa.Uuid(), nullable=True),
        sa.Column("status", _status, server_default="pending", nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("activation_operation_id", sa.Uuid(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by", sa.String(length=255), nullable=True),
        sa.Column("fencing_token", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "transition_version", sa.Integer(), server_default="1", nullable=False
        ),
        sa.Column("handed_off_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handoff_receipt_id", sa.Uuid(), nullable=True),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_reason_code", _reason, nullable=True),
        sa.Column("blocked_metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.String(length=120), nullable=True),
        sa.Column("supersedes_job_id", sa.Uuid(), nullable=True),
        sa.Column("lineage_root_job_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(cancelled_at IS NULL AND cancellation_reason IS NULL AND status != 'cancelled') OR (cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL AND length(trim(cancellation_reason)) > 0 AND status = 'cancelled')",
            name=op.f("ck_scheduling_jobs_cancellation"),
        ),
        sa.CheckConstraint(
            "(handed_off_at IS NULL AND handoff_receipt_id IS NULL AND status != 'handed_off') OR (handed_off_at IS NOT NULL AND handoff_receipt_id IS NOT NULL AND social_account_connection_id IS NOT NULL AND status = 'handed_off')",
            name=op.f("ck_scheduling_jobs_handoff_receipt"),
        ),
        sa.CheckConstraint(
            "approval_resource_type = 'marketing_content_item'",
            name=op.f("ck_scheduling_jobs_approval_type"),
        ),
        sa.CheckConstraint(
            "status != 'blocked' OR blocked_at IS NOT NULL",
            name=op.f("ck_scheduling_jobs_blocked_details"),
        ),
        sa.CheckConstraint(
            "status != 'claimed' OR claimed_at IS NOT NULL",
            name=op.f("ck_scheduling_jobs_claimed_lease"),
        ),
        sa.CheckConstraint(
            "(blocked_at IS NULL AND blocked_reason_code IS NULL) OR (blocked_at IS NOT NULL AND blocked_reason_code IS NOT NULL)",
            name=op.f("ck_scheduling_jobs_blocked_reason"),
        ),
        sa.CheckConstraint(
            "(claimed_at IS NULL AND claim_expires_at IS NULL AND claimed_by IS NULL) OR (claimed_at IS NOT NULL AND claim_expires_at IS NOT NULL AND claimed_by IS NOT NULL AND length(trim(claimed_by)) > 0 AND claim_expires_at > claimed_at AND fencing_token > 0)",
            name=op.f("ck_scheduling_jobs_lease"),
        ),
        sa.CheckConstraint(
            "(supersedes_job_id IS NULL AND lineage_root_job_id IS NULL) OR (supersedes_job_id IS NOT NULL AND lineage_root_job_id IS NOT NULL AND lineage_root_job_id != id)",
            name=op.f("ck_scheduling_jobs_lineage"),
        ),
        sa.CheckConstraint(
            "authorized_content_revision >= 1 AND schedule_generation >= 1 AND fencing_token >= 0 AND transition_version >= 1",
            name=op.f("ck_scheduling_jobs_counters"),
        ),
        sa.CheckConstraint(
            "length(trim(schedule_timezone)) > 0 AND length(trim(idempotency_key)) > 0",
            name=op.f("ck_scheduling_jobs_snapshot_text"),
        ),
        sa.CheckConstraint(
            "supersedes_job_id IS NULL OR supersedes_job_id != id",
            name=op.f("ck_scheduling_jobs_predecessor_not_self"),
        ),
        sa.ForeignKeyConstraint(
            [
                "approval_request_id",
                "workspace_id",
                "approval_resource_type",
                "marketing_content_item_id",
                "authorized_content_revision",
            ],
            [
                "approval_requests.id",
                "approval_requests.organization_id",
                "approval_requests.resource_type",
                "approval_requests.resource_id",
                "approval_requests.resource_revision",
            ],
            name="fk_scheduling_jobs_approval_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_scheduling_jobs_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["effective_artist_id"],
            ["artists.id"],
            name=op.f("fk_scheduling_jobs_effective_artist_id_artists"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lineage_root_job_id", "workspace_id", "marketing_content_item_id"],
            [
                "scheduling_jobs.id",
                "scheduling_jobs.workspace_id",
                "scheduling_jobs.marketing_content_item_id",
            ],
            name="fk_scheduling_jobs_lineage_root",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["marketing_content_item_channel_id", "marketing_content_item_id"],
            [
                "marketing_content_item_channels.id",
                "marketing_content_item_channels.marketing_content_item_id",
            ],
            name="fk_scheduling_jobs_channel_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["marketing_content_item_id", "workspace_id"],
            ["marketing_content_items.id", "marketing_content_items.organization_id"],
            name="fk_scheduling_jobs_content_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["social_account_connection_id", "workspace_id"],
            [
                "social_account_connections.id",
                "social_account_connections.organization_id",
            ],
            name="fk_scheduling_jobs_destination_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_job_id", "workspace_id", "marketing_content_item_id"],
            [
                "scheduling_jobs.id",
                "scheduling_jobs.workspace_id",
                "scheduling_jobs.marketing_content_item_id",
            ],
            name="fk_scheduling_jobs_predecessor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["organizations.id"],
            name=op.f("fk_scheduling_jobs_workspace_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduling_jobs")),
        sa.UniqueConstraint(
            "handoff_receipt_id", name="uq_scheduling_jobs_handoff_receipt"
        ),
        sa.UniqueConstraint(
            "id",
            "workspace_id",
            "marketing_content_item_id",
            name="uq_scheduling_jobs_lineage_scope",
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_scheduling_jobs_idempotency_key"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "activation_operation_id",
            name="uq_scheduling_jobs_activation_operation",
        ),
    )
    op.create_index(
        "ix_scheduling_jobs_approval",
        "scheduling_jobs",
        ["approval_request_id"],
        unique=False,
    )
    op.create_index(
        "ix_scheduling_jobs_channel_history",
        "scheduling_jobs",
        ["marketing_content_item_channel_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_scheduling_jobs_content",
        "scheduling_jobs",
        ["workspace_id", "marketing_content_item_id"],
        unique=False,
    )
    op.create_index(
        "ix_scheduling_jobs_destination",
        "scheduling_jobs",
        ["social_account_connection_id"],
        unique=False,
    )
    op.create_index(
        "ix_scheduling_jobs_due",
        "scheduling_jobs",
        ["scheduled_for", "id"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_scheduling_jobs_expired_claim",
        "scheduling_jobs",
        ["claim_expires_at", "id"],
        unique=False,
        postgresql_where=sa.text("status = 'claimed'"),
        sqlite_where=sa.text("status = 'claimed'"),
    )
    op.create_index(
        "ix_scheduling_jobs_workspace_list",
        "scheduling_jobs",
        ["workspace_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_scheduling_jobs_workspace_status_due",
        "scheduling_jobs",
        ["workspace_id", "status", "scheduled_for", "id"],
        unique=False,
    )
    op.create_index(
        "uq_scheduling_jobs_active_channel",
        "scheduling_jobs",
        ["marketing_content_item_channel_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'claimed', 'blocked')"),
        sqlite_where=sa.text("status IN ('pending', 'claimed', 'blocked')"),
    )
    op.create_index(
        "uq_scheduling_jobs_handed_off_intent",
        "scheduling_jobs",
        [
            "marketing_content_item_channel_id",
            "authorized_content_revision",
            "schedule_generation",
        ],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending', 'claimed', 'blocked', 'handed_off')"
        ),
        sqlite_where=sa.text(
            "status IN ('pending', 'claimed', 'blocked', 'handed_off')"
        ),
    )
    op.create_table(
        "scheduling_job_transitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("marketing_content_item_id", sa.Uuid(), nullable=False),
        sa.Column("transition_version", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=60), nullable=False),
        sa.Column("from_status", _status, nullable=True),
        sa.Column("to_status", _status, nullable=False),
        sa.Column("actor_kind", sa.String(length=60), nullable=False),
        sa.Column("actor_key", sa.String(length=255), nullable=False),
        sa.Column("reason_code", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(operation)) > 0 AND length(trim(actor_kind)) > 0 AND length(trim(actor_key)) > 0",
            name=op.f("ck_scheduling_job_transitions_audit_identity"),
        ),
        sa.CheckConstraint(
            "transition_version >= 1",
            name=op.f("ck_scheduling_job_transitions_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "workspace_id", "marketing_content_item_id"],
            [
                "scheduling_jobs.id",
                "scheduling_jobs.workspace_id",
                "scheduling_jobs.marketing_content_item_id",
            ],
            name="fk_scheduling_job_transitions_job_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduling_job_transitions")),
        sa.UniqueConstraint(
            "job_id", "transition_version", name="uq_scheduling_job_transitions_version"
        ),
    )
    op.create_index(
        "ix_scheduling_job_transitions_workspace",
        "scheduling_job_transitions",
        ["workspace_id", "created_at", "id"],
        unique=False,
    )
    for statement in guard_statements(op.get_bind().dialect.name):
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("scheduling_job_transitions")
    op.drop_table("scheduling_jobs")
    op.drop_index(
        "uq_social_accounts_schedule_scope", table_name="social_account_connections"
    )
    op.drop_index(
        "uq_marketing_content_items_schedule_scope",
        table_name="marketing_content_items",
    )
    op.drop_index(
        "uq_marketing_channels_schedule_scope",
        table_name="marketing_content_item_channels",
    )
    op.drop_index("uq_approval_requests_schedule_scope", table_name="approval_requests")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION scheduling_history_guard()")
        op.execute("DROP FUNCTION scheduling_job_guard()")
        _reason.drop(op.get_bind(), checkfirst=True)
        _status.drop(op.get_bind(), checkfirst=True)
