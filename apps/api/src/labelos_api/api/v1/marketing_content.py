from datetime import UTC, datetime
from typing import Annotated, Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from labelos_database.models import (
    ApprovalRequestStatus,
    MarketingContentItem,
    MarketingContentItemChannel,
    MarketingContentItemStatus,
    WorkspaceMembership,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError
from sqlalchemy import select

from labelos_api.auth import CurrentUserContext, SessionDep, get_current_user_context
from labelos_api.scheduling.timezones import ScheduleValidationError, utc_instant
from labelos_api.services import marketing_content_service
from labelos_api.services.marketing_content_service import (
    MarketingContentAuthorizationError,
    MarketingContentChannelCreate,
    MarketingContentChannelReplacement,
    MarketingContentItemCreate,
    MarketingContentItemQuery,
    MarketingContentItemUpdate,
    MarketingContentLifecycleError,
    MarketingContentNotFoundError,
    MarketingContentRelationshipError,
)
from labelos_api.services.social_account_service import (
    DestinationUnavailableReason,
    ResolvedDestination,
    resolved_destination_for_connection,
)

router = APIRouter(prefix="/workspaces", tags=["marketing-content"])


class MarketingContentChannelCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: str = Field(min_length=1, max_length=80)
    placement: str | None = Field(default=None, max_length=80)
    social_account_connection_id: UUID | None = None
    scheduled_at: datetime | None = None
    schedule_timezone: str | None = None
    schedule_local_time: str | None = None
    schedule_disambiguation: str | None = None
    schedule_offset_seconds: int | None = None
    copy_text_override: str | None = Field(default=None, max_length=8000)
    asset_refs: list[Any] | None = None

    @field_validator("scheduled_at", mode="before")
    @classmethod
    def require_timezone(cls, value: datetime | str | None) -> datetime | None:
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

    @field_validator("scheduled_at", mode="before")
    @classmethod
    def require_timezone(cls, value: datetime | str | None) -> datetime | None:
        return _require_timezone(value)


class MarketingContentChannelReplacementRequest(MarketingContentChannelCreateRequest):
    id: UUID | None = None


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
    channels: list[MarketingContentChannelReplacementRequest] | None = None

    @field_validator("scheduled_at", mode="before")
    @classmethod
    def require_timezone(cls, value: datetime | str | None) -> datetime | None:
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
    social_account_connection_id: UUID | None
    scheduled_at: datetime | None
    schedule_generation: int
    schedule_timezone: str | None = None
    schedule_local_time: str | None = None
    schedule_offset_seconds: int | None = None
    published_at: datetime | None
    external_post_id: str | None
    external_url: str | None
    copy_text_override: str | None
    asset_refs: list[Any]
    metadata: dict[str, Any]
    destination_readiness: "MarketingContentDestinationReadinessResponse"
    created_at: datetime
    updated_at: datetime


class MarketingContentDestinationAccountResponse(BaseModel):
    id: UUID
    provider: str
    handle: str | None
    display_name: str | None
    connection_method: str
    status: str


class MarketingContentDestinationReadinessResponse(BaseModel):
    planning_valid: bool
    delivery_ready: bool
    status: str
    label: str
    warning: str | None
    account: MarketingContentDestinationAccountResponse | None


class MarketingContentApprovalStateResponse(BaseModel):
    state: str
    label: str
    approval_request_id: UUID | None
    current_revision: int
    approved_revision: int | None
    approved_revision_is_current: bool
    can_schedule: bool


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
    approval_state: MarketingContentApprovalStateResponse
    content_revision: int
    approved_revision: int | None
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


def _require_timezone(value: datetime | str | None) -> datetime | None:
    try:
        return utc_instant(value) if value is not None else None
    except ScheduleValidationError as exc:
        raise PydanticCustomError(exc.code, "{message}", {"message": str(exc)}) from exc


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
        | ScheduleValidationError
        | MarketingContentAuthorizationError
    ),
) -> NoReturn:
    if isinstance(exc, ScheduleValidationError):
        raise exc
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
    if isinstance(channel, MarketingContentChannelReplacementRequest):
        return MarketingContentChannelReplacement(**channel.model_dump())
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


def _stored_schedule_instant(value: datetime | None) -> datetime | None:
    # Only for persisted UTC schedule columns: SQLite drops their tzinfo on read.
    # Untrusted authoring timestamps must instead pass utc_instant unchanged.
    if value is None:
        return None
    return utc_instant(value.replace(tzinfo=UTC) if value.tzinfo is None else value)


def _channel_response(
    channel: MarketingContentItemChannel,
) -> MarketingContentChannelResponse:
    return MarketingContentChannelResponse(
        id=channel.id,
        marketing_content_item_id=channel.marketing_content_item_id,
        channel=channel.channel,
        placement=channel.placement,
        social_account_connection_id=channel.social_account_connection_id,
        scheduled_at=_stored_schedule_instant(channel.scheduled_at),
        schedule_generation=channel.schedule_generation,
        schedule_timezone=channel.schedule_timezone,
        schedule_local_time=channel.schedule_local_time,
        schedule_offset_seconds=channel.schedule_offset_seconds,
        published_at=channel.published_at,
        external_post_id=channel.external_post_id,
        external_url=channel.external_url,
        copy_text_override=channel.copy_text_override,
        asset_refs=list(channel.asset_refs),
        metadata=dict(channel.metadata_json),
        destination_readiness=_destination_readiness(channel),
        created_at=channel.created_at,
        updated_at=channel.updated_at,
    )


def _destination_readiness(
    channel: MarketingContentItemChannel,
) -> MarketingContentDestinationReadinessResponse:
    connection = channel.social_account_connection
    if channel.social_account_connection_id is None or connection is None:
        return MarketingContentDestinationReadinessResponse(
            planning_valid=True,
            delivery_ready=False,
            status="missing_account",
            label="No Account Selected",
            warning=(
                "Missing account is a delivery warning; content planning remains "
                "valid."
            ),
            account=None,
        )
    destination = resolved_destination_for_connection(
        connection,
        workspace_id=connection.organization_id,
        provider=channel.channel,
    )
    return _destination_readiness_response(destination)


def _destination_readiness_response(
    destination: ResolvedDestination,
) -> MarketingContentDestinationReadinessResponse:
    account = destination.account
    publishing_capable = bool(
        destination.supports_automatic_publication
        or destination.requires_assisted_publication
    )
    reasons = list(destination.unavailable_reasons)
    if not publishing_capable:
        reasons.append(DestinationUnavailableReason.missing_capability)
    unique_reasons = tuple(dict.fromkeys(reasons))
    delivery_ready = destination.usable and publishing_capable
    if delivery_ready and destination.supports_automatic_publication:
        status = "ready"
        label = "Ready"
        warning = None
    elif delivery_ready and destination.requires_assisted_publication:
        status = "assisted"
        label = "Assisted Publishing"
        warning = "Delivery requires assisted publishing."
    else:
        status = _destination_unavailable_status(unique_reasons)
        label = _destination_unavailable_label(status)
        warning = _destination_unavailable_warning(status)
    return MarketingContentDestinationReadinessResponse(
        planning_valid=True,
        delivery_ready=delivery_ready,
        status=status,
        label=label,
        warning=warning,
        account=MarketingContentDestinationAccountResponse(
            id=account.id,
            provider=account.provider,
            handle=account.username,
            display_name=account.display_name,
            connection_method=account.connection_method.value,
            status=account.status.value,
        ),
    )


def _destination_unavailable_status(
    reasons: tuple[DestinationUnavailableReason, ...],
) -> str:
    if DestinationUnavailableReason.disconnected in reasons:
        return "disconnected"
    if DestinationUnavailableReason.reconnect_required in reasons:
        return "reconnect_required"
    if DestinationUnavailableReason.connection_error in reasons:
        return "connection_error"
    if DestinationUnavailableReason.missing_capability in reasons:
        return "missing_capability"
    if DestinationUnavailableReason.provider_mismatch in reasons:
        return "provider_mismatch"
    if DestinationUnavailableReason.wrong_artist in reasons:
        return "wrong_artist"
    if DestinationUnavailableReason.wrong_workspace in reasons:
        return "wrong_workspace"
    return "unavailable"


def _destination_unavailable_label(status_value: str) -> str:
    labels = {
        "disconnected": "Disconnected",
        "reconnect_required": "Reconnect Required",
        "connection_error": "Connection Error",
        "missing_capability": "Missing Publishing Capability",
        "provider_mismatch": "Provider Mismatch",
        "wrong_artist": "Wrong Artist",
        "wrong_workspace": "Wrong Workspace",
    }
    return labels.get(status_value, "Unavailable")


def _destination_unavailable_warning(status_value: str) -> str:
    warnings = {
        "disconnected": (
            "Selected account is disconnected; choose another account before "
            "delivery."
        ),
        "reconnect_required": "Selected account must be reconnected before delivery.",
        "connection_error": "Selected account needs attention before delivery.",
        "missing_capability": "Selected account cannot publish this content.",
        "provider_mismatch": "Selected account provider does not match this channel.",
        "wrong_artist": "Selected account is attached to a different artist.",
        "wrong_workspace": "Selected account belongs to a different workspace.",
    }
    return warnings.get(status_value, "Selected account is not delivery ready.")


def _approval_state(
    item: MarketingContentItem,
) -> MarketingContentApprovalStateResponse:
    approval_request = item.approval_request
    approved_revision_is_current = (
        item.approved_revision is not None
        and item.approved_revision == item.content_revision
        and approval_request is not None
        and approval_request.status == ApprovalRequestStatus.approved
    )
    can_schedule = (
        item.status == MarketingContentItemStatus.approved
        and approved_revision_is_current
        and _has_schedule_target(item)
    )
    if item.status in {
        MarketingContentItemStatus.published,
        MarketingContentItemStatus.cancelled,
        MarketingContentItemStatus.archived,
    }:
        state = item.status.value
        label = item.status.value.replace("_", " ").title()
    elif approved_revision_is_current:
        state = "approved"
        label = "Approved"
    elif approval_request is not None and approval_request.status in {
        ApprovalRequestStatus.requested,
        ApprovalRequestStatus.in_review,
    }:
        state = "in_review"
        label = "In review"
    elif (
        approval_request is not None
        and approval_request.status == ApprovalRequestStatus.changes_requested
    ):
        state = "changes_requested"
        label = "Changes requested"
    elif (
        item.approved_revision is not None
        and item.approved_revision != item.content_revision
    ):
        state = "reapproval_required"
        label = "Reapproval required"
    else:
        state = item.status.value
        label = item.status.value.replace("_", " ").title()
    return MarketingContentApprovalStateResponse(
        state=state,
        label=label,
        approval_request_id=item.approval_request_id,
        current_revision=item.content_revision,
        approved_revision=item.approved_revision,
        approved_revision_is_current=approved_revision_is_current,
        can_schedule=can_schedule,
    )


def _has_schedule_target(item: MarketingContentItem) -> bool:
    return bool(
        item.scheduled_at is not None
        or any(channel.scheduled_at is not None for channel in item.channels)
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
        scheduled_at=_stored_schedule_instant(item.scheduled_at),
        published_at=item.published_at,
        approval_requested_at=item.approval_requested_at,
        approval_request_id=item.approval_request_id,
        approval_state=_approval_state(item),
        content_revision=item.content_revision,
        approved_revision=item.approved_revision,
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
    owner_profile_id: UUID | None = None,
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
                owner_profile_id=owner_profile_id,
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
        ScheduleValidationError,
        MarketingContentLifecycleError,
        MarketingContentAuthorizationError,
        ValueError,
    ) as exc:
        if isinstance(exc, ValueError) and not isinstance(
            exc,
            (
                MarketingContentNotFoundError,
                MarketingContentRelationshipError,
                ScheduleValidationError,
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
        ScheduleValidationError,
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
        ScheduleValidationError,
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
        if payload.channels is not None:
            item = await marketing_content_service.update_content_item_with_channels(
                session,
                workspace_id,
                content_id,
                _update_payload(payload),
                [_channel_create(channel) for channel in payload.channels],
                actor=context,
            )
        else:
            item = await marketing_content_service.update_content_item(
                session,
                workspace_id,
                content_id,
                _update_payload(payload),
                actor=context,
            )
    except (
        MarketingContentNotFoundError,
        MarketingContentRelationshipError,
        ScheduleValidationError,
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
        ScheduleValidationError,
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
