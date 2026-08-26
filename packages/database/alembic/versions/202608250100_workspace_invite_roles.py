"""workspace invite roles

Revision ID: 202608250100
Revises: 202608250000
Create Date: 2026-08-25 01:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608250100"
down_revision: str | None = "202608250000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace_invites",
        sa.Column("workspace_roles", sa.JSON(), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("workspace_invites", "workspace_roles")
