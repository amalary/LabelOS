"""membership capability permissions

Revision ID: 202608241700
Revises: 202608241630
Create Date: 2026-08-24 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608241700"
down_revision: str | None = "202608241630"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organization_memberships",
        sa.Column(
            "capability_permissions",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("organization_memberships", "capability_permissions")
