"""Real PostgreSQL acceptance, execution, replay and failure boundaries."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from labelos_database.models import (
    ApprovalRequest,
    MarketingContentItem,
    MarketingContentItemChannel,
    Publication,
    PublicationAttempt,
    RealtimeEvent,
    SchedulingJob,
    SchedulingJobTransition,
    SocialAccountConnection,
)
from sqlalchemy import func, select, update

from labelos_api.publishing import contracts as domain
from labelos_api.repositories.publishing import (
    PublicationConflict,
    PublicationRepository,
)
from labelos_api.repositories.scheduling import SchedulingConflict
from labelos_api.scheduling.contracts import (
    DurableAccepted,
    SchedulingFeatureControls,
    TerminalRejected,
)
from labelos_api.scheduling.payload import canonical_json, fingerprint
from labelos_api.services.delivery_orchestrator import (
    DeliveryIneligible,
    DeliveryOrchestrator,
)
from test_scheduling_handoff_postgres import prepared as scheduling_prepared
from test_scheduling_repository import repo
from test_scheduling_repository import sessions as repository_sessions  # noqa: F401

CONTROLS = SchedulingFeatureControls(
    execution_enabled=True, delivery_receiver_configured=True
)


@pytest.fixture
def sessions(repository_sessions):  # noqa: F811
    return repository_sessions


async def prepared(sessions):
    request, fence = await scheduling_prepared(sessions)
    async with sessions.begin() as session:
        await session.execute(
            update(SocialAccountConnection).values(external_account_id="account-one")
        )
    return request, fence


async def accept(session, request, fence, **kwargs):
    return await DeliveryOrchestrator().accept_execution(
        repo(session, request.snapshot.workspace_id),
        request=request,
        expected_worker="worker:a",
        expected_fencing_token=fence,
        controls=kwargs.pop("controls", CONTROLS),
        **kwargs,
    )


async def accepted(sessions):
    request, fence = await prepared(sessions)
    async with sessions.begin() as session:
        result = await accept(session, request, fence)
        assert isinstance(result, DurableAccepted)
        row = await PublicationRepository(
            session, request.snapshot.workspace_id
        ).get_by_job(request.job_id)
        return request, fence, row.id


async def count(session, model):
    return await session.scalar(select(func.count()).select_from(model))


def test_creation_replay_context_and_disabled_provider(sessions):
    async def run():
        request, fence, identifier = await accepted(sessions)
        scope = request.snapshot.workspace_id
        async with sessions.begin() as session:
            first = await accept(session, request, fence)
            assert (
                await accept(
                    session, request, fence, controls=SchedulingFeatureControls()
                )
                == first
            )
            context = await DeliveryOrchestrator().prepare_execution(
                repo(session, scope, window=0), identifier
            )
            assert context.publication_id == identifier
            assert context.destination_id == request.destination_id
            assert "APPROVED_PRIVATE_COPY" not in repr(context)
            assert "account-one" not in repr(context)
            assert await count(session, Publication) == 1
            assert await count(session, PublicationAttempt) == 0
            job = await session.get(SchedulingJob, request.job_id)
            assert (
                job.status == "handed_off"
                and job.handoff_receipt_id == first.receipt_id
            )
        result = await DeliveryOrchestrator().execute(
            sessions, workspace_id=scope, publication_id=identifier
        )
        assert (
            result.status == "pending"
            and result.reason_code == "provider_execution_disabled"
        )
        async with sessions.begin() as session:
            assert await count(session, PublicationAttempt) == 0
            events = (
                await session.scalars(
                    select(RealtimeEvent).where(
                        RealtimeEvent.event_type == "marketing.publication.changed"
                    )
                )
            ).all()
            assert len(events) == 1 and events[0].payload["status"] == "pending"

    asyncio.run(run())


def test_concurrent_acceptance_and_conflicting_replay(sessions):
    async def run():
        request, fence = await prepared(sessions)

        async def contender():
            async with sessions.begin() as session:
                return await accept(session, request, fence)

        results = await asyncio.gather(contender(), contender())
        assert isinstance(results[0], DurableAccepted) and results[0] == results[1]
        changed = replace(request, correlation_id=uuid4())
        changed = replace(changed, payload_fingerprint=fingerprint(changed))
        async with sessions.begin() as session:
            assert isinstance(await accept(session, changed, fence), TerminalRejected)
            assert await count(session, Publication) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        "cancelled",
        "superseded",
        "approval",
        "revision",
        "generation",
        "copy",
        "channel",
        "destination",
        "connection",
        "identity_missing",
        "parent",
        "workspace",
        "fence",
        "lease",
    ],
)
def test_ineligible_acceptance_never_creates_publication(sessions, change):
    async def run():
        request, fence = await prepared(sessions)
        async with sessions.begin() as session:
            if change in ("cancelled", "superseded"):
                await repo(
                    session, request.snapshot.workspace_id
                ).apply_user_transition(
                    request.job_id,
                    operation="cancel" if change == "cancelled" else "supersede",
                    operation_id=uuid4(),
                    actor_key="test:user",
                )
            elif change == "approval":
                await session.execute(update(ApprovalRequest).values(status="rejected"))
            elif change == "revision":
                await session.execute(
                    update(MarketingContentItem).values(content_revision=2)
                )
            elif change == "generation":
                await session.execute(
                    update(MarketingContentItemChannel).values(schedule_generation=2)
                )
            elif change == "copy":
                await session.execute(
                    update(MarketingContentItem).values(copy_text="unapproved change")
                )
            elif change == "channel":
                changed = replace(
                    request, snapshot=replace(request.snapshot, channel_id=uuid4())
                )
                request = replace(changed, payload_fingerprint=fingerprint(changed))
            elif change == "destination":
                await session.execute(
                    update(MarketingContentItemChannel).values(
                        social_account_connection_id=None
                    )
                )
            elif change == "connection":
                await session.execute(
                    update(SocialAccountConnection).values(status="disconnected")
                )
            elif change == "identity_missing":
                await session.execute(
                    update(SocialAccountConnection).values(external_account_id=None)
                )
            elif change == "parent":
                await session.execute(
                    update(MarketingContentItem).values(status="draft")
                )
            elif change == "workspace":
                changed = replace(
                    request, snapshot=replace(request.snapshot, workspace_id=uuid4())
                )
                request = replace(changed, payload_fingerprint=fingerprint(changed))
            elif change == "fence":
                fence += 1
            elif change == "lease":
                from test_scheduling_repository import expire

                await expire(session, request.job_id)
        async with sessions.begin() as session:
            assert isinstance(await accept(session, request, fence), TerminalRejected)
            assert await count(session, Publication) == 0
            assert await count(session, PublicationAttempt) == 0

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        "approval",
        "revision",
        "generation",
        "copy",
        "destination",
        "identity",
        "disconnected",
        "parent",
        "foreign_workspace",
    ],
)
def test_accepted_replay_is_history_but_changed_work_cannot_execute(sessions, change):
    async def run():
        request, fence, identifier = await accepted(sessions)
        scope = request.snapshot.workspace_id
        async with sessions.begin() as session:
            if change == "approval":
                await session.execute(update(ApprovalRequest).values(status="rejected"))
            elif change == "revision":
                await session.execute(
                    update(MarketingContentItem).values(content_revision=2)
                )
            elif change == "generation":
                await session.execute(
                    update(MarketingContentItemChannel).values(schedule_generation=2)
                )
            elif change == "copy":
                await session.execute(
                    update(MarketingContentItem).values(copy_text="later edit")
                )
            elif change == "destination":
                await session.execute(
                    update(MarketingContentItemChannel).values(
                        social_account_connection_id=None
                    )
                )
            elif change == "identity":
                await session.execute(
                    update(SocialAccountConnection).values(
                        external_account_id="account-two"
                    )
                )
            elif change == "disconnected":
                await session.execute(
                    update(SocialAccountConnection).values(status="disconnected")
                )
            elif change == "parent":
                await session.execute(
                    update(MarketingContentItem).values(status="draft")
                )
        async with sessions.begin() as session:
            assert isinstance(await accept(session, request, fence), DurableAccepted)
            with pytest.raises(DeliveryIneligible):
                await DeliveryOrchestrator().prepare_execution(
                    repo(session, uuid4() if change == "foreign_workspace" else scope),
                    identifier,
                )
            assert await count(session, PublicationAttempt) == 0

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["outer", "final_handoff", "outbox"])
def test_acceptance_rollback_has_no_detached_publication(
    sessions, monkeypatch, failure
):
    async def run():
        request, fence = await prepared(sessions)
        async with sessions.begin() as session:
            baseline = await count(session, RealtimeEvent)
            transitions = await count(session, SchedulingJobTransition)
        if failure == "final_handoff":

            async def fail(*args, **kwargs):
                raise SchedulingConflict("fence_changed")

            monkeypatch.setattr(
                "labelos_api.repositories.scheduling.SchedulingRepository.record_handoff_acceptance",
                fail,
            )
        if failure == "outbox":
            original = PublicationRepository._outbox

            def fail_outbox(self, *args):
                original(self, *args)
                raise RuntimeError("injected_failure")

            monkeypatch.setattr(PublicationRepository, "_outbox", fail_outbox)
        async with sessions() as session:
            if failure == "outbox":
                with pytest.raises(RuntimeError, match="injected_failure"):
                    await accept(session, request, fence)
                await session.commit()
            else:
                result = await accept(session, request, fence)
                if failure == "outer":
                    assert isinstance(result, DurableAccepted)
                    await session.rollback()
                else:
                    assert isinstance(result, TerminalRejected)
                    await session.commit()
        async with sessions.begin() as session:
            assert await count(session, Publication) == 0
            assert await count(session, PublicationAttempt) == 0
            assert await count(session, RealtimeEvent) == baseline
            assert await count(session, SchedulingJobTransition) == transitions
            assert (
                await session.get(SchedulingJob, request.job_id)
            ).status == "claimed"

    asyncio.run(run())


class TestProvider:
    __test__ = False
    enabled = True

    def __init__(self, sessions, outcome="published"):
        self.sessions = sessions
        self.outcome = outcome
        self.calls = 0

    async def deliver(self, context, attempt):
        self.calls += 1
        # A different session can lock/read the committed start during provider I/O.
        async with self.sessions.begin() as session:
            row = await PublicationRepository(session, context.workspace_id).get(
                context.publication_id, lock=True
            )
            assert row.status in ("processing", "retrying")
            assert row.attempts[-1].id == attempt.id
        if self.outcome == "exception":
            raise RuntimeError("SECRET_PROVIDER_PAYLOAD")
        return domain.PublicationEvidence(
            workspace_id=context.workspace_id,
            publication_id=context.publication_id,
            attempt_id=attempt.id,
            destination_id=context.destination_id,
            outcome=domain.DeliveryOutcome(self.outcome),
            source=domain.EvidenceSource.provider_response,
            observed_at=datetime.now(UTC),
            external_post_id="post-one" if self.outcome == "published" else None,
            reason=(
                domain.PublicationFailureReason.temporary_unavailability
                if self.outcome != "published"
                else None
            ),
        )


def test_success_replay_and_concurrent_execution_cannot_start_again(sessions):
    async def run():
        request, fence, identifier = await accepted(sessions)
        provider = TestProvider(sessions)

        async def execute():
            try:
                return await DeliveryOrchestrator().execute(
                    sessions,
                    workspace_id=request.snapshot.workspace_id,
                    publication_id=identifier,
                    provider=provider,
                )
            except DeliveryIneligible:
                return None

        results = await asyncio.gather(execute(), execute())
        assert (
            sum(
                result is not None and result.status == "published"
                for result in results
            )
            == 1
        )
        assert provider.calls == 1
        assert await execute() is None
        async with sessions.begin() as session:
            assert isinstance(await accept(session, request, fence), DurableAccepted)
            row = await PublicationRepository(
                session, request.snapshot.workspace_id
            ).get(identifier)
            assert row.status == "published" and len(row.attempts) == 1
            assert [t.operation for t in row.transitions] == [
                "start",
                "confirm_success",
            ]

    asyncio.run(run())


def test_explicit_retry_preserves_intent_and_unknown_requires_reconciliation(
    sessions, caplog
):
    async def run():
        request, _, identifier = await accepted(sessions)
        scope = request.snapshot.workspace_id
        orchestrator = DeliveryOrchestrator()
        result = await orchestrator.execute(
            sessions,
            workspace_id=scope,
            publication_id=identifier,
            provider=TestProvider(sessions, "retryable_failure"),
        )
        assert result.status == "retryable_failure"
        result = await orchestrator.execute(
            sessions,
            workspace_id=scope,
            publication_id=identifier,
            provider=TestProvider(sessions, "exception"),
        )
        assert result.status == "manual_action_required"
        with pytest.raises(DeliveryIneligible):
            await orchestrator.execute(
                sessions,
                workspace_id=scope,
                publication_id=identifier,
                provider=TestProvider(sessions),
            )
        async with sessions.begin() as session:
            row = await PublicationRepository(session, scope).get(identifier)
            assert len(row.attempts) == 2 and row.transition_version == 4
            evidence = domain.PublicationEvidence(
                workspace_id=scope,
                publication_id=identifier,
                attempt_id=row.attempts[-1].id,
                destination_id=request.destination_id,
                outcome=domain.DeliveryOutcome.published,
                source=domain.EvidenceSource.reconciliation,
                observed_at=datetime.now(UTC),
                external_post_id="post-one",
            )
        await orchestrator.record_evidence(
            sessions,
            workspace_id=scope,
            publication_id=identifier,
            expected_version=4,
            evidence=evidence,
        )
        async with sessions.begin() as session:
            row = await PublicationRepository(session, scope).get(identifier)
            assert row.status == "published" and len(row.attempts) == 2
            assert row.payload_fingerprint == request.payload_fingerprint

    asyncio.run(run())
    assert "SECRET_PROVIDER_PAYLOAD" not in caplog.text


@pytest.mark.parametrize("failure", ["start", "outcome", "cancelled_task"])
def test_execution_failure_boundaries_never_blindly_redeliver(
    sessions, monkeypatch, failure
):
    async def run():
        request, _, identifier = await accepted(sessions)
        scope = request.snapshot.workspace_id
        orchestrator = DeliveryOrchestrator()
        original = PublicationRepository.append

        async def fail_append(self, *args, **kwargs):
            row = await original(self, *args, **kwargs)
            is_start = kwargs["entry"].attempt is not None
            if (failure == "start" and is_start) or (
                failure == "outcome" and not is_start
            ):
                raise RuntimeError("transaction_failed")
            return row

        class InterruptedProvider(TestProvider):
            async def deliver(self, context, attempt):
                await super().deliver(context, attempt)
                raise asyncio.CancelledError()

        provider = (
            InterruptedProvider(sessions)
            if failure == "cancelled_task"
            else TestProvider(sessions)
        )
        monkeypatch.setattr(PublicationRepository, "append", fail_append)
        expected = (
            asyncio.CancelledError if failure == "cancelled_task" else RuntimeError
        )
        with pytest.raises(expected):
            await orchestrator.execute(
                sessions,
                workspace_id=scope,
                publication_id=identifier,
                provider=provider,
            )
        monkeypatch.setattr(PublicationRepository, "append", original)
        async with sessions.begin() as session:
            row = await PublicationRepository(session, scope).get(identifier)
            assert row.status == ("pending" if failure == "start" else "processing")
            assert len(row.attempts) == (0 if failure == "start" else 1)
            assert provider.calls == (0 if failure == "start" else 1)
            assert len(row.transitions) == (0 if failure == "start" else 1)
            if failure != "start":
                evidence = domain.PublicationEvidence(
                    workspace_id=scope,
                    publication_id=identifier,
                    attempt_id=row.attempts[-1].id,
                    destination_id=request.destination_id,
                    outcome=domain.DeliveryOutcome.unknown,
                    source=domain.EvidenceSource.execution_interrupted,
                    observed_at=datetime.now(UTC),
                    reason=domain.PublicationFailureReason.outcome_unknown,
                )
        if failure != "start":
            with pytest.raises(DeliveryIneligible):
                await orchestrator.execute(
                    sessions,
                    workspace_id=scope,
                    publication_id=identifier,
                    provider=provider,
                )
            await orchestrator.record_evidence(
                sessions,
                workspace_id=scope,
                publication_id=identifier,
                expected_version=1,
                evidence=evidence,
            )
            with pytest.raises(PublicationConflict):
                await orchestrator.record_evidence(
                    sessions,
                    workspace_id=scope,
                    publication_id=identifier,
                    expected_version=1,
                    evidence=evidence,
                )

    asyncio.run(run())


def test_actual_foreign_destination_and_approval_cannot_be_mixed(sessions):
    async def run():
        request, fence = await prepared(sessions)
        foreign, _ = await prepared(sessions)
        for changed in (
            replace(request, destination_id=foreign.destination_id),
            replace(
                request,
                snapshot=replace(
                    request.snapshot,
                    approval_request_id=foreign.snapshot.approval_request_id,
                ),
            ),
            replace(
                request,
                snapshot=replace(
                    request.snapshot, content_item_id=foreign.snapshot.content_item_id
                ),
            ),
        ):
            changed = replace(changed, payload_fingerprint=fingerprint(changed))
            async with sessions.begin() as session:
                assert isinstance(
                    await accept(session, changed, fence), TerminalRejected
                )
                assert await count(session, Publication) == 0

    asyncio.run(run())


def test_repository_only_publication_is_not_scheduling_acceptance(sessions):
    async def run():
        request, fence = await prepared(sessions)
        async with sessions.begin() as session:
            row = await PublicationRepository(
                session, request.snapshot.workspace_id
            ).create(request, created_at=datetime.now(UTC))
            identifier = row.id
        async with sessions.begin() as session:
            assert isinstance(await accept(session, request, fence), TerminalRejected)
            with pytest.raises(
                DeliveryIneligible, match="scheduling_acceptance_missing"
            ):
                await DeliveryOrchestrator().prepare_execution(
                    repo(session, request.snapshot.workspace_id), identifier
                )

    asyncio.run(run())


@pytest.mark.parametrize("caption", [None, "", " \n\t"])
def test_empty_approved_content_is_not_deliverable(sessions, caption):
    import json

    async def run():
        request, fence = await prepared(sessions)
        async with sessions.begin() as session:
            await session.execute(
                update(MarketingContentItem).values(copy_text=caption)
            )
        content = json.loads(request.canonical_payload)
        content["caption"] = caption
        changed = replace(request, canonical_payload=canonical_json(content))
        changed = replace(changed, payload_fingerprint=fingerprint(changed))
        async with sessions.begin() as session:
            assert isinstance(await accept(session, changed, fence), TerminalRejected)
            assert await count(session, Publication) == 0

    asyncio.run(run())
