import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from labelos_database.models import WorkspacePermission

from labelos_api.config import Settings, get_settings
from labelos_api.research.adapters.youtube import YouTubeAdapter
from labelos_api.services import youtube_research_service as service
from labelos_api.services.credential_store import CredentialPayload
from test_analytics_api import _set_context
from test_analytics_api import analytics_client as _analytics_client
from test_governance import complete_datasheet

research_client = _analytics_client

REF = "gcp-secret-manager://projects/test-project/secrets/youtube-test"
CHANNEL = "UCaaaaaaaaaaaaaaaaaaaaaa"
SECRET = "test-api-key-do-not-echo"


def prepare_run(client, seeded, *, key="youtube", production=False, start=True):
    base = f"/api/v1/workspaces/{seeded.workspace_id}/governance"
    source = client.post(base + "/sources", json={"key": key, "display_name": key})
    assert source.status_code == 201, source.text
    dataset = client.post(
        base + "/datasets",
        json={
            "key": uuid4().hex,
            "display_name": "Test channels",
            "provider_id": source.json()["id"],
            "owner_department": "a&r",
        },
    )
    assert dataset.status_code == 201, dataset.text
    version = client.post(
        base + f"/datasets/{dataset.json()['id']}/versions",
        json={
            "version_key": "v1",
            "schema_version": "1",
            "data_fingerprint": "a" * 64,
            "collection_start": datetime.now(UTC).isoformat(),
            "collection_end": (datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
            "source_references": ["synthetic-test-channel"],
        },
    )
    doc = client.post(
        base + f"/versions/{version.json()['id']}/documentation",
        json={
            "document": complete_datasheet().model_dump(mode="json"),
            "change_reason": "Synthetic test review",
            "expected_revision": 0,
            "production_eligible": production,
        },
    )
    assert doc.status_code == 201, doc.text
    run = client.post(
        base + "/collection-runs",
        json={
            "documentation_id": doc.json()["id"],
            "run_key": uuid4().hex,
            "production": production,
        },
    )
    assert run.status_code == 201, run.text
    if start:
        result = client.post(
            base + f"/collection-runs/{run.json()['id']}/transitions",
            json={"status": "running"},
        )
        assert result.status_code == 200, result.text
    return run.json(), version.json(), doc.json()


@pytest.fixture
def configured(research_client, monkeypatch):
    client, maker, seeded = research_client
    _set_context(client, seeded)
    settings = Settings(
        environment="test",
        credential_store_backend="gcp-secret-manager",
        credential_store_gcp_project_id="test-project",
        youtube_research_credentials={seeded.workspace_id: REF},
    )
    client.app.dependency_overrides[get_settings] = lambda: settings
    calls = {"store": 0, "secret": 0, "http": []}

    class Store:
        async def get(self, ref):
            calls["secret"] += 1
            assert ref == REF
            return CredentialPayload({"api_key": SECRET})

    def build(_):
        calls["store"] += 1
        return Store()

    def handle(request):
        calls["http"].append(request.url.path)
        assert request.url.host == "www.googleapis.com"
        assert request.url.params["key"] == SECRET
        if request.url.path.endswith("search"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": {"channelId": CHANNEL},
                            "snippet": {"title": "Public channel"},
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": CHANNEL,
                        "snippet": {"title": "Public channel"},
                        "statistics": {
                            "viewCount": "123",
                            "videoCount": "7",
                            "subscriberCount": "45",
                            "hiddenSubscriberCount": False,
                        },
                    }
                ]
            },
        )

    monkeypatch.setattr(service, "build_credential_store", build)
    monkeypatch.setattr(
        service,
        "YouTubeAdapter",
        lambda: YouTubeAdapter(transport=httpx.MockTransport(handle)),
    )
    return client, maker, seeded, settings, calls


def path(seeded, run):
    return f"/api/v1/workspaces/{seeded.workspace_id}/research/youtube/runs/{run['id']}"


def test_live_routes_return_public_data_with_real_provenance(configured, caplog):
    client, _, seeded, _, calls = configured
    run, version, _ = prepare_run(client, seeded)
    base = path(seeded, run)
    for operation, body in [
        ("search", {"query": "Public", "limit": 1}),
        ("lookup", {"channel_id": CHANNEL}),
        ("observations", {"channel_id": CHANNEL}),
    ]:
        response = client.post(base + "/" + operation, json=body)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["context"]["dataset_version_id"] == version["id"]
        assert response.json()["context"]["collection_run_id"] == run["id"]
        assert SECRET not in response.text and REF not in response.text
    assert len(response.json()["items"]) == 3
    assert calls["secret"] == 3
    assert len(calls["http"]) == 3
    assert SECRET not in caplog.text
    # Display requests do not pretend records were ingested or complete the run.
    current = client.get(
        f"/api/v1/workspaces/{seeded.workspace_id}/governance/collection-runs/{run['id']}"
    ).json()
    assert current["status"] == "running" and current["records_written"] == 0


@pytest.mark.parametrize(
    "case,expected",
    [
        ("guest", 403),
        ("other_workspace", 403),
        ("missing_run", 404),
        ("queued", 409),
        ("completed", 409),
        ("wrong_provider", 409),
        ("unconfigured", 503),
        ("archived", 409),
    ],
)
def test_rejected_requests_never_access_secret_or_provider(configured, case, expected):
    client, _, seeded, settings, calls = configured
    run, version, _ = prepare_run(
        client,
        seeded,
        key="internal" if case == "wrong_provider" else "youtube",
        start=case != "queued",
    )
    base = path(seeded, run)
    governance = f"/api/v1/workspaces/{seeded.workspace_id}/governance"
    if case == "guest":
        _set_context(
            client,
            seeded,
            user_id=seeded.analyst_user_id,
            workspace_permission=WorkspacePermission.guest,
        )
    elif case == "other_workspace":
        base = base.replace(str(seeded.workspace_id), str(seeded.outside_workspace_id))
    elif case == "missing_run":
        base = base.replace(run["id"], str(uuid4()))
    elif case == "completed":
        assert (
            client.post(
                governance + f"/collection-runs/{run['id']}/transitions",
                json={"status": "completed"},
            ).status_code
            == 200
        )
    elif case == "unconfigured":
        settings.youtube_research_credentials = {seeded.outside_workspace_id: REF}
    elif case == "archived":
        from uuid import UUID

        from labelos_database.models import User

        from labelos_api.governance import VersionTransition
        from labelos_api.services.governance_service import GovernanceService

        async def archive():
            async with configured[1]() as session:
                svc = GovernanceService(
                    session,
                    seeded.workspace_id,
                    actor=await session.get(User, seeded.owner_user_id),
                )
                await svc.transition_version(
                    UUID(version["id"]),
                    VersionTransition(state="finalized", expected_state="draft"),
                )
                await svc.transition_version(
                    UUID(version["id"]),
                    VersionTransition(state="archived", expected_state="finalized"),
                )
                await session.commit()

        asyncio.run(archive())
    response = client.post(base + "/search", json={"query": "Public"})
    assert response.status_code == expected, response.text
    assert calls == {"store": 0, "secret": 0, "http": []}


def test_stale_production_documentation_rejected(configured):
    client, _, seeded, _, calls = configured
    run, version, _ = prepare_run(client, seeded, production=True)
    result = client.post(
        f"/api/v1/workspaces/{seeded.workspace_id}/governance/versions/{version['id']}/documentation",
        json={
            "document": {},
            "change_reason": "Review revoked",
            "expected_revision": 1,
            "production_eligible": False,
        },
    )
    assert result.status_code == 201, result.text
    response = client.post(path(seeded, run) + "/search", json={"query": "Public"})
    assert response.status_code == 409
    assert calls["secret"] == 0


def test_provider_failure_is_sanitized(configured, monkeypatch, caplog):
    client, _, seeded, _, _ = configured
    run, _, _ = prepare_run(client, seeded)

    def fail(request):
        return httpx.Response(
            403,
            json={
                "error": {"message": SECRET, "errors": [{"reason": "quotaExceeded"}]}
            },
        )

    monkeypatch.setattr(
        service,
        "YouTubeAdapter",
        lambda: YouTubeAdapter(transport=httpx.MockTransport(fail)),
    )
    response = client.post(path(seeded, run) + "/search", json={"query": "Public"})
    assert response.status_code == 429
    assert response.json() == {"detail": {"code": "quota_exceeded"}}
    assert SECRET not in response.text + caplog.text


def test_no_credentials_or_unbounded_queries_in_request(configured):
    client, _, seeded, _, calls = configured
    run, _, _ = prepare_run(client, seeded)
    for body in [
        {"query": "Public", "api_key": "injected"},
        {"query": "Public", "limit": 51},
        {"query": " "},
    ]:
        assert client.post(path(seeded, run) + "/search", json=body).status_code == 422
    assert calls["secret"] == 0


def test_authentication_required(client):
    base = f"/api/v1/workspaces/{uuid4()}/research/youtube/runs/{uuid4()}"
    assert client.post(base + "/search", json={"query": "Public"}).status_code == 401


def test_settings_load_reference_map_and_reject_wrong_project(monkeypatch):
    workspace_id = uuid4()
    monkeypatch.setenv(
        "YOUTUBE_RESEARCH_CREDENTIALS", json.dumps({str(workspace_id): REF})
    )
    monkeypatch.setenv("CREDENTIAL_STORE_BACKEND", "gcp-secret-manager")
    monkeypatch.setenv("CREDENTIAL_STORE_GCP_PROJECT_ID", "test-project")
    settings = get_settings()
    settings.validate_youtube_research_configuration()
    assert settings.youtube_research_credentials == {workspace_id: REF}
    settings.credential_store_gcp_project_id = "different-project"
    with pytest.raises(RuntimeError):
        settings.validate_youtube_research_configuration()


def test_local_reference_is_rejected_in_production(configured):
    client, _, seeded, settings, calls = configured
    run, _, _ = prepare_run(client, seeded)
    settings.youtube_research_credentials = {}
    settings.youtube_research_local_credential_ref = REF
    assert (
        client.post(path(seeded, run) + "/search", json={"query": "Public"}).status_code
        == 200
    )
    settings.environment = "production"
    with pytest.raises(RuntimeError, match="local-only"):
        settings.validate_youtube_research_configuration()
    calls["secret"] = 0
    assert (
        client.post(path(seeded, run) + "/search", json={"query": "Public"}).status_code
        == 409
    )
    assert calls["secret"] == 0


def test_foreign_run_is_not_visible(configured):
    from labelos_database.models import Organization

    from labelos_api.governance import CollectionRunCreate
    from test_governance import governed_version

    client, maker, seeded, _, calls = configured

    async def create_foreign():
        async with maker() as session:
            workspace = await session.get(Organization, seeded.outside_workspace_id)
            svc, _, _, _, doc = await governed_version(
                session, workspace.id, workspace.owner_user_id
            )
            run = await svc.create_run(
                CollectionRunCreate(documentation_id=doc.id, run_key=uuid4().hex)
            )
            await session.commit()
            return {"id": str(run.id)}

    run = asyncio.run(create_foreign())
    assert (
        client.post(path(seeded, run) + "/search", json={"query": "Public"}).status_code
        == 404
    )
    assert calls["secret"] == 0 and calls["store"] == 0


def test_credential_startup_failure_is_sanitized(configured, monkeypatch, caplog):
    client, _, seeded, _, calls = configured
    run, _, _ = prepare_run(client, seeded)

    def fail(_):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(service, "build_credential_store", fail)
    response = client.post(path(seeded, run) + "/search", json={"query": "Public"})
    assert response.status_code == 503
    assert SECRET not in response.text + caplog.text
    assert not calls["http"]


def test_retry_after_header_is_preserved(configured, monkeypatch):
    from labelos_api.research.adapters.common import RequestGate

    client, _, seeded, _, _ = configured
    run, _, _ = prepare_run(client, seeded)
    transport = httpx.MockTransport(
        lambda _: httpx.Response(429, headers={"Retry-After": "17"})
    )
    monkeypatch.setattr(
        service,
        "YouTubeAdapter",
        lambda: YouTubeAdapter(transport=transport, gate=RequestGate()),
    )
    response = client.post(path(seeded, run) + "/search", json={"query": "Public"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "17"
    assert response.headers["cache-control"] == "no-store"
