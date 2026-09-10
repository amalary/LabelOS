"""scope social account external identity by connection method

Revision ID: 202609061500
Revises: 202609061300
Create Date: 2026-09-06 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202609061500"
down_revision: str | None = "202609061300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        "uq_social_account_connections_org_provider_external",
        table_name="social_account_connections",
    )
    op.create_index(
        "uq_social_account_connections_org_provider_external",
        "social_account_connections",
        ["organization_id", "provider", "connection_method", "external_account_id"],
        unique=True,
        postgresql_where=sa.text(
            "external_account_id IS NOT NULL AND status != 'disconnected'"
        ),
        sqlite_where=sa.text(
            "external_account_id IS NOT NULL AND status != 'disconnected'"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_social_account_connections_org_provider_external",
        table_name="social_account_connections",
    )
    op.create_index(
        "uq_social_account_connections_org_provider_external",
        "social_account_connections",
        ["organization_id", "provider", "external_account_id"],
        unique=True,
        postgresql_where=sa.text(
            "external_account_id IS NOT NULL AND status != 'disconnected'"
        ),
        sqlite_where=sa.text(
            "external_account_id IS NOT NULL AND status != 'disconnected'"
        ),
    )
