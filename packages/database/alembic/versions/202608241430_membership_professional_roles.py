"""membership professional roles

Revision ID: 202608241430
Revises: 202608241330
Create Date: 2026-08-24 14:30:00.000000

"""

from collections.abc import Sequence
import json
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from alembic import op

revision: str = "202608241430"
down_revision: str | None = "202608241330"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "membership_professional_roles",
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("professional_role_id", sa.Uuid(), nullable=False),
        sa.Column(
            "is_primary", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "status", sa.String(length=60), server_default="active", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["organization_memberships.id"],
            name=op.f(
                "fk_membership_professional_roles_membership_id_"
                "organization_memberships"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["professional_role_id"],
            ["professional_roles.id"],
            name=op.f(
                "fk_membership_professional_roles_professional_role_id_"
                "professional_roles"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "membership_id",
            "professional_role_id",
            name=op.f("pk_membership_professional_roles"),
        ),
    )
    op.create_index(
        "ix_membership_professional_roles_membership_id",
        "membership_professional_roles",
        ["membership_id"],
    )
    op.create_index(
        "ix_membership_professional_roles_professional_role_id",
        "membership_professional_roles",
        ["professional_role_id"],
    )
    op.create_index(
        "ix_membership_professional_roles_status",
        "membership_professional_roles",
        ["status"],
    )

    _backfill_membership_professional_roles()
    op.drop_column("organization_memberships", "professional_roles")


def downgrade() -> None:
    op.add_column(
        "organization_memberships",
        sa.Column(
            "professional_roles",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
    )
    op.drop_index(
        "ix_membership_professional_roles_status",
        table_name="membership_professional_roles",
    )
    op.drop_index(
        "ix_membership_professional_roles_professional_role_id",
        table_name="membership_professional_roles",
    )
    op.drop_index(
        "ix_membership_professional_roles_membership_id",
        table_name="membership_professional_roles",
    )
    op.drop_table("membership_professional_roles")


def _backfill_membership_professional_roles() -> None:
    bind = op.get_bind()
    role_rows = bind.execute(
        sa.text("SELECT id, slug, display_name FROM professional_roles")
    ).mappings()
    roles_by_slug: dict[str, UUID] = {}
    roles_by_display_name: dict[str, UUID] = {}
    for row in role_rows:
        role_id = row["id"]
        roles_by_slug[row["slug"]] = role_id
        roles_by_display_name[row["display_name"].lower()] = role_id

    membership_rows = bind.execute(
        sa.text("SELECT id, professional_roles FROM organization_memberships")
    ).mappings()
    for membership in membership_rows:
        role_names = _role_names(membership["professional_roles"])
        for index, role_name in enumerate(role_names):
            role_id = _role_id_for_name(
                bind,
                role_name,
                roles_by_slug=roles_by_slug,
                roles_by_display_name=roles_by_display_name,
            )
            bind.execute(
                sa.text("""
                    INSERT INTO membership_professional_roles (
                        membership_id,
                        professional_role_id,
                        is_primary,
                        status
                    )
                    VALUES (
                        :membership_id,
                        :professional_role_id,
                        :is_primary,
                        'active'
                    )
                    """),
                {
                    "membership_id": membership["id"],
                    "professional_role_id": role_id,
                    "is_primary": index == 0,
                },
            )


def _role_id_for_name(
    bind,
    role_name: str,
    *,
    roles_by_slug: dict[str, UUID],
    roles_by_display_name: dict[str, UUID],
) -> UUID:
    slug = _professional_role_slug(role_name)
    role_id = roles_by_display_name.get(role_name.lower()) or roles_by_slug.get(slug)
    if role_id is not None:
        return role_id

    role_id = uuid5(NAMESPACE_URL, f"labelos-professional-role:{slug}")
    bind.execute(
        sa.text("""
            INSERT INTO professional_roles (
                id,
                slug,
                display_name,
                description,
                is_active
            )
            VALUES (
                :id,
                :slug,
                :display_name,
                :description,
                :is_active
            )
            """),
        {
            "id": role_id,
            "slug": slug,
            "display_name": role_name,
            "description": f"{role_name} professional role.",
            "is_active": True,
        },
    )
    roles_by_slug[slug] = role_id
    roles_by_display_name[role_name.lower()] = role_id
    return role_id


def _role_names(value: object) -> list[str]:
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
        role_name = item.strip()
        if not role_name or role_name in seen:
            continue
        normalized.append(role_name)
        seen.add(role_name)
    return normalized


def _professional_role_slug(value: str) -> str:
    slug = "".join(
        character.lower() if character.isalnum() or character == "&" else "_"
        for character in value.strip()
    ).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "other"
