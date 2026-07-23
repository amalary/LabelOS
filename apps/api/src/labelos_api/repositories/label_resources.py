from uuid import UUID

from labelos_database.models import Artist
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def list_artists(session: AsyncSession, organization_id: UUID) -> list[Artist]:
    rows = await session.scalars(
        select(Artist)
        .where(Artist.organization_id == organization_id)
        .order_by(Artist.name)
    )
    return list(rows.all())


async def get_artist(
    session: AsyncSession,
    organization_id: UUID,
    artist_id: UUID,
) -> Artist | None:
    return await session.scalar(
        select(Artist)
        .where(Artist.organization_id == organization_id)
        .where(Artist.id == artist_id)
    )


async def create_artist(
    session: AsyncSession,
    organization_id: UUID,
    name: str,
) -> Artist:
    artist = Artist(organization_id=organization_id, name=name)
    session.add(artist)
    await session.commit()
    await session.refresh(artist)
    return artist


async def update_artist(
    session: AsyncSession,
    organization_id: UUID,
    artist_id: UUID,
    *,
    name: str,
) -> Artist | None:
    artist = await get_artist(session, organization_id, artist_id)
    if artist is None:
        return None
    artist.name = name
    await session.commit()
    await session.refresh(artist)
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
