"""analytics idempotency fingerprint

Revision ID: 202608291700
Revises: 202608291600
Create Date: 2026-08-29 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608291700"
down_revision: str | None = "202608291600"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analytics_observations",
        sa.Column("idempotency_fingerprint", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analytics_observations", "idempotency_fingerprint")
