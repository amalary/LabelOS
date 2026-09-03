"""marketing content capabilities

Revision ID: 202609031400
Revises: 202609031300
Create Date: 2026-09-03 14:00:00.000000

"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from alembic import op
from labelos_database.capabilities import CAPABILITY_REGISTRY
from labelos_database.roles import DEFAULT_ROLE_CAPABILITY_ASSOCIATIONS

revision: str = "202609031400"
down_revision: str | None = "202609031300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MARKETING_CONTENT_CAPABILITY_KEYS = (
    "marketing.content.view",
    "marketing.content.create",
    "marketing.content.edit",
    "marketing.content.archive",
    "marketing.content.submit_for_review",
    "marketing.content.approve",
)


def upgrade() -> None:
    bind = op.get_bind()
    definitions = {
        definition.key: definition
        for definition in CAPABILITY_REGISTRY
        if definition.key in MARKETING_CONTENT_CAPABILITY_KEYS
    }

    for capability_key in MARKETING_CONTENT_CAPABILITY_KEYS:
        definition = definitions[capability_key]
        existing_id = bind.execute(
            sa.text("SELECT id FROM capabilities WHERE key = :key"),
            {"key": definition.key},
        ).scalar_one_or_none()
        values = {
            "id": UUID(definition.id),
            "key": definition.key,
            "display_name": definition.display_name,
            "description": definition.description,
            "system_capability": definition.system_capability,
        }
        if existing_id is None:
            bind.execute(
                sa.text("""
                    INSERT INTO capabilities (
                        id,
                        key,
                        display_name,
                        description,
                        system_capability
                    )
                    VALUES (
                        :id,
                        :key,
                        :display_name,
                        :description,
                        :system_capability
                    )
                    """),
                values,
            )
        else:
            bind.execute(
                sa.text("""
                    UPDATE capabilities
                    SET
                        display_name = :display_name,
                        description = :description,
                        system_capability = :system_capability
                    WHERE id = :existing_id
                    """),
                {**values, "existing_id": existing_id},
            )

    roles_by_key = {row["key"]: row["id"] for row in bind.execute(sa.text("""
                SELECT id, key
                FROM roles
                WHERE workspace_id IS NULL
                    AND is_system_role IS TRUE
                """)).mappings()}
    capabilities_by_key = {
        row["key"]: row["id"]
        for row in bind.execute(
            sa.text("""
                SELECT id, key
                FROM capabilities
                WHERE key IN :keys
                """).bindparams(
                sa.bindparam(
                    "keys",
                    MARKETING_CONTENT_CAPABILITY_KEYS,
                    expanding=True,
                )
            )
        ).mappings()
    }

    for role_key, capability_keys in DEFAULT_ROLE_CAPABILITY_ASSOCIATIONS.items():
        role_id = roles_by_key.get(role_key)
        if role_id is None:
            continue
        for capability_key in capability_keys:
            if capability_key not in MARKETING_CONTENT_CAPABILITY_KEYS:
                continue
            capability_id = capabilities_by_key.get(capability_key)
            if capability_id is None:
                continue
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
                continue
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
                        f"labelos-role-capability:{role_key}:{capability_key}",
                    ),
                    "role_id": role_id,
                    "capability_id": capability_id,
                },
            )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("""
            DELETE FROM role_capabilities
            WHERE capability_id IN (
                SELECT id
                FROM capabilities
                WHERE key IN :keys
            )
                AND source = 'system_default'
            """).bindparams(
            sa.bindparam(
                "keys",
                MARKETING_CONTENT_CAPABILITY_KEYS,
                expanding=True,
            )
        )
    )
    bind.execute(
        sa.text("""
            DELETE FROM capabilities
            WHERE key IN :keys
                AND system_capability IS TRUE
            """).bindparams(
            sa.bindparam(
                "keys",
                MARKETING_CONTENT_CAPABILITY_KEYS,
                expanding=True,
            )
        )
    )
