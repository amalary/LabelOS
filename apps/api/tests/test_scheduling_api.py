"""Public scheduling API, real RBAC and PostgreSQL coordination/receipts."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from labelos_database.capabilities import Capability
from labelos_database.models import (
    ApprovalRequest,
    ApprovalRequestStage,
    MarketingContentItem,
    MarketingContentItemChannel,
    OrganizationMembership,
    RealtimeEvent,
    SchedulingJob,
    SchedulingJobTransition,
    SocialAccountConnection,
)
from sqlalchemy import func, select, update

from labelos_api.api.v1.scheduling import scheduling_controls
from labelos_api.auth import get_current_user_context, get_session
from labelos_api.main import create_app
from labelos_api.repositories.scheduling import SchedulingRepository
from labelos_api.scheduling.contracts import SchedulingFeatureControls
from test_approval_service import _agent_actor, _seed_actor
from test_scheduling_activation import ENABLED, prepare
from test_scheduling_repository import sessions as sessions


@pytest.fixture
def scheduling_api(sessions, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")

    async def seed():
        async with sessions.begin() as session:
            workspace, actor, command, activation = await prepare(session)
            await session.execute(
                update(OrganizationMembership)
                .where(OrganizationMembership.user_id == actor.id)
                .values(
                    capability_permissions=[
                        Capability.marketing_content_schedule.value,
                        Capability.marketing_content_view.value,
                    ]
                )
            )
            viewer, _ = await _seed_actor(
                session,
                workspace=workspace,
                email=f"{uuid4()}@test.com",
                capabilities=(Capability.marketing_content_view.value,),
            )
            denied, _ = await _seed_actor(
                session,
                workspace=workspace,
                email=f"{uuid4()}@test.com",
                capabilities=(),
            )
            outside, outsider, foreign_command, _ = await prepare(session)
        return (
            workspace,
            actor,
            viewer,
            denied,
            outside,
            outsider,
            command,
            foreign_command,
            activation,
        )

    (
        workspace,
        actor,
        viewer,
        denied,
        outside,
        outsider,
        command,
        foreign_command,
        activation,
    ) = asyncio.run(seed())
    app = create_app()
    state = {"actor": actor, "controls": ENABLED}

    async def session_override():
        async with sessions() as session:
            yield session

    async def actor_override():
        return state["actor"]

    async def controls_override():
        return state["controls"]

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user_context] = actor_override
    app.dependency_overrides[scheduling_controls] = controls_override
    with TestClient(app) as client:
        yield {
            "client": client,
            "sessions": sessions,
            "state": state,
            "workspace": workspace,
            "actor": actor,
            "viewer": viewer,
            "denied": denied,
            "outside": outside,
            "outsider": outsider,
            "command": command,
            "foreign_command": foreign_command,
            "activation": activation,
            "base": f"/api/v1/workspaces/{workspace.id}",
            "channel": (
                f"/api/v1/workspaces/{workspace.id}"
                f"/marketing-content/{command.content_item_id}"
                f"/channels/{command.channel_id}/scheduling"
            ),
        }


def post(api, path, body=None, key=None):
    return api["client"].post(
        path, json=body or {}, headers={"Idempotency-Key": str(key or uuid4())}
    )


def guards(revision=1, generation=1):
    return {
        "expected_content_revision": revision,
        "expected_schedule_generation": generation,
    }


def activate(api, key=None):
    result = post(api, api["channel"] + "/activate", guards(), key)
    assert result.status_code == 200, result.text
    return result.json()


def job_path(api, job, operation=""):
    return f"{api['base']}/scheduling/jobs/{job['id']}" + (
        f"/{operation}" if operation else ""
    )


def change(api, model, identifier, **values):
    async def run():
        async with api["sessions"].begin() as session:
            await session.execute(
                update(model).where(model.id == identifier).values(**values)
            )

    asyncio.run(run())


def block(api, job, reason="connection_unavailable"):
    async def run():
        async with api["sessions"].begin() as session:
            await SchedulingRepository(
                session, api["workspace"].id, lateness_window_seconds=300
            ).block_job(UUID(job["id"]), reason=reason, actor_key="test-validator")

    asyncio.run(run())


def counts(api):
    async def run():
        async with api["sessions"]() as session:
            return tuple(
                [
                    await session.scalar(select(func.count()).select_from(t))
                    for t in (SchedulingJob, SchedulingJobTransition, RealtimeEvent)
                ]
            )

    return asyncio.run(run())


def assert_reason(response, code):
    assert response.status_code == 409, response.text
    assert code in response.json()["detail"]["reason_codes"]


def test_eligibility_activation_replay_and_safe_response(scheduling_api):
    api = scheduling_api
    response = api["client"].get(api["channel"] + "/eligibility")
    assert response.status_code == 200, response.text
    assert response.json()["eligible"] is True
    assert response.json()["schedule_generation"] == 1
    key = uuid4()
    job = activate(api, key)
    before = counts(api)
    assert activate(api, key) == job
    assert counts(api) == before
    assert job["status"] == "pending"
    assert not (
        {
            "claimed_by",
            "claimed_at",
            "claim_expires_at",
            "fencing_token",
            "idempotency_key",
            "blocked_metadata",
            "handoff_receipt_id",
            "credential_reference",
            "destination",
        }
        & job.keys()
    )
    assert api["client"].get(job_path(api, job)).json() == job
    assert_reason(
        post(api, api["channel"] + "/activate", guards()), "active_job_conflict"
    )
    assert_reason(
        post(api, api["channel"] + "/activate", guards(2), key), "idempotency_conflict"
    )
    assert (
        "active_job_conflict"
        in api["client"].get(api["channel"] + "/eligibility").json()["reason_codes"]
    )


@pytest.mark.parametrize("actor_name", ["viewer", "denied", "outsider", "agent"])
def test_mutation_rbac(scheduling_api, actor_name):
    api = scheduling_api
    job = activate(api)
    api["state"]["actor"] = (
        _agent_actor(api["actor"]) if actor_name == "agent" else api[actor_name]
    )
    before = counts(api)
    for path, body in [
        (api["channel"] + "/activate", guards()),
        (job_path(api, job, "cancel"), {}),
        (job_path(api, job, "revalidate"), {}),
        (job_path(api, job, "replace"), guards()),
    ]:
        assert post(api, path, body).status_code in (403, 404)
    assert counts(api) == before


def test_read_rbac_and_workspace_isolation(scheduling_api):
    api = scheduling_api
    job = activate(api)
    api["state"]["actor"] = api["viewer"]
    assert api["client"].get(job_path(api, job)).status_code == 200
    assert api["client"].get(api["base"] + "/scheduling/jobs").status_code == 200
    assert api["client"].get(api["channel"] + "/eligibility").status_code == 403
    api["state"]["actor"] = api["denied"]
    for suffix in ("", "/blocked-reasons"):
        assert api["client"].get(job_path(api, job) + suffix).status_code == 403
    api["state"]["actor"] = api["outsider"]
    assert api["client"].get(job_path(api, job)).status_code == 404
    api["state"]["actor"] = api["actor"]
    wrong_path = job_path(api, job).replace(
        str(api["workspace"].id), str(api["outside"].id)
    )
    assert api["client"].get(wrong_path).status_code == 404
    assert post(api, wrong_path + "/cancel").status_code == 404
    foreign = api["foreign_command"]
    foreign_path = (
        f"{api['base']}/marketing-content/{foreign.content_item_id}"
        f"/channels/{foreign.channel_id}/scheduling"
    )
    assert api["client"].get(foreign_path + "/eligibility").status_code == 404
    assert post(api, foreign_path + "/activate", guards()).status_code == 404


@pytest.mark.parametrize("state", ["pending", "blocked", "claimed"])
def test_cancel_mutable_jobs_and_replay_with_authoring_disabled(scheduling_api, state):
    api = scheduling_api
    job = activate(api)
    if state == "blocked":
        block(api, job)
    elif state == "claimed":
        # Expired leases must not prevent a human cancellation.
        change(
            api,
            SchedulingJob,
            UUID(job["id"]),
            status="claimed",
            fencing_token=1,
            claimed_by="worker-secret-identity",
            claimed_at=func.clock_timestamp() - timedelta(seconds=60),
            claim_expires_at=func.clock_timestamp() - timedelta(seconds=30),
        )
    api["state"]["controls"] = SchedulingFeatureControls()
    key = uuid4()
    response = post(api, job_path(api, job, "cancel"), key=key)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    before = counts(api)
    assert post(api, job_path(api, job, "cancel"), key=key).json() == response.json()
    assert counts(api) == before
    assert_reason(post(api, job_path(api, job, "cancel")), "invalid_state_transition")
    assert_reason(
        post(api, job_path(api, job, "revalidate"), key=key), "idempotency_conflict"
    )
    assert api["client"].get(job_path(api, job)).status_code == 200


def test_revalidation_requires_resolved_blocker_exact_snapshot_and_replays(
    scheduling_api,
):
    api = scheduling_api
    job = activate(api)
    assert_reason(
        post(api, job_path(api, job, "revalidate")), "invalid_state_transition"
    )
    block(api, job)
    reasons = api["client"].get(job_path(api, job, "blocked-reasons")).json()
    assert reasons["primary_reason"] == "connection_unavailable"
    assert reasons["reason_codes"] == ["connection_unavailable"]
    change(
        api,
        SocialAccountConnection,
        api["activation"].destination_id,
        status="disconnected",
    )
    assert_reason(post(api, job_path(api, job, "revalidate")), "connection_unavailable")
    assert_reason(
        post(api, job_path(api, job, "replace"), guards()),
        "replacement_requires_reapproval",
    )
    change(
        api,
        SocialAccountConnection,
        api["activation"].destination_id,
        status="connected",
    )
    key = uuid4()
    response = post(api, job_path(api, job, "revalidate"), key=key)
    assert response.status_code == 200, response.text
    assert response.json()["scheduled_for"] == job["scheduled_for"]
    assert response.json()["id"] == job["id"]
    assert response.json()["blocked_reason_code"] is None
    before = counts(api)
    api["state"]["controls"] = SchedulingFeatureControls()
    assert post(api, job_path(api, job, "revalidate"), key=key).status_code == 200
    assert counts(api) == before


@pytest.mark.parametrize(
    "drift,reason",
    [
        ("revision", "stale_content_revision"),
        ("generation", "changed_schedule_generation"),
        ("timezone", "changed_schedule_generation"),
        ("approval", "stale_approval"),
    ],
)
def test_revalidate_cannot_repair_snapshot_drift(scheduling_api, drift, reason):
    api = scheduling_api
    job = activate(api)
    block(api, job)
    command = api["command"]
    if drift == "revision":
        change(api, MarketingContentItem, command.content_item_id, content_revision=2)
    elif drift == "approval":
        change(
            api, MarketingContentItem, command.content_item_id, approved_revision=None
        )
    else:
        change(
            api,
            MarketingContentItemChannel,
            command.channel_id,
            **(
                {"schedule_generation": 2}
                if drift == "generation"
                else {"schedule_timezone": "Europe/London"}
            ),
        )
    before = counts(api)
    assert_reason(post(api, job_path(api, job, "revalidate")), reason)
    assert counts(api) == before


def test_replacement_after_cancellation_preserves_lineage(scheduling_api):
    api = scheduling_api
    job = activate(api)
    assert post(api, job_path(api, job, "cancel")).status_code == 200
    assert_reason(
        post(api, api["channel"] + "/activate", guards()), "replacement_required"
    )
    key = uuid4()
    response = post(api, job_path(api, job, "replace"), guards(), key)
    assert response.status_code == 200, response.text
    successor = response.json()
    assert successor["id"] != job["id"]
    assert successor["supersedes_job_id"] == job["id"]
    assert successor["lineage_root_job_id"] == job["id"]
    before = counts(api)
    assert post(api, job_path(api, job, "replace"), guards(), key).json() == successor
    assert counts(api) == before
    assert_reason(
        post(api, job_path(api, job, "replace"), guards(2), key), "idempotency_conflict"
    )


def reapprove(api):
    async def run():
        async with api["sessions"].begin() as session:
            command = api["command"]
            old = await session.get(
                ApprovalRequest, api["activation"].snapshot.approval_request_id
            )
            request = ApprovalRequest(
                title="Reapproved schedule",
                organization_id=api["workspace"].id,
                resource_type="marketing_content_item",
                resource_id=command.content_item_id,
                resource_revision=2,
                requested_by_profile_id=old.requested_by_profile_id,
                status="approved",
            )
            session.add(request)
            await session.flush()
            session.add(
                ApprovalRequestStage(
                    approval_request_id=request.id,
                    stage_order=1,
                    required_capability="marketing.content.approve",
                    status="approved",
                )
            )
            await session.execute(
                update(MarketingContentItem)
                .where(MarketingContentItem.id == command.content_item_id)
                .values(
                    content_revision=2,
                    approved_revision=2,
                    approval_request_id=request.id,
                    status="approved",
                )
            )
            await session.execute(
                update(MarketingContentItemChannel)
                .where(MarketingContentItemChannel.id == command.channel_id)
                .values(schedule_generation=2)
            )

    asyncio.run(run())


@pytest.mark.parametrize("predecessor_state", ["blocked", "superseded"])
def test_replacement_requires_material_edit_reapproval_and_is_atomic(
    scheduling_api, predecessor_state
):
    api = scheduling_api
    job = activate(api)
    if predecessor_state == "blocked":
        block(api, job)
    else:
        change(api, SchedulingJob, UUID(job["id"]), status="superseded")
    reapprove(api)
    api["state"]["controls"] = replace(ENABLED, delivery_receiver_configured=False)
    before = counts(api)
    assert_reason(
        post(api, job_path(api, job, "replace"), guards(2, 2)),
        "missing_durable_delivery_receiver",
    )
    assert counts(api) == before
    assert api["client"].get(job_path(api, job)).json()["status"] == predecessor_state
    api["state"]["controls"] = ENABLED
    response = post(api, job_path(api, job, "replace"), guards(2, 2))
    assert response.status_code == 200, response.text
    assert response.json()["content_revision"] == 2
    assert response.json()["supersedes_job_id"] == job["id"]
    assert api["client"].get(job_path(api, job)).json()["status"] == "superseded"


@pytest.mark.parametrize(
    "field,reason",
    [
        ("authoring_enabled", "authoring_disabled"),
        ("execution_enabled", "execution_disabled"),
        ("delivery_receiver_configured", "missing_durable_delivery_receiver"),
    ],
)
def test_controls_fail_closed(scheduling_api, field, reason):
    api = scheduling_api
    api["state"]["controls"] = replace(ENABLED, **{field: False})
    response = api["client"].get(api["channel"] + "/eligibility")
    assert not response.json()["eligible"]
    assert reason in response.json()["reason_codes"]
    assert_reason(post(api, api["channel"] + "/activate", guards()), reason)


def test_filters_and_keyset_pagination(scheduling_api):
    api = scheduling_api
    first = activate(api)
    assert post(api, job_path(api, first, "cancel")).status_code == 200
    second = post(api, job_path(api, first, "replace"), guards()).json()
    block(api, second)
    url = api["base"] + "/scheduling/jobs"
    response = api["client"].get(url, params={"limit": 1}).json()
    assert [j["id"] for j in response["jobs"]] == [second["id"]]
    assert response["next_cursor"]
    page = (
        api["client"]
        .get(url, params={"limit": 1, "cursor": response["next_cursor"]})
        .json()
    )
    assert [j["id"] for j in page["jobs"]] == [first["id"]]
    assert page["next_cursor"] is None
    for filters in [
        {"status": "blocked"},
        {"blocked_reason": "connection_unavailable"},
        {"content_item_id": first["content_item_id"], "status": "blocked"},
        {"channel_id": first["channel_id"], "status": "blocked"},
        {"connection_id": first["connection_id"], "status": "blocked"},
        {"provider": "instagram", "status": "blocked"},
        {
            "scheduled_from": first["scheduled_for"],
            "scheduled_through": first["scheduled_for"],
            "status": "blocked",
        },
    ]:
        response = api["client"].get(url, params=filters)
        assert response.status_code == 200, response.text
        assert [j["id"] for j in response.json()["jobs"]] == [second["id"]]
    for filters in [
        {"provider": "youtube"},
        {"channel_id": str(uuid4())},
        {"content_item_id": str(api["foreign_command"].content_item_id)},
        {"connection_id": str(uuid4())},
        {"blocked_reason": "stale_approval"},
    ]:
        assert api["client"].get(url, params=filters).json()["jobs"] == []
    assert (
        len(
            api["client"]
            .get(url, params=[("status", "blocked"), ("status", "cancelled")])
            .json()["jobs"]
        )
        == 2
    )


@pytest.mark.parametrize(
    "query",
    [
        {"limit": 0},
        {"limit": 101},
        {"status": "published"},
        {"blocked_reason": "secret"},
        {"cursor": "bad"},
        {"scheduled_from": "2026-01-01T00:00:00"},
        {
            "scheduled_from": "2026-02-01T00:00:00Z",
            "scheduled_through": "2026-01-01T00:00:00Z",
        },
    ],
)
def test_invalid_filters_are_structured(scheduling_api, query):
    response = scheduling_api["client"].get(
        scheduling_api["base"] + "/scheduling/jobs", params=query
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["type"]


def test_no_reschedule_or_worker_routes_and_strict_mutation_input(scheduling_api):
    api = scheduling_api
    job = activate(api)
    for payload in [
        guards(0),
        guards(True),
        {**guards(), "scheduled_for": "2026-10-01T00:00:00Z"},
        {**guards(), "controls": {"execution_enabled": True}},
    ]:
        assert post(api, api["channel"] + "/activate", payload).status_code == 422
    assert (
        api["client"].post(api["channel"] + "/activate", json=guards()).status_code
        == 422
    )
    assert (
        post(api, api["channel"] + "/activate", guards(), "invalid-key").status_code
        == 422
    )
    assert (
        post(
            api, job_path(api, job, "cancel"), {"scheduled_for": "2026-10-01T00:00:00Z"}
        ).status_code
        == 422
    )
    assert (
        api["client"]
        .patch(job_path(api, job), json={"scheduled_for": "2026-10-01T00:00:00Z"})
        .status_code
        == 405
    )
    paths = api["client"].get("/openapi.json").json()["paths"]
    assert not any(
        "claim" in path or "run-due" in path or "handoff" in path for path in paths
    )


@pytest.mark.parametrize("terminal", ["cancelled", "superseded", "handed_off"])
def test_terminal_jobs_cannot_be_cancelled_or_revalidated(scheduling_api, terminal):
    api = scheduling_api
    job = activate(api)
    values = {"status": terminal}
    if terminal == "cancelled":
        values.update(cancelled_at=func.clock_timestamp(), cancellation_reason="test")
    if terminal == "handed_off":
        values.update(handed_off_at=func.clock_timestamp(), handoff_receipt_id=uuid4())
    change(api, SchedulingJob, UUID(job["id"]), **values)
    before = counts(api)
    for operation in ("cancel", "revalidate"):
        assert_reason(
            post(api, job_path(api, job, operation)), "invalid_state_transition"
        )
    assert counts(api) == before
    if terminal == "handed_off":
        assert_reason(
            post(api, job_path(api, job, "replace"), guards()),
            "invalid_state_transition",
        )
        assert_reason(
            post(api, api["channel"] + "/activate", guards()), "already_handed_off"
        )
        reapprove(api)
        response = post(api, api["channel"] + "/activate", guards(2, 2))
        assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "drift,reason",
    [
        ("draft", "ineligible_parent_state"),
        ("approval", "stale_approval"),
        ("generation", "changed_schedule_generation"),
        ("revision", "stale_content_revision"),
    ],
)
def test_activation_rejects_invalid_authority_and_guards(scheduling_api, drift, reason):
    api = scheduling_api
    command = api["command"]
    if drift == "draft":
        change(api, MarketingContentItem, command.content_item_id, status="draft")
    elif drift == "approval":
        change(
            api, MarketingContentItem, command.content_item_id, approved_revision=None
        )
    elif drift == "revision":
        change(api, MarketingContentItem, command.content_item_id, content_revision=2)
    else:
        change(
            api, MarketingContentItemChannel, command.channel_id, schedule_generation=2
        )
    before = counts(api)
    assert_reason(post(api, api["channel"] + "/activate", guards()), reason)
    assert counts(api) == before


def test_missed_work_requires_material_reschedule(scheduling_api):
    from labelos_api.config import get_settings

    api = scheduling_api
    instant = api["activation"].snapshot.scheduled_for - timedelta(seconds=3610)
    change(
        api,
        MarketingContentItemChannel,
        api["command"].channel_id,
        scheduled_at=instant,
        schedule_local_time=instant.replace(tzinfo=None).isoformat(),
    )
    job = activate(api)
    block(api, job)
    get_settings().scheduling_worker_lateness_seconds = 0
    assert_reason(post(api, job_path(api, job, "revalidate")), "missed_schedule_window")
    # Replacement without an edit/reapproval cannot move the immutable instant.
    assert_reason(
        post(api, job_path(api, job, "replace"), guards()),
        "replacement_requires_reapproval",
    )


def test_default_receiver_is_unavailable_and_inspection_remains_available(
    scheduling_api,
):
    api = scheduling_api
    job = activate(api)
    api["client"].app.dependency_overrides.pop(scheduling_controls)
    response = api["client"].get(api["channel"] + "/eligibility")
    assert response.status_code == 200
    assert "missing_durable_delivery_receiver" in response.json()["reason_codes"]
    assert post(api, job_path(api, job, "cancel")).status_code == 200
    assert api["client"].get(job_path(api, job)).status_code == 200


def test_concurrent_same_key_is_one_activation(scheduling_api):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    api = scheduling_api
    key = uuid4()
    barrier = Barrier(2)

    def run():
        barrier.wait(timeout=10)
        return post(api, api["channel"] + "/activate", guards(), key)

    before = counts(api)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: run(), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    assert counts(api) == tuple(value + 1 for value in before)


def test_operation_keys_are_workspace_scoped(scheduling_api):
    api = scheduling_api
    key = uuid4()
    first = activate(api, key)
    api["state"]["actor"] = api["outsider"]
    foreign = api["foreign_command"]
    path = (
        f"/api/v1/workspaces/{api['outside'].id}"
        f"/marketing-content/{foreign.content_item_id}"
        f"/channels/{foreign.channel_id}/scheduling/activate"
    )
    response = post(api, path, guards(), key)
    assert response.status_code == 200, response.text
    assert response.json()["workspace_id"] != first["workspace_id"]
