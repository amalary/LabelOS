"""Real independent PostgreSQL transactions; all external publishing is mocked."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from labelos_database.models import Organization, Publication, PublicationLease
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSessionTransaction

from labelos_api.publishing.providers import (
    ProviderOutcome,
    ProviderRegistry,
    ProviderResult,
)
from labelos_api.repositories.publication_leases import (
    PublicationLeaseLost,
    PublicationLeaseRepository,
)
from labelos_api.repositories.publishing import (
    PublicationConflict,
    PublicationRepository,
)
from labelos_api.services.delivery_orchestrator import DeliveryIneligible
from labelos_api.services.publishing_processor import PublishingProcessor
from test_delivery_orchestrator import accepted
from test_publishing_idempotency_postgres import Provider, command, setup, stored
from test_scheduling_repository import sessions as repository_sessions  # noqa: F401


@pytest.fixture
def sessions(repository_sessions):  # noqa: F811
    return repository_sessions


def worker(sessions, scope, provider, **kwargs):
    return PublishingProcessor(
        sessions,
        workspace_id=scope,
        registry=ProviderRegistry({"instagram": provider}),
        **kwargs,
    )


async def expire(sessions, identifier):
    async with sessions.begin() as session:
        await session.execute(
            update(PublicationLease)
            .where(PublicationLease.publication_id == identifier)
            .values(expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )


async def lease_for(sessions, identifier):
    async with sessions() as session:
        return await session.get(PublicationLease, identifier)


def test_simultaneous_processors_publish_once_and_terminal_exclusion(sessions):
    async def run():
        scope, identifier = await setup(sessions)
        provider = Provider()
        workers = [worker(sessions, scope, provider) for _ in range(4)]
        results = await asyncio.gather(*(w.run() for w in workers))
        assert sum(r.claimed for r in results) == 1
        assert len(provider.calls) == 1
        row = await stored(sessions, scope, identifier)
        assert row.status == "published" and len(row.attempts) == 1
        assert (await lease_for(sessions, identifier)).owner_id is None
        assert (await workers[0].run()).claimed == 0

    asyncio.run(run())


def test_exclusive_claim_skip_locked_and_tenant_scope(sessions):
    async def run():
        scope, identifier = await setup(sessions)
        provider = Provider()
        first, second = worker(sessions, scope, provider), worker(
            sessions, scope, provider
        )
        async with sessions.begin() as session:
            claim = await PublicationLeaseRepository(session, scope).claim_next(
                owner_id=first.owner_id, duration=first.lease_duration
            )
            assert claim.publication_id == identifier
            assert await asyncio.wait_for(second.claim_next(), 2) is None
        assert await second.claim_next() is None
        assert await worker(sessions, uuid4(), provider).claim_next() is None
        with pytest.raises(PublicationLeaseLost):
            await second.process_claim(claim)

    asyncio.run(run())


def test_expired_prestart_claim_recovers_and_fences_old_owner(sessions):
    async def run():
        scope, identifier = await setup(sessions)
        provider = Provider()
        first, second = worker(sessions, scope, provider), worker(
            sessions, scope, provider
        )
        old = await first.claim_next()
        await expire(sessions, identifier)
        new = await second.claim_next()
        assert new.fencing_token == old.fencing_token + 1
        with pytest.raises(PublicationLeaseLost):
            await first.process_claim(old)
        for method in ("renew", "release"):
            async with sessions.begin() as session:
                repo = PublicationLeaseRepository(session, scope)
                with pytest.raises(PublicationLeaseLost):
                    if method == "renew":
                        await repo.renew(old, first.lease_duration)
                    else:
                        await repo.release(old)
        assert (await second.process_claim(new)).status == "published"
        assert len(provider.calls) == 1

    asyncio.run(run())


@pytest.mark.parametrize("recover", [False, True])
def test_stale_completion_and_expired_inflight_never_republish(sessions, recover):
    async def run():
        scope, identifier = await setup(sessions)
        provider = Provider()
        provider.release.clear()
        first, second = worker(sessions, scope, provider), worker(
            sessions, scope, provider
        )
        claim = await first.claim_next()
        # Direct internal execution avoids heartbeat intentionally: simulate a
        # paused process whose external request remains in flight after expiry.
        task = asyncio.create_task(first._execute(claim))
        await asyncio.wait_for(provider.entered.wait(), 5)
        try:
            # Provider I/O holds no publication locks, even against another writer.
            async with sessions.begin() as session:
                await session.execute(
                    select(Publication)
                    .where(Publication.id == identifier)
                    .with_for_update(nowait=True)
                )
                with pytest.raises(PublicationLeaseLost, match="requires_outcome"):
                    await PublicationLeaseRepository(session, scope).release(claim)
            await expire(sessions, identifier)
            if recover:
                recovered = await second.run()
                assert recovered.recovered == 1
                assert (
                    await stored(sessions, scope, identifier)
                ).status == "manual_action_required"
            provider.release.set()
            with pytest.raises((PublicationLeaseLost, PublicationConflict)):
                await task
        finally:
            provider.release.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        assert len(provider.calls) == 1
        if not recover:
            assert (await second.run()).recovered == 1
        assert (await second.run()).claimed == 0
        row = await stored(sessions, scope, identifier)
        assert row.status == "manual_action_required" and len(row.attempts) == 1
        assert (await lease_for(sessions, identifier)).interrupted

        async def absent(request):
            return ProviderResult(
                outcome=ProviderOutcome.retryable_failure, confirmed_absent=True
            )

        provider.reconcile = absent
        with pytest.raises(PublicationLeaseLost, match="manual_resolution"):
            await first.delivery.reconcile(
                sessions, **command(scope, identifier, provider)
            )
        assert (await second.run()).claimed == 0

        async def published(request):
            return ProviderResult(
                outcome=ProviderOutcome.published, external_post_id="post-one"
            )

        provider.reconcile = published
        assert (
            await first.delivery.reconcile(
                sessions, **command(scope, identifier, provider)
            )
        ).status == "published"
        assert len(provider.calls) == 1

    asyncio.run(run())


def test_shutdown_after_durable_start_recovers_after_restart(sessions):
    async def run():
        scope, identifier = await setup(sessions)
        provider = Provider()
        provider.release.clear()
        first = worker(sessions, scope, provider)
        task = asyncio.create_task(first.run())
        await asyncio.wait_for(provider.entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await stored(sessions, scope, identifier)).status == "processing"
        second = worker(sessions, scope, provider)
        assert (await second.run()).claimed == 0
        await expire(sessions, identifier)
        assert (await second.run()).recovered == 1
        assert len(provider.calls) == 1

    asyncio.run(run())


def test_future_retry_excluded_even_with_fast_host_clock(sessions):
    async def run():
        scope, identifier = await setup(sessions)
        provider = Provider(ProviderOutcome.retryable_failure)
        processor = worker(sessions, scope, provider)
        assert (await processor.run()).claimed == 1
        row = await stored(sessions, scope, identifier)
        assert row.next_retry_at is not None
        processor.delivery.clock = lambda: row.next_retry_at + timedelta(days=1)
        assert (await processor.run()).claimed == 0
        assert len(provider.calls) == 1

    asyncio.run(run())


def test_cancellation_after_claim_wins_before_start(sessions):
    async def run():
        scope, identifier = await setup(sessions)
        provider = Provider()
        processor = worker(sessions, scope, provider)
        claim = await processor.claim_next()
        await processor.delivery.cancel_waiting(
            sessions, workspace_id=scope, publication_id=identifier, expected_version=0
        )
        with pytest.raises((DeliveryIneligible, PublicationLeaseLost)):
            await processor.process_claim(claim)
        assert (await processor.run()).claimed == 0
        assert not provider.calls
        assert (await stored(sessions, scope, identifier)).status == "cancelled"
        assert (
            await lease_for(sessions, identifier)
        ).fencing_token > claim.fencing_token

    asyncio.run(run())


def test_start_wins_cancellation_race(sessions):
    async def run():
        scope, identifier = await setup(sessions)
        provider = Provider()
        provider.release.clear()
        processor = worker(sessions, scope, provider)
        task = asyncio.create_task(processor.run())
        await asyncio.wait_for(provider.entered.wait(), 5)
        try:
            with pytest.raises(PublicationConflict):
                await processor.delivery.cancel_waiting(
                    sessions,
                    workspace_id=scope,
                    publication_id=identifier,
                    expected_version=0,
                )
        finally:
            provider.release.set()
        await task
        assert (await stored(sessions, scope, identifier)).status == "published"
        assert len(provider.calls) == 1

    asyncio.run(run())


def test_heartbeat_preserves_ownership_during_long_call(sessions, monkeypatch):
    async def run():
        scope, identifier = await setup(sessions)
        provider = Provider()
        provider.release.clear()
        processor = worker(
            sessions, scope, provider, lease_duration=timedelta(seconds=1)
        )
        renewed = asyncio.Event()
        original = PublicationLeaseRepository.renew

        async def renew(self, claim, duration):
            await original(self, claim, duration)
            renewed.set()

        monkeypatch.setattr(PublicationLeaseRepository, "renew", renew)
        claim = await processor.claim_next()
        before = (await lease_for(sessions, identifier)).expires_at
        task = asyncio.create_task(processor.process_claim(claim))
        try:
            await asyncio.wait_for(renewed.wait(), 5)
            assert await worker(sessions, scope, provider).claim_next() is None
            assert (await lease_for(sessions, identifier)).expires_at > before
        finally:
            provider.release.set()
        assert (await task).status == "published"

    asyncio.run(run())


def test_wrong_fence_and_unfenced_direct_execution_cannot_bypass_claim(sessions):
    async def run():
        scope, identifier = await setup(sessions)
        provider = Provider()
        processor = worker(sessions, scope, provider)
        claim = await processor.claim_next()
        with pytest.raises(PublicationLeaseLost):
            await processor.process_claim(
                replace(claim, fencing_token=claim.fencing_token + 1)
            )
        with pytest.raises(PublicationLeaseLost):
            await processor.delivery.execute(
                sessions, **command(scope, identifier, provider)
            )
        assert not provider.calls
        assert (await processor.process_claim(claim)).status == "published"

    asyncio.run(run())


def test_drain_stop_does_not_claim_new_work(sessions):
    async def run():
        scope, identifier = await setup(sessions)
        provider = Provider()
        processor = worker(sessions, scope, provider)
        stop = asyncio.Event()
        stop.set()
        assert (await processor.run(stop=stop)).claimed == 0
        assert not provider.calls
        assert (await stored(sessions, scope, identifier)).status == "pending"

    asyncio.run(run())


@pytest.mark.parametrize("boundary", ["start", "outcome"])
def test_worker_lost_commit_ack_preserves_recoverability(
    sessions, monkeypatch, boundary
):
    async def run():
        scope, identifier = await setup(sessions)
        provider = Provider()
        processor = worker(sessions, scope, provider)
        original_append = PublicationRepository.append
        original_exit = AsyncSessionTransaction.__aexit__

        async def append(self, *args, **kwargs):
            row = await original_append(self, *args, **kwargs)
            if bool(kwargs["entry"].attempt) == (boundary == "start"):
                self.session.info["lost_ack"] = True
            return row

        async def lose_ack(self, *args):
            await original_exit(self, *args)
            if not self.nested and self.session.info.pop("lost_ack", False):
                raise RuntimeError("injected lost acknowledgement")

        monkeypatch.setattr(PublicationRepository, "append", append)
        monkeypatch.setattr(AsyncSessionTransaction, "__aexit__", lose_ack)
        assert (await processor.run()).outcomes["failed"] == 1
        monkeypatch.setattr(PublicationRepository, "append", original_append)
        monkeypatch.setattr(AsyncSessionTransaction, "__aexit__", original_exit)
        row = await stored(sessions, scope, identifier)
        assert len(row.attempts) == 1
        if boundary == "start":
            assert row.status == "processing" and not provider.calls
            await expire(sessions, identifier)
            assert (await processor.run()).recovered == 1
        else:
            assert row.status == "published" and len(provider.calls) == 1
            assert (await processor.run()).claimed == 0

    asyncio.run(run())


def test_heartbeat_loss_stops_local_execution_and_allows_quarantine(sessions):
    async def run():
        scope, identifier = await setup(sessions)
        provider = Provider()
        provider.release.clear()
        processor = worker(
            sessions, scope, provider, lease_duration=timedelta(seconds=1)
        )
        task = asyncio.create_task(processor.run())
        await asyncio.wait_for(provider.entered.wait(), 5)
        await expire(sessions, identifier)
        assert (await asyncio.wait_for(task, 5)).outcomes["claim_lost"] == 1
        assert (await processor.run()).recovered == 1
        assert len(provider.calls) == 1

    asyncio.run(run())


def test_due_retry_consumed_once_by_simultaneous_processors(sessions, monkeypatch):
    from labelos_api.repositories import publishing

    async def run():
        scope, identifier = await setup(sessions)
        provider = Provider(ProviderOutcome.retryable_failure)
        original = publishing.retry_decision

        def immediately_due(*args, **kwargs):
            decision = original(*args, **kwargs)
            return replace(decision, next_retry_at=kwargs["observed_at"])

        # Remove only the policy wait; keep real PostgreSQL wall-time selection.
        monkeypatch.setattr(publishing, "retry_decision", immediately_due)
        processor = worker(sessions, scope, provider)
        assert (await processor.run()).claimed == 1
        provider.outcome = ProviderOutcome.published
        results = await asyncio.gather(
            processor.run(), worker(sessions, scope, provider).run()
        )
        assert sum(r.claimed for r in results) == 1
        assert len(provider.calls) == 2
        assert provider.calls[0].idempotency_key == provider.calls[1].idempotency_key
        row = await stored(sessions, scope, identifier)
        assert row.status == "published" and len(row.attempts) == 2

    asyncio.run(run())


def test_unsupported_pending_work_does_not_starve_later_claims(sessions):
    async def run():
        scope, first = await setup(sessions)
        async with sessions() as session:
            workspace = await session.get(Organization, scope)
        _, _, second = await accepted(sessions, workspace=workspace)
        processor = PublishingProcessor(
            sessions, workspace_id=scope, registry=ProviderRegistry(), batch_size=1
        )
        for _ in range(2):
            result = await processor.run()
            assert result.outcomes["unsupported_provider"] == 1
        for identifier in (first, second):
            lease = await lease_for(sessions, identifier)
            assert lease.fencing_token == 1 and lease.owner_id is None
            assert not (await stored(sessions, scope, identifier)).attempts

    asyncio.run(run())
