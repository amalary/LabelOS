"""campaign planning primitives

Revision ID: 202608271400
Revises: 202608271300
Create Date: 2026-08-27 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608271400"
down_revision: str | None = "202608271300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "campaign_goals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.String(length=4000), nullable=True),
        sa.Column("target_value", sa.String(length=500), nullable=True),
        sa.Column("success_criteria", sa.String(length=1000), nullable=True),
        sa.Column(
            "status",
            sa.String(length=60),
            server_default="active",
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_campaign_goals_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaign_goals")),
    )
    op.create_index(
        "ix_campaign_goals_campaign_id",
        "campaign_goals",
        ["campaign_id"],
    )
    op.create_index(
        "ix_campaign_goals_campaign_id_status",
        "campaign_goals",
        ["campaign_id", "status"],
    )

    op.create_table(
        "campaign_milestones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.String(length=4000), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=60),
            server_default="open",
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_campaign_milestones_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_campaign_milestones_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaign_milestones")),
    )
    op.create_index(
        "ix_campaign_milestones_campaign_id",
        "campaign_milestones",
        ["campaign_id"],
    )
    op.create_index(
        "ix_campaign_milestones_campaign_id_status",
        "campaign_milestones",
        ["campaign_id", "status"],
    )
    op.create_index(
        "ix_campaign_milestones_campaign_id_target_date",
        "campaign_milestones",
        ["campaign_id", "target_date"],
    )
    op.create_index(
        "ix_campaign_milestones_created_by_user_id",
        "campaign_milestones",
        ["created_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_campaign_milestones_created_by_user_id",
        table_name="campaign_milestones",
    )
    op.drop_index(
        "ix_campaign_milestones_campaign_id_target_date",
        table_name="campaign_milestones",
    )
    op.drop_index(
        "ix_campaign_milestones_campaign_id_status",
        table_name="campaign_milestones",
    )
    op.drop_index(
        "ix_campaign_milestones_campaign_id",
        table_name="campaign_milestones",
    )
    op.drop_table("campaign_milestones")
    op.drop_index("ix_campaign_goals_campaign_id_status", table_name="campaign_goals")
    op.drop_index("ix_campaign_goals_campaign_id", table_name="campaign_goals")
    op.drop_table("campaign_goals")
