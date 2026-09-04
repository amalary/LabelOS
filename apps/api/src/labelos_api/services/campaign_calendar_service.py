from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from enum import Enum
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.authorization import (
    AuthorizationActorInput,
    AuthorizationResource,
    Capability,
    ResourceKind,
    authorization_service,
)
from labelos_api.repositories import campaign_calendar
from labelos_api.repositories.approval_resources import (
    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
    get_approval_resource_adapter,
)
from labelos_api.services import approval_service

MAX_CAMPAIGN_CALENDAR_LIMIT = 1000


class CampaignCalendarServiceError(ValueError):
    """Base error for campaign calendar validation and authorization failures."""


class CampaignCalendarAuthorizationError(CampaignCalendarServiceError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class CampaignCalendarValidationError(CampaignCalendarServiceError):
    pass


@dataclass(frozen=True, kw_only=True)
class CampaignCalendarEventQuery:
    start: datetime
    end: datetime
    timezone: str
    campaign_id: UUID | None = None
    artist_id: UUID | None = None
    release_id: UUID | None = None
    event_types: tuple[str, ...] | None = None
    statuses: tuple[str | Enum, ...] | None = None
    include_archived: bool = False
    include_published: bool = False


@dataclass(frozen=True, kw_only=True)
class CampaignCalendarCampaignContext:
    id: str
    name: str
    status: str
    campaign_type: str


@dataclass(frozen=True, kw_only=True)
class CampaignCalendarArtistContext:
    id: str
    name: str


@dataclass(frozen=True, kw_only=True)
class CampaignCalendarReleaseContext:
    id: str
    title: str
    artist_id: str | None


@dataclass(frozen=True, kw_only=True)
class CampaignCalendarChannelContext:
    id: str
    channel: str
    placement: str


@dataclass(frozen=True, kw_only=True)
class CampaignCalendarApprovalContext:
    request_id: str | None
    state: str | None
    label: str | None
    approved_revision_is_current: bool | None
    can_schedule: bool | None
    available_actions: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class NormalizedCampaignCalendarEvent:
    id: str
    event_type: str
    source_type: str
    source_id: str
    source_parent_id: str | None
    title: str
    description: str | None
    starts_at: str
    ends_at: str | None
    date: str | None
    all_day: bool
    timezone: str
    status: str | None
    campaign: CampaignCalendarCampaignContext | None
    artist: CampaignCalendarArtistContext | None
    release: CampaignCalendarReleaseContext | None
    channel: CampaignCalendarChannelContext | None
    approval: CampaignCalendarApprovalContext | None
    url: str | None
    sort_key: str


@dataclass(frozen=True, kw_only=True)
class CampaignCalendarEventListPage:
    events: list[NormalizedCampaignCalendarEvent]
    total: int
    limit: int
    offset: int


async def list_campaign_calendar_events(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    query: CampaignCalendarEventQuery,
    limit: int = 100,
    offset: int = 0,
) -> CampaignCalendarEventListPage:
    _validate_pagination(limit=limit, offset=offset)
    timezone = _validate_query(query)
    await _require_unified_calendar_capabilities(
        session,
        actor=actor,
        workspace_id=workspace_id,
        campaign_id=query.campaign_id,
    )

    local_start = query.start.astimezone(timezone)
    local_end = query.end.astimezone(timezone)
    repository_events = await campaign_calendar.list_events(
        session,
        workspace_id,
        campaign_calendar.CampaignCalendarEventQuery(
            campaign_id=query.campaign_id,
            artist_id=query.artist_id,
            release_id=query.release_id,
            event_types=query.event_types,
            statuses=query.statuses,
            range_start=local_start.date(),
            range_end=local_end.date(),
            include_archived=query.include_archived,
            include_published=query.include_published,
        ),
    )
    normalized = [
        event
        for event in [
            await _normalize_event(
                session,
                workspace_id=workspace_id,
                actor=actor,
                event=event,
                timezone=timezone,
            )
            for event in repository_events
        ]
        if _normalized_event_in_range(event, query.start, query.end, timezone)
    ]
    normalized.sort(key=lambda event: (event.sort_key, event.id))
    total = len(normalized)
    return CampaignCalendarEventListPage(
        events=normalized[offset : offset + limit],
        total=total,
        limit=limit,
        offset=offset,
    )


async def _require_unified_calendar_capabilities(
    session: AsyncSession,
    *,
    actor: AuthorizationActorInput | None,
    workspace_id: UUID,
    campaign_id: UUID | None,
) -> None:
    if actor is None:
        return
    resource = AuthorizationResource(
        kind=(
            ResourceKind.campaign if campaign_id is not None else ResourceKind.workspace
        ),
        id=campaign_id or workspace_id,
        workspace_id=workspace_id,
    )
    for capability in (
        Capability.marketing_campaign_view,
        Capability.marketing_content_view,
    ):
        decision = await authorization_service.decide_capability(
            session,
            actor=actor,
            workspace=workspace_id,
            capability=capability,
            resource=resource,
        )
        if not decision.allowed:
            raise CampaignCalendarAuthorizationError(decision.reason)


def _validate_query(query: CampaignCalendarEventQuery) -> ZoneInfo:
    _require_aware_datetime(query.start, "start")
    _require_aware_datetime(query.end, "end")
    try:
        timezone = ZoneInfo(query.timezone)
    except ZoneInfoNotFoundError as exc:
        raise CampaignCalendarValidationError(
            "Invalid campaign calendar timezone"
        ) from exc
    if query.end < query.start:
        raise CampaignCalendarValidationError(
            "Campaign calendar end must be after start"
        )
    return timezone


def _validate_pagination(*, limit: int, offset: int) -> None:
    if limit < 1 or limit > MAX_CAMPAIGN_CALENDAR_LIMIT:
        raise CampaignCalendarValidationError(
            "Campaign calendar limit must be between 1 and 1000"
        )
    if offset < 0:
        raise CampaignCalendarValidationError(
            "Campaign calendar offset must be greater than or equal to 0"
        )


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CampaignCalendarValidationError(
            f"Campaign calendar {field_name} must be timezone-aware"
        )


async def _normalize_event(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    actor: AuthorizationActorInput | None,
    event: campaign_calendar.CampaignCalendarEvent,
    timezone: ZoneInfo,
) -> NormalizedCampaignCalendarEvent:
    source_id = str(event.source_id)
    parent_id = _source_parent_id(event)
    starts_at, date_value, all_day = _event_start(event.event_at, timezone)
    approval = await _approval_context(
        session,
        workspace_id=workspace_id,
        actor=actor,
        event=event,
    )
    sort_key = _sort_key(starts_at, event.event_type, event.source_id)
    return NormalizedCampaignCalendarEvent(
        id=_deterministic_event_id(event),
        event_type=event.event_type,
        source_type=_normalized_source_type(event.source_type),
        source_id=source_id,
        source_parent_id=parent_id,
        title=event.title,
        description=None,
        starts_at=starts_at.isoformat(),
        ends_at=None,
        date=date_value,
        all_day=all_day,
        timezone=timezone.key,
        status=event.status,
        campaign=_campaign_context(event),
        artist=_artist_context(event),
        release=_release_context(event),
        channel=_channel_context(event),
        approval=approval,
        url=None,
        sort_key=sort_key,
    )


def _event_start(
    event_at: date | datetime,
    timezone: ZoneInfo,
) -> tuple[datetime, str | None, bool]:
    if isinstance(event_at, datetime):
        starts_at = _aware_utc(event_at).astimezone(timezone)
        return starts_at, None, False
    starts_at = datetime.combine(event_at, time.min, tzinfo=timezone)
    return starts_at, event_at.isoformat(), True


def _normalized_event_in_range(
    event: NormalizedCampaignCalendarEvent,
    start: datetime,
    end: datetime,
    timezone: ZoneInfo,
) -> bool:
    if event.all_day:
        if event.date is None:
            return False
        event_date = date.fromisoformat(event.date)
        return (
            start.astimezone(timezone).date()
            <= event_date
            <= end.astimezone(timezone).date()
        )
    starts_at = datetime.fromisoformat(event.starts_at)
    starts_at_utc = starts_at.astimezone(UTC)
    return start.astimezone(UTC) <= starts_at_utc <= end.astimezone(UTC)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _campaign_context(
    event: campaign_calendar.CampaignCalendarEvent,
) -> CampaignCalendarCampaignContext | None:
    return CampaignCalendarCampaignContext(
        id=str(event.campaign_id),
        name=event.campaign_name,
        status=event.campaign_status,
        campaign_type=event.campaign_type,
    )


def _artist_context(
    event: campaign_calendar.CampaignCalendarEvent,
) -> CampaignCalendarArtistContext | None:
    if event.artist_id is None or event.artist_name is None:
        return None
    return CampaignCalendarArtistContext(
        id=str(event.artist_id),
        name=event.artist_name,
    )


def _release_context(
    event: campaign_calendar.CampaignCalendarEvent,
) -> CampaignCalendarReleaseContext | None:
    if event.release_id is None or event.release_title is None:
        return None
    return CampaignCalendarReleaseContext(
        id=str(event.release_id),
        title=event.release_title,
        artist_id=(
            str(event.release_artist_id)
            if event.release_artist_id is not None
            else str(event.artist_id) if event.artist_id is not None else None
        ),
    )


def _channel_context(
    event: campaign_calendar.CampaignCalendarEvent,
) -> CampaignCalendarChannelContext | None:
    if event.channel_id is None or event.channel is None or event.placement is None:
        return None
    return CampaignCalendarChannelContext(
        id=str(event.channel_id),
        channel=event.channel,
        placement=event.placement,
    )


async def _approval_context(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    actor: AuthorizationActorInput | None,
    event: campaign_calendar.CampaignCalendarEvent,
) -> CampaignCalendarApprovalContext | None:
    request = getattr(event, "approval_request", None)
    if request is None:
        request_id = event.approval_request_id
        if request_id is None:
            return None
        request = await approval_service.get_approval_request(
            session,
            workspace_id,
            request_id,
            actor=actor,
        )
    state = _enum_value(request.status)
    actions = ()
    if actor is not None:
        actions = tuple(
            action.value
            for action in await approval_service.available_actions_for_request(
                session,
                workspace_id,
                request,
                actor=actor,
            )
        )
    approved_revision_is_current = None
    can_schedule = None
    if request.resource_type == MARKETING_CONTENT_ITEM_RESOURCE_TYPE:
        adapter = get_approval_resource_adapter(request.resource_type)
        resource = await adapter.resolve(session, workspace_id, request.resource_id)
        if resource is not None:
            approved_revision_is_current = adapter.approved_revision_is_current(
                resource,
                request,
            )
            can_schedule = (
                state == "approved"
                and approved_revision_is_current
                and _has_schedule_target(resource)
            )
    return CampaignCalendarApprovalContext(
        request_id=str(request.id),
        state=state,
        label=request.title,
        approved_revision_is_current=approved_revision_is_current,
        can_schedule=can_schedule,
        available_actions=actions,
    )


def _has_schedule_target(resource: object) -> bool:
    return bool(
        getattr(resource, "scheduled_at", None) is not None
        or any(
            getattr(channel, "scheduled_at", None) is not None
            for channel in getattr(resource, "channels", ())
        )
    )


def _deterministic_event_id(
    event: campaign_calendar.CampaignCalendarEvent,
) -> str:
    source_id = str(event.source_id)
    if event.event_type == campaign_calendar.CAMPAIGN_START:
        return f"campaign:{source_id}:start"
    if event.event_type == campaign_calendar.CAMPAIGN_TARGET_END:
        return f"campaign:{source_id}:target_end"
    if event.event_type == campaign_calendar.CAMPAIGN_MILESTONE_TARGET:
        return f"campaign_milestone:{source_id}:target"
    if event.event_type == campaign_calendar.MARKETING_CONTENT_SCHEDULED:
        return f"marketing_content:{source_id}:scheduled"
    if event.event_type == campaign_calendar.MARKETING_CONTENT_PUBLISHED:
        return f"marketing_content:{source_id}:published"
    if event.event_type == campaign_calendar.MARKETING_CONTENT_CHANNEL_SCHEDULED:
        return f"marketing_content_channel:{source_id}:scheduled"
    if event.event_type == campaign_calendar.MARKETING_CONTENT_CHANNEL_PUBLISHED:
        return f"marketing_content_channel:{source_id}:published"
    if event.event_type == campaign_calendar.MARKETING_CONTENT_APPROVAL_REQUESTED:
        return f"approval_request:{source_id}:requested"
    if event.event_type == campaign_calendar.MARKETING_CONTENT_APPROVED:
        return f"approval_request:{source_id}:approved"
    return f"{event.source_type}:{source_id}:{event.event_type}"


def _source_parent_id(event: campaign_calendar.CampaignCalendarEvent) -> str | None:
    if event.source_type in {"campaign_milestone", "marketing_content_item"}:
        return str(event.campaign_id)
    if event.source_type == "marketing_content_item_channel":
        return str(event.content_item_id) if event.content_item_id is not None else None
    if event.source_type == "approval_request":
        return str(event.content_item_id) if event.content_item_id is not None else None
    return None


def _normalized_source_type(source_type: str) -> str:
    if source_type == "marketing_content_item_channel":
        return "marketing_content_channel"
    return source_type


def _sort_key(starts_at: datetime, event_type: str, source_id: UUID) -> str:
    return f"{starts_at.astimezone(UTC).isoformat()}|{event_type}|{source_id}"


def _enum_value(value: object) -> str | None:
    if value is None:
        return None
    return value.value if isinstance(value, Enum) else str(value)
