"""role capabilities

Revision ID: 202608250000
Revises: 202608242300
Create Date: 2026-08-25 00:00:00.000000

"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from alembic import op
from labelos_database.roles import (
    DEFAULT_CAPABILITIES,
    DEFAULT_ROLE_CAPABILITY_ASSOCIATIONS,
)

revision: str = "202608250000"
down_revision: str | None = "202608242300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "capabilities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column(
            "system_capability",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_capabilities")),
        sa.UniqueConstraint("key", name="uq_capabilities_key"),
    )
    op.create_index("ix_capabilities_key", "capabilities", ["key"])
    op.create_index(
        "ix_capabilities_system_capability",
        "capabilities",
        ["system_capability"],
    )

    _seed_capabilities()

    op.create_table(
        "role_capabilities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("capability_id", sa.Uuid(), nullable=False),
        sa.Column(
            "source",
            sa.String(length=60),
            server_default="system_default",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_role_capabilities_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["capability_id"],
            ["capabilities.id"],
            name=op.f("fk_role_capabilities_capability_id_capabilities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_role_capabilities")),
        sa.UniqueConstraint(
            "role_id",
            "capability_id",
            name="uq_role_capabilities_role_id_capability_id",
        ),
    )
    op.create_index("ix_role_capabilities_role_id", "role_capabilities", ["role_id"])
    op.create_index(
        "ix_role_capabilities_capability_id",
        "role_capabilities",
        ["capability_id"],
    )
    op.create_index("ix_role_capabilities_source", "role_capabilities", ["source"])
    _seed_role_capabilities()


def downgrade() -> None:
    op.drop_index("ix_role_capabilities_source", table_name="role_capabilities")
    op.drop_index("ix_role_capabilities_capability_id", table_name="role_capabilities")
    op.drop_index("ix_role_capabilities_role_id", table_name="role_capabilities")
    op.drop_table("role_capabilities")
    op.drop_index(
        "ix_capabilities_system_capability",
        table_name="capabilities",
    )
    op.drop_index("ix_capabilities_key", table_name="capabilities")
    op.drop_table("capabilities")


def _seed_role_capabilities() -> None:
    bind = op.get_bind()
    roles_by_key = {
        row["key"]: row["id"]
        for row in bind.execute(sa.text("SELECT id, key FROM roles")).mappings()
    }
    capabilities_by_key = {
        row["key"]: row["id"]
        for row in bind.execute(sa.text("SELECT id, key FROM capabilities")).mappings()
    }

    for role_key, capability_keys in DEFAULT_ROLE_CAPABILITY_ASSOCIATIONS.items():
        role_id = roles_by_key.get(role_key)
        if role_id is None:
            continue
        for capability_key in capability_keys:
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
                        capability_id
                    )
                    VALUES (
                        :id,
                        :role_id,
                        :capability_id
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


def _seed_capabilities() -> None:
    bind = op.get_bind()
    for capability in DEFAULT_CAPABILITIES:
        existing_id = bind.execute(
            sa.text("SELECT id FROM capabilities WHERE key = :key"),
            {"key": capability.key},
        ).scalar_one_or_none()
        values = {
            "id": UUID(capability.id),
            "key": capability.key,
            "display_name": capability.display_name,
            "description": capability.description,
            "system_capability": capability.system_capability,
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
