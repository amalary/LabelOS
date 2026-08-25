"""professional roles

Revision ID: 202608241330
Revises: 202608241200
Create Date: 2026-08-24 13:30:00.000000

"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "202608241330"
down_revision: str | None = "202608241200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PROFESSIONAL_ROLES = (
    (
        "f2dc8c9b-b598-5554-bd4d-f503f7b623f5",
        "artist",
        "Artist",
        "Recording artist, performer, or creative act represented in LabelOS.",
    ),
    (
        "a313d0c3-0efb-5cc6-a716-58fa13552533",
        "producer",
        "Producer",
        "Music producer responsible for recording, production, or creative direction.",
    ),
    (
        "7d69d0bb-9349-5e58-9ea0-e9aac9e9e8b7",
        "songwriter",
        "Songwriter",
        "Composer, lyricist, or writer contributing to musical works.",
    ),
    (
        "7a8cc506-bb58-5507-8a9a-0c7ead60e28b",
        "management",
        "Management",
        "Artist or business management responsible for representation and "
        "coordination.",
    ),
    (
        "2ab36064-8195-5024-8feb-5f25bec8b3fd",
        "a&r",
        "A&R",
        "Artists and repertoire role focused on talent discovery and creative "
        "development.",
    ),
    (
        "2655f8f2-dcfa-5c53-89b8-f2f743368f51",
        "legal",
        "Legal",
        "Legal counsel or operations responsible for contracts, rights, and "
        "compliance.",
    ),
    (
        "f399533a-51e2-5e63-8a79-4363d6c97f2b",
        "marketing",
        "Marketing",
        "Marketing role responsible for audience strategy, campaigns, and growth.",
    ),
    (
        "bda1c3ea-acbf-5a59-a97c-6846c7f3305a",
        "publicity",
        "Publicity",
        "Public relations role responsible for press, media, and public "
        "communications.",
    ),
    (
        "a74fe737-0628-57f2-b0d3-f2ca4c6846c9",
        "finance",
        "Finance",
        "Finance role responsible for budgets, payments, accounting, and reporting.",
    ),
    (
        "fd43012b-84ee-59a7-a1ad-dc6da889d484",
        "label_executive",
        "Label Executive",
        "Executive leadership role responsible for label strategy and decision-making.",
    ),
    (
        "ed92e30f-0fb7-54f6-a0af-42c4d26e316c",
        "other",
        "Other",
        "Professional role not covered by the standard LabelOS role catalog.",
    ),
)


def upgrade() -> None:
    op.create_table(
        "professional_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_professional_roles")),
        sa.UniqueConstraint("slug", name="uq_professional_roles_slug"),
    )
    op.create_index(
        "ix_professional_roles_slug",
        "professional_roles",
        ["slug"],
    )
    op.create_index(
        "ix_professional_roles_is_active",
        "professional_roles",
        ["is_active"],
    )

    roles_table = sa.table(
        "professional_roles",
        sa.column("id", sa.Uuid()),
        sa.column("slug", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        roles_table,
        [
            {
                "id": UUID(role_id),
                "slug": slug,
                "display_name": display_name,
                "description": description,
                "is_active": True,
            }
            for role_id, slug, display_name, description in PROFESSIONAL_ROLES
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_professional_roles_is_active", table_name="professional_roles")
    op.drop_index("ix_professional_roles_slug", table_name="professional_roles")
    op.drop_table("professional_roles")
