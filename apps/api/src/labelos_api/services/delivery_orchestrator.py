"""Delivery application boundary; no polling, due selection, leases or retry timers.

The authenticated host supplies workspace scope and Scheduling's locked controls.
Acceptance uses Scheduling's composer; execution consumes an explicit accepted ID.
Production receiver/provider factories remain disabled. No public API is added.
"""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from labelos_database.models import SchedulingJob, SocialAccountConnection
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labelos_api.publishing import contracts as domain
from labelos_api.publishing.execution import (
    DeliveryContext,
    DeliveryResult,
    DisabledPublicationProvider,
    PublicationProvider,
)
from labelos_api.repositories.publishing import (
    PublicationConflict,
    PublicationRepository,
)
from labelos_api.repositories.scheduling import (
    SchedulingConflict,
    SchedulingRepository,
    snapshot_for,
)
from labelos_api.scheduling.contracts import (
    DeliveryAcceptanceReceipt,
    DeliveryAcceptanceRequest,
    DeliveryAcceptanceResult,
    DurableAccepted,
    SchedulingFeatureControls,
    TerminalRejected,
)
from labelos_api.scheduling.payload import (
    InvalidHandoffPayload,
    canonical_json,
    envelope,
    prepare_request,
    validate_request,
)
from labelos_api.services.scheduling_destination import lock_destination
from labelos_api.services.scheduling_eligibility import (
    SchedulingExecutionMode,
    evaluate_channel_eligibility,
)
from labelos_api.services.scheduling_handoff import accept_scheduling_handoff


class DeliveryIneligible(ValueError):
    """Fixed internal reason code; never includes payloads or account identifiers."""


def _require_deliverable_content(request: DeliveryAcceptanceRequest) -> None:
    # Structural/media validation belongs to the canonical payload contract.
    # Provider-specific limits belong to adapters, but an empty post is never work.
    content = json.loads(request.canonical_payload)
    if not (
        (content["caption"] or "").strip()
        or content["asset_refs"]
        or content["hashtags"]
    ):
        raise DeliveryIneligible("content_empty")


async def _identity(session, workspace_id, destination_id) -> str:
    # Caller already holds the destination lock. No credentials are selected.
    row = (
        await session.execute(
            select(
                SocialAccountConnection.provider,
                SocialAccountConnection.external_account_id,
            ).where(
                SocialAccountConnection.organization_id == workspace_id,
                SocialAccountConnection.id == destination_id,
            )
        )
    ).one_or_none()
    if (
        row is None
        or not row.external_account_id
        or not row.external_account_id.strip()
    ):
        raise DeliveryIneligible("destination_identity_missing")
    return hashlib.sha256(
        canonical_json([row.provider, row.external_account_id])
    ).hexdigest()


class _AcceptanceReceiver:
    """Private port adapter, invoked only inside the validated Scheduling composer."""

    def __init__(self, session: AsyncSession, workspace_id: UUID):
        self.session = session
        self.workspace_id = workspace_id

    async def accept(self, session, request):
        if (
            session is not self.session
            or request.snapshot.workspace_id != self.workspace_id
        ):
            return TerminalRejected()
        repo = PublicationRepository(session, self.workspace_id)
        job = await session.scalar(
            select(SchedulingJob).where(
                SchedulingJob.workspace_id == self.workspace_id,
                SchedulingJob.id == request.job_id,
            )
        )
        existing = await repo.get_by_job(request.job_id)
        if job is None:
            return TerminalRejected()
        if existing is not None:
            if (
                job.status != "handed_off"
                or job.handoff_receipt_id != existing.receipt_id
                or existing.canonical_envelope != canonical_json(envelope(request))
                or existing.payload_fingerprint != request.payload_fingerprint
            ):
                return TerminalRejected()
            row = existing
        else:
            # Never fabricate missing acceptance for a historical handed-off job.
            if job.status != "claimed":
                return TerminalRejected()
            try:
                _require_deliverable_content(request)
                identity = await _identity(
                    session, self.workspace_id, request.destination_id
                )
                row = await repo.create(
                    request, created_at=datetime.now(UTC), destination_identity=identity
                )
            except (PublicationConflict, DeliveryIneligible):
                return TerminalRejected()
        return DurableAccepted(
            receipt=DeliveryAcceptanceReceipt(
                delivery_request_id=row.receipt_id,
                idempotency_key=row.idempotency_key,
                payload_fingerprint=row.payload_fingerprint,
            )
        )


class DeliveryOrchestrator:
    async def accept_execution(
        self,
        repository: SchedulingRepository,
        *,
        request: DeliveryAcceptanceRequest,
        expected_worker: str,
        expected_fencing_token: int,
        controls: SchedulingFeatureControls,
    ) -> DeliveryAcceptanceResult:
        """Publication + outbox + handoff history commit in the caller's transaction.

        Scheduling alone validates due time, lease/fence, controls and acceptance.
        Its savepoint rolls back all delivery writes if the final fence check fails.
        """
        return await accept_scheduling_handoff(
            repository,
            receiver=_AcceptanceReceiver(repository.session, repository.workspace_id),
            request=request,
            expected_worker=expected_worker,
            expected_fencing_token=expected_fencing_token,
            controls=controls,
        )

    async def prepare_execution(
        self, repository: SchedulingRepository, publication_id: UUID
    ) -> DeliveryContext:
        """Reload accepted work under source/job/destination/publication locks.

        This context is a transaction-local observation, not a reusable execution
        permit. execute() repeats preparation in the same transaction as the start.
        No due-window or claim checks apply after durable Scheduling acceptance.
        """
        repo = PublicationRepository(repository.session, repository.workspace_id)
        row = await repo.get(publication_id)
        if row is None:
            raise DeliveryIneligible("publication_missing")
        try:
            source = await repository.lock_activation_source(
                row.marketing_content_item_id, row.marketing_content_item_channel_id
            )
            job = await repository.get_job(row.scheduling_job_id)
            if (
                job is None
                or job.status != "handed_off"
                or job.handoff_receipt_id != row.receipt_id
            ):
                raise DeliveryIneligible("scheduling_acceptance_missing")
            reason = await repository.detect_stale_job(job.id)
            if reason:
                raise DeliveryIneligible(reason.value)
            connection = await lock_destination(
                repository.session,
                repository.workspace_id,
                row.social_account_connection_id,
            )
            row = await repo.get(publication_id, lock=True)
            assert row is not None
            if row.status not in ("pending", "retryable_failure"):
                raise DeliveryIneligible("publication_not_executable")
            if (
                row.destination_identity is None
                or row.destination_identity
                != await _identity(
                    repository.session,
                    repository.workspace_id,
                    row.social_account_connection_id,
                )
            ):
                raise DeliveryIneligible("destination_identity_changed")
            if source.channel is None or source.campaign is None:
                raise DeliveryIneligible("content_missing")
            eligibility = evaluate_channel_eligibility(
                workspace_id=repository.workspace_id,
                item=source.item,
                channel=source.channel,
                evidence=source.approval,
                connection=connection,
                effective_artist_id=source.item.artist_id
                or source.campaign.primary_artist_id,
                expected_content_revision=row.authorized_content_revision,
                execution_mode=SchedulingExecutionMode.automatic,
                # Validate content/destination readiness, not Scheduling activation.
                controls=SchedulingFeatureControls(
                    execution_enabled=True, delivery_receiver_configured=True
                ),
            )
            if not eligibility.eligible:
                raise DeliveryIneligible(eligibility.reason_codes[0])
            stored = json.loads(row.canonical_envelope)
            request = DeliveryAcceptanceRequest(
                snapshot=snapshot_for(job),
                job_id=job.id,
                destination_id=row.social_account_connection_id,
                artist_profile_id=job.effective_artist_id,
                authoring_timezone=job.schedule_timezone,
                payload_fingerprint=row.payload_fingerprint,
                payload_schema_version=row.payload_schema_version,
                correlation_id=row.correlation_id,
                canonical_payload=canonical_json(stored["content"]),
            )
            assets = validate_request(request)
            _require_deliverable_content(request)
            current = prepare_request(
                snapshot=request.snapshot,
                job_id=job.id,
                destination_id=request.destination_id,
                artist_profile_id=job.effective_artist_id,
                authoring_timezone=job.schedule_timezone,
                correlation_id=row.correlation_id,
                item=source.item,
                channel=source.channel,
                asset_bytes=assets,
            )
            if (
                current != request
                or canonical_json(envelope(request)) != row.canonical_envelope
            ):
                raise DeliveryIneligible("content_changed")
        except (SchedulingConflict, InvalidHandoffPayload) as exc:
            raise DeliveryIneligible("source_invalid") from exc
        return DeliveryContext(
            workspace_id=repository.workspace_id,
            publication_id=row.id,
            scheduling_job_id=row.scheduling_job_id,
            destination_id=row.social_account_connection_id,
            provider=row.provider,
            destination_identity=row.destination_identity,
            canonical_envelope=row.canonical_envelope,
            transition_version=row.transition_version,
        )

    async def execute(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        workspace_id: UUID,
        publication_id: UUID,
        provider: PublicationProvider | None = None,
    ) -> DeliveryResult:
        """One explicit execution, with an unavailable production default.

        Start commits before adapter I/O; evidence/history/outbox commit afterwards.
        Unknown start/outcome commits propagate and require scoped readback. There
        is no automatic retry or provider call on an ambiguous start commit.
        """
        adapter = provider if provider is not None else DisabledPublicationProvider()
        async with sessions.begin() as session:
            context = await self.prepare_execution(
                SchedulingRepository(session, workspace_id, lateness_window_seconds=0),
                publication_id,
            )
            repo = PublicationRepository(session, workspace_id)
            row = await repo.get(publication_id)
            assert row is not None
            if not adapter.enabled:
                return DeliveryResult(
                    publication_id=row.id,
                    status=row.status,
                    reason_code="provider_execution_disabled",
                )
            attempt = domain.PublicationAttempt(
                id=uuid4(),
                workspace_id=workspace_id,
                publication_id=row.id,
                number=len(row.attempts) + 1,
                started_at=datetime.now(UTC),
            )
            row = await repo.append(
                row.id,
                expected_version=context.transition_version,
                operation_id=uuid4(),
                execution_id=uuid4(),
                entry=domain.PublicationTransition(
                    operation=(
                        domain.PublicationOperation.start
                        if attempt.number == 1
                        else domain.PublicationOperation.retry
                    ),
                    occurred_at=attempt.started_at,
                    attempt=attempt,
                ),
            )
            version = row.transition_version
        # No database session/locks or Scheduling lease spans this call.
        try:
            evidence = await adapter.deliver(context, attempt)
        except Exception:
            evidence = domain.PublicationEvidence(
                workspace_id=workspace_id,
                publication_id=publication_id,
                attempt_id=attempt.id,
                destination_id=context.destination_id,
                outcome=domain.DeliveryOutcome.unknown,
                source=domain.EvidenceSource.execution_interrupted,
                observed_at=datetime.now(UTC),
                reason=domain.PublicationFailureReason.outcome_unknown,
            )
        await self.record_evidence(
            sessions,
            workspace_id=workspace_id,
            publication_id=publication_id,
            expected_version=version,
            evidence=evidence,
        )
        return DeliveryResult(
            publication_id=publication_id,
            status={
                domain.DeliveryOutcome.published: "published",
                domain.DeliveryOutcome.retryable_failure: "retryable_failure",
                domain.DeliveryOutcome.permanent_failure: "permanent_failure",
                domain.DeliveryOutcome.unknown: "manual_action_required",
            }[evidence.outcome],
        )

    async def record_evidence(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        workspace_id: UUID,
        publication_id: UUID,
        expected_version: int,
        evidence: domain.PublicationEvidence,
    ) -> None:
        """Trusted provider/reconciliation input; stale results cannot advance state.

        Do not recheck current content approval here: a real external result must
        remain recordable even when authoring changes after an attempt starts.
        """
        operations = domain.PublicationOperation
        operation = {
            domain.DeliveryOutcome.published: operations.confirm_success,
            domain.DeliveryOutcome.retryable_failure: operations.fail_retryable,
            domain.DeliveryOutcome.permanent_failure: operations.fail_permanently,
            domain.DeliveryOutcome.unknown: operations.require_manual_action,
        }[evidence.outcome]
        async with sessions.begin() as session:
            await PublicationRepository(session, workspace_id).append(
                publication_id,
                expected_version=expected_version,
                operation_id=uuid4(),
                entry=domain.PublicationTransition(
                    operation=operation,
                    occurred_at=datetime.now(UTC),
                    evidence=evidence,
                ),
            )
