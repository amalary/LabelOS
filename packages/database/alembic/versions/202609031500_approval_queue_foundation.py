"""approval queue foundation

Revision ID: 202609031500
Revises: 202609031400
Create Date: 2026-09-03 15:00:00.000000

Existing marketing content rows receive content_revision = 1. Rows already in
approved, scheduled, or published state receive approved_revision = 1 so the
current compatibility approval projection continues to mean "current revision
is approved." This migration does not manufacture approval_requests or
approval_decisions because legacy rows do not contain enough stage/decision
context for an accurate generic approval history.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609031500"
down_revision: str | None = "202609031400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


approval_request_status = postgresql.ENUM(
    "requested",
    "in_review",
    "changes_requested",
    "approved",
    "rejected",
    "cancelled",
    name="approval_request_status",
    create_type=False,
)

approval_stage_status = postgresql.ENUM(
    "pending",
    "in_review",
    "changes_requested",
    "approved",
    "rejected",
    "cancelled",
    "invalidated",
    name="approval_stage_status",
    create_type=False,
)

approval_decision_value = postgresql.ENUM(
    "submitted",
    "approved",
    "rejected",
    "changes_requested",
    "resubmitted",
    "invalidated",
    "cancelled",
    name="approval_decision_value",
    create_type=False,
)


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def upgrade() -> None:
    bind = op.get_bind()
    approval_request_status.create(bind, checkfirst=True)
    approval_stage_status.create(bind, checkfirst=True)
    approval_decision_value.create(bind, checkfirst=True)

    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(length=120), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column(
            "resource_revision",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "status",
            approval_request_status,
            server_default="requested",
            nullable=False,
        ),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by_profile_id", sa.Uuid(), nullable=True),
        sa.Column(
            "submitted_by_actor_kind",
            sa.String(length=60),
            server_default="user",
            nullable=False,
        ),
        sa.Column("submitted_by_actor_key", sa.String(length=255), nullable=True),
        sa.Column(
            "current_stage_order",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("summary", sa.String(length=4000), nullable=True),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "resource_revision >= 1",
            name=op.f("ck_approval_requests_resource_revision_positive"),
        ),
        sa.CheckConstraint(
            "current_stage_order >= 1",
            name=op.f("ck_approval_requests_current_stage_order_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_approval_requests_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_profile_id"],
            ["universal_profiles.id"],
            name=op.f(
                "fk_approval_requests_requested_by_profile_id_universal_profiles"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_approval_requests_requested_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_requests")),
    )
    op.create_index(
        "ix_approval_requests_organization_id",
        "approval_requests",
        ["organization_id"],
    )
    op.create_index(
        "ix_approval_requests_organization_id_status",
        "approval_requests",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_approval_requests_resource_lookup",
        "approval_requests",
        ["organization_id", "resource_type", "resource_id", "resource_revision"],
    )
    op.create_index(
        "ix_approval_requests_queue_order",
        "approval_requests",
        ["organization_id", "status", "submitted_at"],
    )
    op.create_index(
        "ix_approval_requests_requested_by_user",
        "approval_requests",
        ["organization_id", "requested_by_user_id"],
    )
    op.create_index(
        "ix_approval_requests_requested_by_profile",
        "approval_requests",
        ["organization_id", "requested_by_profile_id"],
    )
    op.create_index(
        "uq_approval_requests_active_resource_revision",
        "approval_requests",
        ["organization_id", "resource_type", "resource_id", "resource_revision"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('requested', 'in_review', 'changes_requested')"
        ),
        sqlite_where=sa.text(
            "status IN ('requested', 'in_review', 'changes_requested')"
        ),
    )

    op.create_table(
        "approval_request_stages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("approval_request_id", sa.Uuid(), nullable=False),
        sa.Column("stage_order", sa.Integer(), server_default="1", nullable=False),
        sa.Column("required_capability", sa.String(length=160), nullable=False),
        sa.Column(
            "status",
            approval_stage_status,
            server_default="pending",
            nullable=False,
        ),
        sa.Column("assigned_profile_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "stage_order >= 1",
            name=op.f("ck_approval_request_stages_stage_order_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["approval_request_id"],
            ["approval_requests.id"],
            name=op.f(
                "fk_approval_request_stages_approval_request_id_approval_requests"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_profile_id"],
            ["universal_profiles.id"],
            name=op.f(
                "fk_approval_request_stages_assigned_profile_id_universal_profiles"
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_request_stages")),
        sa.UniqueConstraint(
            "approval_request_id",
            "stage_order",
            name="uq_approval_request_stages_request_stage_order",
        ),
    )
    op.create_index(
        "ix_approval_request_stages_approval_request_id",
        "approval_request_stages",
        ["approval_request_id"],
    )
    op.create_index(
        "ix_approval_request_stages_request_status",
        "approval_request_stages",
        ["approval_request_id", "status"],
    )
    op.create_index(
        "ix_approval_request_stages_reviewer_queue",
        "approval_request_stages",
        ["assigned_profile_id", "status", "started_at"],
    )
    op.create_index(
        "ix_approval_request_stages_required_capability",
        "approval_request_stages",
        ["required_capability"],
    )

    op.create_table(
        "approval_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("approval_request_id", sa.Uuid(), nullable=False),
        sa.Column("stage_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("decision", approval_decision_value, nullable=False),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by_profile_id", sa.Uuid(), nullable=True),
        sa.Column("actor_kind", sa.String(length=60), nullable=False),
        sa.Column("actor_key", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.String(length=4000), nullable=True),
        sa.Column("payload", sa.JSON(), server_default="{}", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["approval_request_id"],
            ["approval_requests.id"],
            name=op.f("fk_approval_decisions_approval_request_id_approval_requests"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_profile_id"],
            ["universal_profiles.id"],
            name=op.f("fk_approval_decisions_decided_by_profile_id_universal_profiles"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            name=op.f("fk_approval_decisions_decided_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_approval_decisions_organization_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stage_id"],
            ["approval_request_stages.id"],
            name=op.f("fk_approval_decisions_stage_id_approval_request_stages"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_decisions")),
    )
    op.create_index(
        "ix_approval_decisions_organization_id",
        "approval_decisions",
        ["organization_id"],
    )
    op.create_index(
        "ix_approval_decisions_request_created",
        "approval_decisions",
        ["approval_request_id", "created_at"],
    )
    op.create_index(
        "ix_approval_decisions_stage_id",
        "approval_decisions",
        ["stage_id"],
    )
    op.create_index(
        "ix_approval_decisions_organization_decision",
        "approval_decisions",
        ["organization_id", "decision"],
    )
    op.create_index(
        "ix_approval_decisions_decided_by_user",
        "approval_decisions",
        ["organization_id", "decided_by_user_id"],
    )
    op.create_index(
        "ix_approval_decisions_decided_by_profile",
        "approval_decisions",
        ["organization_id", "decided_by_profile_id"],
    )

    op.add_column(
        "marketing_content_items",
        sa.Column(
            "content_revision",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
    )
    op.add_column(
        "marketing_content_items",
        sa.Column("approved_revision", sa.Integer(), nullable=True),
    )
    op.add_column(
        "marketing_content_items",
        sa.Column("approval_request_id", sa.Uuid(), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_marketing_content_items_content_revision_positive"),
        "marketing_content_items",
        "content_revision >= 1",
    )
    op.create_foreign_key(
        op.f("fk_marketing_content_items_approval_request_id_approval_requests"),
        "marketing_content_items",
        "approval_requests",
        ["approval_request_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_marketing_content_items_org_approval_request",
        "marketing_content_items",
        ["organization_id", "approval_request_id"],
    )
    bind.execute(sa.text("""
            UPDATE marketing_content_items
            SET approved_revision = 1
            WHERE status IN ('approved', 'scheduled', 'published')
        """))


def downgrade() -> None:
    op.drop_index(
        "ix_marketing_content_items_org_approval_request",
        table_name="marketing_content_items",
    )
    op.drop_constraint(
        op.f("fk_marketing_content_items_approval_request_id_approval_requests"),
        "marketing_content_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("ck_marketing_content_items_content_revision_positive"),
        "marketing_content_items",
        type_="check",
    )
    op.drop_column("marketing_content_items", "approval_request_id")
    op.drop_column("marketing_content_items", "approved_revision")
    op.drop_column("marketing_content_items", "content_revision")

    op.drop_index(
        "ix_approval_decisions_decided_by_profile",
        table_name="approval_decisions",
    )
    op.drop_index(
        "ix_approval_decisions_decided_by_user",
        table_name="approval_decisions",
    )
    op.drop_index(
        "ix_approval_decisions_organization_decision",
        table_name="approval_decisions",
    )
    op.drop_index("ix_approval_decisions_stage_id", table_name="approval_decisions")
    op.drop_index(
        "ix_approval_decisions_request_created",
        table_name="approval_decisions",
    )
    op.drop_index(
        "ix_approval_decisions_organization_id",
        table_name="approval_decisions",
    )
    op.drop_table("approval_decisions")

    op.drop_index(
        "ix_approval_request_stages_required_capability",
        table_name="approval_request_stages",
    )
    op.drop_index(
        "ix_approval_request_stages_reviewer_queue",
        table_name="approval_request_stages",
    )
    op.drop_index(
        "ix_approval_request_stages_request_status",
        table_name="approval_request_stages",
    )
    op.drop_index(
        "ix_approval_request_stages_approval_request_id",
        table_name="approval_request_stages",
    )
    op.drop_table("approval_request_stages")

    op.drop_index(
        "uq_approval_requests_active_resource_revision",
        table_name="approval_requests",
    )
    op.drop_index(
        "ix_approval_requests_requested_by_profile",
        table_name="approval_requests",
    )
    op.drop_index(
        "ix_approval_requests_requested_by_user",
        table_name="approval_requests",
    )
    op.drop_index("ix_approval_requests_queue_order", table_name="approval_requests")
    op.drop_index(
        "ix_approval_requests_resource_lookup",
        table_name="approval_requests",
    )
    op.drop_index(
        "ix_approval_requests_organization_id_status",
        table_name="approval_requests",
    )
    op.drop_index(
        "ix_approval_requests_organization_id",
        table_name="approval_requests",
    )
    op.drop_table("approval_requests")

    bind = op.get_bind()
    approval_decision_value.drop(bind, checkfirst=True)
    approval_stage_status.drop(bind, checkfirst=True)
    approval_request_status.drop(bind, checkfirst=True)
