"""role department associations

Revision ID: 202608242300
Revises: 202608242200
Create Date: 2026-08-24 23:00:00.000000

"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op
from labelos_database.departments import DEFAULT_ROLE_DEPARTMENT_ASSOCIATIONS

revision: str = "202608242300"
down_revision: str | None = "202608242200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "role_departments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column(
            "access_level",
            sa.String(length=60),
            server_default="responsibility",
            nullable=False,
        ),
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
            name=op.f("fk_role_departments_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
            name=op.f("fk_role_departments_department_id_departments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_role_departments")),
        sa.UniqueConstraint(
            "role_id",
            "department_id",
            name="uq_role_departments_role_id_department_id",
        ),
    )
    op.create_index(
        "ix_role_departments_role_id",
        "role_departments",
        ["role_id"],
    )
    op.create_index(
        "ix_role_departments_department_id",
        "role_departments",
        ["department_id"],
    )
    op.create_index(
        "ix_role_departments_access_level",
        "role_departments",
        ["access_level"],
    )
    op.create_index(
        "ix_role_departments_source",
        "role_departments",
        ["source"],
    )
    _seed_role_departments()


def downgrade() -> None:
    op.drop_index("ix_role_departments_source", table_name="role_departments")
    op.drop_index("ix_role_departments_access_level", table_name="role_departments")
    op.drop_index("ix_role_departments_department_id", table_name="role_departments")
    op.drop_index("ix_role_departments_role_id", table_name="role_departments")
    op.drop_table("role_departments")


def _seed_role_departments() -> None:
    bind = op.get_bind()
    roles_by_key = {
        row["key"]: row["id"]
        for row in bind.execute(sa.text("SELECT id, key FROM roles")).mappings()
    }
    departments_by_slug = {
        row["slug"]: row["id"]
        for row in bind.execute(sa.text("SELECT id, slug FROM departments")).mappings()
    }

    for role_key, department_slugs in DEFAULT_ROLE_DEPARTMENT_ASSOCIATIONS.items():
        role_id = roles_by_key.get(role_key)
        if role_id is None:
            continue
        for department_slug in department_slugs:
            department_id = departments_by_slug.get(department_slug)
            if department_id is None:
                continue
            bind.execute(
                sa.text("""
                    INSERT INTO role_departments (
                        id,
                        role_id,
                        department_id
                    )
                    VALUES (
                        :id,
                        :role_id,
                        :department_id
                    )
                    """),
                {
                    "id": uuid5(
                        NAMESPACE_URL,
                        f"labelos-role-department:{role_key}:{department_slug}",
                    ),
                    "role_id": role_id,
                    "department_id": department_id,
                },
            )
