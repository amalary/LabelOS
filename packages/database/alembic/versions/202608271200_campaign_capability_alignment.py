"""campaign capability alignment

Revision ID: 202608271200
Revises: 202608271100
Create Date: 2026-08-27 12:00:00.000000

"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision: str = "202608271200"
down_revision: str | None = "202608271100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    role_id = bind.execute(
        sa.text("""
            SELECT id
            FROM roles
            WHERE key = 'admin'
                AND workspace_id IS NULL
                AND is_system_role IS TRUE
            """)
    ).scalar_one_or_none()
    capability_id = bind.execute(
        sa.text("""
            SELECT id
            FROM capabilities
            WHERE key = 'marketing.campaign.approve'
            """)
    ).scalar_one_or_none()
    if role_id is None or capability_id is None:
        return

    existing_id = bind.execute(
        sa.text("""
            SELECT id
            FROM role_capabilities
            WHERE role_id = :role_id
                AND capability_id = :capability_id
            """),
        {"role_id": role_id, "capability_id": capability_id},
    ).scalar_one_or_none()
    if existing_id is not None:
        return

    bind.execute(
        sa.text("""
            INSERT INTO role_capabilities (
                id,
                role_id,
                capability_id,
                source
            )
            VALUES (
                :id,
                :role_id,
                :capability_id,
                'system_default'
            )
            """),
        {
            "id": uuid5(
                NAMESPACE_URL,
                "labelos-role-capability:admin:marketing.campaign.approve",
            ),
            "role_id": role_id,
            "capability_id": capability_id,
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    role_id = bind.execute(
        sa.text("""
            SELECT id
            FROM roles
            WHERE key = 'admin'
                AND workspace_id IS NULL
                AND is_system_role IS TRUE
            """)
    ).scalar_one_or_none()
    capability_id = bind.execute(
        sa.text("""
            SELECT id
            FROM capabilities
            WHERE key = 'marketing.campaign.approve'
            """)
    ).scalar_one_or_none()
    if role_id is None or capability_id is None:
        return
    bind.execute(
        sa.text("""
            DELETE FROM role_capabilities
            WHERE role_id = :role_id
                AND capability_id = :capability_id
                AND source = 'system_default'
            """),
        {"role_id": role_id, "capability_id": capability_id},
    )
