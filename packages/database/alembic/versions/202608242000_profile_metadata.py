"""profile metadata

Revision ID: 202608242000
Revises: 202608241900
Create Date: 2026-08-24 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608242000"
down_revision: str | None = "202608241900"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "profile_attributes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("attribute_type", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("value", sa.String(length=500), nullable=False),
        sa.Column(
            "source", sa.String(length=80), server_default="user", nullable=False
        ),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
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
            ["profile_id"],
            ["universal_profiles.id"],
            name=op.f("fk_profile_attributes_profile_id_universal_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profile_attributes")),
        sa.UniqueConstraint(
            "profile_id",
            "attribute_type",
            "value",
            name="uq_profile_attributes_profile_id_type_value",
        ),
    )
    op.create_index(
        "ix_profile_attributes_attribute_type",
        "profile_attributes",
        ["attribute_type"],
        unique=False,
    )
    op.create_index(
        "ix_profile_attributes_is_primary",
        "profile_attributes",
        ["is_primary"],
        unique=False,
    )
    op.create_index(
        "ix_profile_attributes_profile_id",
        "profile_attributes",
        ["profile_id"],
        unique=False,
    )
    op.create_index(
        "ix_profile_attributes_profile_id_type",
        "profile_attributes",
        ["profile_id", "attribute_type"],
        unique=False,
    )

    op.create_table(
        "profile_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("link_type", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("username", sa.String(length=120), nullable=True),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=60),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
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
            ["profile_id"],
            ["universal_profiles.id"],
            name=op.f("fk_profile_links_profile_id_universal_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profile_links")),
        sa.UniqueConstraint(
            "profile_id",
            "link_type",
            "url",
            name="uq_profile_links_profile_id_type_url",
        ),
    )
    op.create_index(
        "ix_profile_links_is_primary",
        "profile_links",
        ["is_primary"],
        unique=False,
    )
    op.create_index(
        "ix_profile_links_link_type",
        "profile_links",
        ["link_type"],
        unique=False,
    )
    op.create_index(
        "ix_profile_links_profile_id",
        "profile_links",
        ["profile_id"],
        unique=False,
    )
    op.create_index(
        "ix_profile_links_profile_id_type",
        "profile_links",
        ["profile_id", "link_type"],
        unique=False,
    )
    op.create_index(
        "ix_profile_links_status",
        "profile_links",
        ["status"],
        unique=False,
    )

    op.create_table(
        "profile_preferences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("locale", sa.String(length=35), nullable=True),
        sa.Column("timezone", sa.String(length=120), nullable=True),
        sa.Column("default_workspace_id", sa.Uuid(), nullable=True),
        sa.Column(
            "email_notifications_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "push_notifications_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "sms_notifications_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "marketing_notifications_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("interface_theme", sa.String(length=60), nullable=True),
        sa.Column("interface_density", sa.String(length=60), nullable=True),
        sa.Column(
            "notification_preferences",
            sa.JSON(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "interface_preferences",
            sa.JSON(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "integration_preferences",
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["default_workspace_id"],
            ["organizations.id"],
            name=op.f("fk_profile_preferences_default_workspace_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["universal_profiles.id"],
            name=op.f("fk_profile_preferences_profile_id_universal_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profile_preferences")),
        sa.UniqueConstraint("profile_id", name="uq_profile_preferences_profile_id"),
    )
    op.create_index(
        "ix_profile_preferences_default_workspace_id",
        "profile_preferences",
        ["default_workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_profile_preferences_locale",
        "profile_preferences",
        ["locale"],
        unique=False,
    )
    op.create_index(
        "ix_profile_preferences_profile_id",
        "profile_preferences",
        ["profile_id"],
        unique=False,
    )
    op.create_index(
        "ix_profile_preferences_timezone",
        "profile_preferences",
        ["timezone"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_profile_preferences_timezone", table_name="profile_preferences")
    op.drop_index("ix_profile_preferences_profile_id", table_name="profile_preferences")
    op.drop_index("ix_profile_preferences_locale", table_name="profile_preferences")
    op.drop_index(
        "ix_profile_preferences_default_workspace_id",
        table_name="profile_preferences",
    )
    op.drop_table("profile_preferences")
    op.drop_index("ix_profile_links_status", table_name="profile_links")
    op.drop_index("ix_profile_links_profile_id_type", table_name="profile_links")
    op.drop_index("ix_profile_links_profile_id", table_name="profile_links")
    op.drop_index("ix_profile_links_link_type", table_name="profile_links")
    op.drop_index("ix_profile_links_is_primary", table_name="profile_links")
    op.drop_table("profile_links")
    op.drop_index(
        "ix_profile_attributes_profile_id_type", table_name="profile_attributes"
    )
    op.drop_index("ix_profile_attributes_profile_id", table_name="profile_attributes")
    op.drop_index("ix_profile_attributes_is_primary", table_name="profile_attributes")
    op.drop_index(
        "ix_profile_attributes_attribute_type", table_name="profile_attributes"
    )
    op.drop_table("profile_attributes")
