from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from labelos_database.models import (
    Artist,
    Campaign,
    MarketingContentItem,
    MarketingContentItemChannel,
    MarketingContentItemStatus,
    Release,
    UniversalProfile,
    WorkspaceMembership,
)
from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


def _content_item_load_options():
    return (
        selectinload(MarketingContentItem.channels),
        selectinload(MarketingContentItem.campaign),
        selectinload(MarketingContentItem.artist),
        selectinload(MarketingContentItem.release),
        selectinload(MarketingContentItem.created_by_profile),
        selectinload(MarketingContentItem.owner_profile),
        selectinload(MarketingContentItem.approved_by_profile),
    )


@dataclass(frozen=True, kw_only=True)
class MarketingContentItemListPage:
    items: list[MarketingContentItem]
    total: int
    limit: int
    offset: int


def _filtered_items_statement(
    workspace_id: UUID,
    *,
    campaign_id: UUID | None = None,
    artist_id: UUID | None = None,
    release_id: UUID | None = None,
    status: MarketingContentItemStatus | None = None,
    channel: str | None = None,
    owner_profile_id: UUID | None = None,
    content_type: str | None = None,
    scheduled_start: datetime | None = None,
    scheduled_end: datetime | None = None,
    published_start: datetime | None = None,
    published_end: datetime | None = None,
) -> Select:
    statement = select(MarketingContentItem).where(
        MarketingContentItem.organization_id == workspace_id
    )
    if campaign_id is not None:
        statement = statement.where(MarketingContentItem.campaign_id == campaign_id)
    if artist_id is not None:
        statement = statement.where(MarketingContentItem.artist_id == artist_id)
    if release_id is not None:
        statement = statement.where(MarketingContentItem.release_id == release_id)
    if status is not None:
        statement = statement.where(MarketingContentItem.status == status)
    if owner_profile_id is not None:
        statement = statement.where(
            MarketingContentItem.owner_profile_id == owner_profile_id
        )
    if content_type is not None:
        statement = statement.where(MarketingContentItem.content_type == content_type)
    if scheduled_start is not None:
        statement = statement.where(
            MarketingContentItem.scheduled_at >= scheduled_start
        )
    if scheduled_end is not None:
        statement = statement.where(MarketingContentItem.scheduled_at <= scheduled_end)
    if published_start is not None:
        statement = statement.where(
            MarketingContentItem.published_at >= published_start
        )
    if published_end is not None:
        statement = statement.where(MarketingContentItem.published_at <= published_end)
    if channel is not None:
        statement = statement.where(
            MarketingContentItem.channels.any(
                MarketingContentItemChannel.channel == channel
            )
        )
    return statement


async def get_item(
    session: AsyncSession,
    workspace_id: UUID,
    content_item_id: UUID,
) -> MarketingContentItem | None:
    return await session.scalar(
        select(MarketingContentItem)
        .options(*_content_item_load_options())
        .where(MarketingContentItem.organization_id == workspace_id)
        .where(MarketingContentItem.id == content_item_id)
    )


async def get_item_for_campaign(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    content_item_id: UUID,
) -> MarketingContentItem | None:
    return await session.scalar(
        select(MarketingContentItem)
        .options(*_content_item_load_options())
        .where(MarketingContentItem.organization_id == workspace_id)
        .where(MarketingContentItem.campaign_id == campaign_id)
        .where(MarketingContentItem.id == content_item_id)
    )


async def create_item(
    session: AsyncSession,
    workspace_id: UUID,
    values: Mapping[str, object],
) -> MarketingContentItem:
    item = MarketingContentItem(organization_id=workspace_id, **dict(values))
    session.add(item)
    await session.flush()
    return item


async def update_item(
    session: AsyncSession,
    workspace_id: UUID,
    content_item_id: UUID,
    values: Mapping[str, object],
) -> MarketingContentItem | None:
    item = await get_item(session, workspace_id, content_item_id)
    if item is None:
        return None
    for key, value in values.items():
        setattr(item, key, value)
    await session.flush()
    return item


async def list_items(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    campaign_id: UUID | None = None,
    artist_id: UUID | None = None,
    release_id: UUID | None = None,
    status: MarketingContentItemStatus | None = None,
    channel: str | None = None,
    owner_profile_id: UUID | None = None,
    content_type: str | None = None,
    scheduled_start: datetime | None = None,
    scheduled_end: datetime | None = None,
    published_start: datetime | None = None,
    published_end: datetime | None = None,
    limit: int,
    offset: int,
) -> MarketingContentItemListPage:
    statement = _filtered_items_statement(
        workspace_id,
        campaign_id=campaign_id,
        artist_id=artist_id,
        release_id=release_id,
        status=status,
        channel=channel,
        owner_profile_id=owner_profile_id,
        content_type=content_type,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        published_start=published_start,
        published_end=published_end,
    )
    total = await session.scalar(select(func.count()).select_from(statement.subquery()))
    rows = await session.scalars(
        statement.options(*_content_item_load_options())
        .order_by(
            MarketingContentItem.scheduled_at.asc().nulls_last(),
            MarketingContentItem.created_at.desc(),
            MarketingContentItem.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return MarketingContentItemListPage(
        items=list(rows.all()),
        total=total or 0,
        limit=limit,
        offset=offset,
    )


async def list_items_by_workspace(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    limit: int,
    offset: int,
) -> MarketingContentItemListPage:
    return await list_items(session, workspace_id, limit=limit, offset=offset)


async def list_items_by_campaign(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    *,
    limit: int,
    offset: int,
) -> MarketingContentItemListPage:
    return await list_items(
        session,
        workspace_id,
        campaign_id=campaign_id,
        limit=limit,
        offset=offset,
    )


async def list_items_by_date_range(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    scheduled_start: datetime | None = None,
    scheduled_end: datetime | None = None,
    published_start: datetime | None = None,
    published_end: datetime | None = None,
    limit: int,
    offset: int,
) -> MarketingContentItemListPage:
    return await list_items(
        session,
        workspace_id,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        published_start=published_start,
        published_end=published_end,
        limit=limit,
        offset=offset,
    )


async def create_channels(
    session: AsyncSession,
    content_item_id: UUID,
    values: Sequence[Mapping[str, object]],
) -> list[MarketingContentItemChannel]:
    channels = [
        MarketingContentItemChannel(
            marketing_content_item_id=content_item_id,
            **dict(value),
        )
        for value in values
    ]
    session.add_all(channels)
    await session.flush()
    return channels


async def replace_channels(
    session: AsyncSession,
    content_item_id: UUID,
    values: Sequence[Mapping[str, object]],
) -> list[MarketingContentItemChannel]:
    await session.execute(
        delete(MarketingContentItemChannel).where(
            MarketingContentItemChannel.marketing_content_item_id == content_item_id
        )
    )
    await session.flush()
    return await create_channels(session, content_item_id, values)


async def update_channel(
    session: AsyncSession,
    channel_id: UUID,
    values: Mapping[str, object],
) -> MarketingContentItemChannel | None:
    channel = await session.get(MarketingContentItemChannel, channel_id)
    if channel is None:
        return None
    for key, value in values.items():
        setattr(channel, key, value)
    await session.flush()
    return channel


async def delete_channel(
    session: AsyncSession,
    channel_id: UUID,
) -> bool:
    channel = await session.get(MarketingContentItemChannel, channel_id)
    if channel is None:
        return False
    await session.delete(channel)
    await session.flush()
    return True


async def campaign_in_workspace(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
) -> bool:
    return (
        await session.scalar(
            select(Campaign.id)
            .where(Campaign.id == campaign_id)
            .where(Campaign.organization_id == workspace_id)
        )
        is not None
    )


async def artist_in_workspace(
    session: AsyncSession,
    workspace_id: UUID,
    artist_id: UUID,
) -> bool:
    return (
        await session.scalar(
            select(Artist.id)
            .where(Artist.id == artist_id)
            .where(Artist.organization_id == workspace_id)
        )
        is not None
    )


async def release_in_workspace(
    session: AsyncSession,
    workspace_id: UUID,
    release_id: UUID,
) -> Release | None:
    return await session.scalar(
        select(Release)
        .where(Release.id == release_id)
        .where(Release.organization_id == workspace_id)
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
