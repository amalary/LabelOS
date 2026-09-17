"""Network-free adapter contract and real SQLite delivery persistence tests.

Scheduling authorization/locks are covered by test_delivery_orchestrator against
PostgreSQL. Here only prepare_execution is substituted with an accepted context;
attempt/result transactions and reconciliation use the real repository/domain.
"""

import asyncio
import base64
import hashlib
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from fake_publishing_provider import FakePublishingAdapter
from labelos_api.publishing import contracts as domain
from labelos_api.publishing.execution import DeliveryContext
from labelos_api.publishing.providers import (
    AdapterContractError,
    ProviderCapabilities,
    ProviderRegistry,
    ProviderResolutionError,
    ProviderResult,
    publication_request,
    result_evidence,
    validate_preflight,
    validate_result,
)
from labelos_api.publishing.providers import (
    ProviderOutcome as Outcome,
)
from labelos_api.repositories.publishing import (
    PublicationConflict,
    PublicationRepository,
)
from labelos_api.scheduling.payload import canonical_json
from labelos_api.services.delivery_orchestrator import (
    DeliveryIneligible,
    DeliveryOrchestrator,
)
from test_publishing_persistence import seed
from test_publishing_persistence import sessions as persistence_sessions  # noqa: F401


def result(outcome, **kwargs):
    return ProviderResult(
        outcome=outcome,
        confirmed_absent=outcome
        not in {
            Outcome.published,
            Outcome.accepted,
            Outcome.ambiguous,
            Outcome.unsupported,
        },
        external_post_id="post-one" if outcome == Outcome.published else None,
        **kwargs,
    )


def context_and_attempt():
    data = b"approved-media"
    context = DeliveryContext(
        workspace_id=uuid4(),
        publication_id=uuid4(),
        scheduling_job_id=uuid4(),
        destination_id=uuid4(),
        provider="test_platform",
        destination_identity="a" * 64,
        canonical_envelope=canonical_json(
            {
                "content": {
                    "caption": "PRIVATE_APPROVED_COPY",
                    "channel": "test_platform",
                    "placement": "feed",
                    "hashtags": ["#label"],
                    "asset_refs": [
                        {
                            "sha256": hashlib.sha256(data).hexdigest(),
                            "media_type": "video/mp4",
                            "content_base64": base64.b64encode(data).decode(),
                        }
                    ],
                }
            }
        ),
        transition_version=0,
    )
    attempt = domain.PublicationAttempt(
        id=uuid4(),
        workspace_id=context.workspace_id,
        publication_id=context.publication_id,
        number=1,
        started_at=datetime.now(UTC),
    )
    return context, attempt


def test_request_is_immutable_neutral_private_and_retry_key_is_stable():
    context, attempt = context_and_attempt()
    request = publication_request(context, attempt)
    assert request.media[0].data == b"approved-media"
    assert request.hashtags == ("#label",)
    assert "PRIVATE_APPROVED_COPY" not in repr(request)
    assert "approved-media" not in repr(request.media[0])
    assert context.destination_identity not in repr(request)
    with pytest.raises(FrozenInstanceError):
        request.caption = "changed"
    retry = publication_request(context, replace(attempt, id=uuid4(), number=2))
    assert retry.idempotency_key == request.idempotency_key
    assert retry.attempt.id != request.attempt.id
    with pytest.raises(AdapterContractError):
        publication_request(context, replace(attempt, workspace_id=uuid4()))


def test_registry_exact_resolution_and_no_fallback_or_mutable_configuration():
    first, second = FakePublishingAdapter(), FakePublishingAdapter()
    entries = {"test_platform": first, "another": second}
    registry = ProviderRegistry(entries)
    entries["test_platform"] = second
    assert registry.resolve("test_platform") is first
    assert registry.resolve("another") is second
    for provider in ("unknown", "Test_Platform", " test_platform", "", None):
        with pytest.raises(ProviderResolutionError, match="^unsupported_provider$"):
            registry.resolve(provider)
    with pytest.raises(ProviderResolutionError):
        ProviderRegistry({"INVALID": first})
    with pytest.raises(ProviderResolutionError):
        ProviderRegistry().resolve("youtube")


@pytest.mark.parametrize(
    "outcome,normalized,reason",
    [
        (Outcome.published, "published", None),
        (Outcome.accepted, "unknown", "outcome_unknown"),
        (Outcome.ambiguous, "unknown", "outcome_unknown"),
        (Outcome.retryable_failure, "retryable_failure", "temporary_unavailability"),
        (Outcome.permanent_failure, "permanent_failure", "invalid_content"),
        (Outcome.authorization_required, "retryable_failure", "authorization_required"),
        (Outcome.rate_limited, "retryable_failure", "rate_limited"),
        (Outcome.unsupported, "permanent_failure", "destination_unavailable"),
    ],
)
def test_normalized_evidence_is_bound_by_core(outcome, normalized, reason):
    context, attempt = context_and_attempt()
    evidence = result_evidence(publication_request(context, attempt), result(outcome))
    assert evidence.outcome == normalized
    assert evidence.reason == reason
    assert evidence.workspace_id == context.workspace_id
    assert evidence.publication_id == context.publication_id
    assert evidence.destination_id == context.destination_id
    assert evidence.attempt_id == attempt.id


@pytest.mark.parametrize(
    "values",
    [
        {"outcome": "published", "external_post_id": "post"},
        {"outcome": Outcome.published},
        {"outcome": Outcome.published, "external_post_id": "\nsecret"},
        {"outcome": Outcome.published, "external_post_id": "x" * 513},
        {"outcome": Outcome.accepted, "external_post_id": "not-a-final-post"},
        {"outcome": Outcome.retryable_failure},
        {"outcome": Outcome.authorization_required},
        {"outcome": Outcome.rate_limited, "confirmed_absent": 1},
        {"outcome": Outcome.ambiguous, "confirmed_absent": True},
        {"outcome": Outcome.ambiguous, "retry_after_seconds": 1},
        {
            "outcome": Outcome.rate_limited,
            "confirmed_absent": True,
            "retry_after_seconds": -1,
        },
        {
            "outcome": Outcome.rate_limited,
            "confirmed_absent": True,
            "retry_after_seconds": True,
        },
    ],
)
def test_malformed_results_rejected(values):
    with pytest.raises(AdapterContractError, match="^invalid_adapter_result$"):
        ProviderResult(**values)


def test_boundary_revalidates_instances_and_preflight_cannot_claim_publication():
    malformed = result(Outcome.published)
    object.__setattr__(malformed, "external_post_id", None)
    for value in (malformed, {}, None, "SECRET_RESPONSE"):
        with pytest.raises(AdapterContractError):
            validate_result(value)
    for outcome in (Outcome.published, Outcome.accepted, Outcome.ambiguous):
        with pytest.raises(AdapterContractError):
            validate_preflight(result(outcome))
    assert validate_preflight(None) is None


@pytest.fixture
def sessions(persistence_sessions):  # noqa: F811
    return persistence_sessions


@pytest.fixture
def database_test_engine():
    # Overrides the shared fixture: this suite never requires a network database.
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    yield engine
    asyncio.run(engine.dispose())


async def setup_delivery(sessions, monkeypatch):
    async with sessions.begin() as session:
        repo, _, accepted = await seed(session, persist=False)
        row = await repo.create(
            accepted,
            created_at=datetime.now(UTC),
            destination_identity="a" * 64,
        )
        scope, identifier = row.workspace_id, row.id

    async def prepared(self, repository, publication_id, **kwargs):
        row = await PublicationRepository(
            repository.session, repository.workspace_id
        ).get(publication_id, lock=True)
        states = (
            ("pending", "retryable_failure", "permanent_failure")
            if kwargs.get("allow_terminal")
            else ("pending", "retryable_failure")
        )
        if row is None or row.status not in states:
            raise DeliveryIneligible("publication_not_executable")
        return DeliveryContext(
            workspace_id=row.workspace_id,
            publication_id=row.id,
            scheduling_job_id=row.scheduling_job_id,
            destination_id=row.social_account_connection_id,
            provider=row.provider,
            destination_identity=row.destination_identity,
            canonical_envelope=row.canonical_envelope,
            transition_version=row.transition_version,
        )

    monkeypatch.setattr(DeliveryOrchestrator, "prepare_execution", prepared)
    return scope, identifier


async def stored(sessions, scope, identifier):
    async with sessions.begin() as session:
        return await PublicationRepository(session, scope).get(identifier)


@pytest.mark.parametrize("outcome", list(Outcome))
def test_orchestrator_persists_normalized_results(sessions, monkeypatch, outcome):
    async def run():
        scope, identifier = await setup_delivery(sessions, monkeypatch)
        adapter = FakePublishingAdapter(result(outcome))
        delivery = await DeliveryOrchestrator().execute(
            sessions,
            workspace_id=scope,
            publication_id=identifier,
            registry=ProviderRegistry({"instagram": adapter}),
        )
        row = await stored(sessions, scope, identifier)
        assert row.status == delivery.status
        assert (
            row.status
            == {
                Outcome.published: "published",
                Outcome.accepted: "manual_action_required",
                Outcome.ambiguous: "manual_action_required",
                Outcome.retryable_failure: "retryable_failure",
                Outcome.rate_limited: "retryable_failure",
                Outcome.permanent_failure: "permanent_failure",
                Outcome.authorization_required: "retryable_failure",
                Outcome.unsupported: "permanent_failure",
            }[outcome]
        )
        assert len(row.attempts) == 1 and len(row.transitions) == 2
        assert len(adapter.publications) == 1
        assert delivery.reason_code == outcome.value

    asyncio.run(run())


@pytest.mark.parametrize("malformed", [None, {}, "SECRET", RuntimeError("SECRET")])
def test_invalid_adapter_output_and_exceptions_block_retry(
    sessions, monkeypatch, caplog, malformed
):
    async def run():
        scope, identifier = await setup_delivery(sessions, monkeypatch)
        adapter = FakePublishingAdapter(malformed)
        kwargs = dict(
            workspace_id=scope,
            publication_id=identifier,
            registry=ProviderRegistry({"instagram": adapter}),
        )
        service = DeliveryOrchestrator()
        assert (
            await service.execute(sessions, **kwargs)
        ).status == "manual_action_required"
        with pytest.raises(DeliveryIneligible):
            await service.execute(sessions, **kwargs)
        row = await stored(sessions, scope, identifier)
        assert row.transitions[-1].source == "execution_interrupted"
        assert len(adapter.publications) == 1

    asyncio.run(run())
    assert "SECRET" not in caplog.text


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("missing", "unsupported"),
        ("disabled", "unsupported"),
        ("rejected", "permanent_failure"),
        ("invalid", "retryable_failure"),
        ("exception", "retryable_failure"),
    ],
)
def test_resolution_and_preflight_persist_without_provider_io(
    sessions, monkeypatch, mode, reason
):
    async def run():
        scope, identifier = await setup_delivery(sessions, monkeypatch)
        adapter = FakePublishingAdapter(
            publish=mode != "disabled",
            rejection={
                "rejected": result(Outcome.permanent_failure),
                "invalid": {"raw": "SECRET"},
                "exception": RuntimeError("SECRET"),
            }.get(mode),
        )
        delivery = await DeliveryOrchestrator().execute(
            sessions,
            workspace_id=scope,
            publication_id=identifier,
            registry=ProviderRegistry(
                {} if mode == "missing" else {"instagram": adapter}
            ),
        )
        assert delivery.reason_code == reason
        row = await stored(sessions, scope, identifier)
        if mode in {"missing", "disabled"}:
            assert row.status == "permanent_failure"
            assert row.failure_category == "unsupported_operation"
            assert len(row.attempts) == 1 and len(row.transitions) == 2
        else:
            assert len(row.attempts) == 1 and len(row.transitions) == 2
            assert row.retry_disposition == (
                "permanent" if mode == "rejected" else "manual_action"
            )
        assert not adapter.publications

    asyncio.run(run())


def test_accepted_reconciles_same_attempt_and_does_not_validate_or_publish_again(
    sessions, monkeypatch
):
    async def run():
        scope, identifier = await setup_delivery(sessions, monkeypatch)
        adapter = FakePublishingAdapter(
            result(Outcome.accepted),
            result(Outcome.accepted),
            result(Outcome.published),
        )
        kwargs = dict(
            workspace_id=scope,
            publication_id=identifier,
            registry=ProviderRegistry({"instagram": adapter}),
        )
        service = DeliveryOrchestrator()
        assert (await service.execute(sessions, **kwargs)).reason_code == "accepted"
        assert (
            await service.reconcile(sessions, **kwargs)
        ).status == "manual_action_required"
        assert (await service.reconcile(sessions, **kwargs)).status == "published"
        assert adapter.observations == adapter.publications * 2
        assert len(adapter.validations) == len(adapter.publications) == 1
        row = await stored(sessions, scope, identifier)
        assert len(row.attempts) == 1 and len(row.transitions) == 3
        assert row.transitions[-1].source == "reconciliation"
        with pytest.raises(DeliveryIneligible):
            await service.reconcile(sessions, **kwargs)
        with pytest.raises(DeliveryIneligible, match="publication_missing"):
            await service.reconcile(sessions, **{**kwargs, "workspace_id": uuid4()})

    asyncio.run(run())


@pytest.mark.parametrize(
    "mode", ["capability", "result", "malformed", "exception", "unknown"]
)
def test_unavailable_or_uncertain_reconciliation_cannot_authorize_retry(
    sessions, monkeypatch, mode
):
    async def run():
        scope, identifier = await setup_delivery(sessions, monkeypatch)
        adapter = FakePublishingAdapter(
            result(Outcome.ambiguous),
            {
                "result": result(Outcome.unsupported),
                "malformed": {},
                "exception": RuntimeError("SECRET"),
            }.get(mode),
            reconcile=mode != "capability",
        )
        kwargs = dict(
            workspace_id=scope,
            publication_id=identifier,
            registry=ProviderRegistry({"instagram": adapter}),
        )
        service = DeliveryOrchestrator()
        await service.execute(sessions, **kwargs)
        if mode == "unknown":
            kwargs["registry"] = ProviderRegistry()
        delivery = await service.reconcile(sessions, **kwargs)
        assert delivery.status == "manual_action_required"
        row = await stored(sessions, scope, identifier)
        assert len(row.attempts) == 1 and len(row.transitions) == 2
        assert len(adapter.publications) == 1

    asyncio.run(run())


def test_rate_limit_hint_and_reconciled_nonpublication_allow_only_explicit_retry(
    sessions, monkeypatch
):
    async def run():
        scope, identifier = await setup_delivery(sessions, monkeypatch)
        adapter = FakePublishingAdapter(
            result(Outcome.ambiguous),
            result(Outcome.rate_limited, retry_after_seconds=60),
            result(Outcome.published),
        )
        kwargs = dict(
            workspace_id=scope,
            publication_id=identifier,
            registry=ProviderRegistry({"instagram": adapter}),
        )
        service = DeliveryOrchestrator()
        await service.execute(sessions, **kwargs)
        delivery = await service.reconcile(sessions, **kwargs)
        row = await stored(sessions, scope, identifier)
        service.clock = lambda: row.next_retry_at
        assert delivery.retry_after_seconds == 60
        assert delivery.status == "retryable_failure"
        assert len(adapter.publications) == 1
        assert (
            await service.execute(
                sessions, **kwargs, execution_id=uuid4(), expected_version=3
            )
        ).status == "published"
        first, retry = adapter.publications
        assert first.idempotency_key == retry.idempotency_key
        assert first.attempt.id != retry.attempt.id

    asyncio.run(run())


def test_capabilities_reject_non_booleans():
    with pytest.raises(AdapterContractError):
        ProviderCapabilities(publish="yes")


def test_reconciliation_cannot_check_absence_during_an_active_publish(
    sessions, monkeypatch
):
    async def run():
        scope, identifier = await setup_delivery(sessions, monkeypatch)
        service = DeliveryOrchestrator()

        class InFlightAdapter(FakePublishingAdapter):
            async def publish(self, request):
                with pytest.raises(DeliveryIneligible, match="not_reconcilable"):
                    await service.reconcile(sessions, **kwargs)
                return await super().publish(request)

        adapter = InFlightAdapter(result(Outcome.published))
        kwargs = dict(
            workspace_id=scope,
            publication_id=identifier,
            registry=ProviderRegistry({"instagram": adapter}),
        )
        with pytest.raises(DeliveryIneligible, match="not_reconcilable"):
            await service.reconcile(sessions, **kwargs)
        assert (await service.execute(sessions, **kwargs)).status == "published"
        assert not adapter.observations

    asyncio.run(run())


def test_stale_reconciliation_cannot_overwrite_new_evidence(sessions, monkeypatch):
    async def run():
        scope, identifier = await setup_delivery(sessions, monkeypatch)
        service = DeliveryOrchestrator()

        class RacingAdapter(FakePublishingAdapter):
            async def reconcile(self, request):
                # Simulate another authoritative observer winning the result commit.
                await service.record_evidence(
                    sessions,
                    workspace_id=scope,
                    publication_id=identifier,
                    expected_version=2,
                    evidence=result_evidence(
                        request,
                        result(Outcome.published),
                        source=domain.EvidenceSource.reconciliation,
                    ),
                )
                return result(Outcome.retryable_failure)

        adapter = RacingAdapter(result(Outcome.ambiguous))
        kwargs = dict(
            workspace_id=scope,
            publication_id=identifier,
            registry=ProviderRegistry({"instagram": adapter}),
        )
        await service.execute(sessions, **kwargs)
        with pytest.raises(PublicationConflict):
            await service.reconcile(sessions, **kwargs)
        row = await stored(sessions, scope, identifier)
        assert row.status == "published" and len(row.attempts) == 1
        assert len(adapter.publications) == 1

    asyncio.run(run())
