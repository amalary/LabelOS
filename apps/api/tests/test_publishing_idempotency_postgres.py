"""Stage 7: committed commands and crash boundaries on independent PG sessions."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from labelos_database.models import Organization, Publication, PublicationAttempt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSessionTransaction

from labelos_api.publishing.providers import (
    ProviderCapabilities,
    ProviderOutcome,
    ProviderRegistry,
    ProviderResult,
)
from labelos_api.repositories.publishing import (
    PublicationConflict,
    PublicationRepository,
)
from labelos_api.services.delivery_orchestrator import (
    DeliveryIneligible,
    DeliveryOrchestrator,
)
from test_delivery_orchestrator import accept, accepted, count, prepared
from test_scheduling_repository import sessions as repository_sessions  # noqa: F401


@pytest.fixture
def sessions(repository_sessions):  # noqa: F811
    return repository_sessions


class Provider:
    capabilities = ProviderCapabilities(reconcile=True)

    def __init__(self, outcome=ProviderOutcome.published):
        self.outcome = outcome
        self.calls = []
        self.lookups = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    def validate(self, request):
        return None

    async def publish(self, request):
        self.calls.append(request)
        self.entered.set()
        await self.release.wait()
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return ProviderResult(
            outcome=self.outcome,
            external_post_id=(
                "post-one" if self.outcome == ProviderOutcome.published else None
            ),
            confirmed_absent=self.outcome == ProviderOutcome.retryable_failure,
        )

    async def reconcile(self, request):
        self.lookups.append(request)
        return ProviderResult(
            outcome=ProviderOutcome.published, external_post_id="post-one"
        )


async def setup(sessions):
    request, _, identifier = await accepted(sessions)
    return request.snapshot.workspace_id, identifier


async def stored(sessions, scope, identifier):
    async with sessions.begin() as session:
        return await PublicationRepository(session, scope).get(identifier)


def command(scope, identifier, provider, **kwargs):
    return dict(
        workspace_id=scope,
        publication_id=identifier,
        registry=ProviderRegistry({"instagram": provider}),
        **kwargs,
    )


def test_duplicate_scheduling_event_and_simultaneous_creation(sessions):
    async def run():
        request, fence = await prepared(sessions)

        async def create():
            async with sessions.begin() as session:
                return await accept(session, request, fence)

        receipts = await asyncio.gather(create(), create(), create())
        assert receipts[0] == receipts[1] == receipts[2]
        assert await create() == receipts[0]
        async with sessions.begin() as session:
            assert await count(session, Publication) == 1
            assert await count(session, PublicationAttempt) == 0

        # Exercise repository creation independently of the Scheduling composer.
        request, _ = await prepared(sessions)

        async def low_level_create():
            async with sessions.begin() as session:
                row = await PublicationRepository(
                    session, request.snapshot.workspace_id
                ).create(
                    request, created_at=datetime.now(UTC), destination_identity="a" * 64
                )
                return row.id, row.receipt_id

        results = await asyncio.gather(low_level_create(), low_level_create())
        assert results[0] == results[1]

    asyncio.run(run())


@pytest.mark.parametrize("commit", ["start", "outcome"])
def test_lost_commit_acknowledgement_requires_readback(sessions, monkeypatch, commit):
    async def run():
        scope, identifier = await setup(sessions)
        provider, service = Provider(), DeliveryOrchestrator()
        args = command(scope, identifier, provider, execution_id=uuid4())
        original_exit = AsyncSessionTransaction.__aexit__
        original_append = PublicationRepository.append

        async def append(self, *args, **kwargs):
            row = await original_append(self, *args, **kwargs)
            is_start = kwargs["entry"].attempt is not None
            if is_start == (commit == "start"):
                self.session.info["lose_commit_ack"] = True
            return row

        async def lose_ack(self, *args):
            await original_exit(self, *args)
            if not self.nested and self.session.info.pop("lose_commit_ack", False):
                raise RuntimeError("lost commit acknowledgement")

        monkeypatch.setattr(PublicationRepository, "append", append)
        monkeypatch.setattr(AsyncSessionTransaction, "__aexit__", lose_ack)
        with pytest.raises(RuntimeError, match="lost commit acknowledgement"):
            await service.execute(sessions, **args)
        monkeypatch.setattr(PublicationRepository, "append", original_append)
        monkeypatch.setattr(AsyncSessionTransaction, "__aexit__", original_exit)
        row = await stored(sessions, scope, identifier)
        assert row.status == ("processing" if commit == "start" else "published")
        assert len(provider.calls) == (0 if commit == "start" else 1)
        with pytest.raises(DeliveryIneligible):
            await service.execute(sessions, **args)

    asyncio.run(run())


def test_recovery_rejects_wrong_execution_and_stale_version(sessions):
    async def run():
        scope, identifier = await setup(sessions)
        provider = Provider(asyncio.CancelledError())
        service, execution_id = DeliveryOrchestrator(), uuid4()
        with pytest.raises(asyncio.CancelledError):
            await service.execute(
                sessions,
                **command(scope, identifier, provider, execution_id=execution_id),
            )
        args = dict(workspace_id=scope, publication_id=identifier)
        with pytest.raises(PublicationConflict, match="execution_conflict"):
            await service.recover_interrupted(
                sessions, **args, execution_id=uuid4(), expected_version=1
            )
        with pytest.raises(PublicationConflict, match="version_conflict"):
            await service.recover_interrupted(
                sessions, **args, execution_id=execution_id, expected_version=0
            )
        row = await stored(sessions, scope, identifier)
        assert row.status == "processing" and len(row.transitions) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "outcome", [ProviderOutcome.published, ProviderOutcome.retryable_failure]
)
def test_duplicate_worker_message_during_io_and_after_completion(sessions, outcome):
    async def run():
        scope, identifier = await setup(sessions)
        service, provider = DeliveryOrchestrator(), Provider(outcome)
        provider.release.clear()
        args = command(scope, identifier, provider, execution_id=uuid4())
        first = asyncio.create_task(service.execute(sessions, **args))
        await asyncio.wait_for(provider.entered.wait(), 10)
        try:
            with pytest.raises(DeliveryIneligible):
                await service.execute(sessions, **args)
        finally:
            provider.release.set()
        await first
        with pytest.raises(DeliveryIneligible, match="execution_already_started"):
            await service.execute(sessions, **args)
        row = await stored(sessions, scope, identifier)
        assert len(provider.calls) == len(row.attempts) == 1
        assert row.status == outcome.value

    asyncio.run(run())


def test_simultaneous_retry_commands_are_version_guarded(sessions):
    async def run():
        scope, identifier = await setup(sessions)
        service, provider = DeliveryOrchestrator(), Provider(
            ProviderOutcome.retryable_failure
        )
        args = command(scope, identifier, provider)
        await service.execute(sessions, **args)
        with pytest.raises(DeliveryIneligible):
            await service.execute(sessions, **args)
        with pytest.raises(DeliveryIneligible, match="retry_version_required"):
            await service.execute(sessions, **args, execution_id=uuid4())

        async def retry():
            try:
                return await service.execute(
                    sessions, **args, execution_id=uuid4(), expected_version=2
                )
            except DeliveryIneligible:
                return None

        results = await asyncio.gather(retry(), retry())
        assert sum(result is not None for result in results) == 1
        assert len(provider.calls) == 2
        assert provider.calls[0].idempotency_key == provider.calls[1].idempotency_key
        assert len((await stored(sessions, scope, identifier)).attempts) == 2

    asyncio.run(run())


def test_manual_retry_of_published_item_with_new_command_is_rejected(sessions):
    async def run():
        scope, identifier = await setup(sessions)
        service, provider = DeliveryOrchestrator(), Provider()
        args = command(scope, identifier, provider)
        await service.execute(sessions, **args)
        with pytest.raises(DeliveryIneligible):
            await service.execute(
                sessions, **args, execution_id=uuid4(), expected_version=2
            )
        assert len(provider.calls) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "boundary",
    [
        "before_start_commit",
        "after_start_commit",
        "after_external_success",
        "outcome_rollback",
        "timeout",
    ],
)
def test_crash_and_unknown_outcome_never_blindly_republish(
    sessions, monkeypatch, boundary
):
    async def run():
        scope, identifier = await setup(sessions)
        service = DeliveryOrchestrator()
        provider = Provider(
            TimeoutError() if boundary == "timeout" else ProviderOutcome.published
        )
        execution_id = uuid4()
        args = command(scope, identifier, provider, execution_id=execution_id)
        original_append = PublicationRepository.append
        original_record = service.record_evidence
        original_publish = provider.publish

        async def append(self, *args, **kwargs):
            row = await original_append(self, *args, **kwargs)
            if (boundary == "before_start_commit" and kwargs["entry"].attempt) or (
                boundary == "outcome_rollback" and kwargs["entry"].evidence
            ):
                raise RuntimeError("injected rollback")
            return row

        async def before_call(request):
            raise asyncio.CancelledError()

        async def after_success(*args, **kwargs):
            raise asyncio.CancelledError()

        monkeypatch.setattr(PublicationRepository, "append", append)
        if boundary == "after_start_commit":
            monkeypatch.setattr(provider, "publish", before_call)
        if boundary == "after_external_success":
            monkeypatch.setattr(service, "record_evidence", after_success)
        if boundary == "timeout":
            assert (
                await service.execute(sessions, **args)
            ).status == "manual_action_required"
        else:
            with pytest.raises((RuntimeError, asyncio.CancelledError)):
                await service.execute(sessions, **args)
        monkeypatch.setattr(PublicationRepository, "append", original_append)
        monkeypatch.setattr(service, "record_evidence", original_record)
        monkeypatch.setattr(provider, "publish", original_publish)
        row = await stored(sessions, scope, identifier)
        if boundary == "before_start_commit":
            assert row.status == "pending" and not row.attempts and not provider.calls
            assert (await service.execute(sessions, **args)).status == "published"
            return
        assert len(row.attempts) == 1
        assert len(provider.calls) == (0 if boundary == "after_start_commit" else 1)
        with pytest.raises(DeliveryIneligible):
            await service.execute(sessions, **args)
        recovery = dict(
            workspace_id=scope,
            publication_id=identifier,
            execution_id=execution_id,
            expected_version=1,
        )
        # Executor has stopped; no request is retried even when the test knows it
        # never reached the provider. Real recovery cannot know that fact.
        recovered = await service.recover_interrupted(sessions, **recovery)
        assert recovered.status == "manual_action_required"
        await service.recover_interrupted(sessions, **recovery)
        with pytest.raises(DeliveryIneligible):
            await service.execute(
                sessions,
                **command(
                    scope,
                    identifier,
                    provider,
                    execution_id=uuid4(),
                    expected_version=2,
                ),
            )
        row = await stored(sessions, scope, identifier)
        assert len(row.transitions) == 2 and row.external_post_id is None
        if boundary != "after_start_commit":
            result = await service.reconcile(
                sessions, **command(scope, identifier, provider)
            )
            assert result.status == "published"
            assert provider.lookups[0].attempt.id == row.attempts[0].id
            assert len(provider.calls) == 1

    asyncio.run(run())


def test_execution_identity_cannot_be_reused_across_publications(sessions, monkeypatch):
    async def run():
        scope, first = await setup(sessions)
        provider, service = Provider(), DeliveryOrchestrator()
        execution_id = uuid4()
        await service.execute(
            sessions, **command(scope, first, provider, execution_id=execution_id)
        )
        original = PublicationRepository.require_unused_execution

        async def unchecked(self, execution_id, publication_id):
            pass

        async with sessions.begin() as session:
            workspace = await session.get(Organization, scope)
        _, _, second = await accepted(sessions, workspace=workspace)
        provider2 = Provider()
        args = command(scope, second, provider2)
        with pytest.raises(DeliveryIneligible, match="execution_identity_conflict"):
            await service.execute(sessions, **args, execution_id=execution_id)
        # Simulate a stale precheck: the unique index is the final authority,
        # and its rejection must roll back the attempt before provider I/O.
        monkeypatch.setattr(
            PublicationRepository, "require_unused_execution", unchecked
        )
        with pytest.raises(IntegrityError):
            await service.execute(sessions, **args, execution_id=execution_id)
        monkeypatch.setattr(PublicationRepository, "require_unused_execution", original)
        assert not provider2.calls
        assert not (await stored(sessions, scope, second)).attempts

    asyncio.run(run())
