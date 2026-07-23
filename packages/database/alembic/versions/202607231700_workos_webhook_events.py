"""workos webhook events

Revision ID: 202607231700
Revises: 202607231530
Create Date: 2026-07-23 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607231700"
down_revision: str | None = "202607231530"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("resource_type", sa.String(length=120), nullable=True),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("workos_event_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "processing_status",
            sa.String(length=60),
            server_default="processed",
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_events")),
        sa.UniqueConstraint(
            "provider",
            "event_id",
            name="uq_webhook_events_provider_id",
        ),
    )
    op.create_index(
        "ix_webhook_events_provider_event_id",
        "webhook_events",
        ["provider", "event_id"],
    )
    op.create_index(
        "ix_webhook_events_resource_created_at",
        "webhook_events",
        ["provider", "resource_type", "resource_id", "workos_event_created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_events_resource_created_at", table_name="webhook_events")
    op.drop_index("ix_webhook_events_provider_event_id", table_name="webhook_events")
    op.drop_table("webhook_events")
