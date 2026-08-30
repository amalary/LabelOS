"""workspace invites

Revision ID: 202608241800
Revises: 202608241700
Create Date: 2026-08-24 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608241800"
down_revision: str | None = "202608241700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token", sa.String(length=120), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("inviter_user_id", sa.Uuid(), nullable=True),
        sa.Column("invitee_email", sa.String(length=320), nullable=True),
        sa.Column("professional_roles", sa.JSON(), server_default="[]", nullable=False),
        sa.Column(
            "proposed_department_access",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("maximum_uses", sa.Integer(), nullable=True),
        sa.Column("use_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "status", sa.String(length=60), server_default="active", nullable=False
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
        sa.ForeignKeyConstraint(
            ["inviter_user_id"],
            ["users.id"],
            name=op.f("fk_workspace_invites_inviter_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_workspace_invites_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_invites")),
        sa.UniqueConstraint("token", name="uq_workspace_invites_token"),
    )
    op.create_index(
        "ix_workspace_invites_inviter_user_id",
        "workspace_invites",
        ["inviter_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_workspace_invites_invitee_email",
        "workspace_invites",
        ["invitee_email"],
        unique=False,
    )
    op.create_index(
        "ix_workspace_invites_organization_id",
        "workspace_invites",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_workspace_invites_status_expires_at",
        "workspace_invites",
        ["status", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_workspace_invites_token",
        "workspace_invites",
        ["token"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_workspace_invites_token", table_name="workspace_invites")
    op.drop_index(
        "ix_workspace_invites_status_expires_at", table_name="workspace_invites"
    )
    op.drop_index(
        "ix_workspace_invites_organization_id", table_name="workspace_invites"
    )
    op.drop_index("ix_workspace_invites_invitee_email", table_name="workspace_invites")
    op.drop_index(
        "ix_workspace_invites_inviter_user_id", table_name="workspace_invites"
    )
    op.drop_table("workspace_invites")
