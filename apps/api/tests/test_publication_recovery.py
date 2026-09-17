"""Stage 10: real persistence/RBAC, source preparation covered on PostgreSQL."""

import asyncio
import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from labelos_database.capabilities import Capability
from labelos_database.models import (
    Organization,
    PublicationAction,
    PublicationAttempt,
    RealtimeEvent,
)
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError

from fake_publishing_provider import FakePublishingAdapter
from labelos_api.auth import get_current_user_context, get_session
from labelos_api.main import create_app
from labelos_api.publishing.providers import ProviderOutcome as Outcome
from labelos_api.publishing.providers import ProviderRegistry
from labelos_api.publishing.recovery import resolution
from labelos_api.publishing.retries import MAX_ELAPSED, FailureCategory
from labelos_api.repositories.publishing import (
    PublicationConflict,
    PublicationRepository,
)
from labelos_api.scheduling.payload import canonical_json, fingerprint
from labelos_api.services.delivery_orchestrator import (
    DeliveryIneligible,
    DeliveryOrchestrator,
)
from labelos_api.services.publication_recovery import PublicationRecoveryService
from test_approval_service import _agent_actor, _seed_actor
from test_publishing_persistence import seed as seed_publication
from test_publishing_persistence import sessions as sessions  # noqa: F401
from test_publishing_providers import result, setup_delivery, stored


@pytest.fixture
def recovery_api(sessions, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")

    async def seed():
        scope, identifier = await setup_delivery(sessions, monkeypatch)
        async with sessions.begin() as session:
            workspace = await session.get(Organization, scope)
            actor, _ = await _seed_actor(
                session,
                workspace=workspace,
                email=f"{uuid4()}@test.com",
                capabilities=(
                    Capability.marketing_content_view.value,
                    Capability.marketing_content_schedule.value,
                ),
            )
            viewer, _ = await _seed_actor(
                session,
                workspace=workspace,
                email=f"{uuid4()}@test.com",
                capabilities=(Capability.marketing_content_view.value,),
            )
        return scope, identifier, actor, viewer

    scope, identifier, actor, viewer = asyncio.run(seed())
    state = {"actor": actor}
    app = create_app()

    async def session_override():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user_context] = lambda: state["actor"]
    with TestClient(app) as client:
        yield client, state, scope, identifier, actor, viewer


def fail(
    sessions, scope, identifier, outcome=Outcome.authorization_required, category=None
):
    adapter = FakePublishingAdapter(
        result(outcome, **({"failure_category": category} if category else {}))
    )
    asyncio.run(
        DeliveryOrchestrator().execute(
            sessions,
            workspace_id=scope,
            publication_id=identifier,
            registry=ProviderRegistry({"instagram": adapter}),
        )
    )


def command(client, scope, identifier, operation, action_version=0, **extra):
    return client.post(
        f"/api/v1/workspaces/{scope}/publications/{identifier}/{operation}",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "expected_version": 2,
            "expected_action_version": action_version,
            **extra,
        },
    )


def test_manual_completion_receipt_history_and_secret_free_handoff(
    recovery_api, sessions
):
    client, _, scope, identifier, actor, _ = recovery_api
    fail(sessions, scope, identifier)
    base = f"/api/v1/workspaces/{scope}/publications/{identifier}"
    read = client.get(base)
    assert read.status_code == 200
    data = read.json()
    assert data["resolution"] == "reconnect_required"
    assert (
        set(data["asset_refs"][0]) == {"sha256", "size_bytes", "media_type"}
        if data["asset_refs"]
        else True
    )
    assert all(
        secret not in read.text
        for secret in (
            "credential_ref",
            "access_token",
            "content_base64",
            '"destination_identity":',
        )
    )
    assert (
        command(
            client, scope, identifier, "manual/complete", delivery_confirmed=True
        ).status_code
        == 409
    )
    assert command(client, scope, identifier, "manual/start").status_code == 200
    key = str(uuid4())
    payload = {
        "expected_version": 2,
        "expected_action_version": 1,
        "delivery_confirmed": True,
        "external_post_id": "manual-post",
        "provider_url": "https://www.instagram.com/p/manual-post/",
    }
    response = client.post(
        base + "/manual/complete", headers={"Idempotency-Key": key}, json=payload
    )
    assert response.status_code == 200, response.text
    assert response.json()["resolution"] == "manually_completed"
    assert response.json()["delivery_status"] == "retryable_failure"
    assert response.json()["actions"][-1]["actor_id"] == str(actor.id)
    assert (
        client.post(
            base + "/manual/complete", headers={"Idempotency-Key": key}, json=payload
        ).status_code
        == 200
    )
    assert (
        command(
            client, scope, identifier, "manual/complete", 2, delivery_confirmed=True
        ).status_code
        == 409
    )
    assert command(client, scope, identifier, "recover", 2).status_code == 409

    async def verify():
        row = await stored(sessions, scope, identifier)
        assert len(row.attempts) == 1 and len(row.transitions) == 2
        assert row.attempts[0].outcome == "retryable_failure"
        assert len(row.actions) == 2

        def downgrade(connection):
            scripts = ScriptDirectory.from_config(
                Config(
                    str(
                        Path(__file__).resolve().parents[3]
                        / "packages/database/alembic.ini"
                    )
                )
            )
            with (
                Operations.context(MigrationContext.configure(connection)),
                pytest.raises(RuntimeError, match="action history exists"),
            ):
                scripts.get_revision("202609170300").module.downgrade()

        async with sessions() as session:
            connection = await session.connection()
            await connection.run_sync(downgrade)
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(RealtimeEvent)
                    .where(RealtimeEvent.operation_id.like("publication-action:%"))
                )
                == 2
            )
        for statement in (
            update(PublicationAction).values(reason_code="changed"),
            delete(PublicationAction),
        ):
            async with sessions.begin() as session:
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.execute(statement)

    asyncio.run(verify())


def test_completion_requires_human_permission_and_workspace(recovery_api, sessions):
    client, state, scope, identifier, actor, viewer = recovery_api
    fail(sessions, scope, identifier)
    assert command(client, scope, identifier, "manual/start").status_code == 200
    for denied in (viewer, _agent_actor(actor)):
        state["actor"] = denied
        assert (
            command(
                client, scope, identifier, "manual/complete", 1, delivery_confirmed=True
            ).status_code
            == 403
        )
        assert command(client, scope, identifier, "recover", 1).status_code == 403
    state["actor"] = actor
    assert (
        command(
            client, uuid4(), identifier, "manual/complete", 1, delivery_confirmed=True
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/workspaces/{uuid4()}/publications/{identifier}"
        ).status_code
        == 404
    )
    assert len(asyncio.run(stored(sessions, scope, identifier)).actions) == 1


@pytest.mark.parametrize(
    "outcome,category,state",
    [
        (Outcome.unsupported, None, "terminal_failure"),
        (
            Outcome.permanent_failure,
            FailureCategory.invalid_content_media,
            "terminal_failure",
        ),
        (
            Outcome.permanent_failure,
            FailureCategory.permanent_rejection,
            "terminal_failure",
        ),
        (
            Outcome.retryable_failure,
            FailureCategory.internal_failure,
            "human_intervention_required",
        ),
        (Outcome.ambiguous, None, "reconciliation_required"),
    ],
)
def test_failure_workflow_classification(
    recovery_api, sessions, outcome, category, state
):
    client, _, scope, identifier, _, _ = recovery_api
    fail(sessions, scope, identifier, outcome, category)
    data = client.get(f"/api/v1/workspaces/{scope}/publications/{identifier}").json()
    assert data["resolution"] == state
    response = command(client, scope, identifier, "manual/start")
    assert response.status_code == (
        409 if outcome == Outcome.ambiguous else 200
    ), response.text


@pytest.mark.parametrize(
    "link",
    [
        "https://user:secret@example.com/post",
        "https://example.com/post?token=secret",
        "http://example.com/post",
        "javascript:alert(1)",
    ],
)
def test_completion_rejects_credential_bearing_or_unsafe_links(
    recovery_api, sessions, link
):
    client, _, scope, identifier, _, _ = recovery_api
    fail(sessions, scope, identifier)
    assert command(client, scope, identifier, "manual/start").status_code == 200
    assert (
        command(
            client,
            scope,
            identifier,
            "manual/complete",
            1,
            delivery_confirmed=True,
            provider_url=link,
        ).status_code
        == 409
    )


def test_recovery_uses_original_budget_and_consumes_grant_once(recovery_api, sessions):
    client, _, scope, identifier, _, _ = recovery_api
    fail(sessions, scope, identifier)
    assert command(client, scope, identifier, "recover").status_code == 200
    response = command(client, scope, identifier, "recover", 1)
    assert response.status_code == 409

    async def run():
        row = await stored(sessions, scope, identifier)
        assert row.actions[0].retry_until == row.attempts[0].started_at + MAX_ELAPSED
        adapter = FakePublishingAdapter(result(Outcome.published))
        delivered = await DeliveryOrchestrator().retry_due(
            sessions,
            workspace_id=scope,
            registry=ProviderRegistry({"instagram": adapter}),
        )
        assert len(delivered) == 1 and delivered[0].status == "published"
        row = await stored(sessions, scope, identifier)
        assert len(row.attempts) == 2 and row.attempts[0].outcome == "retryable_failure"
        assert len(row.actions) == 1 and len(row.transitions) == 4

    asyncio.run(run())


def test_retry_exhaustion_and_expired_recovery_cannot_reset_budget(
    recovery_api, sessions
):
    _, _, scope, identifier, actor, _ = recovery_api

    async def run():
        now = datetime.now(UTC)
        adapter = FakePublishingAdapter(
            *[result(Outcome.retryable_failure) for _ in range(5)]
        )
        registry = ProviderRegistry({"instagram": adapter})
        for number in range(5):
            await DeliveryOrchestrator(clock=lambda now=now: now).execute(
                sessions,
                workspace_id=scope,
                publication_id=identifier,
                registry=registry,
                execution_id=uuid4(),
                expected_version=number * 2,
            )
            row = await stored(sessions, scope, identifier)
            now = row.next_retry_at or now
        assert resolution(row, now) == "retry_exhausted"
        async with sessions.begin() as session:
            service = PublicationRecoveryService(
                session, scope, actor=actor, clock=lambda: now
            )
            with pytest.raises(PublicationConflict, match="failure_not_remediable"):
                await service.command(
                    identifier,
                    operation="authorize_retry",
                    operation_id=uuid4(),
                    expected_version=10,
                    expected_action_version=0,
                )
            row = await service.command(
                identifier,
                operation="begin_manual",
                operation_id=uuid4(),
                expected_version=10,
                expected_action_version=0,
            )
            assert resolution(row, now) == "manual_publishing"
        assert len(row.attempts) == 5

    asyncio.run(run())


def test_manual_reservation_blocks_due_worker_and_direct_attempt_insert(
    recovery_api, sessions
):
    client, _, scope, identifier, _, _ = recovery_api
    fail(sessions, scope, identifier, Outcome.retryable_failure)
    assert command(client, scope, identifier, "manual/start").status_code == 200

    async def run():
        row = await stored(sessions, scope, identifier)
        now = row.next_retry_at + timedelta(seconds=1)
        assert not await DeliveryOrchestrator(clock=lambda: now).retry_due(
            sessions, workspace_id=scope, registry=ProviderRegistry()
        )
        with pytest.raises(DeliveryIneligible, match="manual_delivery_reserved"):
            await DeliveryOrchestrator(clock=lambda now=now: now).execute(
                sessions,
                workspace_id=scope,
                publication_id=identifier,
                expected_version=2,
                execution_id=uuid4(),
            )
        async with sessions.begin() as session:
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    session.add(
                        PublicationAttempt(
                            workspace_id=scope,
                            publication_id=identifier,
                            number=2,
                            execution_id=uuid4(),
                            started_at=now,
                        )
                    )
                    await session.flush()
        async with sessions() as session:
            assert not await PublicationRepository(session, scope).due_retries(now=now)

    asyncio.run(run())


def test_expired_remediation_never_replenishes_retry_budget(recovery_api, sessions):
    _, _, scope, identifier, actor, _ = recovery_api
    fail(sessions, scope, identifier)

    async def run():
        row = await stored(sessions, scope, identifier)
        deadline = row.attempts[0].started_at + MAX_ELAPSED
        async with sessions.begin() as session:
            service = PublicationRecoveryService(
                session, scope, actor=actor, clock=lambda: deadline
            )
            assert (await service.handoff(row))["resolution"] == "retry_exhausted"
            with pytest.raises(PublicationConflict, match="retry_budget_exhausted"):
                await service.command(
                    identifier,
                    operation="authorize_retry",
                    operation_id=uuid4(),
                    expected_version=2,
                    expected_action_version=0,
                )
        async with sessions.begin() as session:
            await PublicationRecoveryService(session, scope, actor=actor).command(
                identifier,
                operation="authorize_retry",
                operation_id=uuid4(),
                expected_version=2,
                expected_action_version=0,
            )
        async with sessions() as session:
            assert not await PublicationRepository(session, scope).due_retries(
                now=deadline
            )
        row = await stored(sessions, scope, identifier)
        with pytest.raises(PublicationConflict):
            PublicationRepository.require_retry_eligible(row, deadline)
        assert len(row.attempts) == 1

    asyncio.run(run())


def test_existing_foreign_publication_is_not_accessible(
    recovery_api, sessions, monkeypatch
):
    client, _, scope, _, _, _ = recovery_api
    foreign_scope, foreign_id = asyncio.run(setup_delivery(sessions, monkeypatch))
    fail(sessions, foreign_scope, foreign_id)
    assert (
        client.get(f"/api/v1/workspaces/{scope}/publications/{foreign_id}").status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/workspaces/{foreign_scope}/publications/{foreign_id}"
        ).status_code
        == 404
    )
    assert (
        command(
            client, scope, foreign_id, "manual/complete", delivery_confirmed=True
        ).status_code
        == 404
    )
    assert (
        command(
            client,
            foreign_scope,
            foreign_id,
            "manual/complete",
            delivery_confirmed=True,
        ).status_code
        == 404
    )


def test_manual_completion_allows_unknown_external_identifier(recovery_api, sessions):
    client, _, scope, identifier, _, _ = recovery_api
    fail(sessions, scope, identifier)
    assert command(client, scope, identifier, "manual/start").status_code == 200
    assert command(client, scope, identifier, "recover", 1).status_code == 409
    response = command(
        client, scope, identifier, "manual/complete", 1, delivery_confirmed=True
    )
    assert response.status_code == 200
    assert response.json()["external_post_id"] is None
    assert response.json()["completion_source"] == "human"


def test_prepared_asset_download_is_bound_to_publication_and_workspace(
    recovery_api, sessions
):
    client, state, original_scope, _, _, _ = recovery_api
    data = b"approved-video-data"
    digest = hashlib.sha256(data).hexdigest()

    async def prepare():
        async with sessions.begin() as session:
            repo, _, request = await seed_publication(session, persist=False)
            payload = json.loads(request.canonical_payload)
            payload["asset_refs"] = [
                {
                    "sha256": digest,
                    "size_bytes": len(data),
                    "media_type": "video/mp4",
                    "content_base64": base64.b64encode(data).decode(),
                }
            ]
            request = replace(request, canonical_payload=canonical_json(payload))
            request = replace(request, payload_fingerprint=fingerprint(request))
            row = await repo.create(request, created_at=datetime.now(UTC))
            workspace = await session.get(Organization, repo.workspace_id)
            actor, _ = await _seed_actor(
                session,
                workspace=workspace,
                email=f"{uuid4()}@test.com",
                capabilities=(Capability.marketing_content_view.value,),
            )
            return row.workspace_id, row.id, actor

    scope, identifier, actor = asyncio.run(prepare())
    state["actor"] = actor
    base = f"/api/v1/workspaces/{scope}/publications/{identifier}"
    read = client.get(base)
    assert read.status_code == 200
    assert read.json()["asset_refs"] == [
        {"sha256": digest, "size_bytes": len(data), "media_type": "video/mp4"}
    ]
    assert "content_base64" not in read.text
    response = client.get(base + f"/assets/{digest}")
    assert response.status_code == 200 and response.content == data
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["cache-control"] == "private, no-store"
    assert client.get(base + "/assets/unknown").status_code == 404
    assert (
        client.get(
            f"/api/v1/workspaces/{original_scope}/publications/{identifier}/assets/{digest}"
        ).status_code
        == 404
    )
