from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from labelos_database.models import (
    ApprovalDecision,
    ApprovalDecisionValue,
    ApprovalRequest,
    ApprovalRequestStage,
    ApprovalRequestStatus,
    MarketingContentItem,
    WorkspaceMembership,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from labelos_api.auth import CurrentUserContext, SessionDep, get_current_user_context
from labelos_api.repositories.approval_resources import (
    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
    UnsupportedApprovalResourceTypeError,
    get_approval_resource_adapter,
)
from labelos_api.services import approval_service, marketing_content_service
from labelos_api.services.approval_service import (
    ApprovalAgentDecisionDeniedError,
    ApprovalAlreadyResolvedError,
    ApprovalDuplicateActiveRequestError,
    ApprovalInvalidTransitionError,
    ApprovalMissingCapabilityError,
    ApprovalRequestNotFoundError,
    ApprovalResourceNotFoundError,
    ApprovalSelfApprovalError,
    ApprovalServiceError,
    ApprovalStaleResourceRevisionError,
    ApprovalUnsupportedResourceTypeError,
)
from labelos_api.services.marketing_content_service import (
    MarketingContentAuthorizationError,
    MarketingContentNotFoundError,
)

router = APIRouter(prefix="/workspaces", tags=["approvals"])


class ApprovalDecisionAction(StrEnum):
    approved = "approved"
    rejected = "rejected"
    changes_requested = "changes_requested"
    cancelled = "cancelled"


class ApprovalSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str | None = Field(default=None, max_length=4000)
    metadata: dict[str, Any] | None = None


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ApprovalDecisionAction
    reason: str | None = Field(default=None, max_length=4000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def require_reason_for_negative_decisions(self) -> ApprovalDecisionRequest:
        if self.action in {
            ApprovalDecisionAction.rejected,
            ApprovalDecisionAction.changes_requested,
        } and not _clean_text(self.reason):
            raise ValueError("A reason is required for this approval decision")
        return self


class ApprovalAssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assigned_profile_id: UUID | None = None


class ApprovalActorResponse(BaseModel):
    user_id: UUID | None
    profile_id: UUID | None
    actor_kind: str | None = None
    actor_key: str | None = None
    display_name: str | None = None


class ApprovalStageResponse(BaseModel):
    id: UUID
    stage_order: int
    required_capability: str
    status: str
    assigned_profile_id: UUID | None
    started_at: datetime | None
    completed_at: datetime | None


class ApprovalDecisionResponse(BaseModel):
    id: UUID
    stage_id: UUID | None
    decision: ApprovalDecisionValue
    decided_by_user_id: UUID | None
    decided_by_profile_id: UUID | None
    actor_kind: str
    actor_key: str | None
    reason: str | None
    payload: dict[str, Any]
    created_at: datetime


class ApprovalContextResponse(BaseModel):
    id: UUID | None
    name: str | None


class ApprovalChannelPlacementResponse(BaseModel):
    channel: str
    placement: str


class MarketingContentApprovalPreviewResponse(BaseModel):
    id: UUID
    title: str
    content_type: str
    copy_text: str | None
    asset_refs: list[Any]
    status: str
    current_revision: int
    approved_revision: int | None


class ApprovalRequestSummaryResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    resource_type: str
    resource_id: UUID
    submitted_revision: int
    status: ApprovalRequestStatus
    current_stage: ApprovalStageResponse | None
    stage_assignment: ApprovalActorResponse | None
    submitter: ApprovalActorResponse
    title: str
    summary: str | None
    submitted_at: datetime
    resolved_at: datetime | None
    campaign: ApprovalContextResponse | None
    artist: ApprovalContextResponse | None


class ApprovalRequestListResponse(BaseModel):
    approvals: list[ApprovalRequestSummaryResponse]
    total: int
    limit: int
    offset: int


class ApprovalRequestDetailResponse(ApprovalRequestSummaryResponse):
    current_resource_revision: int | None
    is_stale: bool
    decision_history: list[ApprovalDecisionResponse]
    marketing_content_preview: MarketingContentApprovalPreviewResponse | None
    release: ApprovalContextResponse | None
    channels: list[ApprovalChannelPlacementResponse]
    available_actions: list[ApprovalDecisionAction]


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


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


def _service_error(exc: ApprovalServiceError) -> NoReturn:
    if isinstance(exc, ApprovalMissingCapabilityError):
        _raise_capability_denial(exc.reason)
    if isinstance(
        exc,
        (
            ApprovalRequestNotFoundError,
            ApprovalResourceNotFoundError,
        ),
    ):
        raise _not_found() from exc
    if isinstance(exc, ApprovalUnsupportedResourceTypeError):
        raise _bad_request("Unsupported approval resource type") from exc
    if isinstance(
        exc,
        (
            ApprovalAlreadyResolvedError,
            ApprovalDuplicateActiveRequestError,
            ApprovalInvalidTransitionError,
            ApprovalSelfApprovalError,
            ApprovalStaleResourceRevisionError,
            ApprovalAgentDecisionDeniedError,
        ),
    ):
        raise _conflict(str(exc)) from exc
    raise _bad_request(str(exc)) from exc


def _stage_response(stage: ApprovalRequestStage) -> ApprovalStageResponse:
    return ApprovalStageResponse(
        id=stage.id,
        stage_order=stage.stage_order,
        required_capability=stage.required_capability,
        status=stage.status.value,
        assigned_profile_id=stage.assigned_profile_id,
        started_at=stage.started_at,
        completed_at=stage.completed_at,
    )


def _current_stage(request: ApprovalRequest) -> ApprovalRequestStage | None:
    for stage in request.stages:
        if stage.stage_order == request.current_stage_order:
            return stage
    return None


def _submitter_response(request: ApprovalRequest) -> ApprovalActorResponse:
    profile = request.requested_by_profile
    return ApprovalActorResponse(
        user_id=request.requested_by_user_id,
        profile_id=request.requested_by_profile_id,
        actor_kind=request.submitted_by_actor_kind,
        actor_key=request.submitted_by_actor_key,
        display_name=profile.display_name if profile is not None else None,
    )


def _assignment_response(
    stage: ApprovalRequestStage | None,
) -> ApprovalActorResponse | None:
    if stage is None or stage.assigned_profile_id is None:
        return None
    profile = stage.assigned_profile
    return ApprovalActorResponse(
        user_id=getattr(profile, "user_id", None),
        profile_id=stage.assigned_profile_id,
        display_name=profile.display_name if profile is not None else None,
    )


def _decision_response(decision: ApprovalDecision) -> ApprovalDecisionResponse:
    return ApprovalDecisionResponse(
        id=decision.id,
        stage_id=decision.stage_id,
        decision=decision.decision,
        decided_by_user_id=decision.decided_by_user_id,
        decided_by_profile_id=decision.decided_by_profile_id,
        actor_kind=decision.actor_kind,
        actor_key=decision.actor_key,
        reason=decision.reason,
        payload=dict(decision.payload),
        created_at=decision.created_at,
    )


def _request_context(resource: object) -> tuple[
    ApprovalContextResponse | None,
    ApprovalContextResponse | None,
    ApprovalContextResponse | None,
    list[ApprovalChannelPlacementResponse],
]:
    if not isinstance(resource, MarketingContentItem):
        return None, None, None, []
    campaign = (
        ApprovalContextResponse(id=resource.campaign_id, name=resource.campaign.name)
        if resource.campaign is not None
        else None
    )
    artist = (
        ApprovalContextResponse(id=resource.artist_id, name=resource.artist.name)
        if resource.artist is not None
        else None
    )
    release = (
        ApprovalContextResponse(id=resource.release_id, name=resource.release.title)
        if resource.release is not None
        else None
    )
    channels = [
        ApprovalChannelPlacementResponse(
            channel=channel.channel,
            placement=channel.placement,
        )
        for channel in resource.channels
    ]
    return campaign, artist, release, channels


def _preview(resource: object) -> MarketingContentApprovalPreviewResponse | None:
    if not isinstance(resource, MarketingContentItem):
        return None
    return MarketingContentApprovalPreviewResponse(
        id=resource.id,
        title=resource.title,
        content_type=resource.content_type,
        copy_text=resource.copy_text,
        asset_refs=list(resource.asset_refs),
        status=resource.status.value,
        current_revision=resource.content_revision,
        approved_revision=resource.approved_revision,
    )


async def _load_resource_for_response(
    session: SessionDep,
    *,
    workspace_id: UUID,
    request: ApprovalRequest,
) -> tuple[object | None, int | None]:
    try:
        adapter = get_approval_resource_adapter(request.resource_type)
        resource = await adapter.resolve(session, workspace_id, request.resource_id)
    except UnsupportedApprovalResourceTypeError as exc:
        raise _bad_request("Unsupported approval resource type") from exc
    if resource is None:
        return None, None
    return resource, adapter.current_revision(resource)


async def _summary_response(
    session: SessionDep,
    *,
    workspace_id: UUID,
    request: ApprovalRequest,
) -> ApprovalRequestSummaryResponse:
    resource, _current_revision = await _load_resource_for_response(
        session,
        workspace_id=workspace_id,
        request=request,
    )
    campaign, artist, _release, _channels = _request_context(resource)
    stage = _current_stage(request)
    return ApprovalRequestSummaryResponse(
        id=request.id,
        workspace_id=request.organization_id,
        resource_type=request.resource_type,
        resource_id=request.resource_id,
        submitted_revision=request.resource_revision,
        status=request.status,
        current_stage=_stage_response(stage) if stage is not None else None,
        stage_assignment=_assignment_response(stage),
        submitter=_submitter_response(request),
        title=request.title,
        summary=request.summary,
        submitted_at=request.submitted_at,
        resolved_at=request.resolved_at,
        campaign=campaign,
        artist=artist,
    )


async def _detail_response(
    session: SessionDep,
    *,
    workspace_id: UUID,
    request: ApprovalRequest,
    context: CurrentUserContext,
) -> ApprovalRequestDetailResponse:
    resource, current_revision = await _load_resource_for_response(
        session,
        workspace_id=workspace_id,
        request=request,
    )
    campaign, artist, release, channels = _request_context(resource)
    stage = _current_stage(request)
    actions = await approval_service.available_actions_for_request(
        session,
        workspace_id,
        request,
        actor=context,
    )
    return ApprovalRequestDetailResponse(
        id=request.id,
        workspace_id=request.organization_id,
        resource_type=request.resource_type,
        resource_id=request.resource_id,
        submitted_revision=request.resource_revision,
        current_resource_revision=current_revision,
        is_stale=(
            current_revision is not None
            and current_revision != request.resource_revision
        ),
        status=request.status,
        current_stage=_stage_response(stage) if stage is not None else None,
        stage_assignment=_assignment_response(stage),
        submitter=_submitter_response(request),
        decision_history=[
            _decision_response(decision) for decision in request.decisions
        ],
        marketing_content_preview=_preview(resource),
        title=request.title,
        summary=request.summary,
        submitted_at=request.submitted_at,
        resolved_at=request.resolved_at,
        campaign=campaign,
        artist=artist,
        release=release,
        channels=channels,
        available_actions=[ApprovalDecisionAction(action.value) for action in actions],
    )


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


async def _idempotent_decision_response(
    session: SessionDep,
    *,
    workspace_id: UUID,
    approval_request_id: UUID,
    payload: ApprovalDecisionRequest,
    context: CurrentUserContext,
) -> ApprovalRequestDetailResponse | None:
    if payload.idempotency_key is None:
        return None
    history = await approval_service.get_approval_history(
        session,
        workspace_id,
        approval_request_id,
        actor=context,
    )
    for decision in history:
        if decision.payload.get("idempotency_key") != payload.idempotency_key:
            continue
        if decision.decision.value != payload.action.value:
            raise _conflict(
                "idempotency_key was already used with a different approval action"
            )
        request = await approval_service.get_approval_request(
            session,
            workspace_id,
            approval_request_id,
            actor=context,
        )
        return await _detail_response(
            session,
            workspace_id=workspace_id,
            request=request,
            context=context,
        )
    return None


@router.get("/{workspace_id}/approvals", response_model=ApprovalRequestListResponse)
async def list_approvals(
    workspace_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    status_filter: Annotated[
        ApprovalRequestStatus | None,
        Query(alias="status"),
    ] = None,
    resource_type: str | None = None,
    campaign_id: UUID | None = None,
    artist_id: UUID | None = None,
    submitter_user_id: UUID | None = None,
    submitter_profile_id: UUID | None = None,
    assigned_reviewer_profile_id: UUID | None = None,
    assigned_to_me: bool = False,
    submitted_by_me: bool = False,
    submitted_start: datetime | None = None,
    submitted_end: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApprovalRequestListResponse:
    try:
        _require_timezone(submitted_start)
        _require_timezone(submitted_end)
        page = await approval_service.list_approval_requests(
            session,
            workspace_id,
            actor=context,
            query=approval_service.ApprovalRequestQuery(
                status=status_filter,
                resource_type=resource_type,
                requested_by_user_id=submitter_user_id,
                requested_by_profile_id=submitter_profile_id,
                assigned_profile_id=assigned_reviewer_profile_id,
                submitted_by_current_actor=submitted_by_me,
                assigned_to_current_profile=assigned_to_me,
                campaign_id=campaign_id,
                artist_id=artist_id,
                submitted_start=submitted_start,
                submitted_end=submitted_end,
            ),
            limit=limit,
            offset=offset,
        )
    except (ApprovalServiceError, ValueError) as exc:
        if isinstance(exc, ApprovalServiceError):
            _service_error(exc)
        raise _bad_request(str(exc)) from exc
    return ApprovalRequestListResponse(
        approvals=[
            await _summary_response(
                session,
                workspace_id=workspace_id,
                request=request,
            )
            for request in page.items
        ],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{workspace_id}/approvals/{approval_request_id}",
    response_model=ApprovalRequestDetailResponse,
)
async def get_approval(
    workspace_id: UUID,
    approval_request_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> ApprovalRequestDetailResponse:
    try:
        request = await approval_service.get_approval_request(
            session,
            workspace_id,
            approval_request_id,
            actor=context,
        )
    except ApprovalServiceError as exc:
        _service_error(exc)
    return await _detail_response(
        session,
        workspace_id=workspace_id,
        request=request,
        context=context,
    )


@router.post(
    "/{workspace_id}/approvals/{approval_request_id}/decisions",
    response_model=ApprovalRequestDetailResponse,
)
async def submit_approval_decision(
    workspace_id: UUID,
    approval_request_id: UUID,
    payload: ApprovalDecisionRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> ApprovalRequestDetailResponse:
    try:
        idempotent = await _idempotent_decision_response(
            session,
            workspace_id=workspace_id,
            approval_request_id=approval_request_id,
            payload=payload,
            context=context,
        )
        if idempotent is not None:
            return idempotent
        decision_payload = (
            {"idempotency_key": payload.idempotency_key}
            if payload.idempotency_key is not None
            else None
        )
        if payload.action == ApprovalDecisionAction.approved:
            request = await approval_service.approve_request(
                session,
                workspace_id,
                approval_request_id,
                actor=context,
                comment=payload.reason,
                decision_payload=decision_payload,
            )
        elif payload.action == ApprovalDecisionAction.rejected:
            request = await approval_service.reject_request(
                session,
                workspace_id,
                approval_request_id,
                actor=context,
                comment=payload.reason,
                decision_payload=decision_payload,
            )
        elif payload.action == ApprovalDecisionAction.changes_requested:
            request = await approval_service.request_changes(
                session,
                workspace_id,
                approval_request_id,
                actor=context,
                comment=payload.reason,
                decision_payload=decision_payload,
            )
        else:
            request = await approval_service.cancel_request(
                session,
                workspace_id,
                approval_request_id,
                actor=context,
                reason=payload.reason,
                decision_payload=decision_payload,
            )
    except ApprovalServiceError as exc:
        _service_error(exc)
    return await _detail_response(
        session,
        workspace_id=workspace_id,
        request=request,
        context=context,
    )


@router.post(
    "/{workspace_id}/approvals/{approval_request_id}/assign",
    response_model=ApprovalRequestDetailResponse,
)
async def assign_approval(
    workspace_id: UUID,
    approval_request_id: UUID,
    payload: ApprovalAssignRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> ApprovalRequestDetailResponse:
    try:
        request = await approval_service.assign_stage_reviewer(
            session,
            workspace_id,
            approval_request_id,
            payload.assigned_profile_id,
            actor=context,
        )
    except ApprovalServiceError as exc:
        _service_error(exc)
    return await _detail_response(
        session,
        workspace_id=workspace_id,
        request=request,
        context=context,
    )


@router.post(
    "/{workspace_id}/campaigns/{campaign_id}/marketing-content/{content_id}/approval-requests",
    response_model=ApprovalRequestDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_campaign_marketing_content_approval_request(
    workspace_id: UUID,
    campaign_id: UUID,
    content_id: UUID,
    payload: ApprovalSubmitRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> ApprovalRequestDetailResponse:
    membership = await _current_workspace_membership(
        session,
        context=context,
        workspace_id=workspace_id,
    )
    if membership is None:
        raise _not_found()
    try:
        await marketing_content_service.get_campaign_content_item(
            session,
            workspace_id,
            campaign_id,
            content_id,
            actor=context,
        )
        request = await approval_service.submit_resource_for_approval(
            session,
            workspace_id,
            MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
            content_id,
            actor=context,
            summary=payload.summary,
            metadata_json=payload.metadata,
        )
    except (MarketingContentNotFoundError, MarketingContentAuthorizationError) as exc:
        if isinstance(exc, MarketingContentAuthorizationError):
            _raise_capability_denial(exc.reason)
        raise _not_found() from exc
    except ApprovalServiceError as exc:
        _service_error(exc)
    return await _detail_response(
        session,
        workspace_id=workspace_id,
        request=request,
        context=context,
    )
