from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from labelos_database.models import (
    Artist,
    ArtistProfile,
    Campaign,
    MarketingContentItem,
    MarketingContentItemChannel,
    MarketingContentItemStatus,
    Publication,
    Release,
    SocialAccountConnection,
    UniversalProfile,
    WorkspaceMembership,
)
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from labelos_api.repositories.publication_calendar import published_for_item


def _content_item_load_options():
    return (
        selectinload(MarketingContentItem.channels),
        selectinload(MarketingContentItem.channels).selectinload(
            MarketingContentItemChannel.social_account_connection
        ),
        selectinload(MarketingContentItem.campaign),
        selectinload(MarketingContentItem.artist),
        selectinload(MarketingContentItem.release),
        selectinload(MarketingContentItem.created_by_profile),
        selectinload(MarketingContentItem.owner_profile),
        selectinload(MarketingContentItem.approved_by_profile),
        selectinload(MarketingContentItem.approval_request),
    )


@dataclass(frozen=True, kw_only=True)
class MarketingContentItemListPage:
    items: list[MarketingContentItem]
    total: int
    limit: int
    offset: int


CHANNEL_MATERIAL_FIELDS = frozenset(
    {
        "channel",
        "placement",
        "social_account_connection_id",
        "scheduled_at",
        "schedule_timezone",
        "schedule_local_time",
        "schedule_offset_seconds",
        "copy_text_override",
        "asset_refs",
        "metadata_json",
    }
)
CHANNEL_VALUE_FIELDS = CHANNEL_MATERIAL_FIELDS | {
    "published_at",
    "external_post_id",
    "external_url",
}


def changed_channel_fields(
    channel: MarketingContentItemChannel, values: Mapping[str, object]
) -> set[str]:
    def comparable(value: object) -> object:
        # SQLite returns naive timestamps; persisted channel timestamps denote UTC.
        if isinstance(value, datetime):
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return value

    return {
        field
        for field, value in values.items()
        if comparable(getattr(channel, field)) != comparable(value)
    }


@dataclass(frozen=True, kw_only=True)
class ChannelReconciliationResult:
    """IDs ordered by channel/placement; updated IDs are a subset of retained IDs.

    Results are durable only once the caller commits the surrounding transaction.
    """

    retained_channel_ids: tuple[UUID, ...]
    created_channel_ids: tuple[UUID, ...]
    updated_channel_ids: tuple[UUID, ...]
    removed_channel_ids: tuple[UUID, ...]
    material_change: bool


@dataclass(frozen=True, kw_only=True)
class ChannelReconciliationPlan:
    """Identify removals and material edits before mutating any existing rows.

    Build from a parent loaded with get_item_for_update and authorized by the
    service. Hold that lock through apply and commit; never reuse a plan across
    transactions. Channels, revision, approval and events share a transaction.
    """

    item: MarketingContentItem
    retained: tuple[MarketingContentItemChannel, ...]
    created: tuple[MarketingContentItemChannel, ...]
    updated: tuple[tuple[MarketingContentItemChannel, dict[str, object]], ...]
    removed: tuple[MarketingContentItemChannel, ...]
    material_change: bool

    @property
    def changed(self) -> bool:
        return bool(self.created or self.updated or self.removed)


def plan_channel_reconciliation(
    item: MarketingContentItem, values: Sequence[Mapping[str, object]]
) -> ChannelReconciliationPlan:
    existing = {(row.channel, row.placement): row for row in item.channels}
    if len(existing) != len(item.channels):
        raise ValueError("Ambiguous channel identity; explicit identity is required")
    existing_by_id = {row.id: row for row in item.channels}
    claimed_ids: set[UUID] = set()
    proposed = {}
    for value in values:
        if value.keys() - (CHANNEL_VALUE_FIELDS | {"id"}):
            raise ValueError("Unsupported channel fields")
        channel_id = value.get("id")
        if channel_id is not None and not isinstance(channel_id, UUID):
            raise ValueError("Channel ID must be a UUID")
        if channel_id is not None and channel_id not in existing_by_id:
            raise ValueError("Channel ID does not belong to this content item")
        # Construct detached candidates to apply model validation and replacement
        # defaults, including clearing omitted optional values on retained rows.
        candidate = MarketingContentItemChannel(
            marketing_content_item_id=item.id,
            **{
                "placement": "default",
                "asset_refs": [],
                "metadata_json": {},
                **{field: data for field, data in value.items() if field != "id"},
            },
        )
        key = (candidate.channel, candidate.placement)
        if key in proposed:
            raise ValueError("Duplicate channel and placement target")
        source = (
            existing_by_id[channel_id] if channel_id is not None else existing.get(key)
        )
        if source is not None:
            if source.id in claimed_ids:
                raise ValueError("Channel ID is used more than once")
            claimed_ids.add(source.id)
        proposed[key] = (candidate, source)

    retained = []
    created = []
    updated = []
    material_change = False
    for key, (candidate, row) in sorted(proposed.items()):
        if row is None or (row.channel, row.placement) != key:
            created.append(candidate)
            material_change = True
            continue
        retained.append(row)
        replacement = {
            field: getattr(candidate, field) for field in CHANNEL_VALUE_FIELDS
        }
        changed = changed_channel_fields(row, replacement)
        if changed:
            updated.append((row, {field: replacement[field] for field in changed}))
            material_change |= bool(changed & CHANNEL_MATERIAL_FIELDS)
    retained_ids = {row.id for row in retained}
    removed = tuple(
        row for _, row in sorted(existing.items()) if row.id not in retained_ids
    )
    material_change |= bool(removed)
    return ChannelReconciliationPlan(
        item=item,
        retained=tuple(retained),
        created=tuple(created),
        updated=tuple(updated),
        removed=removed,
        material_change=material_change,
    )


async def apply_channel_reconciliation(
    session: AsyncSession, plan: ChannelReconciliationPlan
) -> ChannelReconciliationResult:
    for row, values in plan.updated:
        if values.keys() & CHANNEL_MATERIAL_FIELDS:
            row.schedule_generation += 1
        for field, value in values.items():
            setattr(row, field, value)
        if "social_account_connection_id" in values:
            session.expire(row, ["social_account_connection"])
    for row in plan.removed:
        await session.delete(row)
    # Release logical keys before inserting replacements (including explicit-ID
    # swaps). Both flushes remain inside the caller's transaction.
    if plan.removed:
        await session.flush()
    session.add_all(plan.created)
    await session.flush()
    if plan.changed:
        session.expire(plan.item, ["channels"])
    return ChannelReconciliationResult(
        retained_channel_ids=tuple(row.id for row in plan.retained),
        created_channel_ids=tuple(row.id for row in plan.created),
        updated_channel_ids=tuple(row.id for row, _ in plan.updated),
        removed_channel_ids=tuple(row.id for row in plan.removed),
        material_change=plan.material_change,
    )


async def reconcile_channels(
    session: AsyncSession,
    content_item_id: UUID,
    values: Sequence[Mapping[str, object]],
) -> ChannelReconciliationResult:
    item = await get_item_for_update(session, content_item_id)
    if item is None:
        raise ValueError("Marketing content item not found")
    return await apply_channel_reconciliation(
        session, plan_channel_reconciliation(item, values)
    )


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
        status_match = MarketingContentItem.status == status
        if status == MarketingContentItemStatus.published:
            status_match = or_(status_match, published_for_item(workspace_id).exists())
        statement = statement.where(status_match)
    if owner_profile_id is not None:
        statement = statement.where(
            MarketingContentItem.owner_profile_id == owner_profile_id
        )
    if content_type is not None:
        statement = statement.where(MarketingContentItem.content_type == content_type)
    scheduled_conditions = []
    channel_scheduled_conditions = []
    if scheduled_start is not None:
        scheduled_conditions.append(
            MarketingContentItem.scheduled_at >= scheduled_start
        )
        channel_scheduled_conditions.append(
            MarketingContentItemChannel.scheduled_at >= scheduled_start
        )
    if scheduled_end is not None:
        scheduled_conditions.append(MarketingContentItem.scheduled_at <= scheduled_end)
        channel_scheduled_conditions.append(
            MarketingContentItemChannel.scheduled_at <= scheduled_end
        )
    if scheduled_conditions:
        publication_match = published_for_item(workspace_id)
        if scheduled_start is not None:
            publication_match = publication_match.where(
                Publication.published_at >= scheduled_start
            )
        if scheduled_end is not None:
            publication_match = publication_match.where(
                Publication.published_at <= scheduled_end
            )
        statement = statement.where(
            or_(
                publication_match.exists(),
                and_(*scheduled_conditions),
                MarketingContentItem.channels.any(and_(*channel_scheduled_conditions)),
            )
        )
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


async def get_item_for_update(
    session: AsyncSession,
    content_item_id: UUID,
    *,
    workspace_id: UUID | None = None,
) -> MarketingContentItem | None:
    """Serialize writers on the parent before reading channels or revision.

    Refresh cached ORM state after waiting for the lock. PostgreSQL's default
    READ COMMITTED isolation then exposes the preceding writer's committed rows
    to the selectinload queries. Always lock the parent before approval requests.
    The caller owns the transaction and must commit or roll it back to release.
    """
    statement = (
        select(MarketingContentItem)
        .options(*_content_item_load_options())
        .where(MarketingContentItem.id == content_item_id)
        .with_for_update(of=MarketingContentItem)
        .execution_options(populate_existing=True)
    )
    if workspace_id is not None:
        statement = statement.where(
            MarketingContentItem.organization_id == workspace_id
        )
    item = await session.scalar(statement)
    if item is not None:
        # Child mutations and snapshot verification follow the same parent-first
        # protocol. Refresh again under ordered child locks, never cached intent.
        await session.scalars(
            select(MarketingContentItemChannel)
            .options(
                selectinload(MarketingContentItemChannel.social_account_connection)
            )
            .where(MarketingContentItemChannel.marketing_content_item_id == item.id)
            .order_by(MarketingContentItemChannel.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    return item


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
    item = await get_item_for_update(
        session, content_item_id, workspace_id=workspace_id
    )
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
    if await get_item_for_update(session, content_item_id) is None:
        raise ValueError("Marketing content item not found")
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
    await reconcile_channels(session, content_item_id, values)
    rows = await session.scalars(
        select(MarketingContentItemChannel)
        .where(MarketingContentItemChannel.marketing_content_item_id == content_item_id)
        .order_by(
            MarketingContentItemChannel.channel, MarketingContentItemChannel.placement
        )
    )
    return list(rows.all())


async def update_channel(
    session: AsyncSession,
    channel_id: UUID,
    values: Mapping[str, object],
) -> MarketingContentItemChannel | None:
    if values.keys() - CHANNEL_VALUE_FIELDS:
        raise ValueError("Unsupported channel fields")
    channel = await _get_channel_for_update(session, channel_id)
    if channel is None:
        return None
    changed = changed_channel_fields(channel, values)
    if changed & {"channel", "placement"}:
        item = await get_item_for_update(session, channel.marketing_content_item_id)
        assert item is not None
        replacements = [
            {
                "id": row.id,
                **{field: getattr(row, field) for field in CHANNEL_VALUE_FIELDS},
                **(dict(values) if row.id == channel_id else {}),
            }
            for row in item.channels
        ]
        plan = plan_channel_reconciliation(item, replacements)
        await apply_channel_reconciliation(session, plan)
        return plan.created[0]
    if changed & CHANNEL_MATERIAL_FIELDS:
        channel.schedule_generation += 1
    for key, value in values.items():
        setattr(channel, key, value)
    if "social_account_connection_id" in values:
        session.expire(channel, ["social_account_connection"])
    await session.flush()
    return channel


async def get_social_account_connection(
    session: AsyncSession,
    workspace_id: UUID,
    connection_id: UUID,
) -> SocialAccountConnection | None:
    return await session.scalar(
        select(SocialAccountConnection)
        .options(
            selectinload(SocialAccountConnection.artist_profile).selectinload(
                ArtistProfile.artist
            )
        )
        .where(SocialAccountConnection.organization_id == workspace_id)
        .where(SocialAccountConnection.id == connection_id)
    )


async def delete_channel(
    session: AsyncSession,
    channel_id: UUID,
) -> bool:
    channel = await _get_channel_for_update(session, channel_id)
    if channel is None:
        return False
    await session.delete(channel)
    await session.flush()
    return True


async def _get_channel_for_update(
    session: AsyncSession, channel_id: UUID
) -> MarketingContentItemChannel | None:
    parent_id = await session.scalar(
        select(MarketingContentItemChannel.marketing_content_item_id).where(
            MarketingContentItemChannel.id == channel_id
        )
    )
    if parent_id is None:
        return None
    item = await get_item_for_update(session, parent_id)
    if item is None:
        return None
    return next((row for row in item.channels if row.id == channel_id), None)


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


async def campaign_artist_id(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
) -> UUID | None:
    return await session.scalar(
        select(Campaign.primary_artist_id)
        .where(Campaign.id == campaign_id)
        .where(Campaign.organization_id == workspace_id)
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
