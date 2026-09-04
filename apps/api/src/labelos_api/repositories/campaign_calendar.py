from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from enum import Enum
from uuid import UUID

from labelos_database.models import (
    ApprovalRequest,
    ApprovalRequestStatus,
    Campaign,
    CampaignArtist,
    CampaignMilestone,
    CampaignRelease,
    CampaignStatus,
    MarketingContentItem,
    MarketingContentItemChannel,
    MarketingContentItemStatus,
)
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

CAMPAIGN_START = "campaign.start"
CAMPAIGN_TARGET_END = "campaign.target_end"
CAMPAIGN_MILESTONE_TARGET = "campaign.milestone.target"
MARKETING_CONTENT_SCHEDULED = "marketing.content.scheduled"
MARKETING_CONTENT_CHANNEL_SCHEDULED = "marketing.content.channel_scheduled"
MARKETING_CONTENT_PUBLISHED = "marketing.content.published"
MARKETING_CONTENT_CHANNEL_PUBLISHED = "marketing.content.channel_published"
MARKETING_CONTENT_APPROVAL_REQUESTED = "marketing.content.approval_requested"
MARKETING_CONTENT_APPROVED = "marketing.content.approved"

PUBLISHED_EVENT_TYPES = frozenset(
    {MARKETING_CONTENT_PUBLISHED, MARKETING_CONTENT_CHANNEL_PUBLISHED}
)

ALL_EVENT_TYPES = frozenset(
    {
        CAMPAIGN_START,
        CAMPAIGN_TARGET_END,
        CAMPAIGN_MILESTONE_TARGET,
        MARKETING_CONTENT_SCHEDULED,
        MARKETING_CONTENT_CHANNEL_SCHEDULED,
        MARKETING_CONTENT_PUBLISHED,
        MARKETING_CONTENT_CHANNEL_PUBLISHED,
        MARKETING_CONTENT_APPROVAL_REQUESTED,
        MARKETING_CONTENT_APPROVED,
    }
)


@dataclass(frozen=True, kw_only=True)
class CampaignCalendarEvent:
    event_type: str
    event_at: date | datetime
    source_type: str
    source_id: UUID
    workspace_id: UUID
    campaign_id: UUID
    campaign_name: str
    campaign_status: str
    campaign_type: str
    status: str
    title: str
    artist_id: UUID | None = None
    artist_name: str | None = None
    release_id: UUID | None = None
    release_title: str | None = None
    release_artist_id: UUID | None = None
    content_item_id: UUID | None = None
    content_item_title: str | None = None
    channel_id: UUID | None = None
    channel: str | None = None
    placement: str | None = None
    approval_request_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class CampaignCalendarEventQuery:
    campaign_id: UUID | None = None
    artist_id: UUID | None = None
    release_id: UUID | None = None
    event_types: Sequence[str] | None = None
    statuses: Sequence[str | Enum] | None = None
    range_start: date | datetime | None = None
    range_end: date | datetime | None = None
    include_archived: bool = False
    include_published: bool = False


def _campaign_load_options():
    return (
        selectinload(Campaign.primary_artist),
        selectinload(Campaign.release),
        selectinload(Campaign.artist_links).selectinload(CampaignArtist.artist),
        selectinload(Campaign.release_links).selectinload(CampaignRelease.release),
    )


def _milestone_load_options():
    return (
        selectinload(CampaignMilestone.campaign).selectinload(Campaign.primary_artist),
        selectinload(CampaignMilestone.campaign).selectinload(Campaign.release),
        selectinload(CampaignMilestone.campaign)
        .selectinload(Campaign.artist_links)
        .selectinload(CampaignArtist.artist),
        selectinload(CampaignMilestone.campaign)
        .selectinload(Campaign.release_links)
        .selectinload(CampaignRelease.release),
    )


def _content_load_options():
    return (
        selectinload(MarketingContentItem.channels),
        selectinload(MarketingContentItem.campaign).selectinload(
            Campaign.primary_artist
        ),
        selectinload(MarketingContentItem.campaign).selectinload(Campaign.release),
        selectinload(MarketingContentItem.campaign)
        .selectinload(Campaign.artist_links)
        .selectinload(CampaignArtist.artist),
        selectinload(MarketingContentItem.campaign)
        .selectinload(Campaign.release_links)
        .selectinload(CampaignRelease.release),
        selectinload(MarketingContentItem.artist),
        selectinload(MarketingContentItem.release),
        selectinload(MarketingContentItem.approval_request),
    )


async def list_events(
    session: AsyncSession,
    workspace_id: UUID,
    query: CampaignCalendarEventQuery | None = None,
) -> list[CampaignCalendarEvent]:
    query = query or CampaignCalendarEventQuery()
    event_types = _requested_event_types(query)
    events: list[CampaignCalendarEvent] = []

    if {CAMPAIGN_START, CAMPAIGN_TARGET_END} & event_types:
        campaigns = await session.scalars(
            _campaigns_statement(workspace_id, query).options(*_campaign_load_options())
        )
        events.extend(_project_campaign_events(campaigns.all(), query, event_types))

    if CAMPAIGN_MILESTONE_TARGET in event_types:
        milestones = await session.scalars(
            _milestones_statement(workspace_id, query).options(
                *_milestone_load_options()
            )
        )
        events.extend(_project_milestone_events(milestones.all(), query, event_types))

    content_event_types = event_types - {
        CAMPAIGN_START,
        CAMPAIGN_TARGET_END,
        CAMPAIGN_MILESTONE_TARGET,
    }
    if content_event_types:
        items = await session.scalars(
            _content_items_statement(workspace_id, query).options(
                *_content_load_options()
            )
        )
        events.extend(_project_content_events(items.unique().all(), query, event_types))

    return sorted(events, key=_event_sort_key)


def _campaigns_statement(
    workspace_id: UUID, query: CampaignCalendarEventQuery
) -> Select[tuple[Campaign]]:
    statement = select(Campaign).where(Campaign.organization_id == workspace_id)
    statement = _filter_campaign_scope(statement, query)
    statement = _filter_campaign_status(statement, query)
    statement = _filter_campaign_dates(statement, query)
    return statement


def _milestones_statement(
    workspace_id: UUID, query: CampaignCalendarEventQuery
) -> Select[tuple[CampaignMilestone]]:
    statement = (
        select(CampaignMilestone)
        .join(CampaignMilestone.campaign)
        .where(Campaign.organization_id == workspace_id)
        .where(CampaignMilestone.target_date.is_not(None))
    )
    statement = _filter_campaign_scope(statement, query)
    if not query.include_archived:
        statement = statement.where(Campaign.status != CampaignStatus.archived)
    status_values = _status_values(query.statuses)
    if status_values:
        campaign_statuses = _enum_values(status_values, CampaignStatus)
        filters = [CampaignMilestone.status.in_(status_values)]
        if campaign_statuses:
            filters.append(Campaign.status.in_(campaign_statuses))
        statement = statement.where(or_(*filters))
    elif not query.include_archived:
        statement = statement.where(CampaignMilestone.status != "archived")
    start_date, end_date = _date_bounds(query.range_start, query.range_end)
    if start_date is not None:
        statement = statement.where(CampaignMilestone.target_date >= start_date)
    if end_date is not None:
        statement = statement.where(CampaignMilestone.target_date <= end_date)
    return statement


def _content_items_statement(
    workspace_id: UUID, query: CampaignCalendarEventQuery
) -> Select[tuple[MarketingContentItem]]:
    statement = select(MarketingContentItem).where(
        MarketingContentItem.organization_id == workspace_id
    )
    statement = statement.join(MarketingContentItem.campaign)
    statement = statement.outerjoin(MarketingContentItem.approval_request)
    statement = _filter_content_scope(statement, query)
    statement = _filter_content_status(statement, query)
    statement = _filter_content_dates(statement, query)
    return statement


def _filter_campaign_scope(statement: Select, query: CampaignCalendarEventQuery):
    if query.campaign_id is not None:
        statement = statement.where(Campaign.id == query.campaign_id)
    if query.artist_id is not None:
        statement = statement.where(
            or_(
                Campaign.primary_artist_id == query.artist_id,
                Campaign.artist_links.any(CampaignArtist.artist_id == query.artist_id),
            )
        )
    if query.release_id is not None:
        statement = statement.where(
            or_(
                Campaign.release_id == query.release_id,
                Campaign.release_links.any(
                    CampaignRelease.release_id == query.release_id
                ),
            )
        )
    return statement


def _filter_content_scope(statement: Select, query: CampaignCalendarEventQuery):
    if query.campaign_id is not None:
        statement = statement.where(
            MarketingContentItem.campaign_id == query.campaign_id
        )
    if query.artist_id is not None:
        statement = statement.where(
            or_(
                MarketingContentItem.artist_id == query.artist_id,
                Campaign.primary_artist_id == query.artist_id,
                Campaign.artist_links.any(CampaignArtist.artist_id == query.artist_id),
            )
        )
    if query.release_id is not None:
        statement = statement.where(
            or_(
                MarketingContentItem.release_id == query.release_id,
                Campaign.release_id == query.release_id,
                Campaign.release_links.any(
                    CampaignRelease.release_id == query.release_id
                ),
            )
        )
    return statement


def _filter_campaign_status(statement: Select, query: CampaignCalendarEventQuery):
    status_values = _status_values(query.statuses)
    if status_values:
        campaign_statuses = _enum_values(status_values, CampaignStatus)
        if campaign_statuses:
            statement = statement.where(Campaign.status.in_(campaign_statuses))
        else:
            statement = statement.where(False)
    elif not query.include_archived:
        statement = statement.where(Campaign.status != CampaignStatus.archived)
    return statement


def _filter_content_status(statement: Select, query: CampaignCalendarEventQuery):
    status_values = _status_values(query.statuses)
    if status_values:
        content_statuses = _enum_values(status_values, MarketingContentItemStatus)
        request_statuses = _enum_values(status_values, ApprovalRequestStatus)
        filters = []
        if content_statuses:
            filters.append(MarketingContentItem.status.in_(content_statuses))
        if request_statuses:
            filters.append(ApprovalRequest.status.in_(request_statuses))
        statement = statement.where(or_(*filters) if filters else False)
    elif not query.include_archived:
        statement = statement.where(
            MarketingContentItem.status != MarketingContentItemStatus.archived
        )
    return statement


def _filter_campaign_dates(statement: Select, query: CampaignCalendarEventQuery):
    start_date, end_date = _date_bounds(query.range_start, query.range_end)
    date_filters = []
    if CAMPAIGN_START in _requested_event_types(query):
        conditions = [Campaign.start_date.is_not(None)]
        if start_date is not None:
            conditions.append(Campaign.start_date >= start_date)
        if end_date is not None:
            conditions.append(Campaign.start_date <= end_date)
        date_filters.append(and_(*conditions))
    if CAMPAIGN_TARGET_END in _requested_event_types(query):
        conditions = [Campaign.target_end_date.is_not(None)]
        if start_date is not None:
            conditions.append(Campaign.target_end_date >= start_date)
        if end_date is not None:
            conditions.append(Campaign.target_end_date <= end_date)
        date_filters.append(and_(*conditions))
    return statement.where(or_(*date_filters)) if date_filters else statement


def _filter_content_dates(statement: Select, query: CampaignCalendarEventQuery):
    start_datetime, end_datetime = _datetime_bounds(query.range_start, query.range_end)
    event_types = _requested_event_types(query)
    filters = []
    for field, event_type, is_channel_field in (
        (MarketingContentItem.scheduled_at, MARKETING_CONTENT_SCHEDULED, False),
        (
            MarketingContentItemChannel.scheduled_at,
            MARKETING_CONTENT_CHANNEL_SCHEDULED,
            True,
        ),
        (MarketingContentItem.published_at, MARKETING_CONTENT_PUBLISHED, False),
        (
            MarketingContentItemChannel.published_at,
            MARKETING_CONTENT_CHANNEL_PUBLISHED,
            True,
        ),
        (ApprovalRequest.submitted_at, MARKETING_CONTENT_APPROVAL_REQUESTED, False),
        (
            MarketingContentItem.approval_requested_at,
            MARKETING_CONTENT_APPROVAL_REQUESTED,
            False,
        ),
        (MarketingContentItem.approved_at, MARKETING_CONTENT_APPROVED, False),
        (ApprovalRequest.resolved_at, MARKETING_CONTENT_APPROVED, False),
    ):
        if event_type not in event_types:
            continue
        conditions = [field.is_not(None)]
        if start_datetime is not None:
            conditions.append(field >= start_datetime)
        if end_datetime is not None:
            conditions.append(field <= end_datetime)
        if is_channel_field:
            filters.append(MarketingContentItem.channels.any(and_(*conditions)))
        else:
            filters.append(and_(*conditions))
    return statement.where(or_(*filters)) if filters else statement


def _project_campaign_events(
    campaigns: Sequence[Campaign],
    query: CampaignCalendarEventQuery,
    event_types: frozenset[str],
) -> list[CampaignCalendarEvent]:
    events = []
    for campaign in campaigns:
        if not _campaign_projectable(campaign, query):
            continue
        if campaign.start_date and CAMPAIGN_START in event_types:
            events.append(
                _campaign_event(
                    campaign,
                    event_type=CAMPAIGN_START,
                    event_at=campaign.start_date,
                    title=f"{campaign.name} starts",
                )
            )
        if campaign.target_end_date and CAMPAIGN_TARGET_END in event_types:
            events.append(
                _campaign_event(
                    campaign,
                    event_type=CAMPAIGN_TARGET_END,
                    event_at=campaign.target_end_date,
                    title=f"{campaign.name} target end",
                )
            )
    return [event for event in events if _event_in_range(event.event_at, query)]


def _project_milestone_events(
    milestones: Sequence[CampaignMilestone],
    query: CampaignCalendarEventQuery,
    event_types: frozenset[str],
) -> list[CampaignCalendarEvent]:
    if CAMPAIGN_MILESTONE_TARGET not in event_types:
        return []
    events = []
    for milestone in milestones:
        campaign = milestone.campaign
        if milestone.target_date is None or not _milestone_projectable(
            milestone, query
        ):
            continue
        artist_id, artist_name = _campaign_artist_context(campaign)
        release_id, release_title, release_artist_id = _campaign_release_context(
            campaign
        )
        events.append(
            CampaignCalendarEvent(
                event_type=CAMPAIGN_MILESTONE_TARGET,
                event_at=milestone.target_date,
                source_type="campaign_milestone",
                source_id=milestone.id,
                workspace_id=campaign.organization_id,
                campaign_id=campaign.id,
                campaign_name=campaign.name,
                campaign_status=campaign.status.value,
                campaign_type=campaign.campaign_type.value,
                status=milestone.status,
                title=milestone.title,
                artist_id=artist_id,
                artist_name=artist_name,
                release_id=release_id,
                release_title=release_title,
                release_artist_id=release_artist_id,
            )
        )
    return [event for event in events if _event_in_range(event.event_at, query)]


def _project_content_events(
    items: Sequence[MarketingContentItem],
    query: CampaignCalendarEventQuery,
    event_types: frozenset[str],
) -> list[CampaignCalendarEvent]:
    events = []
    for item in items:
        if not _content_projectable(item, query):
            continue
        if item.scheduled_at and MARKETING_CONTENT_SCHEDULED in event_types:
            events.append(
                _content_event(
                    item,
                    event_type=MARKETING_CONTENT_SCHEDULED,
                    event_at=item.scheduled_at,
                    source_type="marketing_content_item",
                    source_id=item.id,
                    title=item.title,
                )
            )
        if item.published_at and MARKETING_CONTENT_PUBLISHED in event_types:
            events.append(
                _content_event(
                    item,
                    event_type=MARKETING_CONTENT_PUBLISHED,
                    event_at=item.published_at,
                    source_type="marketing_content_item",
                    source_id=item.id,
                    title=item.title,
                )
            )
        approval_requested_at = _approval_requested_at(item)
        if (
            approval_requested_at is not None
            and MARKETING_CONTENT_APPROVAL_REQUESTED in event_types
        ):
            events.append(
                _content_event(
                    item,
                    event_type=MARKETING_CONTENT_APPROVAL_REQUESTED,
                    event_at=approval_requested_at,
                    source_type=(
                        "approval_request"
                        if item.approval_request is not None
                        else "marketing_content_item"
                    ),
                    source_id=item.approval_request_id or item.id,
                    title=item.title,
                    approval_request_id=item.approval_request_id,
                )
            )
        approved_at = _approved_at(item)
        if approved_at is not None and MARKETING_CONTENT_APPROVED in event_types:
            events.append(
                _content_event(
                    item,
                    event_type=MARKETING_CONTENT_APPROVED,
                    event_at=approved_at,
                    source_type=(
                        "approval_request"
                        if item.approved_at is None
                        and item.approval_request is not None
                        else "marketing_content_item"
                    ),
                    source_id=(
                        item.approval_request_id
                        if item.approved_at is None and item.approval_request_id
                        else item.id
                    ),
                    title=item.title,
                    approval_request_id=item.approval_request_id,
                )
            )
        for channel in item.channels:
            if (
                channel.scheduled_at
                and MARKETING_CONTENT_CHANNEL_SCHEDULED in event_types
            ):
                events.append(
                    _channel_event(
                        item,
                        channel,
                        event_type=MARKETING_CONTENT_CHANNEL_SCHEDULED,
                        event_at=channel.scheduled_at,
                    )
                )
            if (
                channel.published_at
                and MARKETING_CONTENT_CHANNEL_PUBLISHED in event_types
            ):
                events.append(
                    _channel_event(
                        item,
                        channel,
                        event_type=MARKETING_CONTENT_CHANNEL_PUBLISHED,
                        event_at=channel.published_at,
                    )
                )
    return [event for event in events if _event_in_range(event.event_at, query)]


def _campaign_event(
    campaign: Campaign,
    *,
    event_type: str,
    event_at: date,
    title: str,
) -> CampaignCalendarEvent:
    artist_id, artist_name = _campaign_artist_context(campaign)
    release_id, release_title, release_artist_id = _campaign_release_context(campaign)
    return CampaignCalendarEvent(
        event_type=event_type,
        event_at=event_at,
        source_type="campaign",
        source_id=campaign.id,
        workspace_id=campaign.organization_id,
        campaign_id=campaign.id,
        campaign_name=campaign.name,
        campaign_status=campaign.status.value,
        campaign_type=campaign.campaign_type.value,
        status=campaign.status.value,
        title=title,
        artist_id=artist_id,
        artist_name=artist_name,
        release_id=release_id,
        release_title=release_title,
        release_artist_id=release_artist_id,
    )


def _content_event(
    item: MarketingContentItem,
    *,
    event_type: str,
    event_at: datetime,
    source_type: str,
    source_id: UUID,
    title: str,
    approval_request_id: UUID | None = None,
) -> CampaignCalendarEvent:
    artist_id, artist_name = _content_artist_context(item)
    release_id, release_title, release_artist_id = _content_release_context(item)
    return CampaignCalendarEvent(
        event_type=event_type,
        event_at=event_at,
        source_type=source_type,
        source_id=source_id,
        workspace_id=item.organization_id,
        campaign_id=item.campaign_id,
        campaign_name=item.campaign.name,
        campaign_status=item.campaign.status.value,
        campaign_type=item.campaign.campaign_type.value,
        status=item.status.value,
        title=title,
        artist_id=artist_id,
        artist_name=artist_name,
        release_id=release_id,
        release_title=release_title,
        release_artist_id=release_artist_id,
        content_item_id=item.id,
        content_item_title=item.title,
        approval_request_id=approval_request_id,
    )


def _channel_event(
    item: MarketingContentItem,
    channel: MarketingContentItemChannel,
    *,
    event_type: str,
    event_at: datetime,
) -> CampaignCalendarEvent:
    event = _content_event(
        item,
        event_type=event_type,
        event_at=event_at,
        source_type="marketing_content_item_channel",
        source_id=channel.id,
        title=f"{item.title} - {channel.channel}",
    )
    return replace(
        event,
        channel_id=channel.id,
        channel=channel.channel,
        placement=channel.placement,
    )


def _campaign_artist_context(campaign: Campaign) -> tuple[UUID | None, str | None]:
    if campaign.primary_artist is not None:
        return campaign.primary_artist.id, campaign.primary_artist.name
    for link in campaign.artist_links:
        if link.artist is not None:
            return link.artist.id, link.artist.name
    return None, None


def _campaign_release_context(
    campaign: Campaign,
) -> tuple[UUID | None, str | None, UUID | None]:
    if campaign.release is not None:
        return campaign.release.id, campaign.release.title, campaign.release.artist_id
    for link in campaign.release_links:
        if link.release is not None:
            return link.release.id, link.release.title, link.release.artist_id
    return None, None, None


def _content_artist_context(
    item: MarketingContentItem,
) -> tuple[UUID | None, str | None]:
    if item.artist is not None:
        return item.artist.id, item.artist.name
    return _campaign_artist_context(item.campaign)


def _content_release_context(
    item: MarketingContentItem,
) -> tuple[UUID | None, str | None, UUID | None]:
    if item.release is not None:
        return item.release.id, item.release.title, item.release.artist_id
    return _campaign_release_context(item.campaign)


def _approval_requested_at(item: MarketingContentItem) -> datetime | None:
    if item.approval_request is not None:
        return item.approval_request.submitted_at
    return item.approval_requested_at


def _approved_at(item: MarketingContentItem) -> datetime | None:
    request = item.approval_request
    if request is not None:
        if request.status == ApprovalRequestStatus.approved:
            return request.resolved_at
        return None
    return item.approved_at


def _campaign_projectable(
    campaign: Campaign, query: CampaignCalendarEventQuery
) -> bool:
    status_values = _status_values(query.statuses)
    if status_values and campaign.status.value not in status_values:
        return False
    return query.include_archived or campaign.status != CampaignStatus.archived


def _milestone_projectable(
    milestone: CampaignMilestone, query: CampaignCalendarEventQuery
) -> bool:
    campaign = milestone.campaign
    if not query.include_archived and (
        campaign.status == CampaignStatus.archived or milestone.status == "archived"
    ):
        return False
    status_values = _status_values(query.statuses)
    if not status_values:
        return True
    return campaign.status.value in status_values or milestone.status in status_values


def _content_projectable(
    item: MarketingContentItem, query: CampaignCalendarEventQuery
) -> bool:
    if (
        not query.include_archived
        and item.status == MarketingContentItemStatus.archived
    ):
        return False
    status_values = _status_values(query.statuses)
    if not status_values:
        return True
    if item.status.value in status_values:
        return True
    request = item.approval_request
    return request is not None and request.status.value in status_values


def _requested_event_types(query: CampaignCalendarEventQuery) -> frozenset[str]:
    if query.event_types is None:
        event_types = set(ALL_EVENT_TYPES)
    else:
        event_types = set(query.event_types) & ALL_EVENT_TYPES
    if not query.include_published:
        event_types -= PUBLISHED_EVENT_TYPES
    return frozenset(event_types)


def _status_values(statuses: Sequence[str | Enum] | None) -> frozenset[str]:
    if statuses is None:
        return frozenset()
    return frozenset(
        status.value if isinstance(status, Enum) else str(status) for status in statuses
    )


def _enum_values(status_values: frozenset[str], enum_type: type[Enum]) -> list[Enum]:
    return [status for status in enum_type if status.value in status_values]


def _date_bounds(
    range_start: date | datetime | None,
    range_end: date | datetime | None,
) -> tuple[date | None, date | None]:
    return _as_date(range_start), _as_date(range_end)


def _datetime_bounds(
    range_start: date | datetime | None,
    range_end: date | datetime | None,
) -> tuple[datetime | None, datetime | None]:
    start = _as_datetime_start(range_start)
    end = _as_datetime_end(range_end)
    return start, end


def _as_date(value: date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        _require_aware_datetime(value)
        return value.astimezone(UTC).date()
    return value


def _as_datetime_start(value: date | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _utc_datetime(value)
    return datetime.combine(value, time.min, tzinfo=UTC)


def _as_datetime_end(value: date | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _utc_datetime(value)
    return datetime.combine(value, time.max, tzinfo=UTC)


def _utc_datetime(value: datetime) -> datetime:
    _require_aware_datetime(value)
    return value.astimezone(UTC)


def _require_aware_datetime(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "Campaign calendar datetime range bounds must be timezone-aware"
        )


def _event_in_range(
    event_at: date | datetime, query: CampaignCalendarEventQuery
) -> bool:
    if isinstance(event_at, datetime):
        start, end = _datetime_bounds(query.range_start, query.range_end)
        comparable = _coerce_event_datetime(event_at)
    else:
        start, end = _date_bounds(query.range_start, query.range_end)
        comparable = event_at
    if start is not None and comparable < start:
        return False
    return not (end is not None and comparable > end)


def _coerce_event_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _event_sort_key(event: CampaignCalendarEvent) -> tuple[datetime, str, str]:
    event_at = event.event_at
    if isinstance(event_at, datetime):
        sortable = _coerce_event_datetime(event_at)
    else:
        sortable = datetime.combine(event_at, time.min, tzinfo=UTC)
    return sortable, event.event_type, str(event.source_id)
