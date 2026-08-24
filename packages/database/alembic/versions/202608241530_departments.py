"""departments

Revision ID: 202608241530
Revises: 202608241430
Create Date: 2026-08-24 15:30:00.000000

"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from labelos_database.departments import (
    DEFAULT_DEPARTMENTS,
    DEFAULT_ROLE_DEPARTMENT_ACCESS,
)

revision: str = "202608241530"
down_revision: str | None = "202608241430"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column(
            "access_sensitivity",
            sa.String(length=40),
            server_default="standard",
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_departments")),
        sa.UniqueConstraint("slug", name="uq_departments_slug"),
    )
    op.create_index("ix_departments_slug", "departments", ["slug"])
    op.create_index("ix_departments_is_active", "departments", ["is_active"])

    departments_table = sa.table(
        "departments",
        sa.column("id", sa.Uuid()),
        sa.column("slug", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("access_sensitivity", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        departments_table,
        [
            {
                "id": UUID(department.id),
                "slug": department.slug,
                "display_name": department.display_name,
                "description": department.description,
                "access_sensitivity": department.access_sensitivity.value,
                "is_active": True,
            }
            for department in DEFAULT_DEPARTMENTS
        ],
    )

    op.add_column(
        "professional_roles",
        sa.Column(
            "default_department_access",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
    )
    bind = op.get_bind()
    for role_slug, department_slugs in DEFAULT_ROLE_DEPARTMENT_ACCESS.items():
        bind.execute(
            sa.text("""
                UPDATE professional_roles
                SET default_department_access = :default_department_access
                WHERE slug = :slug
                """).bindparams(
                sa.bindparam("default_department_access", type_=sa.JSON()),
            ),
            {
                "slug": role_slug,
                "default_department_access": department_slugs,
            },
        )


def downgrade() -> None:
    op.drop_column("professional_roles", "default_department_access")
    op.drop_index("ix_departments_is_active", table_name="departments")
    op.drop_index("ix_departments_slug", table_name="departments")
    op.drop_table("departments")
