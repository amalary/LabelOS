"""Approval disposition with real PostgreSQL locks, leases and journal guards."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from labelos_database.models import (
    ApprovalDecision,
    ApprovalRequest,
    MarketingContentItem,
    MarketingContentItemChannel,
    Publication,
    PublicationLease,
    RealtimeEvent,
    SchedulingJob,
)
from sqlalchemy import func, select, update

from labelos_api.publishing import contracts as domain
from labelos_api.publishing.providers import ProviderOutcome
from labelos_api.repositories.publication_calendar import list_facts
from labelos_api.repositories.publication_leases import PublicationLeaseLost
from labelos_api.repositories.publishing import (
    PublicationConflict,
    PublicationRepository,
    aggregate,
)
from labelos_api.repositories.scheduling import JobActivation, snapshot_for
from labelos_api.scheduling.contracts import DurableAccepted
from labelos_api.scheduling.payload import prepare_request
from labelos_api.services.delivery_orchestrator import DeliveryIneligible
from labelos_api.services.publication_recovery import PublicationRecoveryService
from test_delivery_orchestrator import accept, accepted
from test_publishing_idempotency_postgres import Provider, stored
from test_publishing_worker_postgres import expire, lease_for, worker
from test_scheduling_repository import claim as scheduling_claim
from test_scheduling_repository import repo
from test_scheduling_repository import sessions as sessions  # noqa: F401


async def invalidate(sessions, request, change="decision"):
    async with sessions.begin() as session:
        item = await session.get(MarketingContentItem, request.snapshot.content_item_id)
        approval = await session.get(
            ApprovalRequest, request.snapshot.approval_request_id
        )
        if change in ("decision", "decision_and_destination"):
            session.add(
                ApprovalDecision(
                    approval_request_id=approval.id,
                    organization_id=request.snapshot.workspace_id,
                    decision="invalidated",
                    actor_kind="system",
                )
            )
            if change == "decision_and_destination":
                channel = await session.get(
                    MarketingContentItemChannel, request.snapshot.channel_id
                )
                channel.social_account_connection_id = None
        elif change == "status":
            approval.status = "rejected"
        elif change == "approved_revision":
            item.approved_revision = None
        elif change == "revision":
            item.content_revision += 1
        elif change == "parent":
            item.status = "archived"
        elif change == "generation":
            channel = await session.get(
                MarketingContentItemChannel, request.snapshot.channel_id
            )
            channel.schedule_generation += 1
        elif change == "missing_schedule":
            channel = await session.get(
                MarketingContentItemChannel, request.snapshot.channel_id
            )
            channel.scheduled_at = None


@pytest.mark.parametrize("after_claim", [False, True])
@pytest.mark.parametrize(
    "change,reason",
    [
        ("decision", "stale_approval"),
        ("decision_and_destination", "stale_approval"),
        ("status", "stale_approval"),
        ("approved_revision", "stale_approval"),
        ("revision", "stale_content_revision"),
        ("parent", "ineligible_parent_state"),
        ("generation", "changed_schedule_generation"),
        ("missing_schedule", "missing_schedule_intent"),
    ],
)
def test_durable_invalidation_before_execution(sessions, after_claim, change, reason):
    async def run():
        request, fence, identifier = await accepted(sessions)
        scope = request.snapshot.workspace_id
        provider = Provider()
        processor = worker(sessions, scope, provider)
        claim = await processor.claim_next() if after_claim else None
        await invalidate(sessions, request, change)
        if claim:
            result = await processor.process_claim(claim)
            assert (result.status, result.reason_code) == ("cancelled", reason)
        else:
            assert (await processor.run()).outcomes[reason] == 1
        row = await stored(sessions, scope, identifier)
        assert row.status == "cancelled" and row.cancellation_reason == reason
        assert not row.attempts and not provider.calls
        assert [t.operation for t in row.transitions] == ["cancel"]
        assert aggregate(row).history[-1].cancellation_reason == reason
        lease = await lease_for(sessions, identifier)
        assert lease.owner_id is None and lease.fencing_token == 2
        for _ in range(3):
            assert (await processor.run()).claimed == 0
        async with sessions.begin() as session:
            # Duplicate accepted handoff remains a historical receipt, even when
            # its original authority and intent are no longer current.
            replay = await accept(session, request, fence)
            assert isinstance(replay, DurableAccepted)
            assert replay.receipt_id == row.receipt_id
            assert (
                await session.scalar(select(func.count()).select_from(Publication)) == 1
            )
            events = (
                await session.scalars(
                    select(RealtimeEvent).where(
                        RealtimeEvent.event_type == "marketing.publication.changed"
                    )
                )
            ).all()
            assert len(events) == 2
            cancellation = next(e for e in events if e.payload["status"] == "cancelled")
            assert cancellation.payload["cancellationReason"] == reason
            assert (
                await list_facts(session, scope, [request.snapshot.content_item_id])
                == []
            )
            projection = await PublicationRecoveryService(
                session, scope, actor=None
            ).handoff(row)
            assert (
                projection["delivery_status"] == projection["resolution"] == "cancelled"
            )
            assert projection["cancellation_reason"] == reason
            assert projection["cancelled_at"] == row.cancelled_at
        assert (await processor.run()).claimed == 0

    asyncio.run(run())


def test_competing_workers_and_stale_owner_cannot_override_invalidation(sessions):
    async def run():
        request, _, identifier = await accepted(sessions)
        scope = request.snapshot.workspace_id
        provider = Provider()
        stale = worker(sessions, scope, provider)
        old_claim = await stale.claim_next()
        await invalidate(sessions, request)
        await expire(sessions, identifier)
        with pytest.raises(PublicationLeaseLost):
            await stale.process_claim(old_claim)
        assert (await stored(sessions, scope, identifier)).status == "pending"
        contenders = [worker(sessions, scope, provider) for _ in range(4)]
        results = await asyncio.gather(*(w.run() for w in contenders))
        assert sum(r.claimed for r in results) == 1
        assert sum(r.outcomes["stale_approval"] for r in results) == 1
        with pytest.raises((DeliveryIneligible, PublicationLeaseLost)):
            await stale.process_claim(old_claim)
        row = await stored(sessions, scope, identifier)
        assert row.status == "cancelled" and row.transition_version == 1
        with pytest.raises(PublicationConflict, match="publication_version_conflict"):
            async with sessions.begin() as session:
                await PublicationRepository(session, scope).append(
                    identifier,
                    expected_version=0,
                    operation_id=uuid4(),
                    claim=old_claim,
                    execution_id=uuid4(),
                    entry=domain.PublicationTransition(
                        operation=domain.PublicationOperation.start,
                        occurred_at=row.updated_at,
                        attempt=domain.PublicationAttempt(
                            id=uuid4(),
                            workspace_id=scope,
                            publication_id=identifier,
                            number=1,
                            started_at=row.updated_at,
                        ),
                    ),
                )
        assert not provider.calls
        assert (await stale.run()).claimed == 0

    asyncio.run(run())


@pytest.mark.parametrize("path", ["worker", "retry_due"])
def test_invalidated_retry_preserves_attempts_and_never_resurrects(
    sessions, monkeypatch, path
):
    from labelos_api.repositories import publishing

    async def run():
        request, _, identifier = await accepted(sessions)
        scope = request.snapshot.workspace_id
        provider = Provider(ProviderOutcome.retryable_failure)
        original = publishing.retry_decision
        monkeypatch.setattr(
            publishing,
            "retry_decision",
            lambda *args, **kwargs: replace(
                original(*args, **kwargs), next_retry_at=kwargs["observed_at"]
            ),
        )
        processor = worker(sessions, scope, provider)
        await processor.run()
        before = await stored(sessions, scope, identifier)
        await invalidate(sessions, request)
        if path == "worker":
            assert (await processor.run()).outcomes["stale_approval"] == 1
        else:
            results = await processor.delivery.retry_due(
                sessions, workspace_id=scope, registry=processor.registry
            )
            assert len(results) == 1 and results[0].status == "cancelled"
        after = await stored(sessions, scope, identifier)
        assert after.status == "cancelled" and after.next_retry_at is None
        assert after.retry_disposition is None
        assert [a.id for a in after.attempts] == [a.id for a in before.attempts]
        assert [t.id for t in after.transitions[:-1]] == [
            t.id for t in before.transitions
        ]
        assert len(provider.calls) == 1
        assert (await processor.run()).claimed == 0
        assert (
            await processor.delivery.retry_due(
                sessions, workspace_id=scope, registry=processor.registry
            )
            == []
        )

    asyncio.run(run())


def test_invalidation_rolls_back_state_history_outbox_and_lease_together(
    sessions, monkeypatch
):
    async def run():
        request, _, identifier = await accepted(sessions)
        scope = request.snapshot.workspace_id
        provider = Provider()
        processor = worker(sessions, scope, provider)
        claim = await processor.claim_next()
        await invalidate(sessions, request)
        original = PublicationRepository._outbox

        def fail(self, row, operation_id):
            original(self, row, operation_id)
            raise RuntimeError("injected cancellation rollback")

        monkeypatch.setattr(PublicationRepository, "_outbox", fail)
        with pytest.raises(RuntimeError, match="injected cancellation rollback"):
            await processor.process_claim(claim)
        row = await stored(sessions, scope, identifier)
        assert row.status == "pending" and not row.transitions
        lease = await lease_for(sessions, identifier)
        assert (
            lease.fencing_token == claim.fencing_token
            and lease.owner_id == claim.owner_id
        )
        monkeypatch.setattr(PublicationRepository, "_outbox", original)
        assert (await processor.process_claim(claim)).status == "cancelled"
        assert not provider.calls

    asyncio.run(run())


def test_workspace_isolation_and_existing_cancellation(sessions):
    async def run():
        request, _, identifier = await accepted(sessions)
        other, _, other_id = await accepted(sessions)
        scope = request.snapshot.workspace_id
        provider = Provider()
        processor = worker(sessions, scope, provider)
        await invalidate(sessions, request)
        with pytest.raises(DeliveryIneligible, match="publication_missing"):
            await processor.delivery.execute(
                sessions,
                workspace_id=other.snapshot.workspace_id,
                publication_id=identifier,
            )
        assert (await stored(sessions, scope, identifier)).status == "pending"
        await processor.run()
        assert (
            await stored(sessions, other.snapshot.workspace_id, other_id)
        ).status == "pending"
        await processor.delivery.cancel_waiting(
            sessions,
            workspace_id=other.snapshot.workspace_id,
            publication_id=other_id,
            expected_version=0,
        )
        other_row = await stored(sessions, other.snapshot.workspace_id, other_id)
        assert (
            other_row.status == "cancelled"
            and other_row.cancellation_reason == "scheduling_cancelled"
        )
        assert not provider.calls

    asyncio.run(run())


def test_final_lease_expiry_rolls_back_invalidation(sessions, monkeypatch):
    from labelos_api.repositories import publishing

    async def run():
        request, _, identifier = await accepted(sessions)
        scope = request.snapshot.workspace_id
        provider = Provider()
        processor = worker(sessions, scope, provider)
        claim = await processor.claim_next()
        await invalidate(sessions, request)
        original = publishing.require_ownership
        checks = 0

        async def expire_at_final_check(session, row, current_claim):
            nonlocal checks
            checks += 1
            if checks == 2:
                await session.execute(
                    update(PublicationLease)
                    .where(PublicationLease.publication_id == identifier)
                    .values(expires_at=func.clock_timestamp() - timedelta(seconds=1))
                )
            return await original(session, row, current_claim)

        monkeypatch.setattr(publishing, "require_ownership", expire_at_final_check)
        with pytest.raises(PublicationLeaseLost):
            await processor.process_claim(claim)
        assert checks == 2
        row = await stored(sessions, scope, identifier)
        assert row.status == "pending" and not row.transitions
        lease = await lease_for(sessions, identifier)
        assert lease.owner_id == claim.owner_id
        assert lease.fencing_token == claim.fencing_token
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(RealtimeEvent)
                    .where(RealtimeEvent.event_type == "marketing.publication.changed")
                )
                == 1
            )
        monkeypatch.setattr(publishing, "require_ownership", original)
        assert (await processor.process_claim(claim)).status == "cancelled"
        assert not provider.calls

    asyncio.run(run())


def test_newly_approved_revision_uses_new_intent(sessions):
    async def run():
        request, _, identifier = await accepted(sessions)
        scope = request.snapshot.workspace_id
        provider = Provider()
        processor = worker(sessions, scope, provider)
        await invalidate(sessions, request)
        await processor.run()
        async with sessions.begin() as session:
            item = await session.get(
                MarketingContentItem, request.snapshot.content_item_id
            )
            channel = await session.get(
                MarketingContentItemChannel, request.snapshot.channel_id
            )
            item.content_revision += 1
            item.approved_revision = item.content_revision
            approval = ApprovalRequest(
                organization_id=scope,
                resource_type="marketing_content_item",
                resource_id=item.id,
                resource_revision=item.content_revision,
                title="New revision approved",
                status="approved",
            )
            session.add(approval)
            await session.flush()
            item.approval_request_id = approval.id
            channel.schedule_generation += 1
            await session.flush()
            activation = JobActivation(
                snapshot=replace(
                    request.snapshot,
                    content_revision=item.content_revision,
                    approval_request_id=approval.id,
                    schedule_generation=channel.schedule_generation,
                ),
                operation_id=uuid4(),
                created_by_user_id=(
                    await session.get(SchedulingJob, request.job_id)
                ).created_by_user_id,
                schedule_timezone="UTC",
                destination_id=request.destination_id,
                effective_artist_id=None,
            )
            await repo(session, scope).create_pending_job(activation)
            job = (await scheduling_claim(session, scope))[0]
            new_request = prepare_request(
                snapshot=snapshot_for(job),
                job_id=job.id,
                destination_id=request.destination_id,
                artist_profile_id=None,
                authoring_timezone="UTC",
                correlation_id=uuid4(),
                item=item,
                channel=channel,
                asset_bytes={},
            )
            assert isinstance(
                await accept(session, new_request, job.fencing_token), DurableAccepted
            )
            new_row = await PublicationRepository(session, scope).get_by_job(job.id)
            new_id = new_row.id
        assert new_id != identifier
        assert (await processor.run()).outcomes["published"] == 1
        assert (await stored(sessions, scope, identifier)).status == "cancelled"
        assert (await stored(sessions, scope, new_id)).status == "published"
        assert len(provider.calls) == 1

    asyncio.run(run())
