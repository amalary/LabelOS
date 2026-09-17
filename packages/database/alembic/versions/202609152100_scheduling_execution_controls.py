"""Fail-closed, transaction-coordinated scheduling execution controls.

Revision ID: 202609152100
Revises: 202609152000
"""

import sqlalchemy as sa
from alembic import op

revision = "202609152100"
down_revision = "202609152000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduling_execution_controls",
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "execution_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_table("scheduling_execution_controls")
