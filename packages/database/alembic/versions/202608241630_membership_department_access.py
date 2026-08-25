"""membership department access grants

Revision ID: 202608241630
Revises: 202608241530
Create Date: 2026-08-24 16:30:00.000000

"""

from collections.abc import Sequence
import json
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "202608241630"
down_revision: str | None = "202608241530"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "membership_department_access",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column(
            "access_level",
            sa.String(length=60),
            server_default="member",
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(length=60),
            server_default="role_default",
            nullable=False,
        ),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["organization_memberships.id"],
            name=op.f(
                "fk_membership_department_access_membership_id_"
                "organization_memberships"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
            name=op.f("fk_membership_department_access_department_id_departments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name=op.f("fk_membership_department_access_approved_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_membership_department_access")),
        sa.UniqueConstraint(
            "membership_id",
            "department_id",
            name="uq_membership_department_access_membership_id_department_id",
        ),
    )
    op.create_index(
        "ix_membership_department_access_membership_id",
        "membership_department_access",
        ["membership_id"],
    )
    op.create_index(
        "ix_membership_department_access_department_id",
        "membership_department_access",
        ["department_id"],
    )
    op.create_index(
        "ix_membership_department_access_access_level",
        "membership_department_access",
        ["access_level"],
    )
    op.create_index(
        "ix_membership_department_access_source",
        "membership_department_access",
        ["source"],
    )
    _backfill_approved_department_access()


def downgrade() -> None:
    op.drop_index(
        "ix_membership_department_access_source",
        table_name="membership_department_access",
    )
    op.drop_index(
        "ix_membership_department_access_access_level",
        table_name="membership_department_access",
    )
    op.drop_index(
        "ix_membership_department_access_department_id",
        table_name="membership_department_access",
    )
    op.drop_index(
        "ix_membership_department_access_membership_id",
        table_name="membership_department_access",
    )
    op.drop_table("membership_department_access")


def _backfill_approved_department_access() -> None:
    bind = op.get_bind()
    department_rows = bind.execute(
        sa.text("SELECT id, slug FROM departments")
    ).mappings()
    departments_by_slug = {
        department["slug"]: department["id"] for department in department_rows
    }
    membership_rows = bind.execute(
        sa.text("SELECT id, department_access FROM organization_memberships")
    ).mappings()
    for membership in membership_rows:
        for department_slug in _department_slugs(membership["department_access"]):
            department_id = departments_by_slug.get(department_slug)
            if department_id is None:
                continue
            bind.execute(
                sa.text("""
                    INSERT INTO membership_department_access (
                        id,
                        membership_id,
                        department_id,
                        access_level,
                        source,
                        approved_at
                    )
                    VALUES (
                        :id,
                        :membership_id,
                        :department_id,
                        'member',
                        'invitation',
                        CURRENT_TIMESTAMP
                    )
                    """),
                {
                    "id": uuid4(),
                    "membership_id": membership["id"],
                    "department_id": department_id,
                },
            )


def _department_slugs(value: object) -> list[str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
    else:
        parsed = value
    if not isinstance(parsed, list):
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        if not isinstance(item, str):
            continue
        department_slug = item.strip()
        if not department_slug or department_slug in seen:
            continue
        normalized.append(department_slug)
        seen.add(department_slug)
    return normalized
