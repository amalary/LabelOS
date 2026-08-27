"""campaign relationships

Revision ID: 202608271100
Revises: 202608271000
Create Date: 2026-08-27 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608271100"
down_revision: str | None = "202608271000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
    op.create_table(
        "campaign_artists",
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("artist_id", sa.Uuid(), nullable=False),
        sa.Column(
            "relationship_kind",
            sa.String(length=60),
            nullable=False,
            server_default="collaborator",
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_campaign_artists_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["artist_id"],
            ["artists.id"],
            name=op.f("fk_campaign_artists_artist_id_artists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "campaign_id",
            "artist_id",
            name=op.f("pk_campaign_artists"),
        ),
    )
    op.create_index(
        "ix_campaign_artists_campaign_id",
        "campaign_artists",
        ["campaign_id"],
    )
    op.create_index(
        "ix_campaign_artists_artist_id",
        "campaign_artists",
        ["artist_id"],
    )
    op.create_index(
        "ix_campaign_artists_relationship_kind",
        "campaign_artists",
        ["relationship_kind"],
    )

    op.create_table(
        "campaign_members",
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_membership_id", sa.Uuid(), nullable=False),
        sa.Column(
            "participation_status",
            sa.String(length=60),
            nullable=False,
            server_default="active",
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_campaign_members_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_membership_id"],
            ["workspace_memberships.id"],
            name=op.f(
                "fk_campaign_members_workspace_membership_id_workspace_memberships"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "campaign_id",
            "workspace_membership_id",
            name=op.f("pk_campaign_members"),
        ),
    )
    op.create_index(
        "ix_campaign_members_campaign_id",
        "campaign_members",
        ["campaign_id"],
    )
    op.create_index(
        "ix_campaign_members_workspace_membership_id",
        "campaign_members",
        ["workspace_membership_id"],
    )
    op.create_index(
        "ix_campaign_members_participation_status",
        "campaign_members",
        ["participation_status"],
    )

    bind = op.get_bind()
    bind.execute(sa.text("""
            INSERT INTO campaign_artists (
                campaign_id,
                artist_id,
                relationship_kind,
                sort_order
            )
            SELECT id, primary_artist_id, 'primary', 0
            FROM campaigns
            WHERE primary_artist_id IS NOT NULL
            ON CONFLICT (campaign_id, artist_id) DO NOTHING
            """))


def downgrade() -> None:
    op.drop_index(
        "ix_campaign_members_participation_status",
        table_name="campaign_members",
    )
    op.drop_index(
        "ix_campaign_members_workspace_membership_id",
        table_name="campaign_members",
    )
    op.drop_index("ix_campaign_members_campaign_id", table_name="campaign_members")
    op.drop_table("campaign_members")

    op.drop_index(
        "ix_campaign_artists_relationship_kind",
        table_name="campaign_artists",
    )
    op.drop_index("ix_campaign_artists_artist_id", table_name="campaign_artists")
    op.drop_index("ix_campaign_artists_campaign_id", table_name="campaign_artists")
    op.drop_table("campaign_artists")
