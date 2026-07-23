"""organization scoped label resources

Revision ID: 202607231530
Revises: 202607231330
Create Date: 2026-07-23 15:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607231530"
down_revision: str | None = "202607231330"
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


def _organization_id_column() -> sa.Column:
    return sa.Column("organization_id", sa.Uuid(), nullable=False)


def _organization_fk(table_name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id"],
        ["organizations.id"],
        name=op.f(f"fk_{table_name}_organization_id_organizations"),
        ondelete="CASCADE",
    )


def upgrade() -> None:
    op.create_table(
        "artists",
        sa.Column("id", sa.Uuid(), nullable=False),
        _organization_id_column(),
        sa.Column("name", sa.String(length=200), nullable=False),
        *_timestamps(),
        _organization_fk("artists"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artists")),
        sa.UniqueConstraint(
            "organization_id",
            "name",
            name="uq_artists_organization_id_name",
        ),
    )
    op.create_index("ix_artists_organization_id", "artists", ["organization_id"])

    op.create_table(
        "releases",
        sa.Column("id", sa.Uuid(), nullable=False),
        _organization_id_column(),
        sa.Column("artist_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        *_timestamps(),
        _organization_fk("releases"),
        sa.ForeignKeyConstraint(
            ["artist_id"],
            ["artists.id"],
            name=op.f("fk_releases_artist_id_artists"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_releases")),
    )
    op.create_index("ix_releases_organization_id", "releases", ["organization_id"])
    op.create_index(
        "ix_releases_organization_id_artist_id",
        "releases",
        ["organization_id", "artist_id"],
    )

    op.create_table(
        "campaigns",
        sa.Column("id", sa.Uuid(), nullable=False),
        _organization_id_column(),
        sa.Column("release_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        *_timestamps(),
        _organization_fk("campaigns"),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["releases.id"],
            name=op.f("fk_campaigns_release_id_releases"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaigns")),
    )
    op.create_index("ix_campaigns_organization_id", "campaigns", ["organization_id"])
    op.create_index(
        "ix_campaigns_organization_id_release_id",
        "campaigns",
        ["organization_id", "release_id"],
    )

    op.create_table(
        "contracts",
        sa.Column("id", sa.Uuid(), nullable=False),
        _organization_id_column(),
        sa.Column("artist_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        *_timestamps(),
        _organization_fk("contracts"),
        sa.ForeignKeyConstraint(
            ["artist_id"],
            ["artists.id"],
            name=op.f("fk_contracts_artist_id_artists"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contracts")),
    )
    op.create_index("ix_contracts_organization_id", "contracts", ["organization_id"])
    op.create_index(
        "ix_contracts_organization_id_artist_id",
        "contracts",
        ["organization_id", "artist_id"],
    )

    op.create_table(
        "royalties",
        sa.Column("id", sa.Uuid(), nullable=False),
        _organization_id_column(),
        sa.Column("release_id", sa.Uuid(), nullable=True),
        sa.Column("period", sa.String(length=40), nullable=False),
        *_timestamps(),
        _organization_fk("royalties"),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["releases.id"],
            name=op.f("fk_royalties_release_id_releases"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_royalties")),
    )
    op.create_index("ix_royalties_organization_id", "royalties", ["organization_id"])
    op.create_index(
        "ix_royalties_organization_id_release_id",
        "royalties",
        ["organization_id", "release_id"],
    )

    op.create_table(
        "analytics_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        _organization_id_column(),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        *_timestamps(),
        _organization_fk("analytics_events"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analytics_events")),
    )
    op.create_index(
        "ix_analytics_events_organization_id",
        "analytics_events",
        ["organization_id"],
    )

    op.create_table(
        "ai_agents",
        sa.Column("id", sa.Uuid(), nullable=False),
        _organization_id_column(),
        sa.Column("name", sa.String(length=200), nullable=False),
        *_timestamps(),
        _organization_fk("ai_agents"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_agents")),
        sa.UniqueConstraint(
            "organization_id",
            "name",
            name="uq_ai_agents_organization_id_name",
        ),
    )
    op.create_index("ix_ai_agents_organization_id", "ai_agents", ["organization_id"])

    op.create_table(
        "team_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        _organization_id_column(),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        *_timestamps(),
        _organization_fk("team_settings"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team_settings")),
        sa.UniqueConstraint(
            "organization_id",
            "key",
            name="uq_team_settings_organization_id_key",
        ),
    )
    op.create_index(
        "ix_team_settings_organization_id",
        "team_settings",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_team_settings_organization_id", table_name="team_settings")
    op.drop_table("team_settings")
    op.drop_index("ix_ai_agents_organization_id", table_name="ai_agents")
    op.drop_table("ai_agents")
    op.drop_index(
        "ix_analytics_events_organization_id",
        table_name="analytics_events",
    )
    op.drop_table("analytics_events")
    op.drop_index(
        "ix_royalties_organization_id_release_id",
        table_name="royalties",
    )
    op.drop_index("ix_royalties_organization_id", table_name="royalties")
    op.drop_table("royalties")
    op.drop_index(
        "ix_contracts_organization_id_artist_id",
        table_name="contracts",
    )
    op.drop_index("ix_contracts_organization_id", table_name="contracts")
    op.drop_table("contracts")
    op.drop_index(
        "ix_campaigns_organization_id_release_id",
        table_name="campaigns",
    )
    op.drop_index("ix_campaigns_organization_id", table_name="campaigns")
    op.drop_table("campaigns")
    op.drop_index(
        "ix_releases_organization_id_artist_id",
        table_name="releases",
    )
    op.drop_index("ix_releases_organization_id", table_name="releases")
    op.drop_table("releases")
    op.drop_index("ix_artists_organization_id", table_name="artists")
    op.drop_table("artists")
