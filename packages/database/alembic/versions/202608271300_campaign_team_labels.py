"""campaign team labels

Revision ID: 202608271300
Revises: 202608271200
Create Date: 2026-08-27 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608271300"
down_revision: str | None = "202608271200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaign_members",
        sa.Column("responsibility_label", sa.String(length=120), nullable=True),
    )
    op.create_index(
        "ix_campaign_members_responsibility_label",
        "campaign_members",
        ["responsibility_label"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_campaign_members_responsibility_label",
        table_name="campaign_members",
    )
    op.drop_column("campaign_members", "responsibility_label")
