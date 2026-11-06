import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from labelos_database.models import WorkspacePermission

from labelos_api.config import Settings, get_settings
from labelos_api.research import musicbrainz as composition
from labelos_api.research.adapters import common
from labelos_api.research.adapters.musicbrainz import MusicBrainzAdapter
from labelos_api.research.contracts import CollectionContext
from test_analytics_api import _set_context
from test_analytics_api import analytics_client as _analytics_client
from test_youtube_research_api import prepare_run

research_client = _analytics_client
MBID = "11111111-1111-4111-8111-111111111111"
AGENT = "LabelOS/0.1 (mailto:fixtures@example.test)"
FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/research/providers.json").read_text()
)["musicbrainz"]


@pytest.fixture
def configured(research_client, monkeypatch):
    client, maker, seeded = research_client
    _set_context(client, seeded)
    settings = Settings(
        environment="test",
        musicbrainz_user_agent=AGENT,
        musicbrainz_approval_ref=composition.LOCAL_NONCOMMERCIAL_APPROVAL,
    )
    client.app.dependency_overrides[get_settings] = lambda: settings
    calls = []

    def respond(request):
        calls.append(request)
        assert request.url.host == "musicbrainz.org"
        assert request.headers["User-Agent"] == AGENT
        assert "Authorization" not in request.headers
        assert "api_key" not in request.url.params
        assert "token" not in request.url.params
        if "query" in request.url.params:
            key = "search"
        elif request.url.path.endswith("recording"):
            key = "catalog"
        elif request.url.path.endswith("release"):
            key = "release"
        else:
            key = "lookup"
        return httpx.Response(200, json=FIXTURES[key])

    class Adapter(MusicBrainzAdapter):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(composition, "MusicBrainzAdapter", Adapter)
    monkeypatch.setattr(common, "DEFAULT_GATE", common.RequestGate(clock=lambda: 0))
    return client, maker, seeded, settings, calls


def path(seeded, run):
    return (
        f"/api/v1/workspaces/{seeded.workspace_id}"
        f"/research/musicbrainz/runs/{run['id']}"
    )


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("search", {"query": "Fixture Artist", "limit": 2}),
        ("lookup", {"artist_id": MBID}),
        ("catalog", {"artist_id": MBID, "resource": "track"}),
        ("catalog", {"artist_id": MBID, "resource": "release"}),
    ],
)
def test_routes_use_configured_public_adapter(configured, operation, payload):
    client, _, seeded, _, calls = configured
    run, _, _ = prepare_run(client, seeded, key="musicbrainz")
    response = client.post(path(seeded, run) + "/" + operation, json=payload)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["context"]["provider_key"] == "musicbrainz"
    assert len(calls) == 1
    assert "fixtures@example.test" not in response.text
    assert "approval_ref" not in response.text


@pytest.mark.parametrize(
    "case,status",
    [
        ("guest", 403),
        ("other_workspace", 403),
        ("missing_run", 404),
        ("queued", 409),
        ("completed", 409),
        ("wrong_provider", 409),
        ("missing_contact", 503),
        ("placeholder_contact", 503),
        ("missing_approval", 503),
        ("production", 409),
    ],
)
def test_rejection_happens_before_provider_io(configured, case, status):
    client, _, seeded, settings, calls = configured
    run, _, _ = prepare_run(
        client,
        seeded,
        key="youtube" if case == "wrong_provider" else "musicbrainz",
        start=case != "queued",
    )
    base = path(seeded, run)
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
        result = client.post(
            f"/api/v1/workspaces/{seeded.workspace_id}/governance"
            f"/collection-runs/{run['id']}/transitions",
            json={"status": "completed"},
        )
        assert result.status_code == 200
    elif case == "missing_contact":
        settings.musicbrainz_user_agent = None
    elif case == "placeholder_contact":
        settings.musicbrainz_user_agent = "LabelOS/0.1 (REPLACE_WITH_CONTACT_EMAIL)"
    elif case == "missing_approval":
        settings.musicbrainz_approval_ref = None
    elif case == "production":
        settings.environment = "production"
    response = client.post(base + "/search", json={"query": "Fixture"})
    assert response.status_code == status, response.text
    assert calls == []


def test_new_clients_share_rate_limit(configured):
    client, _, seeded, _, calls = configured
    run, _, _ = prepare_run(client, seeded, key="musicbrainz")
    endpoint = path(seeded, run) + "/search"
    assert client.post(endpoint, json={"query": "Fixture"}).status_code == 200
    response = client.post(endpoint, json={"query": "Fixture"})
    assert response.status_code == 429
    assert response.json() == {"detail": {"code": "rate_limited"}}
    assert response.headers["Retry-After"] == "1"
    assert len(calls) == 1


def test_invalid_requests_do_not_reach_musicbrainz(configured):
    client, _, seeded, _, calls = configured
    run, _, _ = prepare_run(client, seeded, key="musicbrainz")
    for operation, payload in [
        ("search", {"query": "Fixture", "api_key": "sensitive-input"}),
        ("search", {"query": "Fixture", "limit": 101}),
        ("search", {"query": " "}),
        ("search", {"query": "Fixture", "cursor": "https://other.example.test"}),
        ("lookup", {"artist_id": "sensitive-input"}),
        ("catalog", {"artist_id": MBID, "resource": "unsupported"}),
    ]:
        response = client.post(path(seeded, run) + "/" + operation, json=payload)
        assert response.status_code == 422
        assert "sensitive-input" not in response.text
    assert calls == []


def test_upstream_failure_is_sanitized(configured, monkeypatch, caplog):
    client, _, seeded, _, _ = configured
    run, _, _ = prepare_run(client, seeded, key="musicbrainz")

    class FailingAdapter(MusicBrainzAdapter):
        def __init__(self, **kwargs):
            super().__init__(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(
                        503,
                        headers={"Retry-After": "3"},
                        text="private-upstream-detail",
                    )
                ),
                **kwargs,
            )

    monkeypatch.setattr(composition, "MusicBrainzAdapter", FailingAdapter)
    response = client.post(path(seeded, run) + "/search", json={"query": "Fixture"})
    assert response.status_code in {429, 503}
    assert response.headers["Retry-After"] == "3"
    assert "private-upstream-detail" not in response.text + caplog.text
    assert "fixtures@example.test" not in response.text + caplog.text


def test_local_permission_cannot_enable_production():
    context = CollectionContext(
        workspace_id=uuid4(),
        provider_id=uuid4(),
        provider_key="musicbrainz",
        collection_run_id=uuid4(),
        dataset_version_id=uuid4(),
    )
    with pytest.raises(composition.MusicBrainzNotConfigured):
        composition.build_musicbrainz_client(
            Settings(
                environment="production",
                musicbrainz_user_agent=AGENT,
                musicbrainz_approval_ref=composition.LOCAL_NONCOMMERCIAL_APPROVAL,
            ),
            context,
        )


def test_authentication_required(client):
    endpoint = (
        f"/api/v1/workspaces/{uuid4()}/research/musicbrainz/runs/{uuid4()}/search"
    )
    assert client.post(endpoint, json={"query": "Fixture"}).status_code == 401
