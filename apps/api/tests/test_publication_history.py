"""Stage 11: authorized, safe publication and chronological attempt projections."""

import asyncio
from uuid import uuid4

from fake_publishing_provider import FakePublishingAdapter
from labelos_api.publishing.providers import ProviderOutcome, ProviderRegistry
from labelos_api.services.delivery_orchestrator import DeliveryOrchestrator
from test_publication_recovery import command, fail
from test_publication_recovery import recovery_api as recovery_api  # noqa: F401
from test_publishing_persistence import sessions as sessions  # noqa: F401
from test_publishing_providers import result, setup_delivery, stored


def test_pending_history_and_view_only_access(recovery_api, sessions):
    client, state, scope, identifier, _, viewer = recovery_api
    state["actor"] = viewer
    base = f"/api/v1/workspaces/{scope}/publications"
    response = client.get(f"{base}/{identifier}")
    assert response.status_code == 200
    data = response.json()
    assert data["can_manage_recovery"] is False
    assert data["can_manage_account"] is False
    assert data["delivery_status"] == "pending"
    assert data["attempt_count"] == 0
    assert data["attempts"] == []
    assert data["started_at"] is None
    assert data["published_at"] is None
    assert data["last_failed_at"] is None
    assert data["latest_failure_reason"] is None
    assert data["origin"] == "scheduled"
    row = asyncio.run(stored(sessions, scope, identifier))
    assert data["scheduling_job_id"] == str(row.scheduling_job_id)
    assert data["channel_id"] == str(row.marketing_content_item_channel_id)
    page = client.get(
        base, params={"content_item_id": data["content_item_id"], "limit": 1}
    )
    assert page.status_code == 200
    assert page.json() == {"publications": [data], "next_after_id": None}
    exhausted = client.get(
        base,
        params={
            "content_item_id": data["content_item_id"],
            "after_id": str(identifier),
        },
    )
    assert exhausted.json() == {"publications": [], "next_after_id": None}


def test_failure_then_success_preserves_attempt_history(recovery_api, sessions):
    client, _, scope, identifier, _, _ = recovery_api
    fail(sessions, scope, identifier)
    base = f"/api/v1/workspaces/{scope}/publications/{identifier}"
    failed = client.get(base).json()
    assert failed["can_manage_recovery"] is True
    assert failed["can_manage_account"] is False
    assert failed["destination_connection_method"] is None
    assert failed["destination_connection_status"] is None
    assert failed["attempt_count"] == 1
    assert failed["resolution"] == "reconnect_required"
    assert failed["latest_failure_reason"] == "authorization_required"
    first = failed["attempts"][0]
    assert first["number"] == 1
    assert first["started_at"] == failed["started_at"]
    assert first["completed_at"] == failed["last_failed_at"]
    assert first["outcome"] == "retryable_failure"
    assert set(first) == {
        "id",
        "number",
        "started_at",
        "completed_at",
        "outcome",
        "failure_reason",
        "external_post_id",
        "observations",
    }
    assert set(first["observations"][0]) == {
        "version",
        "observed_at",
        "outcome",
        "source",
        "failure_reason",
    }
    assert command(client, scope, identifier, "recover").status_code == 200

    async def retry():
        await DeliveryOrchestrator().retry_due(
            sessions,
            workspace_id=scope,
            registry=ProviderRegistry(
                {"instagram": FakePublishingAdapter(result(ProviderOutcome.published))}
            ),
        )

    asyncio.run(retry())
    response = client.get(base)
    published = response.json()
    assert published["delivery_status"] == "published"
    assert published["completion_source"] == "provider"
    assert published["published_at"] is not None
    assert published["external_post_id"] is not None
    assert published["attempt_count"] == 2
    assert [a["number"] for a in published["attempts"]] == [1, 2]
    assert published["attempts"][0] == first
    assert published["attempts"][1]["outcome"] == "published"
    assert published["last_failed_at"] == failed["last_failed_at"]
    for forbidden in (
        "credential_ref",
        "access_token",
        "refresh_token",
        "authorization_header",
        "canonical_envelope",
        "content_base64",
        "execution_id",
        "http_status",
    ):
        assert forbidden not in response.text


def test_manual_completion_does_not_invent_provider_success(recovery_api, sessions):
    client, _, scope, identifier, _, _ = recovery_api
    fail(sessions, scope, identifier)
    assert command(client, scope, identifier, "manual/start").status_code == 200
    completed = command(
        client, scope, identifier, "manual/complete", 1, delivery_confirmed=True
    ).json()
    assert completed["manual_completed_at"] is not None
    assert completed["published_at"] is None
    assert completed["delivery_status"] == "retryable_failure"
    assert completed["resolution"] == "manually_completed"
    assert completed["attempt_count"] == 1
    assert completed["attempts"][0]["outcome"] == "retryable_failure"


def test_history_list_cannot_disclose_other_workspace(
    recovery_api, sessions, monkeypatch
):
    client, _, scope, _, _, _ = recovery_api
    foreign_scope, foreign_id = asyncio.run(setup_delivery(sessions, monkeypatch))
    foreign = asyncio.run(stored(sessions, foreign_scope, foreign_id))
    base = f"/api/v1/workspaces/{scope}/publications"
    assert (
        client.get(
            base, params={"content_item_id": str(foreign.marketing_content_item_id)}
        ).status_code
        == 404
    )
    assert client.get(base, params={"content_item_id": str(uuid4())}).status_code == 404
    assert client.get(base).status_code == 422
