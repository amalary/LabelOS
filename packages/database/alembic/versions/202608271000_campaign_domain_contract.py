"""campaign domain contract

Revision ID: 202608271000
Revises: 202608261000
Create Date: 2026-08-27 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608271000"
down_revision: str | None = "202608261000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


campaign_type = sa.Enum(
    "release",
    "marketing",
    "artist_development",
    "catalog",
    "other",
    name="campaign_type",
)
campaign_status = sa.Enum(
    "draft",
    "planning",
    "active",
    "paused",
    "completed",
    "cancelled",
    "archived",
    name="campaign_status",
)


def upgrade() -> None:
    bind = op.get_bind()
    campaign_type.create(bind, checkfirst=True)
    campaign_status.create(bind, checkfirst=True)

    op.add_column("campaigns", sa.Column("description", sa.String(length=4000)))
    op.add_column(
        "campaigns",
        sa.Column(
            "campaign_type",
            campaign_type,
            nullable=False,
            server_default="other",
        ),
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "status",
            campaign_status,
            nullable=False,
            server_default="draft",
        ),
    )
    op.add_column("campaigns", sa.Column("start_date", sa.Date()))
    op.add_column("campaigns", sa.Column("target_end_date", sa.Date()))
    op.add_column("campaigns", sa.Column("created_by_user_id", sa.Uuid()))
    op.add_column("campaigns", sa.Column("created_by_profile_id", sa.Uuid()))
    op.add_column("campaigns", sa.Column("owner_profile_id", sa.Uuid()))
    op.add_column("campaigns", sa.Column("primary_artist_id", sa.Uuid()))

    op.create_foreign_key(
        op.f("fk_campaigns_created_by_user_id_users"),
        "campaigns",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_campaigns_created_by_profile_id_universal_profiles"),
        "campaigns",
        "universal_profiles",
        ["created_by_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_campaigns_owner_profile_id_universal_profiles"),
        "campaigns",
        "universal_profiles",
        ["owner_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_campaigns_primary_artist_id_artists"),
        "campaigns",
        "artists",
        ["primary_artist_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_campaigns_organization_id_campaign_type",
        "campaigns",
        ["organization_id", "campaign_type"],
    )
    op.create_index(
        "ix_campaigns_organization_id_status",
        "campaigns",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_campaigns_organization_id_owner_profile_id",
        "campaigns",
        ["organization_id", "owner_profile_id"],
    )
    op.create_index(
        "ix_campaigns_organization_id_created_by_user_id",
        "campaigns",
        ["organization_id", "created_by_user_id"],
    )
    op.create_index(
        "ix_campaigns_organization_id_created_by_profile_id",
        "campaigns",
        ["organization_id", "created_by_profile_id"],
    )
    op.create_index(
        "ix_campaigns_organization_id_primary_artist_id",
        "campaigns",
        ["organization_id", "primary_artist_id"],
    )
    op.create_index(
        "ix_campaigns_organization_id_start_date",
        "campaigns",
        ["organization_id", "start_date"],
    )
    op.create_index(
        "ix_campaigns_organization_id_target_end_date",
        "campaigns",
        ["organization_id", "target_end_date"],
    )

    op.create_table(
        "campaign_releases",
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column(
            "relationship_kind",
            sa.String(length=60),
            nullable=False,
            server_default="related",
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
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_campaign_releases_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["releases.id"],
            name=op.f("fk_campaign_releases_release_id_releases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "campaign_id",
            "release_id",
            name=op.f("pk_campaign_releases"),
        ),
    )
    op.create_index(
        "ix_campaign_releases_campaign_id",
        "campaign_releases",
        ["campaign_id"],
    )
    op.create_index(
        "ix_campaign_releases_release_id",
        "campaign_releases",
        ["release_id"],
    )
    op.create_index(
        "ix_campaign_releases_relationship_kind",
        "campaign_releases",
        ["relationship_kind"],
    )

    bind.execute(sa.text("""
            INSERT INTO campaign_releases (
                campaign_id,
                release_id,
                relationship_kind
            )
            SELECT id, release_id, 'primary'
            FROM campaigns
            WHERE release_id IS NOT NULL
            ON CONFLICT (campaign_id, release_id) DO NOTHING
            """))


def downgrade() -> None:
    op.drop_index(
        "ix_campaign_releases_relationship_kind",
        table_name="campaign_releases",
    )
    op.drop_index("ix_campaign_releases_release_id", table_name="campaign_releases")
    op.drop_index("ix_campaign_releases_campaign_id", table_name="campaign_releases")
    op.drop_table("campaign_releases")

    op.drop_index(
        "ix_campaigns_organization_id_primary_artist_id",
        table_name="campaigns",
    )
    op.drop_index(
        "ix_campaigns_organization_id_target_end_date",
        table_name="campaigns",
    )
    op.drop_index(
        "ix_campaigns_organization_id_start_date",
        table_name="campaigns",
    )
    op.drop_index(
        "ix_campaigns_organization_id_created_by_profile_id",
        table_name="campaigns",
    )
    op.drop_index(
        "ix_campaigns_organization_id_created_by_user_id",
        table_name="campaigns",
    )
    op.drop_index(
        "ix_campaigns_organization_id_owner_profile_id",
        table_name="campaigns",
    )
    op.drop_index("ix_campaigns_organization_id_status", table_name="campaigns")
    op.drop_index(
        "ix_campaigns_organization_id_campaign_type",
        table_name="campaigns",
    )

    op.drop_constraint(
        op.f("fk_campaigns_primary_artist_id_artists"),
        "campaigns",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_campaigns_owner_profile_id_universal_profiles"),
        "campaigns",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_campaigns_created_by_profile_id_universal_profiles"),
        "campaigns",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_campaigns_created_by_user_id_users"),
        "campaigns",
        type_="foreignkey",
    )

    op.drop_column("campaigns", "primary_artist_id")
    op.drop_column("campaigns", "owner_profile_id")
    op.drop_column("campaigns", "created_by_profile_id")
    op.drop_column("campaigns", "created_by_user_id")
    op.drop_column("campaigns", "target_end_date")
    op.drop_column("campaigns", "start_date")
    op.drop_column("campaigns", "status")
    op.drop_column("campaigns", "campaign_type")
    op.drop_column("campaigns", "description")

    bind = op.get_bind()
    campaign_status.drop(bind, checkfirst=True)
    campaign_type.drop(bind, checkfirst=True)
