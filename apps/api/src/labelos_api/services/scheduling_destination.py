"""Shared destination locks and safe column selection for scheduling mutations."""

from uuid import UUID

from labelos_database.models import ArtistProfile, SocialAccountConnection
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload, load_only
from sqlalchemy.orm.attributes import set_committed_value


async def lock_destination(
    session: AsyncSession, workspace_id: UUID, destination_id: UUID | None
) -> SocialAccountConnection | None:
    if destination_id is None:
        return None
    # Deliberately exclude credentials, credential references and metadata.
    connection = await session.scalar(
        select(SocialAccountConnection)
        .options(
            lazyload("*"),
            load_only(
                SocialAccountConnection.id,
                SocialAccountConnection.organization_id,
                SocialAccountConnection.artist_profile_id,
                SocialAccountConnection.provider,
                SocialAccountConnection.status,
                SocialAccountConnection.capabilities,
                SocialAccountConnection.last_error_code,
                raiseload=True,
            ),
        )
        .where(
            SocialAccountConnection.id == destination_id,
            SocialAccountConnection.organization_id == workspace_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if connection is not None:
        profile = None
        if connection.artist_profile_id is not None:
            profile = await session.scalar(
                select(ArtistProfile)
                .options(
                    lazyload("*"),
                    load_only(ArtistProfile.artist_id, raiseload=True),
                )
                .where(ArtistProfile.id == connection.artist_profile_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        set_committed_value(connection, "artist_profile", profile)
    return connection
