from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from labelos_api.auth import CurrentUserContext, SessionDep, get_current_user_context
from labelos_api.services import campaign_calendar_service
from labelos_api.services.campaign_calendar_service import (
    MAX_CAMPAIGN_CALENDAR_LIMIT,
    CampaignCalendarAuthorizationError,
    CampaignCalendarEventQuery,
    CampaignCalendarValidationError,
    NormalizedCampaignCalendarEvent,
)

router = APIRouter(prefix="/workspaces", tags=["campaign-calendar"])


class CampaignCalendarCampaignContextResponse(BaseModel):
    id: UUID
    name: str
    status: str
    campaign_type: str


class CampaignCalendarArtistContextResponse(BaseModel):
    id: UUID
    name: str


class CampaignCalendarReleaseContextResponse(BaseModel):
    id: UUID
    title: str
    artist_id: UUID | None


class CampaignCalendarChannelContextResponse(BaseModel):
    id: UUID
    channel: str
    placement: str


class CampaignCalendarApprovalContextResponse(BaseModel):
    request_id: UUID | None
    state: str | None
    label: str | None
    approved_revision_is_current: bool | None
    can_schedule: bool | None
    available_actions: list[str]


class CampaignCalendarEventResponse(BaseModel):
    id: str
    event_type: str
    source_type: str
    source_id: UUID
    source_parent_id: UUID | None
    title: str
    description: str | None
    starts_at: datetime
    ends_at: datetime | None
    date: str | None
    all_day: bool
    timezone: str
    status: str | None
    campaign: CampaignCalendarCampaignContextResponse | None
    artist: CampaignCalendarArtistContextResponse | None
    release: CampaignCalendarReleaseContextResponse | None
    channel: CampaignCalendarChannelContextResponse | None
    approval: CampaignCalendarApprovalContextResponse | None
    url: str | None
    sort_key: str


class CampaignCalendarResponse(BaseModel):
    workspace_id: UUID
    start: datetime
    end: datetime
    timezone: str
    events: list[CampaignCalendarEventResponse]
    total: int
    limit: int
    offset: int


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _raise_capability_denial(reason: str) -> NoReturn:
    if reason in {"invalid_resource_scope", "membership_not_found"}:
        raise _not_found()
    if reason == "insufficient_department_access":
        raise _forbidden("Insufficient department access")
    raise _forbidden("Insufficient capability permission")


def _service_error(
    exc: CampaignCalendarAuthorizationError | CampaignCalendarValidationError,
) -> NoReturn:
    if isinstance(exc, CampaignCalendarAuthorizationError):
        _raise_capability_denial(exc.reason)
    raise _bad_request(str(exc)) from exc


def _event_types(values: list[str] | None) -> tuple[str, ...] | None:
    if values is None:
        return None
    event_types = tuple(
        event_type.strip()
        for value in values
        for event_type in value.split(",")
        if event_type.strip()
    )
    return event_types or None


def _event_response(
    event: NormalizedCampaignCalendarEvent,
) -> CampaignCalendarEventResponse:
    data = asdict(event)
    if data["approval"] is not None:
        data["approval"]["available_actions"] = list(
            data["approval"]["available_actions"]
        )
    return CampaignCalendarEventResponse.model_validate(data)


@router.get(
    "/{workspace_id}/campaign-calendar",
    response_model=CampaignCalendarResponse,
)
async def list_campaign_calendar(
    workspace_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    start: datetime,
    end: datetime,
    timezone: str = "UTC",
    campaign_id: UUID | None = None,
    artist_id: UUID | None = None,
    release_id: UUID | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    event_types: Annotated[list[str] | None, Query()] = None,
    include_archived: bool = False,
    include_published: bool = False,
    limit: Annotated[int, Query(ge=1, le=MAX_CAMPAIGN_CALENDAR_LIMIT)] = 1000,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CampaignCalendarResponse:
    try:
        page = await campaign_calendar_service.list_campaign_calendar_events(
            session,
            workspace_id,
            actor=context,
            query=CampaignCalendarEventQuery(
                start=start,
                end=end,
                timezone=timezone,
                campaign_id=campaign_id,
                artist_id=artist_id,
                release_id=release_id,
                event_types=_event_types(event_types),
                statuses=(status_filter,) if status_filter is not None else None,
                include_archived=include_archived,
                include_published=include_published,
            ),
            limit=limit,
            offset=offset,
        )
    except (CampaignCalendarAuthorizationError, CampaignCalendarValidationError) as exc:
        _service_error(exc)
    return CampaignCalendarResponse(
        workspace_id=workspace_id,
        start=start,
        end=end,
        timezone=timezone,
        events=[_event_response(event) for event in page.events],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
