"""Unsubstituted source readiness, worker claims and competing human commands."""

import asyncio
from uuid import uuid4

import pytest
from labelos_database.capabilities import Capability
from labelos_database.models import (
    MarketingContentItem,
    Organization,
    SocialAccountConnection,
)
from sqlalchemy import update

from labelos_api.publishing.providers import ProviderRegistry
from labelos_api.repositories.publishing import PublicationConflict
from labelos_api.services.delivery_orchestrator import (
    DeliveryIneligible,
    DeliveryOrchestrator,
)
from labelos_api.services.publication_recovery import PublicationRecoveryService
from labelos_api.services.publishing_processor import PublishingProcessor
from test_approval_service import _seed_actor
from test_delivery_orchestrator import accepted
from test_publishing_idempotency_postgres import Provider, stored
from test_scheduling_repository import sessions as sessions  # noqa: F401


async def setup(sessions):
    request, _, identifier = await accepted(sessions)
    scope = request.snapshot.workspace_id
    async with sessions.begin() as session:
        workspace = await session.get(Organization, scope)
        actor, _ = await _seed_actor(
            session,
            workspace=workspace,
            email=f"{uuid4()}@test.com",
            capabilities=(
                Capability.marketing_content_schedule.value,
                Capability.marketing_content_view.value,
            ),
        )
        await session.execute(
            update(SocialAccountConnection)
            .where(SocialAccountConnection.id == request.destination_id)
            .values(status="reconnect_required")
        )
    provider = Provider()
    worker = PublishingProcessor(
        sessions, workspace_id=scope, registry=ProviderRegistry({"instagram": provider})
    )
    await worker.run()
    row = await stored(sessions, scope, identifier)
    assert row.retry_disposition == "blocked_reconnection" and len(row.attempts) == 1
    assert not provider.calls
    return request, identifier, actor, worker, provider


def test_reconnect_is_durable_and_recovery_revalidates_before_worker_claim(sessions):
    async def run():
        request, identifier, actor, worker, provider = await setup(sessions)
        scope = request.snapshot.workspace_id
        async with sessions.begin() as session:
            service = PublicationRecoveryService(session, scope, actor=actor)
            with pytest.raises(DeliveryIneligible, match="reconnect_required"):
                await service.command(
                    identifier,
                    operation="authorize_retry",
                    operation_id=uuid4(),
                    expected_version=2,
                    expected_action_version=0,
                )
        assert (await worker.run()).claimed == 0
        async with sessions.begin() as session:
            await session.execute(
                update(SocialAccountConnection)
                .where(SocialAccountConnection.id == request.destination_id)
                .values(status="connected")
            )
        assert (
            await worker.run()
        ).claimed == 0  # Health alone does not authorize retry.
        async with sessions.begin() as session:
            service = PublicationRecoveryService(session, scope, actor=actor)
            await service.command(
                identifier,
                operation="authorize_retry",
                operation_id=uuid4(),
                expected_version=2,
                expected_action_version=0,
            )
        assert (await worker.run()).claimed == 1
        row = await stored(sessions, scope, identifier)
        assert row.status == "published" and len(row.attempts) == 2
        assert len(provider.calls) == 1 and len(row.actions) == 1

    asyncio.run(run())


@pytest.mark.parametrize("change", ["identity", "content", "scope"])
def test_recovery_rejects_changed_identity_content_and_missing_grants(sessions, change):
    async def run():
        request, identifier, actor, _, _ = await setup(sessions)
        scope = request.snapshot.workspace_id
        async with sessions.begin() as session:
            values = {"status": "connected"}
            if change == "identity":
                values["external_account_id"] = "different-account"
            if change == "scope":
                values["capabilities"] = []
            await session.execute(
                update(SocialAccountConnection)
                .where(SocialAccountConnection.id == request.destination_id)
                .values(**values)
            )
            if change == "content":
                await session.execute(
                    update(MarketingContentItem)
                    .where(MarketingContentItem.id == request.snapshot.content_item_id)
                    .values(content_revision=2)
                )
        async with sessions.begin() as session:
            service = PublicationRecoveryService(session, scope, actor=actor)
            with pytest.raises(DeliveryIneligible):
                await service.command(
                    identifier,
                    operation="authorize_retry",
                    operation_id=uuid4(),
                    expected_version=2,
                    expected_action_version=0,
                )
        assert not (await stored(sessions, scope, identifier)).actions

    asyncio.run(run())


def test_manual_reservation_serializes_completions_and_excludes_workers(sessions):
    async def run():
        request, identifier, actor, worker, _ = await setup(sessions)
        scope = request.snapshot.workspace_id
        async with sessions.begin() as session:
            service = PublicationRecoveryService(session, scope, actor=actor)
            row = await service.command(
                identifier,
                operation="begin_manual",
                operation_id=uuid4(),
                expected_version=2,
                expected_action_version=0,
            )
            handoff = await service.handoff(row)
            assert handoff["caption"] == "APPROVED_PRIVATE_COPY"
            assert (
                handoff["destination_account"]["external_account_id"] == "account-one"
            )
            assert "SECRET_TOKEN" not in str(handoff)
        assert (await worker.run()).claimed == 0

        async def complete():
            try:
                async with sessions.begin() as session:
                    await PublicationRecoveryService(
                        session, scope, actor=actor
                    ).command(
                        identifier,
                        operation="complete_manual",
                        operation_id=uuid4(),
                        expected_version=2,
                        expected_action_version=1,
                    )
                return True
            except PublicationConflict:
                return False

        assert sorted(await asyncio.gather(complete(), complete())) == [False, True]
        row = await stored(sessions, scope, identifier)
        assert len(row.actions) == 2 and len(row.attempts) == 1
        assert row.status == "retryable_failure"
        assert (await worker.run()).claimed == 0
        with pytest.raises(DeliveryIneligible, match="manual_delivery_reserved"):
            await DeliveryOrchestrator().execute(
                sessions,
                workspace_id=scope,
                publication_id=identifier,
                expected_version=2,
                execution_id=uuid4(),
            )

    asyncio.run(run())
