"""Workspace-scoped scheduling persistence in a caller-owned transaction.

PostgreSQL READ COMMITTED is required for mutations. Callers authenticate and
authorize actors, coordinate execution controls and destination eligibility, and
commit/roll back the complete unit of work. No method commits, calls a provider,
or dispatches events. A claim is coordination, not execution authorization.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from labelos_database.models import (
    ApprovalRequest,
    Campaign,
    MarketingContentItem,
    MarketingContentItemChannel,
    SchedulingJob,
    SchedulingJobTransition,
)
from labelos_database.scheduling import (
    SchedulingBlockedReason as Reason,
)
from labelos_database.scheduling import (
    SchedulingJobStatus as Status,
)
from sqlalchemy import func, literal, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload

from labelos_api.repositories import approvals
from labelos_api.scheduling.contracts import (
    ApprovalEvidence,
    DeliveryAcceptanceReceipt,
    DeliveryAcceptanceRequest,
    DueDisposition,
    ScheduleSnapshot,
    approval_blocked_reason,
    due_disposition,
    schedule_blocked_reason,
)

ACTIVE = (Status.pending, Status.claimed, Status.blocked)


class SchedulingConflict(ValueError):
    """The operation, snapshot, state, or expected lease no longer matches."""


class RetryableInternalFailure(StrEnum):
    """Only known pre-handoff coordination failures may be automatically retried.

    Unknown acceptance/commit outcomes require durable readback, not requeueing.
    """

    database_contention = "database_contention"
    local_preparation_interrupted = "local_preparation_interrupted"


@dataclass(frozen=True, kw_only=True)
class JobActivation:
    snapshot: ScheduleSnapshot
    operation_id: UUID
    created_by_user_id: UUID
    schedule_timezone: str
    destination_id: UUID | None
    effective_artist_id: UUID | None
    supersedes_job_id: UUID | None = None
    lineage_root_job_id: UUID | None = None

    def values(self) -> dict:
        snapshot = self.snapshot
        return dict(
            workspace_id=snapshot.workspace_id,
            marketing_content_item_id=snapshot.content_item_id,
            marketing_content_item_channel_id=snapshot.channel_id,
            authorized_content_revision=snapshot.content_revision,
            approval_request_id=snapshot.approval_request_id,
            schedule_generation=snapshot.schedule_generation,
            scheduled_for=snapshot.scheduled_for,
            activation_operation_id=self.operation_id,
            created_by_user_id=self.created_by_user_id,
            schedule_timezone=self.schedule_timezone,
            social_account_connection_id=self.destination_id,
            effective_artist_id=self.effective_artist_id,
            supersedes_job_id=self.supersedes_job_id,
            lineage_root_job_id=self.lineage_root_job_id,
        )


@dataclass(frozen=True)
class JobCursor:
    created_at: datetime
    id: UUID


@dataclass(frozen=True)
class ActivationSource:
    """Authoritative source records, valid only while transaction locks are held."""

    item: MarketingContentItem
    channel: MarketingContentItemChannel | None
    campaign: Campaign | None
    approval: ApprovalEvidence | None


@dataclass(frozen=True)
class JobPage:
    jobs: tuple[SchedulingJob, ...]
    next_cursor: JobCursor | None


def _bounded(limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")


def _identity(value: str) -> None:
    if not value.strip() or len(value) > 255:
        raise ValueError("An explicit actor/worker identity is required")


def snapshot_for(job: SchedulingJob) -> ScheduleSnapshot:
    return ScheduleSnapshot(
        workspace_id=job.workspace_id,
        content_item_id=job.marketing_content_item_id,
        channel_id=job.marketing_content_item_channel_id,
        content_revision=job.authorized_content_revision,
        approval_request_id=job.approval_request_id,
        schedule_generation=job.schedule_generation,
        scheduled_for=job.scheduled_for,
    )


class SchedulingRepository:
    def __init__(
        self,
        session: AsyncSession,
        workspace_id: UUID,
        *,
        lateness_window_seconds: int,
    ):
        if not isinstance(workspace_id, UUID):
            raise ValueError("workspace_id is required")
        if type(lateness_window_seconds) is not int or lateness_window_seconds < 0:
            raise ValueError("An explicit nonnegative lateness policy is required")
        self.session = session
        self.workspace_id = workspace_id
        self.lateness_window_seconds = lateness_window_seconds
        self.window = timedelta(seconds=lateness_window_seconds)

    def _jobs(self):
        return select(SchedulingJob).where(
            SchedulingJob.workspace_id == self.workspace_id
        )

    async def _now(self) -> datetime:
        # now()/CURRENT_TIMESTAMP is transaction-start time and can be stale
        # after waiting on locks. Always use PostgreSQL's actual wall clock.
        if self.session.get_bind().dialect.name != "postgresql":
            raise RuntimeError("Scheduling mutations require PostgreSQL")
        now = await self.session.scalar(select(func.clock_timestamp()))
        assert isinstance(now, datetime)
        return now

    async def get_job(self, job_id: UUID) -> SchedulingJob | None:
        return await self.session.scalar(
            self._jobs()
            .where(SchedulingJob.id == job_id)
            .execution_options(populate_existing=True)
        )

    async def find_existing_job(
        self, activation: JobActivation
    ) -> SchedulingJob | None:
        """Replay includes terminal history; changed inputs are a hard conflict."""
        if activation.snapshot.workspace_id != self.workspace_id:
            raise SchedulingConflict("Activation workspace mismatch")
        job = await self.session.scalar(
            self._jobs()
            .where(SchedulingJob.activation_operation_id == activation.operation_id)
            .execution_options(populate_existing=True)
        )
        if job is not None and any(
            getattr(job, key) != value for key, value in activation.values().items()
        ):
            raise SchedulingConflict("Activation operation was reused with new inputs")
        return job

    async def get_activation_result(self, operation_id: UUID) -> SchedulingJob | None:
        """Read durable command history, including terminal jobs, within workspace."""
        return await self.session.scalar(
            self._jobs()
            .where(SchedulingJob.activation_operation_id == operation_id)
            .execution_options(populate_existing=True)
        )

    async def lock_activation_source(
        self, content_item_id: UUID, channel_id: UUID
    ) -> ActivationSource:
        parents = await self._parents(MarketingContentItem.id == content_item_id)
        if not parents:
            raise SchedulingConflict("Content not found in workspace")
        channels, evidence, campaigns = await self._lock_sources(parents)
        parent = parents[0]
        # Reserve existing job rows before taking destination locks.
        await self.session.execute(
            select(SchedulingJob.id)
            .where(
                SchedulingJob.workspace_id == self.workspace_id,
                SchedulingJob.marketing_content_item_id == parent.id,
            )
            .order_by(SchedulingJob.id)
            .with_for_update()
        )
        return ActivationSource(
            parent,
            channels.get(channel_id),
            campaigns.get(parent.campaign_id),
            evidence.get(parent.id),
        )

    async def list_jobs(
        self,
        *,
        statuses: Sequence[Status] | None = None,
        content_item_id: UUID | None = None,
        channel_id: UUID | None = None,
        scheduled_from: datetime | None = None,
        scheduled_through: datetime | None = None,
        cursor: JobCursor | None = None,
        limit: int = 100,
    ) -> JobPage:
        _bounded(limit)
        query = self._jobs()
        if statuses is not None:
            query = query.where(SchedulingJob.status.in_([Status(s) for s in statuses]))
        for column, value in (
            (SchedulingJob.marketing_content_item_id, content_item_id),
            (SchedulingJob.marketing_content_item_channel_id, channel_id),
        ):
            if value is not None:
                query = query.where(column == value)
        if scheduled_from is not None:
            query = query.where(SchedulingJob.scheduled_for >= scheduled_from)
        if scheduled_through is not None:
            query = query.where(SchedulingJob.scheduled_for <= scheduled_through)
        if cursor is not None:
            query = query.where(
                tuple_(SchedulingJob.created_at, SchedulingJob.id)
                < tuple_(literal(cursor.created_at), literal(cursor.id))
            )
        rows = tuple(
            (
                await self.session.scalars(
                    query.order_by(
                        SchedulingJob.created_at.desc(), SchedulingJob.id.desc()
                    )
                    .limit(limit + 1)
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        page = rows[:limit]
        next_cursor = (
            JobCursor(page[-1].created_at, page[-1].id) if len(rows) > limit else None
        )
        return JobPage(page, next_cursor)

    async def find_active_job(self, channel_id: UUID) -> SchedulingJob | None:
        return await self.session.scalar(
            self._jobs()
            .where(
                SchedulingJob.marketing_content_item_channel_id == channel_id,
                SchedulingJob.status.in_(ACTIVE),
            )
            .execution_options(populate_existing=True)
        )

    async def _lock_sources(self, parents):
        """Batch descendant locks/refresh; no relationship lazy loading or N+1."""
        if not parents:
            return {}, {}, {}
        ids = [p.id for p in parents]
        campaigns = (
            await self.session.scalars(
                select(Campaign)
                .options(lazyload("*"))
                .where(
                    Campaign.organization_id == self.workspace_id,
                    Campaign.id.in_({p.campaign_id for p in parents}),
                )
                .order_by(Campaign.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
        channels = (
            await self.session.scalars(
                select(MarketingContentItemChannel)
                .options(lazyload("*"))
                .where(MarketingContentItemChannel.marketing_content_item_id.in_(ids))
                .order_by(MarketingContentItemChannel.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
        await self.session.execute(
            select(ApprovalRequest.id)
            .where(
                ApprovalRequest.organization_id == self.workspace_id,
                ApprovalRequest.resource_type == "marketing_content_item",
                ApprovalRequest.resource_id.in_(ids),
            )
            .order_by(ApprovalRequest.id)
            .with_for_update()
        )
        evidence = await approvals.load_current_approval_evidence(
            self.session,
            self.workspace_id,
            "marketing_content_item",
            [(p.id, p.content_revision) for p in parents],
        )
        return ({c.id: c for c in channels}, evidence, {c.id: c for c in campaigns})

    async def _parents(self, predicate, *, limit=None, skip_locked=False):
        query = (
            select(MarketingContentItem)
            .options(lazyload("*"))
            .where(MarketingContentItem.organization_id == self.workspace_id, predicate)
            .order_by(MarketingContentItem.id)
            .with_for_update(skip_locked=skip_locked)
        )
        if limit is not None:
            query = query.limit(limit)
        return (
            await self.session.scalars(query.execution_options(populate_existing=True))
        ).all()

    def _stale_reason(self, job, parent, channel, evidence, campaign):
        if (
            channel is None
            or campaign is None
            or channel.marketing_content_item_id != parent.id
            or channel.social_account_connection_id != job.social_account_connection_id
            or (parent.artist_id or campaign.primary_artist_id)
            != job.effective_artist_id
        ):
            return Reason.destination_mismatch
        snapshot = snapshot_for(job)
        reason = approval_blocked_reason(
            snapshot,
            current_revision=parent.content_revision,
            approved_revision=parent.approved_revision,
            parent_status=parent.status,
            evidence=(
                evidence
                if parent.approval_request_id in (None, job.approval_request_id)
                else None
            ),
        )
        if reason:
            return Reason(reason)
        reason = schedule_blocked_reason(
            snapshot,
            scheduled_at=channel.scheduled_at,
            schedule_generation=channel.schedule_generation,
        )
        if reason:
            return Reason(reason)
        if channel.schedule_timezone != job.schedule_timezone:
            return Reason.changed_schedule_generation
        return None

    async def _locked_job(self, job_id):
        parent_id = await self.session.scalar(
            select(SchedulingJob.marketing_content_item_id).where(
                SchedulingJob.workspace_id == self.workspace_id,
                SchedulingJob.id == job_id,
            )
        )
        if parent_id is None:
            raise SchedulingConflict("Job not found in workspace")
        parents = await self._parents(MarketingContentItem.id == parent_id)
        channels, evidence, campaigns = await self._lock_sources(parents)
        job = await self.session.scalar(
            self._jobs()
            .where(SchedulingJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is None:
            raise SchedulingConflict("Job not found in workspace")
        parent = parents[0]
        reason = self._stale_reason(
            job,
            parent,
            channels.get(job.marketing_content_item_channel_id),
            evidence.get(parent.id),
            campaigns.get(parent.campaign_id),
        )
        return job, reason

    async def detect_stale_job(self, job_id: UUID) -> Reason | None:
        """Read authoritative snapshot drift while retaining coordination locks."""
        _, reason = await self._locked_job(job_id)
        return reason

    def _history(
        self,
        job,
        previous,
        operation,
        actor_kind,
        actor_key,
        now,
        *,
        operation_id=None,
        reason=None,
    ):
        self.session.add(
            SchedulingJobTransition(
                job_id=job.id,
                workspace_id=self.workspace_id,
                marketing_content_item_id=job.marketing_content_item_id,
                transition_version=job.transition_version,
                operation_id=operation_id or uuid4(),
                operation=operation,
                from_status=previous,
                to_status=job.status,
                actor_kind=actor_kind,
                actor_key=actor_key,
                reason_code=reason,
                created_at=now,
            )
        )

    async def create_pending_job(self, activation: JobActivation) -> SchedulingJob:
        existing = await self.find_existing_job(activation)
        if existing is not None:
            return existing
        parents = await self._parents(
            MarketingContentItem.id == activation.snapshot.content_item_id
        )
        if not parents:
            raise SchedulingConflict("Content not found in workspace")
        channels, evidence, campaigns = await self._lock_sources(parents)
        # A concurrent activation can have committed while we waited for parent.
        existing = await self.find_existing_job(activation)
        if existing is not None:
            return existing
        candidate = SchedulingJob(**activation.values())
        parent = parents[0]
        reason = self._stale_reason(
            candidate,
            parent,
            channels.get(activation.snapshot.channel_id),
            evidence.get(parent.id),
            campaigns.get(parent.campaign_id),
        )
        if reason:
            raise SchedulingConflict(reason.value)
        if activation.supersedes_job_id is not None:
            predecessor = await self.session.scalar(
                self._jobs()
                .where(
                    SchedulingJob.id == activation.supersedes_job_id,
                    SchedulingJob.marketing_content_item_id == parent.id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                predecessor is None
                or predecessor.status != Status.superseded
                or activation.lineage_root_job_id
                != (predecessor.lineage_root_job_id or predecessor.id)
            ):
                raise SchedulingConflict("Invalid supersession lineage")
        elif activation.lineage_root_job_id is not None:
            raise SchedulingConflict("Lineage root requires a predecessor")
        identifier = uuid4()
        now = await self._now()
        # ON CONFLICT preserves the caller's transaction for expected races,
        # including an operation ID raced across different parent rows.
        job = await self.session.scalar(
            insert(SchedulingJob)
            .values(
                **activation.values(),
                id=identifier,
                idempotency_key=f"labelos:scheduling:v1:{self.workspace_id}:{identifier}",
                status=Status.pending,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing()
            .returning(SchedulingJob)
        )
        if job is None:
            existing = await self.find_existing_job(activation)
            if existing is not None:
                return existing
            raise SchedulingConflict(
                "Channel already reserves this active/accepted intent"
            )
        self._history(
            job,
            None,
            "activate",
            "user",
            str(activation.created_by_user_id),
            now,
            operation_id=activation.operation_id,
        )
        await self.session.flush()
        return job

    async def find_due_pending_jobs(self, *, limit: int = 100):
        """Read due candidates, including late ones; this does not reserve jobs."""
        _bounded(limit)
        now = await self._now()
        return tuple(
            (
                await self.session.scalars(
                    self._jobs()
                    .where(
                        SchedulingJob.status == Status.pending,
                        SchedulingJob.scheduled_for <= now,
                    )
                    .order_by(SchedulingJob.scheduled_for, SchedulingJob.id)
                    .limit(limit)
                    .execution_options(populate_existing=True)
                )
            ).all()
        )

    def _disposition(self, job, now):
        return due_disposition(
            scheduled_for=job.scheduled_for, now=now, lateness_window=self.window
        )

    def _block_values(self, reason, now):
        return dict(
            status=Status.blocked,
            blocked_at=now,
            blocked_reason_code=reason,
            blocked_metadata={
                "reason_codes": [reason.value],
                "lateness_window_seconds": self.lateness_window_seconds,
            },
        )

    async def _batch(self, *, worker_id, limit, lease_duration=None):
        _bounded(limit)
        _identity(worker_id)
        now = await self._now()
        recovering = lease_duration is None
        candidate = (
            (SchedulingJob.status == Status.claimed)
            & (SchedulingJob.claim_expires_at <= now)
            if recovering
            else (SchedulingJob.status == Status.pending)
            & (SchedulingJob.scheduled_for <= now)
        )
        parents = await self._parents(
            select(SchedulingJob.id)
            .where(
                SchedulingJob.workspace_id == self.workspace_id,
                SchedulingJob.marketing_content_item_id == MarketingContentItem.id,
                candidate,
            )
            .exists(),
            limit=limit,
            skip_locked=True,
        )
        if not parents:
            return ()
        channels, evidence, campaigns = await self._lock_sources(parents)
        by_id = {p.id: p for p in parents}
        # Parent locks precede job locks. Lock jobs in UUID order, then process
        # the bounded selection in due order. Each parent admits at most limit jobs.
        selected = (
            self._jobs()
            .with_only_columns(SchedulingJob.id)
            .where(
                SchedulingJob.marketing_content_item_id.in_(by_id),
                candidate,
            )
            .order_by(SchedulingJob.scheduled_for, SchedulingJob.id)
            .limit(limit)
        )
        jobs = (
            await self.session.scalars(
                self._jobs()
                .where(SchedulingJob.id.in_(selected))
                .order_by(SchedulingJob.id)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
        ).all()
        now = await self._now()
        result = []
        for job in jobs:
            parent = by_id[job.marketing_content_item_id]
            reason = self._stale_reason(
                job,
                parent,
                channels.get(job.marketing_content_item_channel_id),
                evidence.get(parent.id),
                campaigns.get(parent.campaign_id),
            )
            disposition = self._disposition(job, now)
            if disposition == DueDisposition.missed and reason is None:
                reason = Reason.missed_schedule_window
            if not recovering and disposition == DueDisposition.future:
                continue
            previous = job.status
            job.fencing_token += 1
            job.transition_version += 1
            job.updated_at = now
            job.claimed_at = job.claim_expires_at = job.claimed_by = None
            if reason:
                for key, value in self._block_values(reason, now).items():
                    setattr(job, key, value)
                operation = "block"
            elif recovering:
                job.status = Status.pending
                operation = "recover_claim"
            else:
                job.status = Status.claimed
                job.claimed_by = worker_id
                job.claimed_at = now
                job.claim_expires_at = now + lease_duration
                operation = "claim"
            self._history(
                job,
                previous,
                operation,
                "worker",
                worker_id,
                now,
                reason=reason.value if reason else None,
            )
            if recovering or job.status == Status.claimed:
                result.append(job)
        await self.session.flush()
        return tuple(sorted(result, key=lambda j: (j.scheduled_for, j.id)))

    async def claim_batch(
        self, *, worker_id: str, limit: int, lease_duration: timedelta
    ):
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        return await self._batch(
            worker_id=worker_id, limit=limit, lease_duration=lease_duration
        )

    async def recover_expired_leases(self, *, worker_id: str, limit: int):
        """Privileged recovery: only expired claims; bump fences even when blocking."""
        return await self._batch(worker_id=worker_id, limit=limit)

    async def _change(
        self,
        job,
        values,
        *,
        operation,
        actor_key,
        now,
        expected_worker=None,
        expected_fencing_token=None,
        reason=None,
    ):
        _identity(actor_key)
        previous = job.status
        guard = [
            SchedulingJob.id == job.id,
            SchedulingJob.workspace_id == self.workspace_id,
            SchedulingJob.status == previous,
            SchedulingJob.transition_version == job.transition_version,
            SchedulingJob.fencing_token == job.fencing_token,
        ]
        if previous == Status.claimed:
            if expected_worker is None or expected_fencing_token is None:
                raise SchedulingConflict(
                    "Expected worker and fencing token are required"
                )
            guard.extend(
                [
                    SchedulingJob.claimed_by == expected_worker,
                    SchedulingJob.fencing_token == expected_fencing_token,
                    SchedulingJob.claim_expires_at > func.clock_timestamp(),
                ]
            )
        if operation == "accept_delivery":
            guard.extend(
                [
                    SchedulingJob.scheduled_for <= func.clock_timestamp(),
                    SchedulingJob.scheduled_for >= func.clock_timestamp() - self.window,
                ]
            )
        values = dict(
            values,
            transition_version=job.transition_version + 1,
            fencing_token=job.fencing_token + 1,
            updated_at=now,
            claimed_at=None,
            claim_expires_at=None,
            claimed_by=None,
        )
        changed = await self.session.scalar(
            update(SchedulingJob)
            .where(*guard)
            .values(**values)
            .returning(SchedulingJob)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        if changed is None:
            raise SchedulingConflict("Job state or lease ownership changed/expired")
        self._history(
            changed,
            previous,
            operation,
            "worker" if expected_worker is not None else "user",
            actor_key,
            now,
            reason=reason,
        )
        await self.session.flush()
        return changed

    async def cancel_pending_job(self, job_id: UUID, *, actor_key: str):
        job, _ = await self._locked_job(job_id)
        if job.status != Status.pending:
            raise SchedulingConflict("Only a pending job may be cancelled here")
        now = await self._now()
        return await self._change(
            job,
            dict(
                status=Status.cancelled,
                cancelled_at=now,
                cancellation_reason="user_cancelled",
            ),
            operation="cancel",
            actor_key=actor_key,
            now=now,
            reason="user_cancelled",
        )

    async def supersede_active_job(
        self,
        job_id: UUID,
        *,
        actor_key: str,
        expected_worker=None,
        expected_fencing_token=None,
    ):
        job, _ = await self._locked_job(job_id)
        if job.status not in ACTIVE:
            raise SchedulingConflict("Only an active job may be superseded")
        return await self._change(
            job,
            dict(status=Status.superseded),
            operation="supersede",
            actor_key=actor_key,
            now=await self._now(),
            expected_worker=expected_worker,
            expected_fencing_token=expected_fencing_token,
        )

    async def block_job(
        self,
        job_id: UUID,
        *,
        reason: Reason,
        actor_key: str,
        expected_worker=None,
        expected_fencing_token=None,
    ):
        job, _ = await self._locked_job(job_id)
        if job.status not in (Status.pending, Status.claimed):
            raise SchedulingConflict("Only pending or claimed jobs may be blocked")
        now = await self._now()
        reason = Reason(reason)
        return await self._change(
            job,
            self._block_values(reason, now),
            operation="block",
            actor_key=actor_key,
            now=now,
            expected_worker=expected_worker,
            expected_fencing_token=expected_fencing_token,
            reason=reason.value,
        )

    async def requeue_retryable_failure(
        self,
        job_id: UUID,
        *,
        expected_worker: str,
        expected_fencing_token: int,
        failure: RetryableInternalFailure,
    ):
        failure = RetryableInternalFailure(failure)
        job, reason = await self._locked_job(job_id)
        if job.status != Status.claimed:
            raise SchedulingConflict("Only a current claim may be requeued")
        now = await self._now()
        if reason is None and self._disposition(job, now) == DueDisposition.missed:
            reason = Reason.missed_schedule_window
        values = (
            self._block_values(reason, now) if reason else dict(status=Status.pending)
        )
        return await self._change(
            job,
            values,
            operation="block" if reason else "recover_claim",
            actor_key=expected_worker,
            now=now,
            expected_worker=expected_worker,
            expected_fencing_token=expected_fencing_token,
            reason=reason.value if reason else failure.value,
        )

    async def record_handoff_acceptance(
        self,
        job_id: UUID,
        *,
        expected_worker: str,
        expected_fencing_token: int,
        request: DeliveryAcceptanceRequest,
        receipt: DeliveryAcceptanceReceipt,
    ):
        """Record a trusted Delivery inbox receipt in that inbox's transaction.

        Caller must persist/verify the durable inbox with the same session and
        roll back the entire transaction on any exception. A DTO is not proof
        of durability. Unknown commit outcomes must be read back by job/key.
        """
        job, reason = await self._locked_job(job_id)
        if job.status != Status.claimed:
            raise SchedulingConflict("Only a current claim may be handed off")
        now = await self._now()
        if (
            reason is not None
            or self._disposition(job, now) != DueDisposition.claimable
        ):
            raise SchedulingConflict(
                reason.value if reason else "missed_schedule_window"
            )
        if (
            request.job_id != job.id
            or request.snapshot != snapshot_for(job)
            or request.destination_id != job.social_account_connection_id
            or request.artist_profile_id != job.effective_artist_id
            or request.authoring_timezone != job.schedule_timezone
            or request.idempotency_key != job.idempotency_key
            or not receipt.matches(request)
        ):
            raise SchedulingConflict("handoff_contract_violation")
        return await self._change(
            job,
            dict(
                status=Status.handed_off,
                handed_off_at=now,
                handoff_receipt_id=receipt.delivery_request_id,
            ),
            operation="accept_delivery",
            actor_key=expected_worker,
            now=now,
            expected_worker=expected_worker,
            expected_fencing_token=expected_fencing_token,
        )
