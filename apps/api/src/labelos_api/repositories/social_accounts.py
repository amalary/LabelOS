from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from labelos_database.models import (
    Artist,
    ArtistProfile,
    SocialAccountConnection,
    SocialAccountConnectionStatus,
    UniversalProfile,
    WorkspaceMembership,
)
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


def _connection_load_options():
    return (
        selectinload(SocialAccountConnection.artist_profile).selectinload(
            ArtistProfile.artist
        ),
        selectinload(SocialAccountConnection.created_by_user),
        selectinload(SocialAccountConnection.created_by_profile),
    )


@dataclass(frozen=True, kw_only=True)
class SocialAccountConnectionListPage:
    items: list[SocialAccountConnection]
    total: int
    limit: int
    offset: int


def _filtered_connections_statement(
    workspace_id: UUID,
    *,
    provider: str | None = None,
    status: SocialAccountConnectionStatus | None = None,
    artist_profile_id: UUID | None = None,
    include_disconnected: bool = True,
) -> Select:
    statement = select(SocialAccountConnection).where(
        SocialAccountConnection.organization_id == workspace_id
    )
    if provider is not None:
        statement = statement.where(SocialAccountConnection.provider == provider)
    if status is not None:
        statement = statement.where(SocialAccountConnection.status == status)
    elif not include_disconnected:
        statement = statement.where(
            SocialAccountConnection.status != SocialAccountConnectionStatus.disconnected
        )
    if artist_profile_id is not None:
        statement = statement.where(
            SocialAccountConnection.artist_profile_id == artist_profile_id
        )
    return statement


async def get_connection(
    session: AsyncSession,
    workspace_id: UUID,
    connection_id: UUID,
) -> SocialAccountConnection | None:
    return await session.scalar(
        select(SocialAccountConnection)
        .options(*_connection_load_options())
        .where(SocialAccountConnection.organization_id == workspace_id)
        .where(SocialAccountConnection.id == connection_id)
    )


async def list_connections(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    provider: str | None = None,
    status: SocialAccountConnectionStatus | None = None,
    artist_profile_id: UUID | None = None,
    include_disconnected: bool = True,
    limit: int,
    offset: int,
) -> SocialAccountConnectionListPage:
    statement = _filtered_connections_statement(
        workspace_id,
        provider=provider,
        status=status,
        artist_profile_id=artist_profile_id,
        include_disconnected=include_disconnected,
    )
    total = await session.scalar(select(func.count()).select_from(statement.subquery()))
    rows = await session.scalars(
        statement.options(*_connection_load_options())
        .order_by(
            SocialAccountConnection.updated_at.desc(),
            SocialAccountConnection.created_at.desc(),
            SocialAccountConnection.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return SocialAccountConnectionListPage(
        items=list(rows.all()),
        total=total or 0,
        limit=limit,
        offset=offset,
    )


async def create_connection(
    session: AsyncSession,
    workspace_id: UUID,
    values: Mapping[str, object],
) -> SocialAccountConnection:
    connection = SocialAccountConnection(organization_id=workspace_id, **dict(values))
    session.add(connection)
    await session.flush()
    return connection


async def update_connection(
    session: AsyncSession,
    workspace_id: UUID,
    connection_id: UUID,
    values: Mapping[str, object],
) -> SocialAccountConnection | None:
    connection = await get_connection(session, workspace_id, connection_id)
    if connection is None:
        return None
    for key, value in values.items():
        setattr(connection, key, value)
    await session.flush()
    return connection


async def artist_profile_in_workspace(
    session: AsyncSession,
    workspace_id: UUID,
    artist_profile_id: UUID,
) -> bool:
    return (
        await session.scalar(
            select(ArtistProfile.id)
            .join(ArtistProfile.artist)
            .where(ArtistProfile.id == artist_profile_id)
            .where(Artist.organization_id == workspace_id)
        )
        is not None
    )


async def profile_is_active_workspace_member(
    session: AsyncSession,
    workspace_id: UUID,
    profile_id: UUID,
) -> bool:
    return (
        await session.scalar(
            select(WorkspaceMembership.id)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .where(WorkspaceMembership.profile_id == profile_id)
            .where(WorkspaceMembership.status == "active")
        )
        is not None
    )


async def user_is_active_workspace_member(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
) -> bool:
    return (
        await session.scalar(
            select(WorkspaceMembership.id)
            .join(WorkspaceMembership.profile)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .where(WorkspaceMembership.status == "active")
            .where(UniversalProfile.user_id == user_id)
        )
        is not None
    )
