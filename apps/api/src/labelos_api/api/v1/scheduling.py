"""Workspace authoring/inspection only. No claims, leases or Delivery execution."""

import base64
import binascii
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from labelos_database.capabilities import Capability
from labelos_database.models import (
    SchedulingExecutionControl,
    SchedulingJob,
    SchedulingJobTransition,
)
from labelos_database.scheduling import SchedulingBlockedReason, SchedulingJobStatus
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.api.v1.marketing_content import _raise_capability_denial
from labelos_api.auth import CurrentUserContext, SessionDep, get_current_user_context
from labelos_api.config import get_settings
from labelos_api.exceptions import SchedulingAPIConflict
from labelos_api.repositories.scheduling import (
    JobCursor,
    SchedulingConflict,
    SchedulingRepository,
)
from labelos_api.scheduling.contracts import SchedulingFeatureControls
from labelos_api.scheduling.events import job_correlation_id, safe_reason_code
from labelos_api.scheduling.receivers import (
    UnavailableDeliveryReceiver,
    configured_receiver,
)
from labelos_api.services import marketing_content_service as content
from labelos_api.services.scheduling_activation import (
    ActivateChannelSchedule,
    SchedulingActivationRejected,
)
from labelos_api.services.scheduling_commands import (
    SchedulingCommandService,
    authorized_item,
)
from labelos_api.services.scheduling_eligibility import (
    SchedulingExecutionMode,
    evaluate_content_batch,
)

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["scheduling"])
Actor = Annotated[CurrentUserContext, Depends(get_current_user_context)]
OperationKey = Annotated[UUID, Header(alias="Idempotency-Key")]


class SchedulingErrorDetail(BaseModel):
    code: str
    reason_codes: list[str]


class SchedulingErrorResponse(BaseModel):
    detail: SchedulingErrorDetail


router.responses[409] = {"model": SchedulingErrorResponse}


class ScheduleActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_revision: int = Field(ge=1, strict=True)
    expected_schedule_generation: int = Field(ge=1, strict=True)


class ScheduleJobCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SchedulingJobResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    content_item_id: UUID
    channel_id: UUID
    connection_id: UUID | None
    approval_request_id: UUID
    content_revision: int
    schedule_generation: int
    scheduled_for: datetime
    schedule_timezone: str
    status: SchedulingJobStatus
    blocked_reason_code: SchedulingBlockedReason | None
    supersedes_job_id: UUID | None
    lineage_root_job_id: UUID | None
    created_at: datetime
    updated_at: datetime
    cancelled_at: datetime | None
    handed_off_at: datetime | None


class SchedulingJobListResponse(BaseModel):
    jobs: list[SchedulingJobResponse]
    limit: int
    next_cursor: str | None


class SchedulingHistoryEntry(BaseModel):
    transition_version: int
    operation_id: UUID
    operation: str
    from_status: SchedulingJobStatus | None
    to_status: SchedulingJobStatus
    actor_kind: str
    reason_code: str | None
    created_at: datetime


class SchedulingHistoryResponse(BaseModel):
    job_id: UUID
    correlation_id: UUID
    transitions: list[SchedulingHistoryEntry]
    next_before_version: int | None


class SchedulingBlockedReasonsResponse(BaseModel):
    job_id: UUID
    status: SchedulingJobStatus
    primary_reason: SchedulingBlockedReason | None
    reason_codes: list[SchedulingBlockedReason]


class ChannelSchedulingEligibilityResponse(BaseModel):
    eligible: bool
    content_revision: int
    schedule_generation: int
    approval_request_id: UUID | None
    scheduled_for: datetime | None
    schedule_timezone: str | None
    active_job_id: UUID | None
    reason_codes: list[str]
    authoring_enabled: bool
    execution_enabled: bool
    delivery_receiver_configured: bool


class SchedulingJobFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: list[SchedulingJobStatus] | None = None
    content_item_id: UUID | None = None
    channel_id: UUID | None = None
    connection_id: UUID | None = None
    scheduled_from: AwareDatetime | None = None
    scheduled_through: AwareDatetime | None = None
    blocked_reason: SchedulingBlockedReason | None = None
    provider: str | None = Field(default=None, min_length=1, max_length=80)
    cursor: str | None = Field(default=None, max_length=512)
    limit: int = Field(default=100, ge=1, le=100)

    @model_validator(mode="after")
    def validate_range(self):
        if (
            self.scheduled_from is not None
            and self.scheduled_through is not None
            and self.scheduled_from > self.scheduled_through
        ):
            raise PydanticCustomError(
                "invalid_scheduled_range",
                "scheduled_through must not precede scheduled_from",
            )
        if self.cursor is not None:
            _decode_cursor(self.cursor)
        return self


def _decode_cursor(value: str) -> JobCursor:
    try:
        stamp, identifier = (
            base64.b64decode(value, altchars=b"-_", validate=True).decode().split("|")
        )
        instant = datetime.fromisoformat(stamp)
        if instant.tzinfo is None:
            raise ValueError("Naive cursor")
        return JobCursor(instant, UUID(identifier))
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise PydanticCustomError(
            "invalid_cursor", "Invalid pagination cursor"
        ) from exc


def _encode_cursor(cursor: JobCursor | None):
    if cursor is None:
        return None
    instant = cursor.created_at
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return base64.urlsafe_b64encode(
        f"{instant.isoformat()}|{cursor.id}".encode()
    ).decode()


def job_response(job: SchedulingJob) -> SchedulingJobResponse:
    return SchedulingJobResponse(
        id=job.id,
        workspace_id=job.workspace_id,
        content_item_id=job.marketing_content_item_id,
        channel_id=job.marketing_content_item_channel_id,
        connection_id=job.social_account_connection_id,
        approval_request_id=job.approval_request_id,
        content_revision=job.authorized_content_revision,
        schedule_generation=job.schedule_generation,
        scheduled_for=job.scheduled_for,
        schedule_timezone=job.schedule_timezone,
        status=job.status,
        blocked_reason_code=job.blocked_reason_code,
        supersedes_job_id=job.supersedes_job_id,
        lineage_root_job_id=job.lineage_root_job_id,
        created_at=job.created_at,
        updated_at=job.updated_at,
        cancelled_at=job.cancelled_at,
        handed_off_at=job.handed_off_at,
    )


async def scheduling_session(session: SessionDep):
    try:
        yield session
    except content.MarketingContentAuthorizationError as exc:
        await session.rollback()
        _raise_capability_denial(exc.reason)
    except content.MarketingContentNotFoundError as exc:
        await session.rollback()
        raise HTTPException(404, detail="Not found") from exc
    except SchedulingConflict as exc:
        await session.rollback()
        if isinstance(exc, SchedulingActivationRejected):
            reasons = list(exc.reason_codes)
        elif str(exc) in {reason.value for reason in SchedulingBlockedReason} | {
            "invalid_state_transition"
        }:
            reasons = [str(exc)]
        else:
            reasons = [
                {
                    "Activation operation was reused with new inputs": (
                        "idempotency_conflict"
                    ),
                    "Channel already reserves this active/accepted intent": (
                        "active_job_conflict"
                    ),
                }.get(str(exc), "scheduling_conflict")
            ]
        raise SchedulingAPIConflict(reasons) from exc
    except BaseException:
        await session.rollback()
        raise


Session = Annotated[AsyncSession, Depends(scheduling_session)]


async def scheduling_controls(workspace_id: UUID, session: Session):
    settings = get_settings()
    enabled = await session.scalar(
        select(SchedulingExecutionControl.execution_enabled)
        .where(SchedulingExecutionControl.workspace_id == workspace_id)
        .with_for_update(read=True)
    )
    return SchedulingFeatureControls(
        authoring_enabled=settings.scheduling_authoring_enabled,
        execution_enabled=settings.scheduling_execution_enabled and enabled is True,
        delivery_receiver_configured=not isinstance(
            configured_receiver(settings), UnavailableDeliveryReceiver
        ),
    )


Controls = Annotated[SchedulingFeatureControls, Depends(scheduling_controls)]


def _repository(session, workspace_id):
    return SchedulingRepository(
        session,
        workspace_id,
        lateness_window_seconds=get_settings().scheduling_worker_lateness_seconds,
    )


def _commands(session, workspace_id, actor, controls):
    return SchedulingCommandService(
        session,
        workspace_id,
        actor=actor,
        controls=controls,
        lateness_window_seconds=get_settings().scheduling_worker_lateness_seconds,
    )


async def _job(session, workspace_id, job_id, actor):
    job = await _repository(session, workspace_id).get_job(job_id)
    if job is None:
        raise content.MarketingContentNotFoundError("Not found")
    await authorized_item(session, workspace_id, job.marketing_content_item_id, actor)
    return job


@router.get(
    "/marketing-content/{content_item_id}/channels/{channel_id}/scheduling/eligibility",
    response_model=ChannelSchedulingEligibilityResponse,
)
async def channel_scheduling_eligibility(
    workspace_id: UUID,
    content_item_id: UUID,
    channel_id: UUID,
    session: Session,
    context: Actor,
    controls: Controls,
):
    item = await authorized_item(
        session, workspace_id, content_item_id, context, mutate=True
    )
    channel = next((c for c in item.channels if c.id == channel_id), None)
    if channel is None:
        raise content.MarketingContentNotFoundError("Not found")
    readiness = (
        await evaluate_content_batch(
            session,
            workspace_id,
            [item],
            execution_mode=SchedulingExecutionMode.automatic,
            controls=controls,
        )
    )[item.id].channels[channel_id]
    repository = _repository(session, workspace_id)
    active = await repository.find_active_job(channel_id)
    reasons = list(readiness.reason_codes)
    if not controls.authoring_enabled:
        reasons.insert(0, "authoring_disabled")
    if readiness.scheduled_for is not None:
        now = await session.scalar(
            select(
                func.clock_timestamp()
                if session.get_bind().dialect.name == "postgresql"
                else func.current_timestamp()
            )
        )
        assert isinstance(now, datetime)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        # This projection describes new activation, whose instant must be future.
        # The worker's lateness allowance applies only to already activated jobs.
        if readiness.scheduled_for <= now:
            reasons.append("missed_schedule_window")
    previous = await session.scalar(
        select(SchedulingJob)
        .where(
            SchedulingJob.workspace_id == workspace_id,
            SchedulingJob.marketing_content_item_channel_id == channel_id,
        )
        .order_by(SchedulingJob.created_at.desc(), SchedulingJob.id.desc())
        .limit(1)
    )
    if previous is not None:
        if active:
            reasons.append("active_job_conflict")
        elif previous.status != SchedulingJobStatus.handed_off:
            reasons.append("replacement_required")
        elif item.content_revision <= previous.authorized_content_revision:
            reasons.append("already_handed_off")
    return ChannelSchedulingEligibilityResponse(
        eligible=not reasons,
        content_revision=item.content_revision,
        schedule_generation=channel.schedule_generation,
        approval_request_id=readiness.approval_request_id,
        scheduled_for=readiness.scheduled_for,
        schedule_timezone=readiness.schedule_timezone,
        active_job_id=active.id if active else None,
        reason_codes=reasons,
        authoring_enabled=controls.authoring_enabled,
        execution_enabled=controls.execution_enabled,
        delivery_receiver_configured=controls.delivery_receiver_configured,
    )


@router.post(
    "/marketing-content/{content_item_id}/channels/{channel_id}/scheduling/activate",
    response_model=SchedulingJobResponse,
)
async def activate_channel_schedule(
    workspace_id: UUID,
    content_item_id: UUID,
    channel_id: UUID,
    payload: ScheduleActivationRequest,
    session: Session,
    context: Actor,
    controls: Controls,
    idempotency_key: OperationKey,
):
    job = await _commands(session, workspace_id, context, controls).activate_command(
        ActivateChannelSchedule(
            content_item_id=content_item_id,
            channel_id=channel_id,
            operation_id=idempotency_key,
            **payload.model_dump(),
        )
    )
    response = job_response(job)
    await session.commit()
    return response


@router.get("/scheduling/jobs", response_model=SchedulingJobListResponse)
async def list_scheduling_jobs(
    workspace_id: UUID,
    session: Session,
    context: Actor,
    filters: Annotated[SchedulingJobFilters, Query()],
):
    await content._require_capability(
        session,
        actor=context,
        workspace_id=workspace_id,
        capability=Capability.marketing_content_view,
    )
    page = await _repository(session, workspace_id).list_jobs(
        statuses=filters.status,
        content_item_id=filters.content_item_id,
        channel_id=filters.channel_id,
        connection_id=filters.connection_id,
        blocked_reason=filters.blocked_reason,
        provider=filters.provider,
        scheduled_from=filters.scheduled_from,
        scheduled_through=filters.scheduled_through,
        cursor=_decode_cursor(filters.cursor) if filters.cursor else None,
        limit=filters.limit,
    )
    # Apply the same campaign resource check as single-item inspection.
    for item_id in {job.marketing_content_item_id for job in page.jobs}:
        await authorized_item(session, workspace_id, item_id, context)
    return SchedulingJobListResponse(
        jobs=[job_response(job) for job in page.jobs],
        limit=filters.limit,
        next_cursor=_encode_cursor(page.next_cursor),
    )


@router.get("/scheduling/jobs/{job_id}", response_model=SchedulingJobResponse)
async def get_scheduling_job(
    workspace_id: UUID, job_id: UUID, session: Session, context: Actor
):
    return job_response(await _job(session, workspace_id, job_id, context))


@router.get(
    "/scheduling/jobs/{job_id}/history", response_model=SchedulingHistoryResponse
)
async def scheduling_job_history(
    workspace_id: UUID,
    job_id: UUID,
    session: Session,
    context: Actor,
    before_version: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
):
    job = await _job(session, workspace_id, job_id, context)
    query = select(SchedulingJobTransition).where(
        SchedulingJobTransition.workspace_id == workspace_id,
        SchedulingJobTransition.job_id == job_id,
    )
    if before_version is not None:
        query = query.where(SchedulingJobTransition.transition_version < before_version)
    rows = list(
        await session.scalars(
            query.order_by(SchedulingJobTransition.transition_version.desc()).limit(
                limit + 1
            )
        )
    )
    return SchedulingHistoryResponse(
        job_id=job.id,
        correlation_id=job_correlation_id(job),
        transitions=[
            SchedulingHistoryEntry(
                transition_version=row.transition_version,
                operation_id=row.operation_id,
                operation=row.operation,
                from_status=row.from_status,
                to_status=row.to_status,
                actor_kind=row.actor_kind,
                reason_code=safe_reason_code(row.reason_code),
                created_at=row.created_at,
            )
            for row in rows[:limit]
        ],
        next_before_version=(
            rows[limit - 1].transition_version if len(rows) > limit else None
        ),
    )


@router.get(
    "/scheduling/jobs/{job_id}/blocked-reasons",
    response_model=SchedulingBlockedReasonsResponse,
)
async def scheduling_blocked_reasons(
    workspace_id: UUID, job_id: UUID, session: Session, context: Actor
):
    job = await _job(session, workspace_id, job_id, context)
    reasons: list[SchedulingBlockedReason] = []
    if job.status == SchedulingJobStatus.blocked:
        assert job.blocked_reason_code is not None
        reasons = list(
            dict.fromkeys(
                [job.blocked_reason_code, *job.blocked_metadata.get("reason_codes", [])]
            )
        )
    return SchedulingBlockedReasonsResponse(
        job_id=job.id,
        status=job.status,
        primary_reason=job.blocked_reason_code if reasons else None,
        reason_codes=reasons,
    )


async def _mutate_job(
    workspace_id,
    job_id,
    session,
    context,
    controls,
    operation_id,
    operation,
    payload=None,
):
    job = await _commands(session, workspace_id, context, controls).job_command(
        job_id,
        operation=operation,
        operation_id=operation_id,
        **(payload.model_dump() if payload else {}),
    )
    response = job_response(job)
    await session.commit()
    return response


@router.post("/scheduling/jobs/{job_id}/cancel", response_model=SchedulingJobResponse)
async def cancel_scheduling_job(
    workspace_id: UUID,
    job_id: UUID,
    payload: ScheduleJobCommandRequest,
    session: Session,
    context: Actor,
    controls: Controls,
    idempotency_key: OperationKey,
):
    return await _mutate_job(
        workspace_id, job_id, session, context, controls, idempotency_key, "cancel"
    )


@router.post(
    "/scheduling/jobs/{job_id}/revalidate", response_model=SchedulingJobResponse
)
async def revalidate_scheduling_job(
    workspace_id: UUID,
    job_id: UUID,
    payload: ScheduleJobCommandRequest,
    session: Session,
    context: Actor,
    controls: Controls,
    idempotency_key: OperationKey,
):
    return await _mutate_job(
        workspace_id, job_id, session, context, controls, idempotency_key, "revalidate"
    )


@router.post("/scheduling/jobs/{job_id}/replace", response_model=SchedulingJobResponse)
async def replace_scheduling_job(
    workspace_id: UUID,
    job_id: UUID,
    payload: ScheduleActivationRequest,
    session: Session,
    context: Actor,
    controls: Controls,
    idempotency_key: OperationKey,
):
    return await _mutate_job(
        workspace_id,
        job_id,
        session,
        context,
        controls,
        idempotency_key,
        "replace",
        payload,
    )
