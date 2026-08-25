"""workspace memberships

Revision ID: 202608242100
Revises: 202608242000
Create Date: 2026-08-24 21:00:00.000000

"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "202608242100"
down_revision: str | None = "202608242000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("organization_membership_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=60),
            server_default="active",
            nullable=False,
        ),
        sa.Column("invited_by", sa.Uuid(), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
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
            ["invited_by"],
            ["universal_profiles.id"],
            name=op.f("fk_workspace_memberships_invited_by_universal_profiles"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_membership_id"],
            ["organization_memberships.id"],
            name=op.f(
                "fk_workspace_memberships_organization_membership_id_organization_memberships"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["universal_profiles.id"],
            name=op.f("fk_workspace_memberships_profile_id_universal_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["organizations.id"],
            name=op.f("fk_workspace_memberships_workspace_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_memberships")),
        sa.UniqueConstraint(
            "organization_membership_id",
            name="uq_workspace_memberships_organization_membership_id",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "profile_id",
            name="uq_workspace_memberships_workspace_id_profile_id",
        ),
    )
    op.create_index(
        "ix_workspace_memberships_invited_by",
        "workspace_memberships",
        ["invited_by"],
        unique=False,
    )
    op.create_index(
        "ix_workspace_memberships_organization_membership_id",
        "workspace_memberships",
        ["organization_membership_id"],
        unique=False,
    )
    op.create_index(
        "ix_workspace_memberships_profile_id",
        "workspace_memberships",
        ["profile_id"],
        unique=False,
    )
    op.create_index(
        "ix_workspace_memberships_status",
        "workspace_memberships",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_workspace_memberships_workspace_id",
        "workspace_memberships",
        ["workspace_id"],
        unique=False,
    )
    _backfill_workspace_memberships()


def _backfill_workspace_memberships() -> None:
    connection = op.get_bind()
    now = datetime.now(UTC)

    users = connection.execute(sa.text("""
            SELECT id, email, first_name, last_name, display_name, profile_image_url
            FROM users
            """)).mappings()
    profile_user_ids = {
        row["user_id"]
        for row in connection.execute(
            sa.text("SELECT user_id FROM universal_profiles")
        ).mappings()
    }
    for user in users:
        if user["id"] in profile_user_ids:
            continue
        connection.execute(
            sa.text("""
                INSERT INTO universal_profiles (
                    id,
                    user_id,
                    display_name,
                    first_name,
                    last_name,
                    avatar_url,
                    primary_email,
                    profile_status,
                    onboarding_status,
                    created_at,
                    updated_at
                )
                VALUES (
                    :id,
                    :user_id,
                    :display_name,
                    :first_name,
                    :last_name,
                    :avatar_url,
                    :primary_email,
                    'active',
                    'not_started',
                    :created_at,
                    :updated_at
                )
                """),
            {
                "id": uuid4(),
                "user_id": user["id"],
                "display_name": user["display_name"],
                "first_name": user["first_name"],
                "last_name": user["last_name"],
                "avatar_url": user["profile_image_url"],
                "primary_email": user["email"],
                "created_at": now,
                "updated_at": now,
            },
        )

    profile_by_user_id = {
        row["user_id"]: row["id"]
        for row in connection.execute(
            sa.text("SELECT id, user_id FROM universal_profiles")
        ).mappings()
    }
    seen_pairs: set[tuple[object, object]] = set()
    memberships = connection.execute(sa.text("""
            SELECT id, organization_id, user_id, status
            FROM organization_memberships
            ORDER BY created_at ASC, id ASC
            """)).mappings()
    for membership in memberships:
        profile_id = profile_by_user_id.get(membership["user_id"])
        if profile_id is None:
            continue
        pair = (membership["organization_id"], profile_id)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        connection.execute(
            sa.text("""
                INSERT INTO workspace_memberships (
                    id,
                    workspace_id,
                    profile_id,
                    organization_membership_id,
                    status,
                    joined_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    :id,
                    :workspace_id,
                    :profile_id,
                    :organization_membership_id,
                    :status,
                    :joined_at,
                    :created_at,
                    :updated_at
                )
                """),
            {
                "id": uuid4(),
                "workspace_id": membership["organization_id"],
                "profile_id": profile_id,
                "organization_membership_id": membership["id"],
                "status": membership["status"],
                "joined_at": (
                    now if membership["status"] in {"active", "accepted"} else None
                ),
                "created_at": now,
                "updated_at": now,
            },
        )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_memberships_workspace_id", table_name="workspace_memberships"
    )
    op.drop_index("ix_workspace_memberships_status", table_name="workspace_memberships")
    op.drop_index(
        "ix_workspace_memberships_profile_id", table_name="workspace_memberships"
    )
    op.drop_index(
        "ix_workspace_memberships_organization_membership_id",
        table_name="workspace_memberships",
    )
    op.drop_index(
        "ix_workspace_memberships_invited_by", table_name="workspace_memberships"
    )
    op.drop_table("workspace_memberships")
