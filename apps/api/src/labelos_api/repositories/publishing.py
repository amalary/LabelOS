"""Persistence only. Callers own authorization and the outer transaction.

Mutations require PostgreSQL READ COMMITTED. SQLite tests install explicit-BEGIN
driver hooks; legacy SQLite savepoint behavior is not a production guarantee.

Not a delivery receiver or worker. The orchestrator calls creation inside the
existing handoff port/session contract; repository creation is not authorization.
"""

from datetime import datetime
from random import random
from uuid import UUID, uuid4

from labelos_database.models import (
    Publication,
    PublicationAttempt,
    PublicationLease,
    PublicationTransition,
    RealtimeEvent,
    SchedulingJob,
    SocialAccountConnection,
)
from labelos_database.publishing import PublicResourceURL
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from labelos_api.publishing import contracts as domain
from labelos_api.publishing.execution import PublicationClaim
from labelos_api.publishing.retries import (
    MAX_ATTEMPTS,
    POLICY_VERSION,
    FailureCategory,
    retry_decision,
)
from labelos_api.realtime.events import realtime_channel
from labelos_api.repositories.publication_leases import (
    PublicationLeaseLost,
    require_ownership,
)
from labelos_api.repositories.scheduling import snapshot_for
from labelos_api.scheduling.contracts import DeliveryAcceptanceRequest
from labelos_api.scheduling.payload import canonical_json, envelope, validate_request


class PublicationConflict(ValueError):
    """Stale version, mismatched immutable intent, or reused operation identity."""


def aggregate(row: Publication) -> domain.Publication:
    attempts = {
        a.id: domain.PublicationAttempt(
            id=a.id,
            workspace_id=a.workspace_id,
            publication_id=a.publication_id,
            number=a.number,
            started_at=a.started_at,
        )
        for a in row.attempts
    }
    history = []
    for entry in row.transitions:
        evidence = None
        if entry.outcome is not None:
            if entry.attempt_id is None or entry.observed_at is None:
                raise PublicationConflict("publication_evidence_missing")
            evidence = domain.PublicationEvidence(
                workspace_id=row.workspace_id,
                publication_id=row.id,
                attempt_id=entry.attempt_id,
                destination_id=row.social_account_connection_id,
                outcome=domain.DeliveryOutcome(entry.outcome),
                source=domain.EvidenceSource(entry.source),
                observed_at=entry.observed_at,
                external_post_id=entry.external_post_id,
                failure_category=(
                    FailureCategory(entry.failure_category)
                    if entry.failure_category
                    else None
                ),
                retry_after_seconds=entry.retry_after_seconds,
                reason=(
                    domain.PublicationFailureReason(entry.failure_reason)
                    if entry.failure_reason
                    else None
                ),
            )
        attempt = None
        if entry.operation in ("start", "retry"):
            if entry.attempt_id is None or entry.attempt_id not in attempts:
                raise PublicationConflict("publication_attempt_missing")
            attempt = attempts[entry.attempt_id]
        history.append(
            domain.PublicationTransition(
                operation=domain.PublicationOperation(entry.operation),
                occurred_at=entry.occurred_at,
                attempt=attempt,
                evidence=evidence,
            )
        )
    result = domain.Publication(
        id=row.id,
        created_at=row.created_at,
        intent=domain.PublicationIntent(
            workspace_id=row.workspace_id,
            scheduling_job_id=row.scheduling_job_id,
            content_item_id=row.marketing_content_item_id,
            channel_id=row.marketing_content_item_channel_id,
            destination_id=row.social_account_connection_id,
            approval_request_id=row.approval_request_id,
            content_revision=row.authorized_content_revision,
            schedule_generation=row.schedule_generation,
            payload_fingerprint=row.payload_fingerprint,
        ),
        history=tuple(history),
    )
    if (
        result.state != row.status
        or len(history) != row.transition_version
        or len(attempts) != len(result.attempts)
    ):
        raise PublicationConflict("publication_history_mismatch")
    return result


class PublicationRepository:
    def __init__(self, session: AsyncSession, workspace_id: UUID):
        self.session = session
        self.workspace_id = workspace_id

    async def get(
        self, publication_id: UUID, *, lock: bool = False
    ) -> Publication | None:
        query = (
            select(Publication)
            .where(
                Publication.workspace_id == self.workspace_id,
                Publication.id == publication_id,
            )
            .options(
                selectinload(Publication.attempts).selectinload(
                    PublicationAttempt.observations
                ),
                selectinload(Publication.transitions),
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def due_retries(
        self, *, now: datetime, limit: int = 100
    ) -> list[tuple[UUID, int]]:
        """Read-only candidates; execute rechecks eligibility under existing locks."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("invalid_retry_batch_size")
        rows = await self.session.execute(
            select(Publication.id, Publication.transition_version)
            .where(
                Publication.workspace_id == self.workspace_id,
                Publication.status == "retryable_failure",
                Publication.retry_disposition.in_(("automatic", "provider_delay")),
                Publication.retry_policy_version == POLICY_VERSION,
                Publication.next_retry_at <= now,
                Publication.retry_deadline_at > now,
            )
            .order_by(Publication.next_retry_at, Publication.id)
            .limit(limit)
        )
        return [(row.id, row.transition_version) for row in rows]

    @staticmethod
    def require_retry_eligible(row: Publication, now: datetime) -> None:
        if row.status != "retryable_failure":
            return
        if (
            row.retry_policy_version != POLICY_VERSION
            or row.retry_disposition not in ("automatic", "provider_delay")
            or row.next_retry_at is None
            or row.retry_deadline_at is None
        ):
            raise PublicationConflict("retry_not_automatic")
        if len(row.attempts) >= MAX_ATTEMPTS or now >= row.retry_deadline_at:
            raise PublicationConflict("retry_budget_exhausted")
        if now < row.next_retry_at:
            raise PublicationConflict("retry_not_due")

    async def get_by_job(self, job_id: UUID) -> Publication | None:
        identifier = await self.session.scalar(
            select(Publication.id).where(
                Publication.workspace_id == self.workspace_id,
                Publication.scheduling_job_id == job_id,
            )
        )
        return await self.get(identifier) if identifier else None

    async def require_unused_execution(
        self, execution_id: UUID, publication_id: UUID
    ) -> None:
        """Reject consumed commands, including commands whose attempt failed.

        Call again under the prepared publication lock before starting. The
        workspace/execution unique constraint also rejects cross-publication
        races at flush/commit, before any external call.
        """
        existing = await self.session.scalar(
            select(PublicationAttempt.publication_id).where(
                PublicationAttempt.workspace_id == self.workspace_id,
                PublicationAttempt.execution_id == execution_id,
            )
        )
        if existing is not None:
            raise PublicationConflict(
                "execution_already_started"
                if existing == publication_id
                else "execution_identity_conflict"
            )

    async def create(
        self,
        request: DeliveryAcceptanceRequest,
        *,
        created_at: datetime,
        destination_identity: str | None = None,
    ) -> Publication:
        """Retain a validated envelope; duplicate requests return the original row.

        This low-level method does not authorize acceptance or mark a job handed off.
        Locks source job before inbox, matching the existing Scheduling lock order.
        """
        validate_request(request)
        if destination_identity is not None and (
            len(destination_identity) != 64
            or any(c not in "0123456789abcdef" for c in destination_identity)
        ):
            raise PublicationConflict("invalid_destination_identity")
        if (
            request.snapshot.workspace_id != self.workspace_id
            or request.idempotency_key
            != f"labelos:scheduling:v1:{self.workspace_id}:{request.job_id}"
        ):
            raise PublicationConflict("publication_scope_mismatch")
        job = await self.session.scalar(
            select(SchedulingJob)
            .where(
                SchedulingJob.workspace_id == self.workspace_id,
                SchedulingJob.id == request.job_id,
            )
            .with_for_update()
        )
        if (
            job is None
            or snapshot_for(job) != request.snapshot
            or job.social_account_connection_id != request.destination_id
            or job.effective_artist_id != request.artist_profile_id
            or job.schedule_timezone != request.authoring_timezone
        ):
            raise PublicationConflict("publication_source_mismatch")
        canonical = canonical_json(envelope(request))
        existing = await self.get_by_job(request.job_id)
        if existing:
            if (
                existing.payload_fingerprint != request.payload_fingerprint
                or existing.canonical_envelope != canonical
                or existing.destination_identity != destination_identity
            ):
                raise PublicationConflict("publication_payload_conflict")
            return existing
        provider = await self.session.scalar(
            select(SocialAccountConnection.provider).where(
                SocialAccountConnection.id == request.destination_id,
                SocialAccountConnection.organization_id == self.workspace_id,
            )
        )
        if provider is None:
            raise PublicationConflict("publication_destination_missing")
        snapshot = request.snapshot
        intent = domain.PublicationIntent(
            workspace_id=self.workspace_id,
            scheduling_job_id=job.id,
            content_item_id=snapshot.content_item_id,
            channel_id=snapshot.channel_id,
            destination_id=request.destination_id,
            approval_request_id=snapshot.approval_request_id,
            content_revision=snapshot.content_revision,
            schedule_generation=snapshot.schedule_generation,
            payload_fingerprint=request.payload_fingerprint,
        )
        value = domain.Publication(id=uuid4(), intent=intent, created_at=created_at)
        row = Publication(
            id=value.id,
            workspace_id=self.workspace_id,
            scheduling_job_id=job.id,
            marketing_content_item_id=intent.content_item_id,
            marketing_content_item_channel_id=intent.channel_id,
            social_account_connection_id=intent.destination_id,
            approval_request_id=intent.approval_request_id,
            authorized_content_revision=intent.content_revision,
            schedule_generation=intent.schedule_generation,
            provider=provider,
            destination_identity=destination_identity,
            receipt_id=uuid4(),
            idempotency_key=request.idempotency_key,
            payload_schema_version=request.payload_schema_version,
            payload_fingerprint=request.payload_fingerprint,
            canonical_envelope=canonical,
            correlation_id=request.correlation_id,
            status="pending",
            transition_version=0,
            created_at=created_at,
            updated_at=created_at,
        )
        async with self.session.begin_nested():
            self.session.add(row)
            await self.session.flush()
            self.session.add(
                PublicationLease(publication_id=row.id, workspace_id=self.workspace_id)
            )
            self._outbox(row, row.receipt_id)
            await self.session.flush()
        result = await self.get(row.id)
        if result is None:
            raise PublicationConflict("publication_missing")
        return result

    async def append(
        self,
        publication_id: UUID,
        *,
        expected_version: int,
        operation_id: UUID,
        entry: domain.PublicationTransition,
        execution_id: UUID | None = None,
        http_status: int | None = None,
        provider_url: str | None = None,
        claim: PublicationClaim | None = None,
    ) -> Publication:
        """Append a validated fact and project state with stale-write rejection.

        Start records must commit before later provider I/O. Observation times and
        outcomes are validated by the unchanged Stage 1 aggregate. No I/O occurs here.
        """
        if provider_url is not None:
            if (
                entry.evidence is None
                or entry.evidence.outcome != domain.DeliveryOutcome.published
            ):
                raise PublicationConflict("url_requires_success")
            PublicResourceURL().process_bind_param(
                provider_url, self.session.get_bind().dialect
            )
        if type(expected_version) is not int or expected_version < 0:
            raise PublicationConflict("invalid_expected_version")
        if entry.attempt is None and execution_id is not None:
            raise PublicationConflict("unexpected_execution_id")
        if not isinstance(operation_id, UUID) or operation_id.int == 0:
            raise PublicationConflict("invalid_operation_id")
        if (entry.attempt is not None) != (
            isinstance(execution_id, UUID) and execution_id.int != 0
        ):
            raise PublicationConflict("invalid_execution_id")
        if http_status is not None and (
            type(http_status) is not int
            or not 100 <= http_status <= 599
            or entry.evidence is None
        ):
            raise PublicationConflict("invalid_http_status")
        async with self.session.begin_nested():
            row = await self.get(publication_id, lock=True)
            if row is None or row.transition_version != expected_version:
                raise PublicationConflict("publication_version_conflict")
            cancelling = entry.operation == domain.PublicationOperation.cancel
            lease = (
                await self.session.get(PublicationLease, row.id, populate_existing=True)
                if cancelling
                else await require_ownership(self.session, row, claim)
            )
            if (
                lease is not None
                and lease.interrupted
                and (
                    entry.attempt
                    or (
                        entry.evidence
                        and entry.evidence.outcome
                        == domain.DeliveryOutcome.retryable_failure
                    )
                )
            ):
                raise PublicationLeaseLost(
                    "interrupted_executor_requires_manual_resolution"
                )
            if entry.attempt:
                self.require_retry_eligible(row, entry.attempt.started_at)
            before = aggregate(row)
            after = before.transition(workspace_id=self.workspace_id, entry=entry)
            if entry.attempt:
                attempt = entry.attempt
                self.session.add(
                    PublicationAttempt(
                        id=attempt.id,
                        workspace_id=self.workspace_id,
                        publication_id=row.id,
                        number=attempt.number,
                        started_at=attempt.started_at,
                        execution_id=execution_id,
                    )
                )
                await self.session.flush()
            evidence = entry.evidence
            retry_values = dict(
                failure_category=None,
                retry_disposition=None,
                next_retry_at=None,
                retry_deadline_at=None,
                retry_policy_version=None,
            )
            if evidence and evidence.outcome != domain.DeliveryOutcome.published:
                category = evidence.failure_category
                if evidence.outcome == domain.DeliveryOutcome.unknown:
                    category = FailureCategory.ambiguous_outcome
                if category is None:
                    assert evidence.reason is not None
                    reason = domain.PublicationFailureReason
                    category = {
                        reason.rate_limited: FailureCategory.rate_limited,
                        reason.authorization_required: FailureCategory.authentication,
                        reason.invalid_content: FailureCategory.invalid_content_media,
                        reason.destination_unavailable: (
                            FailureCategory.unsupported_operation
                        ),
                    }.get(
                        evidence.reason,
                        (
                            FailureCategory.provider_unavailable
                            if evidence.outcome
                            == domain.DeliveryOutcome.retryable_failure
                            else FailureCategory.permanent_rejection
                        ),
                    )
                if (
                    evidence.outcome == domain.DeliveryOutcome.permanent_failure
                    and evidence.failure_category is None
                    and category
                    not in {
                        FailureCategory.invalid_content_media,
                        FailureCategory.unsupported_operation,
                        FailureCategory.permanent_rejection,
                    }
                ):
                    category = FailureCategory.permanent_rejection
                decision = retry_decision(
                    category,
                    attempt_number=len(before.attempts),
                    first_started_at=before.attempts[0].started_at,
                    observed_at=entry.occurred_at,
                    retry_after_seconds=evidence.retry_after_seconds,
                    jitter=random(),
                )
                retry_values = dict(
                    failure_category=category.value,
                    retry_disposition=decision.disposition.value,
                    next_retry_at=decision.next_retry_at,
                    retry_deadline_at=decision.deadline_at,
                    retry_policy_version=decision.policy_version,
                )
            values = dict(
                **retry_values,
                status=after.state.value,
                transition_version=expected_version + 1,
                updated_at=entry.occurred_at,
                external_post_id=evidence.external_post_id if evidence else None,
                provider_url=provider_url,
                published_at=(
                    evidence.observed_at
                    if evidence and evidence.outcome == domain.DeliveryOutcome.published
                    else None
                ),
                cancelled_at=(
                    entry.occurred_at
                    if after.state == domain.PublicationState.cancelled
                    else None
                ),
                cancellation_reason=(
                    "scheduling_cancelled"
                    if after.state == domain.PublicationState.cancelled
                    else None
                ),
                manual_action_at=(
                    entry.occurred_at
                    if after.state == domain.PublicationState.manual_action_required
                    else None
                ),
                manual_action_reason=(
                    "outcome_unknown"
                    if after.state == domain.PublicationState.manual_action_required
                    else None
                ),
            )
            changed = await self.session.scalar(
                update(Publication)
                .where(
                    Publication.id == row.id,
                    Publication.workspace_id == self.workspace_id,
                    Publication.transition_version == expected_version,
                    Publication.status == before.state.value,
                )
                .values(**values)
                .returning(Publication.id)
                .execution_options(synchronize_session=False)
            )
            if changed is None:
                raise PublicationConflict("publication_version_conflict")
            self.session.add(
                PublicationTransition(
                    workspace_id=self.workspace_id,
                    publication_id=row.id,
                    version=expected_version + 1,
                    operation_id=operation_id,
                    operation=entry.operation.value,
                    from_status=before.state.value,
                    to_status=after.state.value,
                    occurred_at=entry.occurred_at,
                    attempt_id=(
                        entry.attempt.id
                        if entry.attempt
                        else evidence.attempt_id if evidence else None
                    ),
                    observed_at=evidence.observed_at if evidence else None,
                    outcome=evidence.outcome.value if evidence else None,
                    source=evidence.source.value if evidence else None,
                    failure_reason=(
                        evidence.reason.value if evidence and evidence.reason else None
                    ),
                    external_post_id=evidence.external_post_id if evidence else None,
                    http_status=http_status,
                    **retry_values,
                    retry_after_seconds=(
                        evidence.retry_after_seconds if evidence else None
                    ),
                )
            )
            await self.session.flush()
            await self.session.refresh(row)
            self._outbox(row, operation_id)
            await self.session.flush()
            if cancelling and lease is not None:
                lease.fencing_token += 1
                lease.owner_id = lease.expires_at = None
                await self.session.flush()
            elif claim is not None:
                # Recheck wall time after all writes; failure rolls back the savepoint.
                lease = await require_ownership(self.session, row, claim)
                assert lease is not None
                if entry.evidence is not None:
                    lease.owner_id = lease.expires_at = None
                    await self.session.flush()
        result = await self.get(publication_id)
        if result is None:
            raise PublicationConflict("publication_missing")
        return result

    def _outbox(self, row, operation_id):
        self.session.add(
            RealtimeEvent(
                organization_id=self.workspace_id,
                channel=realtime_channel(self.workspace_id),
                event_type="marketing.publication.changed",
                entity_type="marketing_content_item",
                entity_id=str(row.marketing_content_item_id),
                operation_id=f"publication:{operation_id}",
                payload={
                    "publicationId": str(row.id),
                    "contentItemId": str(row.marketing_content_item_id),
                    "channelId": str(row.marketing_content_item_channel_id),
                    "status": row.status,
                    "transitionVersion": row.transition_version,
                    "failureCategory": row.failure_category,
                    "retryDisposition": row.retry_disposition,
                    "nextRetryAt": (
                        row.next_retry_at.isoformat() if row.next_retry_at else None
                    ),
                    "correlationId": str(row.correlation_id),
                },
            )
        )
