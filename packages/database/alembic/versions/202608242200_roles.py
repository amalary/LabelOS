"""roles

Revision ID: 202608242200
Revises: 202608242100
Create Date: 2026-08-24 22:00:00.000000

"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from alembic import op

revision: str = "202608242200"
down_revision: str | None = "202608242100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEFAULT_ROLES = (
    (
        "d6c9e57c-6f3d-5177-a5dd-da5c1e16a79f",
        "artist",
        "Artist",
        "Artist, performer, or creative act represented in a workspace.",
    ),
    (
        "c5e33d5a-ba69-530a-a91d-72870504c064",
        "manager",
        "Manager",
        "Artist, business, or project manager coordinating work across a workspace.",
    ),
    (
        "3daa23fa-9389-5204-be68-dabd8bfafc61",
        "producer",
        "Producer",
        "Producer responsible for recording, production, or creative direction.",
    ),
    (
        "06d05755-95af-5cfe-8f4e-8c84fd52dc29",
        "songwriter",
        "Songwriter",
        "Composer, lyricist, or writer contributing to musical works.",
    ),
    (
        "060f948c-f937-53d3-aa46-3c609b3b9cd8",
        "a&r",
        "A&R",
        "Artists and repertoire role focused on talent and creative development.",
    ),
    (
        "8c456426-c05d-53e4-a8f3-29ec55063cf5",
        "marketing",
        "Marketing",
        "Marketing role responsible for audience strategy, campaigns, and growth.",
    ),
    (
        "5683c4d1-99f3-59a0-b9d3-1bc932b68038",
        "release_operations",
        "Release Operations",
        "Operations role responsible for release readiness, delivery, and schedules.",
    ),
    (
        "cd1d3ae8-6458-558c-ac73-dea262b3b03d",
        "legal",
        "Legal",
        "Legal role responsible for contracts, rights, clearances, and compliance.",
    ),
    (
        "ed127f45-6845-5771-bd1a-eaee959185db",
        "finance",
        "Finance",
        "Finance role responsible for budgets, payments, accounting, and reporting.",
    ),
    (
        "9fe438d1-95f9-5bc8-89b8-9e09ad0637b4",
        "analytics",
        "Analytics",
        "Analytics role responsible for reporting, insights, and performance review.",
    ),
    (
        "28b2b159-f8bd-53ac-8b12-52bbd0bc998c",
        "executive",
        "Executive",
        "Executive leadership role responsible for strategy and decision-making.",
    ),
    (
        "76157317-6e0b-5a39-a9a4-abe5080fb36b",
        "administrator",
        "Administrator",
        "Workspace administration role responsible for settings and member operations.",
    ),
)

PROFESSIONAL_ROLE_KEY_ALIASES = {
    "management": "manager",
    "label_executive": "executive",
}


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column(
            "system_role", sa.Boolean(), server_default=sa.false(), nullable=False
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("key", name="uq_roles_key"),
    )
    op.create_index("ix_roles_key", "roles", ["key"])
    op.create_index("ix_roles_system_role", "roles", ["system_role"])

    roles_table = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("system_role", sa.Boolean()),
    )
    op.bulk_insert(
        roles_table,
        [
            {
                "id": UUID(role_id),
                "key": key,
                "display_name": display_name,
                "description": description,
                "system_role": True,
            }
            for role_id, key, display_name, description in DEFAULT_ROLES
        ],
    )

    op.create_table(
        "workspace_membership_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by", sa.Uuid(), nullable=True),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            sa.JSON(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by"],
            ["users.id"],
            name=op.f("fk_workspace_membership_roles_assigned_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_workspace_membership_roles_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["workspace_memberships.id"],
            name=op.f(
                "fk_workspace_membership_roles_membership_id_workspace_memberships"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_membership_roles")),
        sa.UniqueConstraint(
            "membership_id",
            "role_id",
            name="uq_workspace_membership_roles_membership_id_role_id",
        ),
    )
    op.create_index(
        "ix_workspace_membership_roles_membership_id",
        "workspace_membership_roles",
        ["membership_id"],
    )
    op.create_index(
        "ix_workspace_membership_roles_assigned_at",
        "workspace_membership_roles",
        ["assigned_at"],
    )
    op.create_index(
        "ix_workspace_membership_roles_assigned_by",
        "workspace_membership_roles",
        ["assigned_by"],
    )
    op.create_index(
        "ix_workspace_membership_roles_role_id",
        "workspace_membership_roles",
        ["role_id"],
    )

    _backfill_workspace_membership_roles()


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_membership_roles_role_id",
        table_name="workspace_membership_roles",
    )
    op.drop_index(
        "ix_workspace_membership_roles_assigned_by",
        table_name="workspace_membership_roles",
    )
    op.drop_index(
        "ix_workspace_membership_roles_assigned_at",
        table_name="workspace_membership_roles",
    )
    op.drop_index(
        "ix_workspace_membership_roles_membership_id",
        table_name="workspace_membership_roles",
    )
    op.drop_table("workspace_membership_roles")
    op.drop_index("ix_roles_system_role", table_name="roles")
    op.drop_index("ix_roles_key", table_name="roles")
    op.drop_table("roles")


def _backfill_workspace_membership_roles() -> None:
    bind = op.get_bind()
    role_ids_by_key = {
        row["key"]: row["id"]
        for row in bind.execute(sa.text("SELECT id, key FROM roles")).mappings()
    }
    professional_roles = bind.execute(
        sa.text("SELECT id, slug, display_name, description FROM professional_roles")
    ).mappings()

    professional_role_ids_by_id: dict[object, object] = {}
    for professional_role in professional_roles:
        role_key = PROFESSIONAL_ROLE_KEY_ALIASES.get(
            professional_role["slug"],
            professional_role["slug"],
        )
        role_id = role_ids_by_key.get(role_key)
        if role_id is None:
            role_id = uuid5(NAMESPACE_URL, f"labelos-role:{role_key}")
            bind.execute(
                sa.text("""
                    INSERT INTO roles (
                        id,
                        key,
                        display_name,
                        description,
                        system_role
                    )
                    VALUES (
                        :id,
                        :key,
                        :display_name,
                        :description,
                        false
                    )
                    """),
                {
                    "id": role_id,
                    "key": role_key,
                    "display_name": professional_role["display_name"],
                    "description": professional_role["description"],
                },
            )
            role_ids_by_key[role_key] = role_id
        professional_role_ids_by_id[professional_role["id"]] = role_id

    assignments = bind.execute(sa.text("""
            SELECT
                workspace_memberships.id AS workspace_membership_id,
                membership_professional_roles.professional_role_id AS professional_role_id
            FROM workspace_memberships
            JOIN membership_professional_roles
                ON membership_professional_roles.membership_id =
                    workspace_memberships.organization_membership_id
            WHERE membership_professional_roles.status = 'active'
            """)).mappings()
    seen: set[tuple[object, object]] = set()
    for assignment in assignments:
        role_id = professional_role_ids_by_id.get(assignment["professional_role_id"])
        if role_id is None:
            continue
        pair = (assignment["workspace_membership_id"], role_id)
        if pair in seen:
            continue
        seen.add(pair)
        bind.execute(
            sa.text("""
                INSERT INTO workspace_membership_roles (
                    id,
                    membership_id,
                    role_id
                )
                VALUES (
                    :id,
                    :workspace_membership_id,
                    :role_id
                )
                """),
            {
                "id": uuid5(
                    NAMESPACE_URL,
                    "labelos-workspace-membership-role:"
                    f"{assignment['workspace_membership_id']}:{role_id}",
                ),
                "workspace_membership_id": assignment["workspace_membership_id"],
                "role_id": role_id,
            },
        )
