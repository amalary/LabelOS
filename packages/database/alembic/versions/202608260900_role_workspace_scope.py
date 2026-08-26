"""role workspace scope

Revision ID: 202608260900
Revises: 202608250300
Create Date: 2026-08-26 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from labelos_database.bootstrap import seed_system_roles_and_capabilities

revision: str = "202608260900"
down_revision: str | None = "202608250300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("roles", sa.Column("workspace_id", sa.Uuid(), nullable=True))
    op.add_column("roles", sa.Column("name", sa.String(length=120), nullable=True))
    op.add_column(
        "roles",
        sa.Column(
            "is_system_role",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )

    op.execute(sa.text("""
            UPDATE roles
            SET
                name = display_name,
                is_system_role = system_role
            WHERE name IS NULL
            """))

    op.alter_column(
        "roles",
        "name",
        existing_type=sa.String(length=120),
        nullable=False,
    )
    op.create_foreign_key(
        op.f("fk_roles_workspace_id_organizations"),
        "roles",
        "organizations",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_roles_key", "roles", type_="unique")
    op.create_index(
        "uq_roles_system_key",
        "roles",
        ["key"],
        unique=True,
        postgresql_where=sa.text("workspace_id IS NULL"),
    )
    op.create_index(
        "uq_roles_workspace_id_key",
        "roles",
        ["workspace_id", "key"],
        unique=True,
        postgresql_where=sa.text("workspace_id IS NOT NULL"),
    )
    op.create_index("ix_roles_workspace_id", "roles", ["workspace_id"])
    op.create_index("ix_roles_workspace_id_key", "roles", ["workspace_id", "key"])
    op.create_index("ix_roles_is_system_role", "roles", ["is_system_role"])
    seed_system_roles_and_capabilities(op.get_bind())


def downgrade() -> None:
    op.drop_index("ix_roles_is_system_role", table_name="roles")
    op.drop_index("ix_roles_workspace_id_key", table_name="roles")
    op.drop_index("ix_roles_workspace_id", table_name="roles")
    op.drop_index("uq_roles_workspace_id_key", table_name="roles")
    op.drop_index("uq_roles_system_key", table_name="roles")
    op.create_unique_constraint("uq_roles_key", "roles", ["key"])
    op.drop_constraint(
        op.f("fk_roles_workspace_id_organizations"), "roles", type_="foreignkey"
    )
    op.drop_column("roles", "is_system_role")
    op.drop_column("roles", "name")
    op.drop_column("roles", "workspace_id")
