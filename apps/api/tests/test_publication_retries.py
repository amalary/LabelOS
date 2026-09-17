"""Stage 8: pure timing and durable retries, with a clock and no real waits."""

import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from uuid import uuid4

import httpx
import pytest
from labelos_database.models import PublicationAttempt
from sqlalchemy import insert
from sqlalchemy.exc import DBAPIError

from fake_publishing_provider import FakePublishingAdapter
from labelos_api.publishing.providers import ProviderOutcome as Outcome
from labelos_api.publishing.providers import ProviderRegistry
from labelos_api.publishing.retries import (
    MAX_ATTEMPTS,
    MAX_ELAPSED,
    retry_decision,
)
from labelos_api.publishing.retries import (
    FailureCategory as Category,
)
from labelos_api.publishing.retries import (
    RetryDisposition as Disposition,
)
from labelos_api.publishing.youtube import _http_failure, parse_retry_after
from labelos_api.services.delivery_orchestrator import (
    DeliveryIneligible,
    DeliveryOrchestrator,
)
from test_publishing_persistence import sessions as persistence_sessions  # noqa: F401
from test_publishing_providers import (
    result,
    setup_delivery,
    stored,
)

NOW = datetime.now(UTC) + timedelta(days=1)


@pytest.fixture
def sessions(persistence_sessions):  # noqa: F811
    return persistence_sessions


@pytest.mark.parametrize(
    "attempt,low,high", [(1, 15, 30), (2, 30, 60), (3, 60, 120), (4, 120, 240)]
)
def test_exponential_equal_jitter(attempt, low, high):
    for jitter, seconds in ((0, low), (1, high), (0.5, (low + high) / 2)):
        decision = retry_decision(
            Category.transient_network,
            attempt_number=attempt,
            first_started_at=NOW,
            observed_at=NOW,
            jitter=jitter,
        )
        assert decision.next_retry_at == NOW + timedelta(seconds=seconds)
        assert decision.deadline_at == NOW + MAX_ELAPSED


def test_provider_delay_is_floor_and_never_shortened_to_fit_budget():
    def decide(delay):
        return retry_decision(
            Category.rate_limited,
            attempt_number=1,
            first_started_at=NOW,
            observed_at=NOW,
            retry_after_seconds=delay,
            jitter=1,
        )

    assert decide(0).next_retry_at == NOW + timedelta(seconds=30)
    assert decide(900).next_retry_at == NOW + timedelta(seconds=900)
    assert decide(900).disposition == Disposition.provider_delay
    assert decide(86400).disposition == Disposition.exhausted
    assert decide(604800).next_retry_at is None


@pytest.mark.parametrize(
    "category,disposition",
    [
        (Category.transient_network, Disposition.automatic),
        (Category.provider_unavailable, Disposition.automatic),
        (Category.rate_limited, Disposition.automatic),
        (Category.authentication, Disposition.blocked_reconnection),
        (Category.authorization, Disposition.blocked_reconnection),
        (Category.invalid_content_media, Disposition.permanent),
        (Category.unsupported_operation, Disposition.permanent),
        (Category.ambiguous_outcome, Disposition.reconciliation_required),
        (Category.permanent_rejection, Disposition.permanent),
        (Category.internal_failure, Disposition.manual_action),
    ],
)
def test_all_classifications(category, disposition):
    decision = retry_decision(
        category, attempt_number=1, first_started_at=NOW, observed_at=NOW
    )
    assert decision.disposition == disposition
    assert (decision.next_retry_at is not None) == (
        disposition == Disposition.automatic
    )


def test_attempt_and_elapsed_boundaries():
    for attempt, observed in (
        (MAX_ATTEMPTS, NOW),
        (1, NOW + MAX_ELAPSED),
        (1, NOW + MAX_ELAPSED - timedelta(seconds=10)),
    ):
        decision = retry_decision(
            Category.provider_unavailable,
            attempt_number=attempt,
            first_started_at=NOW,
            observed_at=observed,
        )
        assert decision.disposition == Disposition.exhausted
        assert decision.next_retry_at is None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("90", 90),
        ("0", 0),
        ("-2", None),
        ("1.5", None),
        ("NaN", None),
        ("604801", None),
        ("x" * 129, None),
        ("１２", None),
        (format_datetime(NOW + timedelta(seconds=120), usegmt=True), 120),
        (format_datetime(NOW - timedelta(seconds=1), usegmt=True), 0),
    ],
)
def test_safe_retry_after(value, expected):
    assert parse_retry_after(value, now=NOW) == expected


@pytest.mark.parametrize(
    "status,reason,write,category",
    [
        (429, "rateLimitExceeded", True, Category.rate_limited),
        (503, "backendError", False, Category.provider_unavailable),
        (503, "backendError", True, Category.ambiguous_outcome),
        (429, "unrecognized", True, Category.ambiguous_outcome),
        (401, "authError", True, Category.authentication),
        (403, "insufficientPermissions", True, Category.authorization),
        (400, "invalidVideoMetadata", True, Category.invalid_content_media),
        (404, "notFound", False, Category.permanent_rejection),
        (400, "unknownRejection", False, Category.permanent_rejection),
        (403, "authError", True, Category.authentication),
    ],
)
def test_adapter_classifies_http_only_with_side_effect_context(
    status, reason, write, category
):
    response = httpx.Response(
        status,
        headers={"Retry-After": "120"},
        json={"error": {"code": status, "errors": [{"reason": reason}]}},
    )
    failure = _http_failure(response, write_started=write)
    assert failure.failure_category == category
    assert failure.retry_after_seconds == (
        120
        if category in {Category.rate_limited, Category.provider_unavailable}
        else None
    )


def test_retry_survives_restart_succeeds_once_and_preserves_history(
    sessions, monkeypatch
):
    async def run():
        scope, identifier = await setup_delivery(sessions, monkeypatch)
        adapter = FakePublishingAdapter(
            result(Outcome.rate_limited, retry_after_seconds=120),
            result(Outcome.published),
        )
        registry = ProviderRegistry({"instagram": adapter})
        service = DeliveryOrchestrator(clock=lambda: NOW)
        await service.execute(
            sessions, workspace_id=scope, publication_id=identifier, registry=registry
        )
        first = await stored(sessions, scope, identifier)
        assert first.next_retry_at == NOW + timedelta(seconds=120)
        assert first.transitions[-1].retry_after_seconds == 120
        assert first.transitions[-1].next_retry_at == first.next_retry_at
        with pytest.raises(DeliveryIneligible, match="retry_not_due"):
            await service.execute(
                sessions,
                workspace_id=scope,
                publication_id=identifier,
                registry=registry,
                expected_version=2,
                execution_id=uuid4(),
            )
        assert not await service.retry_due(
            sessions, workspace_id=scope, registry=registry
        )
        restarted = DeliveryOrchestrator(clock=lambda: first.next_retry_at)
        assert not await restarted.retry_due(
            sessions, workspace_id=uuid4(), registry=registry
        )
        deliveries = await restarted.retry_due(
            sessions, workspace_id=scope, registry=registry
        )
        assert [r.status for r in deliveries] == ["published"]
        assert not await restarted.retry_due(
            sessions, workspace_id=scope, registry=registry
        )
        final = await stored(sessions, scope, identifier)
        assert len(final.attempts) == 2 and len(final.transitions) == 4
        assert final.attempts[0].id == first.attempts[0].id
        assert final.attempts[1].id != first.attempts[0].id
        assert final.attempts[0].outcome == "retryable_failure"
        assert final.next_retry_at is None and final.retry_disposition is None
        assert (
            adapter.publications[0].idempotency_key
            == adapter.publications[1].idempotency_key
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "outcome,category,disposition",
    [
        (
            Outcome.authorization_required,
            Category.authentication,
            "blocked_reconnection",
        ),
        (
            Outcome.authorization_required,
            Category.authorization,
            "blocked_reconnection",
        ),
        (Outcome.permanent_failure, Category.invalid_content_media, "permanent"),
        (Outcome.retryable_failure, Category.internal_failure, "manual_action"),
        (Outcome.ambiguous, Category.ambiguous_outcome, "reconciliation_required"),
    ],
)
def test_nonautomatic_failures_persist_and_never_retry(
    sessions, monkeypatch, outcome, category, disposition
):
    async def run():
        scope, identifier = await setup_delivery(sessions, monkeypatch)
        adapter = FakePublishingAdapter(result(outcome, failure_category=category))
        registry = ProviderRegistry({"instagram": adapter})
        service = DeliveryOrchestrator(clock=lambda: NOW)
        await service.execute(
            sessions, workspace_id=scope, publication_id=identifier, registry=registry
        )
        row = await stored(sessions, scope, identifier)
        assert row.failure_category == category and row.retry_disposition == disposition
        assert row.next_retry_at is None
        assert not await service.retry_due(
            sessions, workspace_id=scope, registry=registry
        )
        with pytest.raises(DeliveryIneligible):
            await service.execute(
                sessions,
                workspace_id=scope,
                publication_id=identifier,
                registry=registry,
                expected_version=2,
                execution_id=uuid4(),
            )
        assert len(adapter.publications) == 1

    asyncio.run(run())


def test_maximum_attempts_are_durable(sessions, monkeypatch):
    async def run():
        scope, identifier = await setup_delivery(sessions, monkeypatch)
        adapter = FakePublishingAdapter(
            *[result(Outcome.retryable_failure)] * MAX_ATTEMPTS
        )
        registry = ProviderRegistry({"instagram": adapter})
        service = DeliveryOrchestrator(clock=lambda: NOW)
        await service.execute(
            sessions, workspace_id=scope, publication_id=identifier, registry=registry
        )
        for _ in range(MAX_ATTEMPTS - 1):
            row = await stored(sessions, scope, identifier)
            service = DeliveryOrchestrator(clock=lambda row=row: row.next_retry_at)
            assert (
                len(
                    await service.retry_due(
                        sessions, workspace_id=scope, registry=registry
                    )
                )
                == 1
            )
        row = await stored(sessions, scope, identifier)
        assert row.retry_disposition == "exhausted" and row.next_retry_at is None
        service.clock = lambda: NOW + MAX_ELAPSED
        assert not await service.retry_due(
            sessions, workspace_id=scope, registry=registry
        )
        with pytest.raises(DeliveryIneligible):
            await service.execute(
                sessions,
                workspace_id=scope,
                publication_id=identifier,
                registry=registry,
                expected_version=row.transition_version,
                execution_id=uuid4(),
            )
        assert len(row.attempts) == MAX_ATTEMPTS == len(adapter.publications)

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_elapsed_expiration_and_cancellation_while_waiting(
    sessions, monkeypatch, cancel
):
    async def run():
        scope, identifier = await setup_delivery(sessions, monkeypatch)
        adapter = FakePublishingAdapter(result(Outcome.retryable_failure))
        registry = ProviderRegistry({"instagram": adapter})
        service = DeliveryOrchestrator(clock=lambda: NOW)
        await service.execute(
            sessions, workspace_id=scope, publication_id=identifier, registry=registry
        )
        if cancel:
            await service.cancel_waiting(
                sessions,
                workspace_id=scope,
                publication_id=identifier,
                expected_version=2,
            )
        service.clock = lambda: NOW + MAX_ELAPSED
        assert not await service.retry_due(
            sessions, workspace_id=scope, registry=registry
        )
        with pytest.raises(DeliveryIneligible):
            await service.execute(
                sessions,
                workspace_id=scope,
                publication_id=identifier,
                registry=registry,
                expected_version=2,
                execution_id=uuid4(),
            )
        row = await stored(sessions, scope, identifier)
        assert len(row.attempts) == len(adapter.publications) == 1
        if cancel:
            assert row.status == "cancelled" and row.next_retry_at is None
            assert row.transitions[-2].next_retry_at is not None

    asyncio.run(run())


def test_database_guard_rejects_early_direct_attempt(sessions, monkeypatch):
    # The direct SQL check uses an async savepoint so an intentional rejection
    # leaves the surrounding session usable.
    async def check():
        scope, identifier = await setup_delivery(sessions, monkeypatch)
        service = DeliveryOrchestrator(clock=lambda: NOW)
        await service.execute(
            sessions,
            workspace_id=scope,
            publication_id=identifier,
            registry=ProviderRegistry(
                {"instagram": FakePublishingAdapter(result(Outcome.rate_limited))}
            ),
        )
        async with sessions.begin() as session:
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.execute(
                        insert(PublicationAttempt).values(
                            id=uuid4(),
                            workspace_id=scope,
                            publication_id=identifier,
                            number=2,
                            started_at=NOW,
                            execution_id=uuid4(),
                        )
                    )

    asyncio.run(check())


def test_cancellation_after_due_selection_wins(sessions, monkeypatch):
    async def run():
        scope, identifier = await setup_delivery(sessions, monkeypatch)
        adapter = FakePublishingAdapter(result(Outcome.retryable_failure))
        registry = ProviderRegistry({"instagram": adapter})
        service = DeliveryOrchestrator(clock=lambda: NOW)
        await service.execute(
            sessions, workspace_id=scope, publication_id=identifier, registry=registry
        )
        waiting = await stored(sessions, scope, identifier)
        service.clock = lambda: waiting.next_retry_at
        execute = service.execute

        async def cancel_then_execute(*args, **kwargs):
            await service.cancel_waiting(
                sessions,
                workspace_id=scope,
                publication_id=identifier,
                expected_version=2,
            )
            return await execute(*args, **kwargs)

        monkeypatch.setattr(service, "execute", cancel_then_execute)
        assert not await service.retry_due(
            sessions, workspace_id=scope, registry=registry
        )
        assert len(adapter.publications) == 1
        assert (await stored(sessions, scope, identifier)).status == "cancelled"

    asyncio.run(run())
