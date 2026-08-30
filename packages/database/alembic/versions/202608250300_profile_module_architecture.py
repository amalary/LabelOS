"""profile module architecture

Revision ID: 202608250300
Revises: 202608250200
Create Date: 2026-08-25 03:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608250300"
down_revision: str | None = "202608250200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _fail_if_unlinked_artist_profiles_exist()
    _copy_artist_profile_biographies_to_universal_profiles()
    op.drop_constraint(
        op.f("fk_artist_profiles_universal_profile_id_universal_profiles"),
        "artist_profiles",
        type_="foreignkey",
    )
    op.alter_column(
        "artist_profiles",
        "universal_profile_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.create_foreign_key(
        op.f("fk_artist_profiles_universal_profile_id_universal_profiles"),
        "artist_profiles",
        "universal_profiles",
        ["universal_profile_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("artist_profiles", "biography")


def _fail_if_unlinked_artist_profiles_exist() -> None:
    connection = op.get_bind()
    unlinked_count = connection.execute(sa.text("""
            SELECT count(*) AS count
            FROM artist_profiles
            WHERE universal_profile_id IS NULL
            """)).scalar_one()
    if unlinked_count:
        raise RuntimeError(
            "Cannot make artist_profiles.universal_profile_id non-null while "
            f"{unlinked_count} artist profile row(s) are unlinked. Link these rows "
            "to Universal Profiles using a deterministic source before rerunning "
            "this migration."
        )


def _copy_artist_profile_biographies_to_universal_profiles() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("""
            UPDATE universal_profiles
            SET biography = (
                SELECT artist_profiles.biography
                FROM artist_profiles
                WHERE artist_profiles.universal_profile_id = universal_profiles.id
                  AND artist_profiles.biography IS NOT NULL
                  AND trim(artist_profiles.biography) != ''
                ORDER BY artist_profiles.created_at ASC, artist_profiles.id ASC
                LIMIT 1
            )
            WHERE (
              universal_profiles.biography IS NULL
              OR trim(universal_profiles.biography) = ''
            )
              AND EXISTS (
                SELECT 1
                FROM artist_profiles
                WHERE artist_profiles.universal_profile_id = universal_profiles.id
                  AND artist_profiles.biography IS NOT NULL
                  AND trim(artist_profiles.biography) != ''
              )
            """))


def downgrade() -> None:
    op.add_column(
        "artist_profiles",
        sa.Column("biography", sa.String(length=4000), nullable=True),
    )
    op.drop_constraint(
        op.f("fk_artist_profiles_universal_profile_id_universal_profiles"),
        "artist_profiles",
        type_="foreignkey",
    )
    op.alter_column(
        "artist_profiles",
        "universal_profile_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )
    op.create_foreign_key(
        op.f("fk_artist_profiles_universal_profile_id_universal_profiles"),
        "artist_profiles",
        "universal_profiles",
        ["universal_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
