"""marketing content foundation

Revision ID: 202609031300
Revises: 202608291700
Create Date: 2026-09-03 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609031300"
down_revision: str | None = "202608291700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


marketing_content_item_status = postgresql.ENUM(
    "draft",
    "in_review",
    "approved",
    "scheduled",
    "published",
    "cancelled",
    "archived",
    name="marketing_content_item_status",
    create_type=False,
)


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
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
    )


def upgrade() -> None:
    bind = op.get_bind()
    marketing_content_item_status.create(bind, checkfirst=True)

    op.create_table(
        "marketing_content_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("artist_id", sa.Uuid(), nullable=True),
        sa.Column("release_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("content_type", sa.String(length=80), nullable=False),
        sa.Column("copy_text", sa.String(length=8000), nullable=True),
        sa.Column("asset_refs", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column(
            "status",
            marketing_content_item_status,
            server_default="draft",
            nullable=False,
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_profile_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_profile_id", sa.Uuid(), nullable=True),
        sa.Column("owner_profile_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["approved_by_profile_id"],
            ["universal_profiles.id"],
            name=op.f(
                "fk_marketing_content_items_approved_by_profile_id_universal_profiles"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["artist_id"],
            ["artists.id"],
            name=op.f("fk_marketing_content_items_artist_id_artists"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_marketing_content_items_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_profile_id"],
            ["universal_profiles.id"],
            name=op.f(
                "fk_marketing_content_items_created_by_profile_id_universal_profiles"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_marketing_content_items_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_marketing_content_items_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_profile_id"],
            ["universal_profiles.id"],
            name=op.f("fk_marketing_content_items_owner_profile_id_universal_profiles"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["releases.id"],
            name=op.f("fk_marketing_content_items_release_id_releases"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marketing_content_items")),
    )
    op.create_index(
        "ix_marketing_content_items_organization_id",
        "marketing_content_items",
        ["organization_id"],
    )
    op.create_index(
        "ix_marketing_content_items_organization_id_campaign_id",
        "marketing_content_items",
        ["organization_id", "campaign_id"],
    )
    op.create_index(
        "ix_marketing_content_items_organization_id_status",
        "marketing_content_items",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_marketing_content_items_organization_id_scheduled_at",
        "marketing_content_items",
        ["organization_id", "scheduled_at"],
    )
    op.create_index(
        "ix_marketing_content_items_organization_id_published_at",
        "marketing_content_items",
        ["organization_id", "published_at"],
    )
    op.create_index(
        "ix_marketing_content_items_organization_id_artist_id",
        "marketing_content_items",
        ["organization_id", "artist_id"],
    )
    op.create_index(
        "ix_marketing_content_items_organization_id_release_id",
        "marketing_content_items",
        ["organization_id", "release_id"],
    )
    op.create_index(
        "ix_marketing_content_items_org_owner_profile",
        "marketing_content_items",
        ["organization_id", "owner_profile_id"],
    )
    op.create_index(
        "ix_marketing_content_items_org_created_user",
        "marketing_content_items",
        ["organization_id", "created_by_user_id"],
    )
    op.create_index(
        "ix_marketing_content_items_org_created_profile",
        "marketing_content_items",
        ["organization_id", "created_by_profile_id"],
    )

    op.create_table(
        "marketing_content_item_channels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("marketing_content_item_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=80), nullable=False),
        sa.Column(
            "placement",
            sa.String(length=80),
            server_default="default",
            nullable=False,
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_post_id", sa.String(length=255), nullable=True),
        sa.Column("external_url", sa.String(length=2048), nullable=True),
        sa.Column("copy_text_override", sa.String(length=8000), nullable=True),
        sa.Column("asset_refs", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["marketing_content_item_id"],
            ["marketing_content_items.id"],
            name=op.f(
                "fk_marketing_content_item_channels_marketing_content_item_id_marketing_content_items"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marketing_content_item_channels")),
        sa.UniqueConstraint(
            "marketing_content_item_id",
            "channel",
            "placement",
            name="uq_marketing_content_item_channels_item_channel_placement",
        ),
    )
    op.create_index(
        "ix_marketing_content_item_channels_marketing_content_item_id",
        "marketing_content_item_channels",
        ["marketing_content_item_id"],
    )
    op.create_index(
        "ix_marketing_content_item_channels_channel",
        "marketing_content_item_channels",
        ["channel"],
    )
    op.create_index(
        "ix_marketing_content_item_channels_channel_scheduled_at",
        "marketing_content_item_channels",
        ["channel", "scheduled_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_marketing_content_item_channels_channel_scheduled_at",
        table_name="marketing_content_item_channels",
    )
    op.drop_index(
        "ix_marketing_content_item_channels_channel",
        table_name="marketing_content_item_channels",
    )
    op.drop_index(
        "ix_marketing_content_item_channels_marketing_content_item_id",
        table_name="marketing_content_item_channels",
    )
    op.drop_table("marketing_content_item_channels")

    op.drop_index(
        "ix_marketing_content_items_org_created_profile",
        table_name="marketing_content_items",
    )
    op.drop_index(
        "ix_marketing_content_items_org_created_user",
        table_name="marketing_content_items",
    )
    op.drop_index(
        "ix_marketing_content_items_org_owner_profile",
        table_name="marketing_content_items",
    )
    op.drop_index(
        "ix_marketing_content_items_organization_id_release_id",
        table_name="marketing_content_items",
    )
    op.drop_index(
        "ix_marketing_content_items_organization_id_artist_id",
        table_name="marketing_content_items",
    )
    op.drop_index(
        "ix_marketing_content_items_organization_id_published_at",
        table_name="marketing_content_items",
    )
    op.drop_index(
        "ix_marketing_content_items_organization_id_scheduled_at",
        table_name="marketing_content_items",
    )
    op.drop_index(
        "ix_marketing_content_items_organization_id_status",
        table_name="marketing_content_items",
    )
    op.drop_index(
        "ix_marketing_content_items_organization_id_campaign_id",
        table_name="marketing_content_items",
    )
    op.drop_index(
        "ix_marketing_content_items_organization_id",
        table_name="marketing_content_items",
    )
    op.drop_table("marketing_content_items")

    bind = op.get_bind()
    marketing_content_item_status.drop(bind, checkfirst=True)
