"""workos organization link

Revision ID: 202607221430
Revises: 202607171330
Create Date: 2026-07-22 14:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607221430"
down_revision: str | None = "202607171330"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("workos_organization_id", sa.String(length=255), nullable=True),
    )
    op.create_unique_constraint(
        op.f("uq_organizations_workos_organization_id"),
        "organizations",
        ["workos_organization_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("uq_organizations_workos_organization_id"),
        "organizations",
        type_="unique",
    )
    op.drop_column("organizations", "workos_organization_id")
