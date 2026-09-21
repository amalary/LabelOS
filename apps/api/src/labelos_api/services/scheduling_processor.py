"""Bounded internal scheduling runner, hosted by the private scheduling_worker app.

The host authenticates a workload and constructs its workspace allowlist; this
module must never receive a principal or receiver from user request JSON. Each
transaction locks the durable execution switch before source/job/destination rows.
The injected receiver is a trusted, certified transactional Delivery adapter.
"""

import logging
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from time import monotonic
from uuid import UUID

from labelos_database.models import SchedulingExecutionControl
from labelos_database.scheduling import SchedulingBlockedReason as Reason
from labelos_database.scheduling import SchedulingJobStatus as Status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labelos_api.repositories.scheduling import (
    RetryableInternalFailure,
    SchedulingConflict,
    SchedulingRepository,
    snapshot_for,
)
from labelos_api.scheduling.contracts import (
    DurableAccepted,
    PublishingDeliveryAcceptancePort,
    RetryableUnavailable,
    SchedulingFeatureControls,
)
from labelos_api.scheduling.events import job_correlation_id
from labelos_api.scheduling.metrics import scheduling_metrics
from labelos_api.scheduling.payload import InvalidHandoffPayload, prepare_request
from labelos_api.scheduling.receivers import UnavailableDeliveryReceiver
from labelos_api.services.marketing_media import load_approved_assets
from labelos_api.services.scheduling_destination import lock_destination
from labelos_api.services.scheduling_eligibility import (
    SchedulingExecutionMode,
    evaluate_channel_eligibility,
)
from labelos_api.services.scheduling_handoff import accept_scheduling_handoff

logger = logging.getLogger(__name__)


class SchedulingExecutionRefused(RuntimeError):
    """Only fixed reason codes are exposed at the internal boundary."""


@dataclass(frozen=True, kw_only=True)
class SchedulingWorker:
    """Server-constructed identity after host authentication, never an API DTO."""

    principal_id: UUID
    instance_id: UUID
    workspace_ids: frozenset[UUID]

    @property
    def worker_id(self) -> str:
        return f"scheduling:{self.principal_id}:{self.instance_id}"

    def require_workspace(self, workspace_id: UUID) -> None:
        if (
            not isinstance(self.principal_id, UUID)
            or not isinstance(self.instance_id, UUID)
            or workspace_id not in self.workspace_ids
        ):
            raise SchedulingExecutionRefused("worker_scope_denied")


@dataclass(frozen=True)
class ClaimedJob:
    id: UUID
    fencing_token: int
    correlation_id: UUID | None = None


@dataclass(frozen=True)
class SchedulingBatchResult:
    claimed: int
    recovered: int
    outcomes: dict[str, int]


class SchedulingDueJobProcessor:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        worker: SchedulingWorker,
        controls: SchedulingFeatureControls,
        receiver: PublishingDeliveryAcceptancePort | None,
        lateness_window_seconds: int,
        batch_size: int,
        lease_duration: timedelta,
        asset_bytes: Mapping[str, bytes] | None = None,
    ):
        if type(batch_size) is not int or not 1 <= batch_size <= 1000:
            raise ValueError("batch_size must be between 1 and 1000")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        if type(lateness_window_seconds) is not int or lateness_window_seconds < 0:
            raise ValueError("An explicit nonnegative lateness policy is required")
        self.sessions = sessions
        self.worker = worker
        self.controls = controls
        self.receiver = receiver
        self.window = lateness_window_seconds
        self.batch_size = batch_size
        self.lease_duration = lease_duration
        # Trusted callers may supply bytes; production resolves content-scoped
        # prepared media in the existing source-locked database transaction.
        self.asset_bytes = dict(asset_bytes) if asset_bytes is not None else None

    def _repository(self, session, workspace_id):
        return SchedulingRepository(
            session, workspace_id, lateness_window_seconds=self.window
        )

    def _require_enabled(self, workspace_id):
        self.worker.require_workspace(workspace_id)
        if not self.controls.execution_enabled:
            raise SchedulingExecutionRefused("execution_disabled")
        if (
            not self.controls.delivery_receiver_configured
            or self.receiver is None
            or isinstance(self.receiver, UnavailableDeliveryReceiver)
        ):
            raise SchedulingExecutionRefused("missing_durable_delivery_receiver")

    async def _lock_control(self, session, workspace_id):
        self._require_enabled(workspace_id)
        enabled = await session.scalar(
            select(SchedulingExecutionControl.execution_enabled)
            .where(SchedulingExecutionControl.workspace_id == workspace_id)
            .with_for_update(read=True)
        )
        if enabled is not True:
            raise SchedulingExecutionRefused("execution_disabled")

    async def run(self, workspace_id: UUID) -> SchedulingBatchResult:
        """One bounded recovery pass and one bounded claim pass; never poll/sleep.

        Claims commit before work. Unknown failures leave the claim leased for
        database recovery; only explicit known nonacceptance is requeued.
        """
        self._require_enabled(workspace_id)
        started = monotonic()
        outcomes: Counter[str] = Counter()
        async with self.sessions.begin() as session:
            await self._lock_control(session, workspace_id)
            repository = self._repository(session, workspace_id)
            recovered = await repository.recover_expired_leases(
                worker_id=self.worker.worker_id, limit=self.batch_size
            )
            for job in recovered:
                if job.status == Status.blocked:
                    outcomes[job.blocked_reason_code.value] += 1
            recovered_count = len(recovered)
        async with self.sessions.begin() as session:
            await self._lock_control(session, workspace_id)
            jobs = await self._repository(session, workspace_id).claim_batch(
                worker_id=self.worker.worker_id,
                limit=self.batch_size,
                lease_duration=self.lease_duration,
                include_blocked=True,
            )
            claims = []
            for job in jobs:
                if job.status == Status.claimed:
                    claims.append(
                        ClaimedJob(job.id, job.fencing_token, job_correlation_id(job))
                    )
                else:
                    outcomes[job.blocked_reason_code.value] += 1
        for claim in claims:
            try:
                outcome = await self.process_claim(workspace_id, claim)
            except SchedulingExecutionRefused:
                outcome = "execution_refused"
            except SchedulingConflict:
                outcome = "claim_lost"
            except Exception:
                # Includes an ambiguous commit acknowledgement. Do not requeue,
                # expose exception text, or undo a possibly committed handoff.
                outcome = "job_failed"
            outcomes[outcome] += 1
            logger.info(
                "scheduling_job_processed",
                extra={
                    "scheduling_outcome": outcome,
                    "job_id": str(claim.id),
                    "correlation_id": (
                        str(claim.correlation_id) if claim.correlation_id else None
                    ),
                    "failed_count": int(outcome == "job_failed"),
                },
            )
        async with self.sessions() as session:
            metrics = await scheduling_metrics(session, workspace_id)
        # Fixed, low-cardinality dimensions suitable for log-based counters.
        logger.info(
            "scheduling_batch_metrics",
            extra={
                "job_gauges": {
                    key: metrics[key]
                    for key in (
                        "pending",
                        "due",
                        "claimed",
                        "handed_off",
                        "blocked",
                        "cancelled",
                        "superseded",
                    )
                },
                "retained_transition_totals": {
                    key: metrics[key] for key in ("requeued", "expired")
                },
                "failed_count": outcomes["job_failed"],
                "claimed_count": len(claims),
                "recovered_count": recovered_count,
                "outcome_counts": dict(outcomes),
                "duration_seconds": monotonic() - started,
            },
        )
        return SchedulingBatchResult(len(claims), recovered_count, dict(outcomes))

    async def process_claim(self, workspace_id: UUID, claim: ClaimedJob) -> str:
        """Resume a known claim after lost acknowledgement without a new key."""
        async with self.sessions.begin() as session:
            await self._lock_control(session, workspace_id)
            repository = self._repository(session, workspace_id)
            async with repository.job_context(claim.id) as (job, source, reason):
                if job.status == Status.handed_off:
                    # Atomic receiver/job commit is durable readback. No source
                    # reconstruction or new acceptance after subsequent edits.
                    return "handed_off"
                now = await repository._now()
                if (
                    job.status != Status.claimed
                    or job.claimed_by != self.worker.worker_id
                    or job.fencing_token != claim.fencing_token
                    or job.claim_expires_at is None
                    or job.claim_expires_at <= now
                ):
                    raise SchedulingConflict("claim_lost")
                if reason is None and now - job.scheduled_for > repository.window:
                    reason = Reason.missed_schedule_window
                if reason is None:
                    assert source.channel is not None and source.campaign is not None
                    connection = await lock_destination(
                        session, workspace_id, job.social_account_connection_id
                    )
                    eligibility = evaluate_channel_eligibility(
                        workspace_id=workspace_id,
                        item=source.item,
                        channel=source.channel,
                        evidence=source.approval,
                        connection=connection,
                        effective_artist_id=(
                            source.item.artist_id or source.campaign.primary_artist_id
                        ),
                        expected_content_revision=job.authorized_content_revision,
                        execution_mode=SchedulingExecutionMode.automatic,
                        controls=self.controls,
                    )
                    if not eligibility.eligible:
                        code = eligibility.reason_codes[0]
                        reason = (
                            Reason(code)
                            if code in Reason._value2member_map_
                            else Reason.changed_schedule_generation
                        )
                if reason is None:
                    assert source.channel is not None
                    assert job.social_account_connection_id is not None
                    try:
                        assets = self.asset_bytes
                        if assets is None:
                            assets = await load_approved_assets(
                                session, workspace_id, source.item, source.channel
                            )
                        request = prepare_request(
                            snapshot=snapshot_for(job),
                            job_id=job.id,
                            destination_id=job.social_account_connection_id,
                            artist_profile_id=job.effective_artist_id,
                            authoring_timezone=job.schedule_timezone,
                            correlation_id=job_correlation_id(job),
                            item=source.item,
                            channel=source.channel,
                            asset_bytes=assets,
                        )
                    except InvalidHandoffPayload:
                        reason = Reason.handoff_contract_violation
                if reason is not None:
                    await repository.block_job(
                        claim.id,
                        reason=reason,
                        actor_key=self.worker.worker_id,
                        expected_worker=self.worker.worker_id,
                        expected_fencing_token=claim.fencing_token,
                    )
                    return reason.value
                assert self.receiver is not None
                result = await accept_scheduling_handoff(
                    repository,
                    receiver=self.receiver,
                    request=request,
                    expected_worker=self.worker.worker_id,
                    expected_fencing_token=claim.fencing_token,
                    controls=self.controls,
                )
                if isinstance(result, DurableAccepted):
                    return "handed_off"
            # Savepoint rollback can expire ORM state. Reload after leaving cache.
            if isinstance(result, RetryableUnavailable):
                job = await repository.requeue_retryable_failure(
                    claim.id,
                    expected_worker=self.worker.worker_id,
                    expected_fencing_token=claim.fencing_token,
                    failure=RetryableInternalFailure.delivery_unavailable,
                )
                outcome = (
                    job.blocked_reason_code.value
                    if job.blocked_reason_code is not None
                    else "delivery_unavailable"
                )
            else:
                # Lease/lateness may have elapsed inside acceptance. Re-evaluate
                # before assigning the terminal contract reason.
                reason = await repository.detect_stale_job(claim.id)
                job = await repository.get_job(claim.id)
                assert job is not None
                if reason is None and (
                    await repository._now() - job.scheduled_for > repository.window
                ):
                    reason = Reason.missed_schedule_window
                job = await repository.block_job(
                    claim.id,
                    reason=reason or Reason.handoff_contract_violation,
                    actor_key=self.worker.worker_id,
                    expected_worker=self.worker.worker_id,
                    expected_fencing_token=claim.fencing_token,
                )
                assert job.blocked_reason_code is not None
                outcome = job.blocked_reason_code.value
            return outcome
