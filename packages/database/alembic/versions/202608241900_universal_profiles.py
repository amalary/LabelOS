"""universal profiles

Revision ID: 202608241900
Revises: 202608241800
Create Date: 2026-08-24 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608241900"
down_revision: str | None = "202608241800"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "universal_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("first_name", sa.String(length=120), nullable=True),
        sa.Column("last_name", sa.String(length=120), nullable=True),
        sa.Column("slug", sa.String(length=120), nullable=True),
        sa.Column("headline", sa.String(length=240), nullable=True),
        sa.Column("biography", sa.String(length=4000), nullable=True),
        sa.Column("avatar_url", sa.String(length=2048), nullable=True),
        sa.Column("location", sa.String(length=240), nullable=True),
        sa.Column("timezone", sa.String(length=120), nullable=True),
        sa.Column("primary_email", sa.String(length=320), nullable=True),
        sa.Column(
            "profile_status",
            sa.String(length=60),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "onboarding_status",
            sa.String(length=60),
            server_default="not_started",
            nullable=False,
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
            ["user_id"],
            ["users.id"],
            name=op.f("fk_universal_profiles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_universal_profiles")),
        sa.UniqueConstraint("slug", name="uq_universal_profiles_slug"),
        sa.UniqueConstraint("user_id", name="uq_universal_profiles_user_id"),
    )
    op.create_index(
        "ix_universal_profiles_display_name",
        "universal_profiles",
        ["display_name"],
        unique=False,
    )
    op.create_index(
        "ix_universal_profiles_onboarding_status",
        "universal_profiles",
        ["onboarding_status"],
        unique=False,
    )
    op.create_index(
        "ix_universal_profiles_primary_email",
        "universal_profiles",
        ["primary_email"],
        unique=False,
    )
    op.create_index(
        "ix_universal_profiles_profile_status",
        "universal_profiles",
        ["profile_status"],
        unique=False,
    )
    op.create_index(
        "ix_universal_profiles_slug",
        "universal_profiles",
        ["slug"],
        unique=False,
    )
    op.create_index(
        "ix_universal_profiles_user_id",
        "universal_profiles",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_universal_profiles_user_id", table_name="universal_profiles")
    op.drop_index("ix_universal_profiles_slug", table_name="universal_profiles")
    op.drop_index(
        "ix_universal_profiles_profile_status", table_name="universal_profiles"
    )
    op.drop_index(
        "ix_universal_profiles_primary_email", table_name="universal_profiles"
    )
    op.drop_index(
        "ix_universal_profiles_onboarding_status", table_name="universal_profiles"
    )
    op.drop_index("ix_universal_profiles_display_name", table_name="universal_profiles")
    op.drop_table("universal_profiles")
