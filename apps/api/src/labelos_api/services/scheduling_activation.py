"""Explicit activation of approved channel intent. No Delivery/provider I/O.

The service participates in a caller-owned PostgreSQL READ COMMITTED transaction.
The public function owns commit/rollback for a standalone application command.
Controls are trusted deployment inputs, never fields supplied by an API client.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from labelos_database.capabilities import Capability
from labelos_database.models import (
    SchedulingJob,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.authorization import AuthorizationActorInput
from labelos_api.repositories.scheduling import (
    JobActivation,
    SchedulingConflict,
    SchedulingRepository,
)
from labelos_api.scheduling.contracts import (
    DueDisposition,
    ScheduleSnapshot,
    SchedulingFeatureControls,
    due_disposition,
    schedule_blocked_reason,
)
from labelos_api.services import marketing_content_service as content
from labelos_api.services.scheduling_destination import lock_destination
from labelos_api.services.scheduling_eligibility import (
    SchedulingExecutionMode,
    evaluate_channel_eligibility,
)


@dataclass(frozen=True, kw_only=True)
class ActivateChannelSchedule:
    content_item_id: UUID
    channel_id: UUID
    operation_id: UUID
    expected_content_revision: int
    expected_schedule_generation: int
    predecessor_job_id: UUID | None = None


class SchedulingActivationRejected(SchedulingConflict):
    def __init__(self, *reason_codes: str):
        self.reason_codes = reason_codes
        super().__init__(", ".join(reason_codes))


class SchedulingActivationService:
    """Never commits; the caller must roll back the unit on any exception."""

    def __init__(
        self,
        session: AsyncSession,
        workspace_id: UUID,
        *,
        actor: AuthorizationActorInput,
        controls: SchedulingFeatureControls,
        lateness_window_seconds: int,
    ):
        user = content._actor_user(actor)
        if user is None or content._actor_kind(actor) != "user":
            raise content.MarketingContentAuthorizationError(
                "An authenticated human actor is required"
            )
        self.session = session
        self.workspace_id = workspace_id
        self.actor = actor
        self.user = user
        self.controls = controls
        self.repository = SchedulingRepository(
            session, workspace_id, lateness_window_seconds=lateness_window_seconds
        )

    async def _destination(self, destination_id: UUID | None):
        return await lock_destination(self.session, self.workspace_id, destination_id)

    async def activate(self, command: ActivateChannelSchedule) -> SchedulingJob:
        if self.session.get_bind().dialect.name != "postgresql":
            raise RuntimeError("Scheduling activation requires PostgreSQL")
        if (
            type(command.expected_content_revision) is not int
            or command.expected_content_revision < 1
            or type(command.expected_schedule_generation) is not int
            or command.expected_schedule_generation < 1
            or not isinstance(command.operation_id, UUID)
        ):
            raise ValueError(
                "Explicit operation ID and positive source guards required"
            )
        await content._require_capability(
            self.session,
            actor=self.actor,
            workspace_id=self.workspace_id,
            capability=Capability.marketing_content_schedule,
        )
        source = await self.repository.lock_activation_source(
            command.content_item_id, command.channel_id
        )
        await content._require_capability(
            self.session,
            actor=self.actor,
            workspace_id=self.workspace_id,
            capability=Capability.marketing_content_schedule,
            campaign_id=source.item.campaign_id,
        )
        # Parent lock serializes same-source retries. A replay is history, not a
        # new activation: do not revalidate changed intent or execution readiness.
        existing = await self.repository.get_activation_result(command.operation_id)
        if existing is not None:
            if (
                existing.marketing_content_item_id != command.content_item_id
                or existing.marketing_content_item_channel_id != command.channel_id
                or existing.authorized_content_revision
                != command.expected_content_revision
                or existing.schedule_generation != command.expected_schedule_generation
                or existing.created_by_user_id != self.user.id
                or existing.supersedes_job_id != command.predecessor_job_id
            ):
                raise SchedulingConflict(
                    "Activation operation was reused with new inputs"
                )
            return existing
        if not self.controls.authoring_enabled:
            raise SchedulingActivationRejected("authoring_disabled")
        predecessor = None
        if command.predecessor_job_id is not None:
            predecessor = await self.repository.get_job(command.predecessor_job_id)
            if (
                predecessor is None
                or predecessor.marketing_content_item_id != command.content_item_id
                or predecessor.marketing_content_item_channel_id != command.channel_id
                or predecessor.status not in ("superseded", "cancelled")
            ):
                raise SchedulingActivationRejected("invalid_replacement")
            if (
                source.item.content_revision <= predecessor.authorized_content_revision
                or source.approval is None
                or source.approval.request_id == predecessor.approval_request_id
            ):
                raise SchedulingActivationRejected("replacement_requires_reapproval")
        item, channel, campaign = source.item, source.channel, source.campaign
        if channel is None:
            raise SchedulingActivationRejected("channel_mismatch")
        if campaign is None:
            raise SchedulingActivationRejected("destination_mismatch")
        if channel.schedule_generation != command.expected_schedule_generation:
            raise SchedulingActivationRejected("changed_schedule_generation")
        effective_artist_id = item.artist_id or campaign.primary_artist_id
        connection = await self._destination(channel.social_account_connection_id)
        eligibility = evaluate_channel_eligibility(
            workspace_id=self.workspace_id,
            item=item,
            channel=channel,
            evidence=source.approval,
            connection=connection,
            effective_artist_id=effective_artist_id,
            expected_content_revision=command.expected_content_revision,
            execution_mode=SchedulingExecutionMode.automatic,
            controls=self.controls,
        )
        if not eligibility.eligible:
            raise SchedulingActivationRejected(*eligibility.reason_codes)
        assert eligibility.approval_request_id is not None
        assert eligibility.scheduled_for is not None
        assert eligibility.schedule_timezone is not None
        snapshot = ScheduleSnapshot(
            workspace_id=self.workspace_id,
            content_item_id=item.id,
            channel_id=channel.id,
            content_revision=item.content_revision,
            approval_request_id=eligibility.approval_request_id,
            schedule_generation=channel.schedule_generation,
            scheduled_for=eligibility.scheduled_for,
        )
        reason = schedule_blocked_reason(
            snapshot,
            scheduled_at=channel.scheduled_at,
            schedule_generation=channel.schedule_generation,
        )
        if reason:
            raise SchedulingActivationRejected(reason)
        # Use actual DB time after waiting for locks, not transaction start time.
        now = await self.session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        if (
            due_disposition(
                scheduled_for=snapshot.scheduled_for,
                now=now,
                lateness_window=self.repository.window,
            )
            == DueDisposition.missed
        ):
            raise SchedulingActivationRejected("missed_schedule_window")
        job = await self.repository.create_pending_job(
            JobActivation(
                snapshot=snapshot,
                operation_id=command.operation_id,
                created_by_user_id=self.user.id,
                schedule_timezone=eligibility.schedule_timezone,
                destination_id=channel.social_account_connection_id,
                effective_artist_id=effective_artist_id,
                supersedes_job_id=predecessor.id if predecessor else None,
                lineage_root_job_id=(
                    predecessor.lineage_root_job_id or predecessor.id
                    if predecessor
                    else None
                ),
            )
        )
        # Repository inserts the immutable activation transition in this session.
        return job


async def activate_channel_schedule(
    session: AsyncSession,
    workspace_id: UUID,
    command: ActivateChannelSchedule,
    *,
    actor: AuthorizationActorInput,
    controls: SchedulingFeatureControls,
    lateness_window_seconds: int,
) -> SchedulingJob:
    """Standalone application boundary: job, audit and outbox commit together."""
    try:
        job = await SchedulingActivationService(
            session,
            workspace_id,
            actor=actor,
            controls=controls,
            lateness_window_seconds=lateness_window_seconds,
        ).activate(command)
        await session.commit()
        return job
    except BaseException:
        await session.rollback()
        raise
