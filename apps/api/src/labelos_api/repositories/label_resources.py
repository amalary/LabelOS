from uuid import UUID

from labelos_database.models import Artist, ArtistProfile, Release
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


def _artist_profile_values(name: str, profile: dict | None = None) -> dict:
    values = dict(profile or {})
    values.setdefault("stage_name", name)
    return values


def _should_create_artist_profile(profile: dict | None) -> bool:
    return bool(profile and profile.get("universal_profile_id") is not None)


async def list_artists(
    session: AsyncSession,
    organization_id: UUID,
    *,
    search: str | None = None,
) -> list[Artist]:
    statement = (
        select(Artist)
        .options(selectinload(Artist.profile))
        .where(Artist.organization_id == organization_id)
    )
    if search:
        statement = statement.where(Artist.name.ilike(f"%{search}%"))
    rows = await session.scalars(statement.order_by(Artist.name))
    return list(rows.all())


async def get_artist(
    session: AsyncSession,
    organization_id: UUID,
    artist_id: UUID,
) -> Artist | None:
    return await session.scalar(
        select(Artist)
        .options(selectinload(Artist.profile))
        .where(Artist.organization_id == organization_id)
        .where(Artist.id == artist_id)
    )


async def create_artist(
    session: AsyncSession,
    organization_id: UUID,
    name: str,
    *,
    profile: dict | None = None,
) -> Artist:
    artist = Artist(organization_id=organization_id, name=name)
    if _should_create_artist_profile(profile):
        artist.profile = ArtistProfile(**_artist_profile_values(name, profile))
    session.add(artist)
    await session.commit()
    await session.refresh(artist)
    await session.refresh(artist, attribute_names=["profile"])
    return artist


async def update_artist(
    session: AsyncSession,
    organization_id: UUID,
    artist_id: UUID,
    *,
    name: str,
    profile: dict | None = None,
) -> Artist | None:
    artist = await get_artist(session, organization_id, artist_id)
    if artist is None:
        return None
    previous_name = artist.name
    artist.name = name
    if artist.profile is None and _should_create_artist_profile(profile):
        artist.profile = ArtistProfile(**_artist_profile_values(name, profile))
    elif artist.profile is not None and profile is not None:
        for key, value in profile.items():
            setattr(artist.profile, key, value)
    elif artist.profile is not None and artist.profile.stage_name in {
        None,
        previous_name,
    }:
        artist.profile.stage_name = name
    await session.commit()
    await session.refresh(artist)
    await session.refresh(artist, attribute_names=["profile"])
    return artist


async def delete_artist(
    session: AsyncSession,
    organization_id: UUID,
    artist_id: UUID,
) -> bool:
    artist = await get_artist(session, organization_id, artist_id)
    if artist is None:
        return False
    await session.delete(artist)
    await session.commit()
    return True


async def list_artist_releases(
    session: AsyncSession,
    organization_id: UUID,
    artist_id: UUID,
) -> list[Release] | None:
    artist = await get_artist(session, organization_id, artist_id)
    if artist is None:
        return None
    rows = await session.scalars(
        select(Release)
        .where(Release.organization_id == organization_id)
        .where(Release.artist_id == artist_id)
        .order_by(Release.title)
    )
    return list(rows.all())
