"""realtime events

Revision ID: 202608031400
Revises: 202607231700
Create Date: 2026-08-03 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608031400"
down_revision: str | None = "202607231700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "realtime_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=180), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=True),
        sa.Column("entity_id", sa.String(length=120), nullable=True),
        sa.Column("operation_id", sa.String(length=120), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_display_name", sa.String(length=200), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
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
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_realtime_events_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_realtime_events_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_realtime_events")),
        sa.UniqueConstraint("operation_id", name="uq_realtime_events_operation_id"),
    )
    op.create_index(
        "ix_realtime_events_organization_created",
        "realtime_events",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_realtime_events_channel_created",
        "realtime_events",
        ["channel", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_realtime_events_channel_created", table_name="realtime_events")
    op.drop_index(
        "ix_realtime_events_organization_created", table_name="realtime_events"
    )
    op.drop_table("realtime_events")
