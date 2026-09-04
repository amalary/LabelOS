from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from labelos_database.capabilities import Capability
from labelos_database.models import (
    ApprovalDecision,
    ApprovalDecisionValue,
    ApprovalRequest,
    ApprovalRequestStage,
    ApprovalRequestStatus,
    ApprovalStageStatus,
    MarketingContentItem,
    MarketingContentItemStatus,
    UniversalProfile,
    User,
    WorkspaceMembership,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from labelos_api.authorization import (
    ActorKind,
    AuthorizationActorInput,
    AuthorizationResource,
    ResourceKind,
    authorization_service,
)
from labelos_api.realtime import RealtimeEventType, RealtimePublisher
from labelos_api.repositories import approvals
from labelos_api.repositories.approval_resources import (
    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
    ApprovalResourceAdapter,
    UnsupportedApprovalResourceTypeError,
    get_approval_resource_adapter,
)


class ApprovalServiceError(ValueError):
    """Base error for approval queue business-rule failures."""


class ApprovalRequestNotFoundError(ApprovalServiceError):
    pass


class ApprovalResourceNotFoundError(ApprovalServiceError):
    pass


class ApprovalUnsupportedResourceTypeError(ApprovalServiceError):
    pass


class ApprovalInvalidTransitionError(ApprovalServiceError):
    pass


class ApprovalDuplicateActiveRequestError(ApprovalServiceError):
    pass


class ApprovalStaleResourceRevisionError(ApprovalServiceError):
    pass


class ApprovalMissingCapabilityError(ApprovalServiceError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ApprovalSelfApprovalError(ApprovalServiceError):
    pass


class ApprovalAgentDecisionDeniedError(ApprovalServiceError):
    pass


class ApprovalAlreadyResolvedError(ApprovalServiceError):
    pass


MAX_APPROVAL_LIST_LIMIT = 500
ACTIVE_STATUSES = approvals.ACTIVE_REQUEST_STATUSES
TERMINAL_STATUSES = frozenset(
    {
        ApprovalRequestStatus.approved,
        ApprovalRequestStatus.rejected,
        ApprovalRequestStatus.cancelled,
    }
)


@dataclass(frozen=True, kw_only=True)
class ApprovalRequestQuery:
    status: ApprovalRequestStatus | str | None = None
    resource_type: str | None = None
    requested_by_user_id: UUID | None = None
    requested_by_profile_id: UUID | None = None
    assigned_profile_id: UUID | None = None
    current_profile_id: UUID | None = None
    submitted_by_current_actor: bool = False
    assigned_to_current_profile: bool = False
    campaign_id: UUID | None = None
    artist_id: UUID | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _coerce_request_status(
    status: ApprovalRequestStatus | str,
) -> ApprovalRequestStatus:
    try:
        return (
            status
            if isinstance(status, ApprovalRequestStatus)
            else ApprovalRequestStatus(status)
        )
    except ValueError as exc:
        raise ApprovalInvalidTransitionError("Invalid approval request status") from exc


def _validate_list_pagination(*, limit: int, offset: int) -> None:
    if limit < 1 or limit > MAX_APPROVAL_LIST_LIMIT:
        raise ApprovalInvalidTransitionError(
            "Approval request list limit must be between 1 and 500"
        )
    if offset < 0:
        raise ApprovalInvalidTransitionError(
            "Approval request list offset must be greater than or equal to 0"
        )


def _adapter(resource_type: str) -> ApprovalResourceAdapter:
    try:
        return get_approval_resource_adapter(resource_type)
    except UnsupportedApprovalResourceTypeError as exc:
        raise ApprovalUnsupportedResourceTypeError(str(exc)) from exc


def _capability(value: str) -> Capability:
    try:
        return Capability(value)
    except ValueError as exc:
        raise ApprovalMissingCapabilityError("unknown_capability") from exc


def _actor_user(actor: AuthorizationActorInput | None) -> User | None:
    if isinstance(actor, User):
        return actor
    user = getattr(actor, "user", None)
    return user if isinstance(user, User) else None


def _actor_user_id(actor: AuthorizationActorInput | None) -> UUID | None:
    if isinstance(actor, UUID):
        return actor
    user = _actor_user(actor)
    return user.id if user is not None else None


async def _actor_profile_id(
    session: AsyncSession,
    *,
    actor: AuthorizationActorInput | None,
    workspace_id: UUID,
) -> UUID | None:
    explicit_profile_id = getattr(actor, "profile_id", None)
    if isinstance(explicit_profile_id, UUID):
        return explicit_profile_id
    active_membership = getattr(actor, "active_membership", None)
    if active_membership is not None:
        profile_id = getattr(active_membership, "profile_id", None)
        if isinstance(profile_id, UUID):
            return profile_id
    user_id = _actor_user_id(actor)
    if user_id is None:
        return None
    return await session.scalar(
        select(WorkspaceMembership.profile_id)
        .join(WorkspaceMembership.profile)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.status == "active")
        .where(UniversalProfile.user_id == user_id)
    )


def _actor_kind(actor: AuthorizationActorInput | None) -> str:
    actor_ref = getattr(actor, "authorization_actor", None)
    kind = getattr(actor_ref, "kind", None)
    if kind is not None:
        return str(kind.value if isinstance(kind, ActorKind) else kind)
    return "user"


def _actor_key(actor: AuthorizationActorInput | None) -> str | None:
    actor_ref = getattr(actor, "authorization_actor", None)
    subject = getattr(actor_ref, "subject", None)
    if isinstance(subject, str) and subject:
        return subject
    if isinstance(actor, UUID):
        return str(actor)
    user = _actor_user(actor)
    if user is not None:
        return user.email or str(user.id)
    principal = getattr(actor, "principal", None)
    principal_subject = getattr(principal, "subject", None)
    return principal_subject if isinstance(principal_subject, str) else None


def _resource_context(
    *,
    adapter: ApprovalResourceAdapter,
    resource: object,
    workspace_id: UUID,
) -> AuthorizationResource:
    context = adapter.context(resource)
    resource_id = context.campaign_id or workspace_id
    return AuthorizationResource(
        kind=(
            ResourceKind.campaign
            if context.campaign_id is not None
            else ResourceKind.workspace
        ),
        id=resource_id,
        workspace_id=workspace_id,
    )


async def _require_capability(
    session: AsyncSession,
    *,
    actor: AuthorizationActorInput | None,
    workspace_id: UUID,
    capability: str,
    adapter: ApprovalResourceAdapter,
    resource: object,
) -> None:
    _capability(capability)
    if actor is None:
        return
    decision = await authorization_service.decide_capability(
        session,
        actor=actor,
        workspace=workspace_id,
        capability=capability,
        resource=_resource_context(
            adapter=adapter,
            resource=resource,
            workspace_id=workspace_id,
        ),
    )
    if not decision.allowed:
        raise ApprovalMissingCapabilityError(decision.reason)


async def _load_resource(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    resource_type: str,
    resource_id: UUID,
) -> tuple[ApprovalResourceAdapter, object]:
    adapter = _adapter(resource_type)
    resource = await adapter.resolve(session, workspace_id, resource_id)
    if resource is None:
        raise ApprovalResourceNotFoundError("Approval resource not found")
    return adapter, resource


async def _load_request(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    approval_request_id: UUID,
) -> ApprovalRequest:
    request = await approvals.get_request_with_stages_and_decisions(
        session,
        workspace_id,
        approval_request_id,
    )
    if request is None:
        raise ApprovalRequestNotFoundError("Approval request not found")
    return request


async def _lock_request(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    approval_request_id: UUID,
) -> ApprovalRequest:
    request = await session.scalar(
        select(ApprovalRequest)
        .options(
            selectinload(ApprovalRequest.stages).selectinload(
                ApprovalRequestStage.decisions
            ),
            selectinload(ApprovalRequest.decisions),
        )
        .where(ApprovalRequest.organization_id == workspace_id)
        .where(ApprovalRequest.id == approval_request_id)
        .with_for_update()
    )
    if request is None:
        raise ApprovalRequestNotFoundError("Approval request not found")
    return request


def _current_stage(request: ApprovalRequest) -> ApprovalRequestStage:
    for stage in request.stages:
        if stage.stage_order == request.current_stage_order:
            return stage
    raise ApprovalInvalidTransitionError("Current approval stage not found")


def _assert_active(request: ApprovalRequest) -> None:
    if request.status in TERMINAL_STATUSES:
        raise ApprovalAlreadyResolvedError("Approval request is already resolved")
    if request.status not in ACTIVE_STATUSES:
        raise ApprovalInvalidTransitionError("Approval request is not active")


async def _guarded_lifecycle_transition(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    request: ApprovalRequest,
    stage: ApprovalRequestStage,
    request_status: ApprovalRequestStatus,
    stage_status: ApprovalStageStatus,
    resolved_at: datetime,
    allowed_stage_statuses: frozenset[ApprovalStageStatus],
) -> None:
    request_result = await session.execute(
        update(ApprovalRequest)
        .where(ApprovalRequest.organization_id == workspace_id)
        .where(ApprovalRequest.id == request.id)
        .where(ApprovalRequest.status.in_(ACTIVE_STATUSES))
        .values(status=request_status, resolved_at=resolved_at)
    )
    if request_result.rowcount != 1:
        raise ApprovalAlreadyResolvedError("Approval request is already resolved")

    stage_result = await session.execute(
        update(ApprovalRequestStage)
        .where(ApprovalRequestStage.id == stage.id)
        .where(ApprovalRequestStage.approval_request_id == request.id)
        .where(ApprovalRequestStage.status.in_(allowed_stage_statuses))
        .values(status=stage_status, completed_at=resolved_at)
    )
    if stage_result.rowcount != 1:
        raise ApprovalAlreadyResolvedError("Approval request is already resolved")

    request.status = request_status
    request.resolved_at = resolved_at
    stage.status = stage_status
    stage.completed_at = resolved_at


def _assert_not_self_approval(
    request: ApprovalRequest,
    *,
    actor_user_id: UUID | None,
    actor_profile_id: UUID | None,
    actor_key: str | None,
) -> None:
    if actor_user_id is not None and actor_user_id == request.requested_by_user_id:
        raise ApprovalSelfApprovalError("Submitter cannot approve their own revision")
    if (
        actor_profile_id is not None
        and actor_profile_id == request.requested_by_profile_id
    ):
        raise ApprovalSelfApprovalError("Submitter cannot approve their own revision")
    if (
        actor_key is not None
        and request.submitted_by_actor_key is not None
        and actor_key == request.submitted_by_actor_key
    ):
        raise ApprovalSelfApprovalError("Submitter cannot approve their own revision")


async def _assert_profile_in_workspace(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    profile_id: UUID,
) -> None:
    found = await session.scalar(
        select(WorkspaceMembership.id)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.profile_id == profile_id)
        .where(WorkspaceMembership.status == "active")
    )
    if found is None:
        raise ApprovalResourceNotFoundError("Reviewer profile not found")


def _decision_values(
    *,
    request: ApprovalRequest,
    stage: ApprovalRequestStage | None,
    decision: ApprovalDecisionValue,
    actor: AuthorizationActorInput | None,
    actor_user_id: UUID | None,
    actor_profile_id: UUID | None,
    reason: str | None,
    payload: dict | None = None,
) -> dict[str, object]:
    values: dict[str, object] = {
        "stage_id": stage.id if stage is not None else None,
        "decision": decision,
        "decided_by_user_id": actor_user_id,
        "decided_by_profile_id": actor_profile_id,
        "actor_kind": _actor_kind(actor),
        "actor_key": _actor_key(actor),
        "reason": reason,
        "payload": payload or {},
        "created_at": _now(),
    }
    return {key: value for key, value in values.items() if value is not None}


async def _append_decision(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    request: ApprovalRequest,
    stage: ApprovalRequestStage | None,
    decision: ApprovalDecisionValue,
    actor: AuthorizationActorInput | None,
    actor_user_id: UUID | None,
    actor_profile_id: UUID | None,
    reason: str | None,
    payload: dict | None = None,
) -> ApprovalDecision:
    appended = await approvals.append_decision(
        session,
        workspace_id,
        request.id,
        _decision_values(
            request=request,
            stage=stage,
            decision=decision,
            actor=actor,
            actor_user_id=actor_user_id,
            actor_profile_id=actor_profile_id,
            reason=reason,
            payload=payload,
        ),
    )
    if appended is None:
        raise ApprovalRequestNotFoundError("Approval request not found")
    return appended


async def _publish_approval_event(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    request: ApprovalRequest,
    stage: ApprovalRequestStage | None,
    actor: AuthorizationActorInput | None,
    resource: object | None,
) -> None:
    payload = {
        "approvalRequestId": str(request.id),
        "resourceType": request.resource_type,
        "resourceId": str(request.resource_id),
        "resourceRevision": request.resource_revision,
        "status": request.status.value,
        "stageStatus": stage.status.value if stage is not None else None,
        "actorKind": _actor_kind(actor),
    }
    if isinstance(resource, MarketingContentItem):
        payload["contentItemId"] = str(resource.id)
        payload["campaignId"] = str(resource.campaign_id)
    await RealtimePublisher(session).publish(
        organization_id=workspace_id,
        event_type=RealtimeEventType.approval_updated,
        actor=_actor_user(actor),
        entity_type="approval_request",
        entity_id=request.id,
        payload=payload,
    )


def _submission_projection(
    request: ApprovalRequest,
    resource: object,
) -> None:
    if isinstance(resource, MarketingContentItem):
        resource.status = MarketingContentItemStatus.in_review
        resource.approval_request_id = request.id
        resource.approval_requested_at = request.submitted_at


def _decision_projection(
    request: ApprovalRequest,
    resource: object,
    *,
    decision: ApprovalDecisionValue,
    actor_profile_id: UUID | None,
    decided_at: datetime,
) -> None:
    if not isinstance(resource, MarketingContentItem):
        return
    resource.approval_request_id = request.id
    if decision == ApprovalDecisionValue.approved:
        resource.status = MarketingContentItemStatus.approved
        resource.approved_revision = request.resource_revision
        resource.approved_at = decided_at
        resource.approved_by_profile_id = actor_profile_id
    elif decision in {
        ApprovalDecisionValue.changes_requested,
        ApprovalDecisionValue.rejected,
    }:
        resource.status = MarketingContentItemStatus.draft
    elif decision == ApprovalDecisionValue.cancelled:
        resource.status = MarketingContentItemStatus.cancelled
    elif decision == ApprovalDecisionValue.invalidated:
        resource.status = MarketingContentItemStatus.draft
        resource.approval_request_id = None


async def submit_resource_for_approval(
    session: AsyncSession,
    workspace_id: UUID,
    resource_type: str,
    resource_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    summary: str | None = None,
    metadata_json: dict | None = None,
) -> ApprovalRequest:
    adapter, resource = await _load_resource(
        session,
        workspace_id=workspace_id,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=adapter.capabilities.submit,
        adapter=adapter,
        resource=resource,
    )
    actor_user_id = _actor_user_id(actor)
    actor_profile_id = await _actor_profile_id(
        session,
        actor=actor,
        workspace_id=workspace_id,
    )
    submitted_at = _now()
    revision = adapter.current_revision(resource)
    existing = await approvals.find_active_request_for_resource_revision(
        session,
        workspace_id,
        resource_type,
        resource_id,
        revision,
    )
    if existing is not None:
        raise ApprovalDuplicateActiveRequestError(
            "An active approval request already exists for this resource revision"
        )
    if not adapter.is_eligible_for_submission(resource):
        raise ApprovalInvalidTransitionError("Resource is not eligible for approval")
    queue_summary = adapter.queue_summary(resource)
    try:
        request = await approvals.create_request(
            session,
            workspace_id,
            {
                "resource_type": resource_type,
                "resource_id": resource_id,
                "resource_revision": revision,
                "status": ApprovalRequestStatus.in_review,
                "requested_by_user_id": actor_user_id,
                "requested_by_profile_id": actor_profile_id,
                "submitted_by_actor_kind": _actor_kind(actor),
                "submitted_by_actor_key": _actor_key(actor),
                "title": queue_summary.title,
                "summary": summary,
                "metadata_json": metadata_json or {},
                "submitted_at": submitted_at,
            },
        )
    except approvals.DuplicateActiveApprovalRequestError as exc:
        raise ApprovalDuplicateActiveRequestError(str(exc)) from exc
    stage = await approvals.create_initial_stage(
        session,
        workspace_id,
        request.id,
        {
            "required_capability": adapter.capabilities.approve,
            "status": ApprovalStageStatus.in_review,
            "started_at": submitted_at,
        },
    )
    if stage is None:
        raise ApprovalRequestNotFoundError("Approval request not found")
    await _append_decision(
        session,
        workspace_id=workspace_id,
        request=request,
        stage=stage,
        decision=ApprovalDecisionValue.submitted,
        actor=actor,
        actor_user_id=actor_user_id,
        actor_profile_id=actor_profile_id,
        reason=summary,
        payload={"resourceRevision": revision},
    )
    _submission_projection(request, resource)
    await _publish_approval_event(
        session,
        workspace_id=workspace_id,
        request=request,
        stage=stage,
        actor=actor,
        resource=resource,
    )
    await session.commit()
    return await _load_request(
        session,
        workspace_id=workspace_id,
        approval_request_id=request.id,
    )


async def get_approval_request(
    session: AsyncSession,
    workspace_id: UUID,
    approval_request_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> ApprovalRequest:
    request = await _load_request(
        session,
        workspace_id=workspace_id,
        approval_request_id=approval_request_id,
    )
    adapter, resource = await _load_resource(
        session,
        workspace_id=workspace_id,
        resource_type=request.resource_type,
        resource_id=request.resource_id,
    )
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=adapter.capabilities.view,
        adapter=adapter,
        resource=resource,
    )
    return request


async def list_approval_requests(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    query: ApprovalRequestQuery | None = None,
    limit: int = 100,
    offset: int = 0,
) -> approvals.ApprovalRequestListPage:
    _validate_list_pagination(limit=limit, offset=offset)
    normalized = query or ApprovalRequestQuery()
    resource_type = normalized.resource_type or MARKETING_CONTENT_ITEM_RESOURCE_TYPE
    adapter, resource = await _list_authorization_resource(
        session,
        workspace_id=workspace_id,
        resource_type=resource_type,
        campaign_id=normalized.campaign_id,
    )
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=adapter.capabilities.view,
        adapter=adapter,
        resource=resource,
    )
    actor_user_id = _actor_user_id(actor)
    actor_profile_id = await _actor_profile_id(
        session,
        actor=actor,
        workspace_id=workspace_id,
    )
    return await approvals.list_requests(
        session,
        workspace_id,
        status=(
            _coerce_request_status(normalized.status)
            if normalized.status is not None
            else None
        ),
        resource_type=normalized.resource_type,
        requested_by_user_id=normalized.requested_by_user_id,
        requested_by_profile_id=normalized.requested_by_profile_id,
        assigned_profile_id=normalized.assigned_profile_id,
        current_profile_id=normalized.current_profile_id or actor_profile_id,
        submitted_by_current_actor=normalized.submitted_by_current_actor,
        current_actor_user_id=actor_user_id,
        current_actor_profile_id=actor_profile_id,
        assigned_to_current_profile=normalized.assigned_to_current_profile,
        campaign_id=normalized.campaign_id,
        artist_id=normalized.artist_id,
        limit=limit,
        offset=offset,
    )


async def _list_authorization_resource(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    resource_type: str,
    campaign_id: UUID | None,
) -> tuple[ApprovalResourceAdapter, object]:
    adapter = _adapter(resource_type)
    if (
        campaign_id is not None
        and resource_type == MARKETING_CONTENT_ITEM_RESOURCE_TYPE
    ):
        item = await session.scalar(
            select(MarketingContentItem)
            .where(MarketingContentItem.organization_id == workspace_id)
            .where(MarketingContentItem.campaign_id == campaign_id)
        )
        if item is not None:
            return adapter, item
    placeholder = MarketingContentItem(
        organization_id=workspace_id,
        campaign_id=campaign_id,
        title="approval queue",
        content_type="queue",
    )
    return adapter, placeholder


async def assign_stage_reviewer(
    session: AsyncSession,
    workspace_id: UUID,
    approval_request_id: UUID,
    assigned_profile_id: UUID | None,
    *,
    actor: AuthorizationActorInput | None = None,
) -> ApprovalRequest:
    request = await _lock_request(
        session,
        workspace_id=workspace_id,
        approval_request_id=approval_request_id,
    )
    _assert_active(request)
    adapter, resource = await _load_resource(
        session,
        workspace_id=workspace_id,
        resource_type=request.resource_type,
        resource_id=request.resource_id,
    )
    stage = _current_stage(request)
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=stage.required_capability,
        adapter=adapter,
        resource=resource,
    )
    if assigned_profile_id is not None:
        await _assert_profile_in_workspace(
            session,
            workspace_id=workspace_id,
            profile_id=assigned_profile_id,
        )
    stage.assigned_profile_id = assigned_profile_id
    await _publish_approval_event(
        session,
        workspace_id=workspace_id,
        request=request,
        stage=stage,
        actor=actor,
        resource=resource,
    )
    await session.commit()
    return await _load_request(
        session,
        workspace_id=workspace_id,
        approval_request_id=approval_request_id,
    )


async def approve_request(
    session: AsyncSession,
    workspace_id: UUID,
    approval_request_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    comment: str | None = None,
) -> ApprovalRequest:
    return await _human_stage_decision(
        session,
        workspace_id=workspace_id,
        approval_request_id=approval_request_id,
        actor=actor,
        comment=comment,
        decision=ApprovalDecisionValue.approved,
        request_status=ApprovalRequestStatus.approved,
        stage_status=ApprovalStageStatus.approved,
    )


async def request_changes(
    session: AsyncSession,
    workspace_id: UUID,
    approval_request_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    comment: str | None = None,
) -> ApprovalRequest:
    return await _human_stage_decision(
        session,
        workspace_id=workspace_id,
        approval_request_id=approval_request_id,
        actor=actor,
        comment=comment,
        decision=ApprovalDecisionValue.changes_requested,
        request_status=ApprovalRequestStatus.changes_requested,
        stage_status=ApprovalStageStatus.changes_requested,
    )


async def reject_request(
    session: AsyncSession,
    workspace_id: UUID,
    approval_request_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    comment: str | None = None,
) -> ApprovalRequest:
    return await _human_stage_decision(
        session,
        workspace_id=workspace_id,
        approval_request_id=approval_request_id,
        actor=actor,
        comment=comment,
        decision=ApprovalDecisionValue.rejected,
        request_status=ApprovalRequestStatus.rejected,
        stage_status=ApprovalStageStatus.rejected,
    )


async def _human_stage_decision(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    approval_request_id: UUID,
    actor: AuthorizationActorInput | None,
    comment: str | None,
    decision: ApprovalDecisionValue,
    request_status: ApprovalRequestStatus,
    stage_status: ApprovalStageStatus,
) -> ApprovalRequest:
    if _actor_kind(actor) == ActorKind.ai_agent.value:
        raise ApprovalAgentDecisionDeniedError(
            "AI agents cannot issue review decisions"
        )
    request = await _lock_request(
        session,
        workspace_id=workspace_id,
        approval_request_id=approval_request_id,
    )
    _assert_active(request)
    stage = _current_stage(request)
    adapter, resource = await _load_resource(
        session,
        workspace_id=workspace_id,
        resource_type=request.resource_type,
        resource_id=request.resource_id,
    )
    if adapter.current_revision(resource) != request.resource_revision:
        raise ApprovalStaleResourceRevisionError(
            "Approval request no longer matches the current resource revision"
        )
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=stage.required_capability,
        adapter=adapter,
        resource=resource,
    )
    actor_user_id = _actor_user_id(actor)
    actor_profile_id = await _actor_profile_id(
        session,
        actor=actor,
        workspace_id=workspace_id,
    )
    _assert_not_self_approval(
        request,
        actor_user_id=actor_user_id,
        actor_profile_id=actor_profile_id,
        actor_key=_actor_key(actor),
    )
    decided_at = _now()
    await _guarded_lifecycle_transition(
        session,
        workspace_id=workspace_id,
        request=request,
        stage=stage,
        request_status=request_status,
        stage_status=stage_status,
        resolved_at=decided_at,
        allowed_stage_statuses=frozenset(
            {ApprovalStageStatus.pending, ApprovalStageStatus.in_review}
        ),
    )
    await _append_decision(
        session,
        workspace_id=workspace_id,
        request=request,
        stage=stage,
        decision=decision,
        actor=actor,
        actor_user_id=actor_user_id,
        actor_profile_id=actor_profile_id,
        reason=comment,
    )
    _decision_projection(
        request,
        resource,
        decision=decision,
        actor_profile_id=actor_profile_id,
        decided_at=decided_at,
    )
    await _publish_approval_event(
        session,
        workspace_id=workspace_id,
        request=request,
        stage=stage,
        actor=actor,
        resource=resource,
    )
    await session.commit()
    return await _load_request(
        session,
        workspace_id=workspace_id,
        approval_request_id=approval_request_id,
    )


async def cancel_request(
    session: AsyncSession,
    workspace_id: UUID,
    approval_request_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    reason: str | None = None,
) -> ApprovalRequest:
    return await _system_or_submitter_resolution(
        session,
        workspace_id=workspace_id,
        approval_request_id=approval_request_id,
        actor=actor,
        reason=reason,
        decision=ApprovalDecisionValue.cancelled,
        request_status=ApprovalRequestStatus.cancelled,
        stage_status=ApprovalStageStatus.cancelled,
    )


async def invalidate_request(
    session: AsyncSession,
    workspace_id: UUID,
    approval_request_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    reason: str | None = None,
) -> ApprovalRequest:
    return await _system_or_submitter_resolution(
        session,
        workspace_id=workspace_id,
        approval_request_id=approval_request_id,
        actor=actor,
        reason=reason,
        decision=ApprovalDecisionValue.invalidated,
        request_status=ApprovalRequestStatus.cancelled,
        stage_status=ApprovalStageStatus.invalidated,
    )


async def _system_or_submitter_resolution(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    approval_request_id: UUID,
    actor: AuthorizationActorInput | None,
    reason: str | None,
    decision: ApprovalDecisionValue,
    request_status: ApprovalRequestStatus,
    stage_status: ApprovalStageStatus,
) -> ApprovalRequest:
    request = await _lock_request(
        session,
        workspace_id=workspace_id,
        approval_request_id=approval_request_id,
    )
    _assert_active(request)
    stage = _current_stage(request)
    adapter, resource = await _load_resource(
        session,
        workspace_id=workspace_id,
        resource_type=request.resource_type,
        resource_id=request.resource_id,
    )
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=adapter.capabilities.submit,
        adapter=adapter,
        resource=resource,
    )
    actor_user_id = _actor_user_id(actor)
    actor_profile_id = await _actor_profile_id(
        session,
        actor=actor,
        workspace_id=workspace_id,
    )
    resolved_at = _now()
    await _guarded_lifecycle_transition(
        session,
        workspace_id=workspace_id,
        request=request,
        stage=stage,
        request_status=request_status,
        stage_status=stage_status,
        resolved_at=resolved_at,
        allowed_stage_statuses=frozenset(
            {
                ApprovalStageStatus.pending,
                ApprovalStageStatus.in_review,
                ApprovalStageStatus.changes_requested,
            }
        ),
    )
    await _append_decision(
        session,
        workspace_id=workspace_id,
        request=request,
        stage=stage,
        decision=decision,
        actor=actor,
        actor_user_id=actor_user_id,
        actor_profile_id=actor_profile_id,
        reason=reason,
    )
    _decision_projection(
        request,
        resource,
        decision=decision,
        actor_profile_id=actor_profile_id,
        decided_at=resolved_at,
    )
    await _publish_approval_event(
        session,
        workspace_id=workspace_id,
        request=request,
        stage=stage,
        actor=actor,
        resource=resource,
    )
    await session.commit()
    return await _load_request(
        session,
        workspace_id=workspace_id,
        approval_request_id=approval_request_id,
    )


async def resubmit_resource(
    session: AsyncSession,
    workspace_id: UUID,
    resource_type: str,
    resource_id: UUID,
    *,
    previous_approval_request_id: UUID,
    actor: AuthorizationActorInput | None = None,
    summary: str | None = None,
) -> ApprovalRequest:
    previous = await _load_request(
        session,
        workspace_id=workspace_id,
        approval_request_id=previous_approval_request_id,
    )
    adapter, resource = await _load_resource(
        session,
        workspace_id=workspace_id,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    if previous.resource_type != resource_type or previous.resource_id != resource_id:
        raise ApprovalInvalidTransitionError(
            "Previous approval request does not belong to resource"
        )
    current_revision = adapter.current_revision(resource)
    if current_revision <= previous.resource_revision:
        raise ApprovalStaleResourceRevisionError(
            "Resubmission must target a newer resource revision"
        )
    new_request = await submit_resource_for_approval(
        session,
        workspace_id,
        resource_type,
        resource_id,
        actor=actor,
        summary=summary,
    )
    actor_user_id = _actor_user_id(actor)
    actor_profile_id = await _actor_profile_id(
        session,
        actor=actor,
        workspace_id=workspace_id,
    )
    await _append_decision(
        session,
        workspace_id=workspace_id,
        request=new_request,
        stage=_current_stage(new_request),
        decision=ApprovalDecisionValue.resubmitted,
        actor=actor,
        actor_user_id=actor_user_id,
        actor_profile_id=actor_profile_id,
        reason=summary,
        payload={"previousApprovalRequestId": str(previous.id)},
    )
    await session.commit()
    return await _load_request(
        session,
        workspace_id=workspace_id,
        approval_request_id=new_request.id,
    )


async def get_approval_history(
    session: AsyncSession,
    workspace_id: UUID,
    approval_request_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> list[ApprovalDecision]:
    request = await get_approval_request(
        session,
        workspace_id,
        approval_request_id,
        actor=actor,
    )
    decisions = await approvals.list_decisions_chronologically(
        session,
        workspace_id,
        request.id,
    )
    if decisions is None:
        raise ApprovalRequestNotFoundError("Approval request not found")
    return decisions
