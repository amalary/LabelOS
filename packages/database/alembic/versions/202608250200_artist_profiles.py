"""artist profiles extend universal profiles

Revision ID: 202608250200
Revises: 202608250100
Create Date: 2026-08-25 02:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608250200"
down_revision: str | None = "202608250100"
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
        "artist_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("artist_id", sa.Uuid(), nullable=False),
        sa.Column("universal_profile_id", sa.Uuid(), nullable=True),
        sa.Column("stage_name", sa.String(length=200), nullable=True),
        sa.Column("genres", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("influences", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("biography", sa.String(length=4000), nullable=True),
        sa.Column("imagery", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("dsp_links", sa.JSON(), server_default="{}", nullable=False),
        sa.Column(
            "catalog_references",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "creative_metadata",
            sa.JSON(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("career_stage", sa.String(length=120), nullable=True),
        sa.Column("audience", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("preferences", sa.JSON(), server_default="{}", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["artist_id"],
            ["artists.id"],
            name=op.f("fk_artist_profiles_artist_id_artists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["universal_profile_id"],
            ["universal_profiles.id"],
            name=op.f("fk_artist_profiles_universal_profile_id_universal_profiles"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artist_profiles")),
        sa.UniqueConstraint("artist_id", name="uq_artist_profiles_artist_id"),
    )
    op.create_index(
        "ix_artist_profiles_artist_id",
        "artist_profiles",
        ["artist_id"],
    )
    op.create_index(
        "ix_artist_profiles_universal_profile_id",
        "artist_profiles",
        ["universal_profile_id"],
    )
    op.create_index(
        "ix_artist_profiles_stage_name",
        "artist_profiles",
        ["stage_name"],
    )
    op.create_index(
        "ix_artist_profiles_career_stage",
        "artist_profiles",
        ["career_stage"],
    )


def downgrade() -> None:
    op.drop_index("ix_artist_profiles_career_stage", table_name="artist_profiles")
    op.drop_index("ix_artist_profiles_stage_name", table_name="artist_profiles")
    op.drop_index(
        "ix_artist_profiles_universal_profile_id",
        table_name="artist_profiles",
    )
    op.drop_index("ix_artist_profiles_artist_id", table_name="artist_profiles")
    op.drop_table("artist_profiles")
