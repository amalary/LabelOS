from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from labelos_database.models import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalRequestStage,
    ApprovalRequestStatus,
    ApprovalStageStatus,
)
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from labelos_api.repositories.approval_resources import (
    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
    get_approval_resource_adapter,
)

ACTIVE_REQUEST_STATUSES = frozenset(
    {
        ApprovalRequestStatus.requested,
        ApprovalRequestStatus.in_review,
        ApprovalRequestStatus.changes_requested,
    }
)
RESOLVED_REQUEST_STATUSES = frozenset(
    {
        ApprovalRequestStatus.approved,
        ApprovalRequestStatus.rejected,
        ApprovalRequestStatus.cancelled,
    }
)


class DuplicateActiveApprovalRequestError(ValueError):
    """Raised when the active-resource partial unique constraint is hit."""


@dataclass(frozen=True, kw_only=True)
class ApprovalRequestListPage:
    items: list[ApprovalRequest]
    total: int
    limit: int
    offset: int


def _request_load_options():
    return (
        selectinload(ApprovalRequest.requested_by_profile),
        selectinload(ApprovalRequest.stages).selectinload(
            ApprovalRequestStage.assigned_profile
        ),
        selectinload(ApprovalRequest.stages).selectinload(
            ApprovalRequestStage.decisions
        ),
        selectinload(ApprovalRequest.decisions),
    )


async def create_request(
    session: AsyncSession,
    organization_id: UUID,
    values: Mapping[str, object],
) -> ApprovalRequest:
    resource_type = str(values["resource_type"])
    get_approval_resource_adapter(resource_type)
    request = ApprovalRequest(organization_id=organization_id, **dict(values))
    session.add(request)
    try:
        await session.flush()
    except IntegrityError as exc:
        if _is_active_request_integrity_error(exc):
            raise DuplicateActiveApprovalRequestError(
                "An active approval request already exists for this resource revision."
            ) from exc
        raise
    return request


async def create_initial_stage(
    session: AsyncSession,
    organization_id: UUID,
    approval_request_id: UUID,
    values: Mapping[str, object],
) -> ApprovalRequestStage | None:
    request = await get_request(session, organization_id, approval_request_id)
    if request is None:
        return None
    stage = ApprovalRequestStage(
        approval_request_id=approval_request_id,
        stage_order=1,
        **dict(values),
    )
    session.add(stage)
    await session.flush()
    return stage


async def get_request(
    session: AsyncSession,
    organization_id: UUID,
    approval_request_id: UUID,
) -> ApprovalRequest | None:
    return await session.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.organization_id == organization_id)
        .where(ApprovalRequest.id == approval_request_id)
    )


async def get_request_with_stages_and_decisions(
    session: AsyncSession,
    organization_id: UUID,
    approval_request_id: UUID,
) -> ApprovalRequest | None:
    return await session.scalar(
        select(ApprovalRequest)
        .options(*_request_load_options())
        .where(ApprovalRequest.organization_id == organization_id)
        .where(ApprovalRequest.id == approval_request_id)
    )


async def find_active_request_for_resource_revision(
    session: AsyncSession,
    organization_id: UUID,
    resource_type: str,
    resource_id: UUID,
    resource_revision: int,
) -> ApprovalRequest | None:
    get_approval_resource_adapter(resource_type)
    return await session.scalar(
        _resource_revision_statement(
            organization_id,
            resource_type,
            resource_id,
            resource_revision,
        ).where(ApprovalRequest.status.in_(ACTIVE_REQUEST_STATUSES))
    )


async def list_requests(
    session: AsyncSession,
    organization_id: UUID,
    *,
    status: ApprovalRequestStatus | None = None,
    resource_type: str | None = None,
    requested_by_user_id: UUID | None = None,
    requested_by_profile_id: UUID | None = None,
    assigned_profile_id: UUID | None = None,
    current_profile_id: UUID | None = None,
    submitted_by_current_actor: bool = False,
    current_actor_user_id: UUID | None = None,
    current_actor_profile_id: UUID | None = None,
    assigned_to_current_profile: bool = False,
    campaign_id: UUID | None = None,
    artist_id: UUID | None = None,
    submitted_start: datetime | None = None,
    submitted_end: datetime | None = None,
    limit: int,
    offset: int,
) -> ApprovalRequestListPage:
    statement = _filtered_requests_statement(
        organization_id,
        status=status,
        resource_type=resource_type,
        requested_by_user_id=requested_by_user_id,
        requested_by_profile_id=requested_by_profile_id,
        assigned_profile_id=assigned_profile_id,
        current_profile_id=current_profile_id,
        submitted_by_current_actor=submitted_by_current_actor,
        current_actor_user_id=current_actor_user_id,
        current_actor_profile_id=current_actor_profile_id,
        assigned_to_current_profile=assigned_to_current_profile,
        campaign_id=campaign_id,
        artist_id=artist_id,
        submitted_start=submitted_start,
        submitted_end=submitted_end,
    )
    total = await session.scalar(select(func.count()).select_from(statement.subquery()))
    rows = await session.scalars(
        statement.options(*_request_load_options())
        .order_by(
            ApprovalRequest.submitted_at.desc(),
            ApprovalRequest.created_at.desc(),
            ApprovalRequest.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return ApprovalRequestListPage(
        items=list(rows.unique().all()),
        total=total or 0,
        limit=limit,
        offset=offset,
    )


async def update_request_lifecycle(
    session: AsyncSession,
    organization_id: UUID,
    approval_request_id: UUID,
    *,
    status: ApprovalRequestStatus | None = None,
    current_stage_order: int | None = None,
    resolved_at: datetime | None = None,
) -> ApprovalRequest | None:
    request = await get_request(session, organization_id, approval_request_id)
    if request is None:
        return None
    if status is not None:
        request.status = status
    if current_stage_order is not None:
        request.current_stage_order = current_stage_order
    if resolved_at is not None:
        request.resolved_at = resolved_at
    await session.flush()
    return request


async def update_stage_lifecycle(
    session: AsyncSession,
    organization_id: UUID,
    stage_id: UUID,
    *,
    status: ApprovalStageStatus | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> ApprovalRequestStage | None:
    stage = await session.scalar(
        select(ApprovalRequestStage)
        .join(ApprovalRequest)
        .where(ApprovalRequest.organization_id == organization_id)
        .where(ApprovalRequestStage.id == stage_id)
    )
    if stage is None:
        return None
    if status is not None:
        stage.status = status
    if started_at is not None:
        stage.started_at = started_at
    if completed_at is not None:
        stage.completed_at = completed_at
    await session.flush()
    return stage


async def append_decision(
    session: AsyncSession,
    organization_id: UUID,
    approval_request_id: UUID,
    values: Mapping[str, object],
) -> ApprovalDecision | None:
    request = await get_request(session, organization_id, approval_request_id)
    if request is None:
        return None
    stage_id = values.get("stage_id")
    if isinstance(stage_id, UUID) and not await _stage_in_request(
        session, approval_request_id, stage_id
    ):
        return None
    decision = ApprovalDecision(
        approval_request_id=approval_request_id,
        organization_id=organization_id,
        **dict(values),
    )
    session.add(decision)
    await session.flush()
    return decision


async def list_decisions_chronologically(
    session: AsyncSession,
    organization_id: UUID,
    approval_request_id: UUID,
) -> list[ApprovalDecision] | None:
    request = await get_request(session, organization_id, approval_request_id)
    if request is None:
        return None
    rows = await session.scalars(
        select(ApprovalDecision)
        .where(ApprovalDecision.organization_id == organization_id)
        .where(ApprovalDecision.approval_request_id == approval_request_id)
        .order_by(ApprovalDecision.created_at.asc(), ApprovalDecision.id.asc())
    )
    return list(rows.all())


async def find_conflicting_or_resolved_request(
    session: AsyncSession,
    organization_id: UUID,
    resource_type: str,
    resource_id: UUID,
    resource_revision: int,
) -> ApprovalRequest | None:
    get_approval_resource_adapter(resource_type)
    return await session.scalar(
        _resource_revision_statement(
            organization_id,
            resource_type,
            resource_id,
            resource_revision,
        )
        .where(
            ApprovalRequest.status.in_(
                tuple(ACTIVE_REQUEST_STATUSES | RESOLVED_REQUEST_STATUSES)
            )
        )
        .order_by(
            ApprovalRequest.status.in_(ACTIVE_REQUEST_STATUSES).desc(),
            ApprovalRequest.created_at.desc(),
            ApprovalRequest.id.desc(),
        )
    )


def _resource_revision_statement(
    organization_id: UUID,
    resource_type: str,
    resource_id: UUID,
    resource_revision: int,
) -> Select[tuple[ApprovalRequest]]:
    return (
        select(ApprovalRequest)
        .where(ApprovalRequest.organization_id == organization_id)
        .where(ApprovalRequest.resource_type == resource_type)
        .where(ApprovalRequest.resource_id == resource_id)
        .where(ApprovalRequest.resource_revision == resource_revision)
    )


def _filtered_requests_statement(
    organization_id: UUID,
    *,
    status: ApprovalRequestStatus | None,
    resource_type: str | None,
    requested_by_user_id: UUID | None,
    requested_by_profile_id: UUID | None,
    assigned_profile_id: UUID | None,
    current_profile_id: UUID | None,
    submitted_by_current_actor: bool,
    current_actor_user_id: UUID | None,
    current_actor_profile_id: UUID | None,
    assigned_to_current_profile: bool,
    campaign_id: UUID | None,
    artist_id: UUID | None,
    submitted_start: datetime | None,
    submitted_end: datetime | None,
) -> Select[tuple[ApprovalRequest]]:
    statement = select(ApprovalRequest).where(
        ApprovalRequest.organization_id == organization_id
    )
    if status is not None:
        statement = statement.where(ApprovalRequest.status == status)
    if resource_type is not None:
        adapter = get_approval_resource_adapter(resource_type)
        statement = statement.where(ApprovalRequest.resource_type == resource_type)
    elif campaign_id is not None or artist_id is not None:
        adapter = get_approval_resource_adapter(MARKETING_CONTENT_ITEM_RESOURCE_TYPE)
        statement = statement.where(
            ApprovalRequest.resource_type == adapter.resource_type
        )
    else:
        adapter = None
    if requested_by_user_id is not None:
        statement = statement.where(
            ApprovalRequest.requested_by_user_id == requested_by_user_id
        )
    if requested_by_profile_id is not None:
        statement = statement.where(
            ApprovalRequest.requested_by_profile_id == requested_by_profile_id
        )
    if submitted_by_current_actor:
        actor_filters = []
        if current_actor_user_id is not None:
            actor_filters.append(
                ApprovalRequest.requested_by_user_id == current_actor_user_id
            )
        if current_actor_profile_id is not None:
            actor_filters.append(
                ApprovalRequest.requested_by_profile_id == current_actor_profile_id
            )
        if actor_filters:
            statement = statement.where(or_(*actor_filters))
    reviewer_profile_id = assigned_profile_id
    if assigned_to_current_profile:
        reviewer_profile_id = current_profile_id
    if reviewer_profile_id is not None:
        statement = statement.where(
            ApprovalRequest.stages.any(
                ApprovalRequestStage.assigned_profile_id == reviewer_profile_id
            )
        )
    if submitted_start is not None:
        statement = statement.where(ApprovalRequest.submitted_at >= submitted_start)
    if submitted_end is not None:
        statement = statement.where(ApprovalRequest.submitted_at <= submitted_end)
    if adapter is not None:
        resource_filter = adapter.queue_filter(
            organization_id=organization_id,
            campaign_id=campaign_id,
            artist_id=artist_id,
        )
        if resource_filter is not None:
            statement = statement.where(resource_filter)
    return statement


async def _stage_in_request(
    session: AsyncSession,
    approval_request_id: UUID,
    stage_id: UUID,
) -> bool:
    return (
        await session.scalar(
            select(ApprovalRequestStage.id)
            .where(ApprovalRequestStage.approval_request_id == approval_request_id)
            .where(ApprovalRequestStage.id == stage_id)
        )
        is not None
    )


def _is_active_request_integrity_error(exc: IntegrityError) -> bool:
    message = str(exc.orig).lower()
    return (
        "uq_approval_requests_active_resource_revision" in message
        or "approval_requests.organization_id" in message
        and "approval_requests.resource_type" in message
        and "approval_requests.resource_id" in message
        and "approval_requests.resource_revision" in message
    )
