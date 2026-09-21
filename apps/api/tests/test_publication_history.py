"""Stage 11: authorized, safe publication and chronological attempt projections."""

import asyncio
from uuid import uuid4

import pytest
from labelos_database.capabilities import Capability
from labelos_database.models import OrganizationMembership
from sqlalchemy import update

from fake_publishing_provider import FakePublishingAdapter
from labelos_api.publishing.providers import ProviderOutcome, ProviderRegistry
from labelos_api.services import marketing_content_service as content
from labelos_api.services.delivery_orchestrator import DeliveryOrchestrator
from test_publication_recovery import command, fail
from test_publication_recovery import recovery_api as recovery_api  # noqa: F401
from test_publishing_persistence import sessions as sessions  # noqa: F401
from test_publishing_providers import result, setup_delivery, stored


def assert_summary_matches_detail(client, scope, detail):
    page = client.get(
        f"/api/v1/workspaces/{scope}/publications",
        params={"content_item_id": detail["content_item_id"]},
    )
    assert page.status_code == 200
    summary = next(
        row for row in page.json()["publications"] if row["id"] == detail["id"]
    )
    assert all(value == detail[key] for key, value in summary.items())


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
    summary = page.json()["publications"][0]
    assert page.json()["next_after_id"] is None
    assert "attempts" not in summary and "asset_refs" not in summary
    for key, value in summary.items():
        assert value == data[key]
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
    assert_summary_matches_detail(client, scope, failed)
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
    recovered = command(client, scope, identifier, "recover")
    assert recovered.status_code == 200
    assert_summary_matches_detail(client, scope, recovered.json())

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
    assert_summary_matches_detail(client, scope, published)
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
    reserved = command(client, scope, identifier, "manual/start")
    assert reserved.status_code == 200
    assert_summary_matches_detail(client, scope, reserved.json())
    completed = command(
        client, scope, identifier, "manual/complete", 1, delivery_confirmed=True
    ).json()
    assert completed["manual_completed_at"] is not None
    assert completed["published_at"] is None
    assert completed["delivery_status"] == "retryable_failure"
    assert completed["resolution"] == "manually_completed"
    assert completed["attempt_count"] == 1
    assert completed["attempts"][0]["outcome"] == "retryable_failure"
    assert_summary_matches_detail(client, scope, completed)


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


def test_history_list_rechecks_revoked_membership(recovery_api, sessions):
    client, state, scope, identifier, _, viewer = recovery_api
    row = asyncio.run(stored(sessions, scope, identifier))
    state["actor"] = viewer

    async def revoke():
        async with sessions.begin() as session:
            await session.execute(
                update(OrganizationMembership)
                .where(
                    OrganizationMembership.organization_id == scope,
                    OrganizationMembership.user_id == viewer.id,
                )
                .values(capability_permissions=[])
            )

    asyncio.run(revoke())
    assert (
        client.get(
            f"/api/v1/workspaces/{scope}/publications",
            params={"content_item_id": str(row.marketing_content_item_id)},
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "outcome",
    [
        ProviderOutcome.accepted,
        ProviderOutcome.unsupported,
        ProviderOutcome.rate_limited,
    ],
)
def test_history_unknown_permanent_and_retry_summaries(recovery_api, sessions, outcome):
    client, _, scope, identifier, _, _ = recovery_api
    fail(sessions, scope, identifier, outcome=outcome)
    detail = client.get(f"/api/v1/workspaces/{scope}/publications/{identifier}").json()
    assert_summary_matches_detail(client, scope, detail)


@pytest.mark.parametrize(
    "denied", [Capability.marketing_content_view, Capability.marketing_content_schedule]
)
def test_history_preserves_campaign_authorization(
    recovery_api, sessions, monkeypatch, denied
):
    client, _, scope, identifier, _, _ = recovery_api
    row = asyncio.run(stored(sessions, scope, identifier))
    original = content._require_capability
    campaigns = []

    async def require(session, **kwargs):
        if kwargs.get("campaign_id") and kwargs["capability"] == denied:
            campaigns.append(kwargs["campaign_id"])
            raise content.MarketingContentAuthorizationError("missing_capability")
        await original(session, **kwargs)

    monkeypatch.setattr(content, "_require_capability", require)
    response = client.get(
        f"/api/v1/workspaces/{scope}/publications",
        params={"content_item_id": str(row.marketing_content_item_id)},
    )
    assert len(campaigns) == 1
    if denied == Capability.marketing_content_view:
        assert response.status_code == 403
    else:
        assert response.status_code == 200
        assert response.json()["publications"][0]["can_manage_recovery"] is False
