"""Dedicated human scheduling activation permission.

Revision ID: 202609152000
Revises: 202609151800
"""

from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision = "202609152000"
down_revision = "202609151800"
branch_labels = None
depends_on = None

KEY = "marketing.content.schedule"
capabilities = sa.table(
    "capabilities",
    sa.column("id", sa.Uuid()),
    sa.column("key", sa.String()),
    sa.column("display_name", sa.String()),
    sa.column("description", sa.String()),
    sa.column("system_capability", sa.Boolean()),
)
roles = sa.table(
    "roles",
    sa.column("id", sa.Uuid()),
    sa.column("key", sa.String()),
    sa.column("workspace_id", sa.Uuid()),
    sa.column("is_system_role", sa.Boolean()),
)
links = sa.table(
    "role_capabilities",
    sa.column("id", sa.Uuid()),
    sa.column("role_id", sa.Uuid()),
    sa.column("capability_id", sa.Uuid()),
    sa.column("source", sa.String()),
)


def upgrade() -> None:
    bind = op.get_bind()
    identifier = bind.scalar(
        sa.select(capabilities.c.id).where(capabilities.c.key == KEY)
    )
    if identifier is None:
        identifier = uuid5(NAMESPACE_URL, f"labelos-capability:{KEY}")
        bind.execute(
            capabilities.insert().values(
                id=identifier,
                key=KEY,
                display_name="Activate marketing schedules",
                description="Activate approved channel schedules without editing their intent.",
                system_capability=True,
            )
        )
    for role_id, role_key in bind.execute(
        sa.select(roles.c.id, roles.c.key).where(
            roles.c.workspace_id.is_(None),
            roles.c.is_system_role.is_(True),
            roles.c.key.in_(("owner", "admin", "manager", "marketing")),
        )
    ):
        existing = bind.scalar(
            sa.select(links.c.id).where(
                links.c.role_id == role_id,
                links.c.capability_id == identifier,
            )
        )
        if existing is None:
            bind.execute(
                links.insert().values(
                    id=uuid5(
                        NAMESPACE_URL, f"labelos-role-capability:{role_key}:{KEY}"
                    ),
                    role_id=role_id,
                    capability_id=identifier,
                    source="system_default",
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    identifiers = sa.select(capabilities.c.id).where(capabilities.c.key == KEY)
    bind.execute(links.delete().where(links.c.capability_id.in_(identifiers)))
    bind.execute(capabilities.delete().where(capabilities.c.key == KEY))
