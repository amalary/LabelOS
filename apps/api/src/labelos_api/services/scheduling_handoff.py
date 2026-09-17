"""Internal composition boundary, not a public API or worker authentication path.

The future workload boundary must authenticate/scope the worker and lock execution
controls before calling this function. No production successful receiver is wired.
The caller owns the outer transaction; successful return is durable at its commit.
"""

import logging
from uuid import UUID

from labelos_database.scheduling import SchedulingJobStatus

from labelos_api.repositories.scheduling import (
    SchedulingConflict,
    SchedulingRepository,
    snapshot_for,
)
from labelos_api.scheduling.contracts import (
    DeliveryAcceptanceRequest,
    DeliveryAcceptanceResult,
    DurableAccepted,
    DurableDeliveryReceiverUnavailable,
    PublishingDeliveryAcceptancePort,
    RetryableUnavailable,
    SchedulingFeatureControls,
    TerminalRejected,
)
from labelos_api.scheduling.payload import (
    InvalidHandoffPayload,
    prepare_request,
    validate_request,
)
from labelos_api.services.scheduling_destination import lock_destination
from labelos_api.services.scheduling_eligibility import (
    SchedulingExecutionMode,
    evaluate_channel_eligibility,
)

logger = logging.getLogger(__name__)


async def accept_scheduling_handoff(
    repository: SchedulingRepository,
    *,
    receiver: PublishingDeliveryAcceptancePort,
    request: DeliveryAcceptanceRequest,
    expected_worker: str,
    expected_fencing_token: int,
    controls: SchedulingFeatureControls,
) -> DeliveryAcceptanceResult:
    """Accept and transition atomically; nonacceptance never marks handed_off.

    Savepoint rollback also removes a misbehaving receiver's partial writes.
    Unexpected failures propagate without logging their potentially unsafe text;
    an unknown outer commit must be reconciled by original job/key, not requeued.
    """
    try:
        async with repository.session.begin_nested():
            result = await _accept(
                repository,
                receiver,
                request,
                expected_worker,
                expected_fencing_token,
                controls,
            )
            if not isinstance(
                result, (DurableAccepted, RetryableUnavailable, TerminalRejected)
            ):
                raise SchedulingConflict("handoff_contract_violation")
            if not isinstance(result, DurableAccepted):
                raise _NonAcceptance(result)
    except _NonAcceptance as exc:
        result = exc.result
    except DurableDeliveryReceiverUnavailable:
        result = RetryableUnavailable()
    except (InvalidHandoffPayload, SchedulingConflict):
        result = TerminalRejected()
    # Fixed outcome and typed correlation only. Never log payload, receiver
    # repr, free-form worker identity, ORM destination or exception details.
    logger.info(
        "scheduling_handoff_result",
        extra={
            "handoff_outcome": type(result).__name__,
            "correlation_id": (
                str(request.correlation_id)
                if isinstance(request.correlation_id, UUID)
                else None
            ),
        },
    )
    return result


class _NonAcceptance(Exception):
    def __init__(self, result: DeliveryAcceptanceResult):
        self.result = result


async def _accept(repository, receiver, request, worker, fence, controls):
    assets = validate_request(request)
    if request.snapshot.workspace_id != repository.workspace_id:
        return TerminalRejected()
    # Source first, then jobs, destination, inbox: never lock an inbox before
    # Scheduling's coordination rows. Reload source even for receipt readback.
    source = await repository.lock_activation_source(
        request.snapshot.content_item_id, request.snapshot.channel_id
    )
    job = await repository.get_job(request.job_id)
    if (
        job is None
        or snapshot_for(job) != request.snapshot
        or job.social_account_connection_id != request.destination_id
        or job.effective_artist_id != request.artist_profile_id
        or job.schedule_timezone != request.authoring_timezone
    ):
        return TerminalRejected()
    if job.status == SchedulingJobStatus.handed_off:
        # Historical retry must return its original receipt even after edits or
        # a control change. The receiver must deduplicate, never overwrite.
        result = await receiver.accept(repository.session, request)
        if not isinstance(result, DurableAccepted):
            return result
        if (
            not result.receipt.matches(request)
            or result.receipt_id != job.handoff_receipt_id
        ):
            raise SchedulingConflict("handoff_contract_violation")
        return result
    if not controls.can_execute:
        return RetryableUnavailable()
    reason = await repository.detect_stale_job(job.id)
    if reason or job.status != SchedulingJobStatus.claimed:
        return TerminalRejected()
    channel = source.channel
    if channel is None or source.campaign is None:
        return TerminalRejected()
    connection = await lock_destination(
        repository.session, repository.workspace_id, job.social_account_connection_id
    )
    eligibility = evaluate_channel_eligibility(
        workspace_id=repository.workspace_id,
        item=source.item,
        channel=channel,
        evidence=source.approval,
        connection=connection,
        effective_artist_id=source.item.artist_id or source.campaign.primary_artist_id,
        expected_content_revision=request.snapshot.content_revision,
        execution_mode=SchedulingExecutionMode.automatic,
        controls=controls,
    )
    if not eligibility.eligible:
        return TerminalRejected()
    current = prepare_request(
        snapshot=request.snapshot,
        job_id=job.id,
        destination_id=request.destination_id,
        artist_profile_id=job.effective_artist_id,
        authoring_timezone=job.schedule_timezone,
        correlation_id=request.correlation_id,
        item=source.item,
        channel=channel,
        asset_bytes=assets,
    )
    if current != request:
        return TerminalRejected()
    # Check lease, snapshot and due window BEFORE calling the receiver; the
    # conditional transition rechecks time/fence again after local persistence.
    await repository.validate_handoff_claim(
        job.id, expected_worker=worker, expected_fencing_token=fence
    )
    result = await receiver.accept(repository.session, request)
    if isinstance(result, DurableAccepted):
        await repository.record_handoff_acceptance(
            job.id,
            expected_worker=worker,
            expected_fencing_token=fence,
            request=request,
            receipt=result.receipt,
        )
    elif not isinstance(result, (RetryableUnavailable, TerminalRejected)):
        raise SchedulingConflict("handoff_contract_violation")
    return result
