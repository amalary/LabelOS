"""workos user organization models

Revision ID: 202607231330
Revises: 202607221430
Create Date: 2026-07-23 13:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607231330"
down_revision: str | None = "202607221430"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("uq_users_email"), "users", type_="unique")
    op.add_column(
        "users",
        sa.Column("workos_user_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("first_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("last_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("profile_image_url", sa.String(length=2048), nullable=True),
    )
    op.create_unique_constraint(
        op.f("uq_users_workos_user_id"),
        "users",
        ["workos_user_id"],
    )
    op.create_index(
        "ix_users_workos_user_id",
        "users",
        ["workos_user_id"],
        unique=False,
    )

    op.create_index(
        "ix_organizations_workos_organization_id",
        "organizations",
        ["workos_organization_id"],
        unique=False,
    )

    op.add_column(
        "organization_memberships",
        sa.Column("workos_membership_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "organization_memberships",
        sa.Column(
            "status",
            sa.String(length=60),
            server_default="active",
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        op.f("uq_organization_memberships_workos_membership_id"),
        "organization_memberships",
        ["workos_membership_id"],
    )
    op.create_index(
        "ix_organization_memberships_workos_membership_id",
        "organization_memberships",
        ["workos_membership_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_organization_memberships_workos_membership_id",
        table_name="organization_memberships",
    )
    op.drop_constraint(
        op.f("uq_organization_memberships_workos_membership_id"),
        "organization_memberships",
        type_="unique",
    )
    op.drop_column("organization_memberships", "status")
    op.drop_column("organization_memberships", "workos_membership_id")
    op.drop_index(
        "ix_organizations_workos_organization_id",
        table_name="organizations",
    )
    op.drop_index("ix_users_workos_user_id", table_name="users")
    op.drop_constraint(op.f("uq_users_workos_user_id"), "users", type_="unique")
    op.drop_column("users", "profile_image_url")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
    op.drop_column("users", "workos_user_id")
    op.create_unique_constraint(op.f("uq_users_email"), "users", ["email"])
