from datetime import datetime
from typing import Annotated, Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from labelos_database.models import (
    MarketingContentItem,
    MarketingContentItemChannel,
    MarketingContentItemStatus,
    WorkspaceMembership,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from labelos_api.auth import CurrentUserContext, SessionDep, get_current_user_context
from labelos_api.services import marketing_content_service
from labelos_api.services.marketing_content_service import (
    MarketingContentAuthorizationError,
    MarketingContentChannelCreate,
    MarketingContentItemCreate,
    MarketingContentItemQuery,
    MarketingContentItemUpdate,
    MarketingContentLifecycleError,
    MarketingContentNotFoundError,
    MarketingContentRelationshipError,
)

router = APIRouter(prefix="/workspaces", tags=["marketing-content"])


class MarketingContentChannelCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: str = Field(min_length=1, max_length=80)
    placement: str | None = Field(default=None, max_length=80)
    scheduled_at: datetime | None = None
    copy_text_override: str | None = Field(default=None, max_length=8000)
    asset_refs: list[Any] | None = None

    @field_validator("scheduled_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        return _require_timezone(value)


class MarketingContentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=240)
    content_type: str = Field(min_length=1, max_length=80)
    copy_text: str | None = Field(default=None, max_length=8000)
    asset_refs: list[Any] | None = None
    artist_id: UUID | None = None
    release_id: UUID | None = None
    owner_profile_id: UUID | None = None
    scheduled_at: datetime | None = None
    channels: list[MarketingContentChannelCreateRequest] = Field(default_factory=list)

    @field_validator("scheduled_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        return _require_timezone(value)


class MarketingContentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=240)
    content_type: str | None = Field(default=None, min_length=1, max_length=80)
    copy_text: str | None = Field(default=None, max_length=8000)
    asset_refs: list[Any] | None = None
    artist_id: UUID | None = None
    release_id: UUID | None = None
    owner_profile_id: UUID | None = None
    scheduled_at: datetime | None = None
    channels: list[MarketingContentChannelCreateRequest] | None = None

    @field_validator("scheduled_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        return _require_timezone(value)

    @model_validator(mode="after")
    def require_update(self) -> "MarketingContentUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one marketing content field is required")
        return self


class MarketingContentStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: MarketingContentItemStatus
    approved_by_profile_id: UUID | None = None


class MarketingContentChannelResponse(BaseModel):
    id: UUID
    marketing_content_item_id: UUID
    channel: str
    placement: str
    scheduled_at: datetime | None
    published_at: datetime | None
    external_post_id: str | None
    external_url: str | None
    copy_text_override: str | None
    asset_refs: list[Any]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class MarketingContentResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    campaign_id: UUID
    title: str
    content_type: str
    copy_text: str | None
    asset_refs: list[Any]
    metadata: dict[str, Any]
    status: MarketingContentItemStatus
    artist_id: UUID | None
    release_id: UUID | None
    owner_profile_id: UUID | None
    created_by_user_id: UUID | None
    created_by_profile_id: UUID | None
    scheduled_at: datetime | None
    published_at: datetime | None
    approval_requested_at: datetime | None
    approval_request_id: UUID | None
    approved_at: datetime | None
    approved_by_profile_id: UUID | None
    channels: list[MarketingContentChannelResponse]
    created_at: datetime
    updated_at: datetime


class MarketingContentListResponse(BaseModel):
    marketing_content: list[MarketingContentResponse]
    total: int
    limit: int
    offset: int


def _require_timezone(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("Datetime must include timezone information")
    return value


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _raise_capability_denial(reason: str) -> NoReturn:
    if reason in {"invalid_resource_scope", "membership_not_found"}:
        raise _not_found()
    if reason == "insufficient_department_access":
        raise _forbidden("Insufficient department access")
    raise _forbidden("Insufficient capability permission")


def _service_error(
    exc: (
        MarketingContentNotFoundError
        | MarketingContentRelationshipError
        | MarketingContentLifecycleError
        | MarketingContentAuthorizationError
    ),
) -> NoReturn:
    if isinstance(exc, MarketingContentAuthorizationError):
        _raise_capability_denial(exc.reason)
    if isinstance(exc, MarketingContentNotFoundError):
        raise _not_found() from exc
    if isinstance(exc, MarketingContentLifecycleError):
        raise _conflict(str(exc)) from exc
    raise _bad_request(str(exc)) from exc


async def _current_workspace_membership(
    session: SessionDep,
    *,
    context: CurrentUserContext,
    workspace_id: UUID,
) -> WorkspaceMembership | None:
    return await session.scalar(
        select(WorkspaceMembership)
        .join(WorkspaceMembership.profile)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.status == "active")
        .where(WorkspaceMembership.profile.has(user_id=context.user.id))
    )


def _channel_create(
    channel: MarketingContentChannelCreateRequest,
) -> MarketingContentChannelCreate:
    return MarketingContentChannelCreate(**channel.model_dump())


def _create_payload(
    campaign_id: UUID,
    payload: MarketingContentCreateRequest,
    *,
    context: CurrentUserContext,
    created_by_profile_id: UUID,
) -> MarketingContentItemCreate:
    values = payload.model_dump(exclude={"channels"})
    return MarketingContentItemCreate(
        campaign_id=campaign_id,
        **values,
        created_by_user_id=context.user.id,
        created_by_profile_id=created_by_profile_id,
        channels=[_channel_create(channel) for channel in payload.channels],
    )


def _update_payload(
    payload: MarketingContentUpdateRequest,
) -> MarketingContentItemUpdate:
    values = payload.model_dump(exclude_unset=True, exclude={"channels"})
    fields = payload.model_fields_set
    return MarketingContentItemUpdate(
        **{key: value for key, value in values.items() if value is not None},
        clear_artist=("artist_id" in fields and payload.artist_id is None),
        clear_release=("release_id" in fields and payload.release_id is None),
        clear_copy_text=("copy_text" in fields and payload.copy_text is None),
        clear_scheduled_at=("scheduled_at" in fields and payload.scheduled_at is None),
        clear_owner_profile=(
            "owner_profile_id" in fields and payload.owner_profile_id is None
        ),
        material_change=True,
    )


def _channel_response(
    channel: MarketingContentItemChannel,
) -> MarketingContentChannelResponse:
    return MarketingContentChannelResponse(
        id=channel.id,
        marketing_content_item_id=channel.marketing_content_item_id,
        channel=channel.channel,
        placement=channel.placement,
        scheduled_at=channel.scheduled_at,
        published_at=channel.published_at,
        external_post_id=channel.external_post_id,
        external_url=channel.external_url,
        copy_text_override=channel.copy_text_override,
        asset_refs=list(channel.asset_refs),
        metadata=dict(channel.metadata_json),
        created_at=channel.created_at,
        updated_at=channel.updated_at,
    )


def _content_response(item: MarketingContentItem) -> MarketingContentResponse:
    return MarketingContentResponse(
        id=item.id,
        workspace_id=item.organization_id,
        campaign_id=item.campaign_id,
        title=item.title,
        content_type=item.content_type,
        copy_text=item.copy_text,
        asset_refs=list(item.asset_refs),
        metadata=dict(item.metadata_json),
        status=item.status,
        artist_id=item.artist_id,
        release_id=item.release_id,
        owner_profile_id=item.owner_profile_id,
        created_by_user_id=item.created_by_user_id,
        created_by_profile_id=item.created_by_profile_id,
        scheduled_at=item.scheduled_at,
        published_at=item.published_at,
        approval_requested_at=item.approval_requested_at,
        approval_request_id=item.approval_request_id,
        approved_at=item.approved_at,
        approved_by_profile_id=item.approved_by_profile_id,
        channels=[_channel_response(channel) for channel in item.channels],
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _list_response(page) -> MarketingContentListResponse:
    return MarketingContentListResponse(
        marketing_content=[_content_response(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


async def _assert_campaign_scoped_item(
    session: SessionDep,
    *,
    workspace_id: UUID,
    campaign_id: UUID,
    content_id: UUID,
    context: CurrentUserContext,
) -> None:
    try:
        await marketing_content_service.get_campaign_content_item(
            session,
            workspace_id,
            campaign_id,
            content_id,
            actor=context,
        )
    except (
        MarketingContentNotFoundError,
        MarketingContentAuthorizationError,
    ) as exc:
        _service_error(exc)


@router.get(
    "/{workspace_id}/marketing-content",
    response_model=MarketingContentListResponse,
)
async def list_workspace_marketing_content(
    workspace_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    start: datetime | None = None,
    end: datetime | None = None,
    campaign_id: UUID | None = None,
    artist_id: UUID | None = None,
    release_id: UUID | None = None,
    status: MarketingContentItemStatus | None = None,
    channel: str | None = None,
    content_type: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MarketingContentListResponse:
    try:
        _require_timezone(start)
        _require_timezone(end)
        page = await marketing_content_service.list_content_items(
            session,
            workspace_id,
            actor=context,
            query=MarketingContentItemQuery(
                campaign_id=campaign_id,
                artist_id=artist_id,
                release_id=release_id,
                status=status,
                channel=channel,
                content_type=content_type,
                scheduled_start=start,
                scheduled_end=end,
            ),
            limit=limit,
            offset=offset,
        )
    except (
        MarketingContentNotFoundError,
        MarketingContentRelationshipError,
        MarketingContentLifecycleError,
        MarketingContentAuthorizationError,
        ValueError,
    ) as exc:
        if isinstance(exc, ValueError) and not isinstance(
            exc,
            (
                MarketingContentNotFoundError,
                MarketingContentRelationshipError,
                MarketingContentLifecycleError,
                MarketingContentAuthorizationError,
            ),
        ):
            raise _bad_request(str(exc)) from exc
        _service_error(exc)
    return _list_response(page)


@router.get(
    "/{workspace_id}/campaigns/{campaign_id}/marketing-content",
    response_model=MarketingContentListResponse,
)
async def list_campaign_marketing_content(
    workspace_id: UUID,
    campaign_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MarketingContentListResponse:
    try:
        page = await marketing_content_service.list_campaign_content_items(
            session,
            workspace_id,
            campaign_id,
            actor=context,
            limit=limit,
            offset=offset,
        )
    except (
        MarketingContentNotFoundError,
        MarketingContentRelationshipError,
        MarketingContentAuthorizationError,
    ) as exc:
        _service_error(exc)
    return _list_response(page)


@router.post(
    "/{workspace_id}/campaigns/{campaign_id}/marketing-content",
    response_model=MarketingContentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_marketing_content(
    workspace_id: UUID,
    campaign_id: UUID,
    payload: MarketingContentCreateRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> MarketingContentResponse:
    membership = await _current_workspace_membership(
        session,
        context=context,
        workspace_id=workspace_id,
    )
    if membership is None:
        raise _not_found()
    try:
        item = await marketing_content_service.create_content_item(
            session,
            workspace_id,
            _create_payload(
                campaign_id,
                payload,
                context=context,
                created_by_profile_id=membership.profile_id,
            ),
            actor=context,
        )
    except (
        MarketingContentNotFoundError,
        MarketingContentRelationshipError,
        MarketingContentAuthorizationError,
    ) as exc:
        _service_error(exc)
    return _content_response(item)


@router.get(
    "/{workspace_id}/campaigns/{campaign_id}/marketing-content/{content_id}",
    response_model=MarketingContentResponse,
)
async def get_marketing_content(
    workspace_id: UUID,
    campaign_id: UUID,
    content_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> MarketingContentResponse:
    try:
        item = await marketing_content_service.get_campaign_content_item(
            session,
            workspace_id,
            campaign_id,
            content_id,
            actor=context,
        )
    except (
        MarketingContentNotFoundError,
        MarketingContentAuthorizationError,
    ) as exc:
        _service_error(exc)
    return _content_response(item)


@router.patch(
    "/{workspace_id}/campaigns/{campaign_id}/marketing-content/{content_id}",
    response_model=MarketingContentResponse,
)
async def update_marketing_content(
    workspace_id: UUID,
    campaign_id: UUID,
    content_id: UUID,
    payload: MarketingContentUpdateRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> MarketingContentResponse:
    await _assert_campaign_scoped_item(
        session,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        content_id=content_id,
        context=context,
    )
    try:
        item = await marketing_content_service.update_content_item(
            session,
            workspace_id,
            content_id,
            _update_payload(payload),
            actor=context,
        )
        if payload.channels is not None:
            item = await marketing_content_service.replace_channels(
                session,
                workspace_id,
                content_id,
                [_channel_create(channel) for channel in payload.channels],
                actor=context,
            )
    except (
        MarketingContentNotFoundError,
        MarketingContentRelationshipError,
        MarketingContentLifecycleError,
        MarketingContentAuthorizationError,
    ) as exc:
        _service_error(exc)
    return _content_response(item)


@router.patch(
    "/{workspace_id}/campaigns/{campaign_id}/marketing-content/{content_id}/status",
    response_model=MarketingContentResponse,
)
async def update_marketing_content_status(
    workspace_id: UUID,
    campaign_id: UUID,
    content_id: UUID,
    payload: MarketingContentStatusUpdateRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> MarketingContentResponse:
    await _assert_campaign_scoped_item(
        session,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        content_id=content_id,
        context=context,
    )
    approved_by_profile_id = payload.approved_by_profile_id
    if (
        payload.status == MarketingContentItemStatus.approved
        and approved_by_profile_id is None
    ):
        membership = await _current_workspace_membership(
            session,
            context=context,
            workspace_id=workspace_id,
        )
        if membership is None:
            raise _not_found()
        approved_by_profile_id = membership.profile_id
    try:
        item = await marketing_content_service.transition_status(
            session,
            workspace_id,
            content_id,
            payload.status,
            actor=context,
            approved_by_profile_id=approved_by_profile_id,
        )
    except (
        MarketingContentNotFoundError,
        MarketingContentRelationshipError,
        MarketingContentLifecycleError,
        MarketingContentAuthorizationError,
    ) as exc:
        _service_error(exc)
    return _content_response(item)


@router.post(
    "/{workspace_id}/campaigns/{campaign_id}/marketing-content/{content_id}/archive",
    response_model=MarketingContentResponse,
)
async def archive_marketing_content(
    workspace_id: UUID,
    campaign_id: UUID,
    content_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> MarketingContentResponse:
    await _assert_campaign_scoped_item(
        session,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        content_id=content_id,
        context=context,
    )
    try:
        item = await marketing_content_service.archive_content_item(
            session,
            workspace_id,
            content_id,
            actor=context,
        )
    except (
        MarketingContentNotFoundError,
        MarketingContentLifecycleError,
        MarketingContentAuthorizationError,
    ) as exc:
        _service_error(exc)
    return _content_response(item)
