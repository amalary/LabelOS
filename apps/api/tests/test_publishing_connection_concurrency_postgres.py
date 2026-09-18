"""Independent PostgreSQL transactions interleaved with mocked provider I/O."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from labelos_database.models import SocialAccountConnection
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from labelos_api.publishing.providers import ProviderRegistry
from labelos_api.repositories.publication_leases import PublicationLeaseLost
from labelos_api.repositories.publishing import (
    PublicationConflict,
    PublicationRepository,
)
from labelos_api.services import social_account_service as accounts
from labelos_api.services.publishing_processor import PublishingProcessor
from labelos_api.social_accounts.providers import SocialAccountProviderErrorCode as Code
from test_publishing_worker_postgres import expire
from test_scheduling_repository import sessions as repository_sessions  # noqa: F401
from test_youtube_publishing import execute, setup


@pytest.fixture
def sessions(repository_sessions):  # noqa: F811
    return repository_sessions


async def change_connection(sessions, request, **values):
    async with sessions.begin() as session:
        await session.execute(
            update(SocialAccountConnection)
            .where(SocialAccountConnection.id == request.destination_id)
            .values(**values)
        )


async def publication(sessions, request):
    async with sessions() as session:
        return await PublicationRepository(session, request.workspace_id).get(
            request.publication_id
        )


@pytest.mark.parametrize("during", ["credentials", "identity", "refresh"])
@pytest.mark.parametrize(
    "observation", ["healthy", "updated_at", "metadata", "rate_limited"]
)
def test_telemetry_during_publishing_does_not_require_reconnection(
    sessions, monkeypatch, during, observation
):
    async def run():
        adapter, request, network, store, _ = await setup(
            sessions, monkeypatch, expired=during == "refresh"
        )
        snapshot = await adapter._connection(request)

        async def observe():
            if observation in {"healthy", "rate_limited"}:
                async with sessions() as session:
                    assert await accounts.record_execution_health(
                        session,
                        expected=snapshot,
                        error_code=(
                            Code.rate_limited if observation == "rate_limited" else None
                        ),
                    )
            else:
                values = {"updated_at": datetime.now(UTC) + timedelta(seconds=1)}
                if observation == "metadata":
                    values.update(
                        last_health_checked_at=datetime.now(UTC),
                        last_synced_at=datetime.now(UTC),
                        last_error_message="Temporary observation",
                        provider_metadata={"observed": True},
                        display_name="Updated display name",
                    )
                await change_connection(sessions, request, **values)

        if during == "credentials":
            original_get = store.get

            async def get(reference):
                values = await original_get(reference)
                await observe()
                return values

            monkeypatch.setattr(store, "get", get)
        else:
            setattr(network, "on_" + during, observe)
        result = await execute(sessions, adapter, request)
        assert result.status == "published"
        row = await publication(sessions, request)
        assert row.retry_disposition is None
        assert len(network.uploads) == 1

    asyncio.run(run())


@pytest.mark.parametrize("during", ["identity", "refresh"])
@pytest.mark.parametrize(
    "change",
    [
        {"credential_ref": "memory://replacement"},
        {"last_error_code": "credential_revoked"},
        {"last_error_code": "authorization_failed"},
        {"status": "disconnected"},
        {"status": "reconnect_required"},
        {"capabilities": []},
        {"external_account_id": "replacement"},
        {"connection_method": "assisted"},
        {"token_expires_at": datetime(2030, 1, 1, tzinfo=UTC)},
    ],
)
def test_authorization_change_during_publishing_remains_fail_closed(
    sessions, monkeypatch, during, change
):
    async def run():
        adapter, request, network, _, _ = await setup(
            sessions, monkeypatch, expired=during == "refresh"
        )

        async def mutate():
            await change_connection(sessions, request, **change)

        setattr(network, "on_" + during, mutate)
        result = await execute(sessions, adapter, request)
        assert result.status == "retryable_failure"
        assert (await publication(sessions, request)).retry_disposition == (
            "blocked_reconnection"
        )
        assert not network.uploads
        async with sessions() as session:
            row = await session.get(SocialAccountConnection, request.destination_id)
            for key, value in change.items():
                assert getattr(row, key) == value

    asyncio.run(run())


def test_concurrent_refresh_cannot_overwrite_newer_refresh(sessions, monkeypatch):
    async def run():
        adapter, request, network, _, _ = await setup(
            sessions, monkeypatch, expired=True
        )
        snapshot = await adapter._connection(request)
        entered, release = asyncio.Event(), asyncio.Event()
        refresh_calls = 0

        async def pause_first_refresh():
            nonlocal refresh_calls
            refresh_calls += 1
            if refresh_calls == 1:
                entered.set()
                await asyncio.wait_for(release.wait(), 10)

        network.on_refresh = pause_first_refresh
        pending = asyncio.create_task(execute(sessions, adapter, request))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            winner, _ = await adapter._accounts.credentials(snapshot)
            assert winner.token_expires_at > snapshot.token_expires_at
            release.set()
            assert (await pending).status == "retryable_failure"
        finally:
            release.set()
            await asyncio.gather(pending, return_exceptions=True)
        assert (await publication(sessions, request)).retry_disposition == (
            "blocked_reconnection"
        )
        assert await adapter._connection(request) == winner
        assert not network.uploads

    asyncio.run(run())


def test_provider_change_during_publishing_is_rejected_by_database(
    sessions, monkeypatch
):
    async def run():
        adapter, request, network, _, _ = await setup(sessions, monkeypatch)
        snapshot = await adapter._connection(request)
        assert not snapshot.same_authorization(replace(snapshot, provider="instagram"))

        async def mutate():
            # The publication's composite FK pins provider/workspace/connection.
            with pytest.raises(IntegrityError, match="fk_publications_provider_scope"):
                await change_connection(sessions, request, provider="instagram")

        network.on_identity = mutate
        assert (await execute(sessions, adapter, request)).status == "published"
        assert len(network.uploads) == 1
        async with sessions() as session:
            row = await session.get(SocialAccountConnection, request.destination_id)
            assert row.provider == snapshot.provider

    asyncio.run(run())


def test_old_health_observation_cannot_clear_newer_telemetry(sessions, monkeypatch):
    async def run():
        adapter, request, _, _, _ = await setup(sessions, monkeypatch)
        snapshot = await adapter._connection(request)
        async with sessions() as session:
            assert await accounts.record_execution_health(
                session, expected=snapshot, error_code=Code.rate_limited
            )
        async with sessions() as session:
            assert not await accounts.record_execution_health(
                session, expected=snapshot, error_code=None
            )
        async with sessions() as session:
            row = await session.get(SocialAccountConnection, request.destination_id)
            assert row.last_error_code == "rate_limited"

    asyncio.run(run())


def test_cross_workspace_snapshot_cannot_refresh_or_observe(sessions, monkeypatch):
    async def run():
        adapter, request, network, store, oauth = await setup(sessions, monkeypatch)
        snapshot = await adapter._connection(request)
        result = await oauth.refresh_credentials(credential_ref=snapshot.credential_ref)
        foreign = replace(snapshot, workspace_id=uuid4())
        async with sessions() as session:
            assert (
                await accounts.apply_execution_refresh(
                    session, expected=foreign, adapter=oauth, result=result
                )
                is None
            )
            assert not await accounts.record_execution_health(
                session, expected=foreign, error_code=Code.credential_revoked
            )

        async def forbidden(_):
            pytest.fail("Cross-workspace execution accessed credentials")

        monkeypatch.setattr(store, "get", forbidden)
        outcome = await adapter.publish(
            replace(request, workspace_id=foreign.workspace_id)
        )
        assert outcome.outcome == "authorization_required"
        assert not network.uploads
        assert await adapter._connection(request) == snapshot

    asyncio.run(run())


def test_stale_publishing_worker_remains_fenced_after_telemetry(sessions, monkeypatch):
    async def run():
        adapter, request, network, _, _ = await setup(sessions, monkeypatch)
        worker = PublishingProcessor(
            sessions,
            workspace_id=request.workspace_id,
            registry=ProviderRegistry({"youtube": adapter}),
        )
        entered, release = asyncio.Event(), asyncio.Event()

        async def pause_identity():
            entered.set()
            await asyncio.wait_for(release.wait(), 10)

        network.on_identity = pause_identity
        claim = await worker.claim_next()
        pending = asyncio.create_task(worker._execute(claim))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            await change_connection(sessions, request, last_synced_at=datetime.now(UTC))
            await expire(sessions, request.publication_id)
            release.set()
            with pytest.raises((PublicationLeaseLost, PublicationConflict)):
                await pending
        finally:
            release.set()
            await asyncio.gather(pending, return_exceptions=True)
        assert len(network.uploads) == 1
        assert (await worker.run()).recovered == 1
        assert (await worker.run()).claimed == 0
        assert (await publication(sessions, request)).status == "manual_action_required"
        assert len(network.uploads) == 1

    asyncio.run(run())
