"""strengthen workspace memberships

Revision ID: 202608241200
Revises: 202608031400
Create Date: 2026-08-24 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608241200"
down_revision: str | None = "202608031400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TYPE organization_membership_role ADD VALUE IF NOT EXISTS 'guest'"
        )

    workspace_permission = sa.Enum(
        "owner",
        "admin",
        "member",
        "guest",
        name="workspace_permission",
    )
    workspace_permission.create(bind, checkfirst=True)

    op.add_column(
        "organization_memberships",
        sa.Column(
            "workspace_permission",
            workspace_permission,
            server_default="member",
            nullable=False,
        ),
    )
    op.add_column(
        "organization_memberships",
        sa.Column(
            "professional_roles",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
    )
    op.add_column(
        "organization_memberships",
        sa.Column(
            "department_access",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
    )
    backfill_expression = """
        CASE
            WHEN role = 'owner' THEN 'owner'
            WHEN role = 'admin' THEN 'admin'
            WHEN role = 'member' THEN 'member'
            ELSE 'guest'
        END
    """
    if bind.dialect.name == "postgresql":
        op.execute(f"""
            UPDATE organization_memberships
            SET workspace_permission = ({backfill_expression})::workspace_permission
            """)
    else:
        op.execute(f"""
            UPDATE organization_memberships
            SET workspace_permission = {backfill_expression}
            """)


def downgrade() -> None:
    op.drop_column("organization_memberships", "department_access")
    op.drop_column("organization_memberships", "professional_roles")
    op.drop_column("organization_memberships", "workspace_permission")
    sa.Enum(name="workspace_permission").drop(op.get_bind(), checkfirst=True)
