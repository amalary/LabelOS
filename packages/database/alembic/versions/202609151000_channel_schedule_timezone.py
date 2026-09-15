"""Explicit channel schedule authoring context; historical intent stays legacy."""

import sqlalchemy as sa
from alembic import op

revision: str = "202609151000"
down_revision: str | None = "202609061800"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "marketing_content_item_channels",
        sa.Column(
            "schedule_generation", sa.Integer(), server_default="1", nullable=False
        ),
    )
    op.add_column(
        "marketing_content_item_channels",
        sa.Column("schedule_timezone", sa.String(255), nullable=True),
    )
    op.add_column(
        "marketing_content_item_channels",
        sa.Column("schedule_local_time", sa.String(32), nullable=True),
    )
    op.add_column(
        "marketing_content_item_channels",
        sa.Column("schedule_offset_seconds", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("marketing_content_item_channels", "schedule_generation")
    op.drop_column("marketing_content_item_channels", "schedule_offset_seconds")
    op.drop_column("marketing_content_item_channels", "schedule_local_time")
    op.drop_column("marketing_content_item_channels", "schedule_timezone")
