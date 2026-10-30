import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from labelos_database.research_models import YouTubeQuotaBucket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from labelos_api.research.adapters.common import RequestGate
from labelos_api.research.adapters.youtube import YouTubeAdapter
from labelos_api.research.errors import AdapterFailure
from labelos_api.research.errors import ProviderErrorCode as Code
from labelos_api.research.youtube_cache import DisplayCache
from labelos_api.research.youtube_quota import YouTubeQuota, reset_time
from labelos_api.services.analytics_service import (
    AnalyticsBulkIngestionError,
    AnalyticsMetricDefinitionCreate,
    AnalyticsObservationCreate,
    AnalyticsProviderRef,
    AnalyticsRelationshipError,
    create_metric_definition,
    create_observation,
    ingest_observations_bulk,
)
from labelos_api.services.credential_store import CredentialPayload
from test_analytics_service import _seed_workspace_graph
from test_analytics_service import sessionmaker as sessionmaker
from test_youtube_research_api import (
    CHANNEL,
    SECRET,
    path,
    prepare_run,
    service,
)
from test_youtube_research_api import (
    configured as configured,
)
from test_youtube_research_api import (
    research_client as research_client,
)


def test_search_cache_preserves_timestamp_and_authorization(configured):
    client, _, seeded, _, calls = configured
    run, _, _ = prepare_run(client, seeded)
    base = path(seeded, run)
    first = client.post(base + "/search", json={"query": "Public"})
    second = client.post(base + "/search", json={"query": "Public"})
    assert first.json() == second.json()
    assert len(calls["http"]) == 1
    governance = f"/api/v1/workspaces/{seeded.workspace_id}/governance"
    client.post(
        governance + f"/collection-runs/{run['id']}/transitions",
        json={"status": "completed"},
    )
    assert client.post(base + "/search", json={"query": "Public"}).status_code == 409
    assert len(calls["http"]) == 1


def test_delete_cache_and_combined_channel_use_one_call(configured):
    client, _, seeded, _, calls = configured
    run, _, _ = prepare_run(client, seeded)
    base = path(seeded, run)
    response = client.post(base + "/channel", json={"channel_id": CHANNEL})
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 3
    assert len(calls["http"]) == 1
    client.post(base + "/search", json={"query": "Public"})
    assert client.delete(base + "/display-cache").status_code == 204
    client.post(base + "/search", json={"query": "Public"})
    assert len(calls["http"]) == 3


@pytest.mark.parametrize(
    "stats,count",
    [
        (None, 0),
        ({}, 0),
        ({"hiddenSubscriberCount": True, "subscriberCount": "100"}, 0),
        ({"subscriberCount": "100"}, 0),
        ({"hiddenSubscriberCount": False, "subscriberCount": "0"}, 1),
    ],
)
def test_missing_hidden_and_zero_counters(configured, monkeypatch, stats, count):
    client, _, seeded, _, _ = configured
    run, _, _ = prepare_run(client, seeded)
    row = {"id": CHANNEL, "snippet": {"title": "Public"}, "statistics": stats}
    monkeypatch.setattr(
        service,
        "YouTubeAdapter",
        lambda: YouTubeAdapter(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"items": [row]})
            )
        ),
    )
    response = client.post(path(seeded, run) + "/channel", json={"channel_id": CHANNEL})
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == count
    if count:
        assert response.json()["items"][0]["value"] == 0


def test_deleted_channel_invalidates_cached_search_without_changing_run(
    configured, monkeypatch
):
    client, _, seeded, _, calls = configured
    run, _, _ = prepare_run(client, seeded)
    base = path(seeded, run)
    client.post(base + "/search", json={"query": "Public"})
    monkeypatch.setattr(
        service,
        "YouTubeAdapter",
        lambda: YouTubeAdapter(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"items": []})
            )
        ),
    )
    response = client.post(base + "/lookup", json={"channel_id": CHANNEL})
    assert response.status_code == 404
    assert client.post(base + "/search", json={"query": "Public"}).json()["items"] == []
    current = client.get(
        f"/api/v1/workspaces/{seeded.workspace_id}/governance/collection-runs/{run['id']}"
    ).json()
    assert current["status"] == "running" and current["records_written"] == 0
    assert len(calls["http"]) == 1


def test_cache_hard_expiry_capacity_and_deletion_during_fetch():
    now = [0.0]
    cache = DisplayCache(ttl=60, capacity=1, clock=lambda: now[0])
    workspace = uuid4()
    key = (workspace, uuid4(), "search", "opaque-digest")
    cache.put(key, "first")
    now[0] = 59
    assert cache.get(key) == "first"
    now[0] = 60
    assert cache.get(key) is None
    token = uuid4()
    cache.pending[key] = token
    cache.clear_workspace(workspace)
    cache.put(key, "must not resurrect", pending_token=token)
    assert cache.get(key) is None
    cache.put(key, "first")
    cache.put((workspace, uuid4()), "second")
    assert cache.get(key) is None


def test_quota_atomic_across_clients_and_survives_failure(tmp_path):
    async def run():
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{tmp_path / 'synthetic-quota.db'}"
        )
        async with engine.begin() as connection:
            await connection.run_sync(YouTubeQuotaBucket.__table__.create)
        sessions = async_sessionmaker(engine)
        now = [datetime(2026, 10, 27, 20, tzinfo=UTC)]
        clients = [
            YouTubeQuota(sessions, clock=lambda: now[0], spacing=False)
            for _ in range(2)
        ]
        outcomes = await asyncio.gather(
            *(clients[i % 2].reserve("search") for i in range(90)),
            return_exceptions=True,
        )
        assert sum(result is None for result in outcomes) == 80
        failures = [result for result in outcomes if result is not None]
        assert all(
            isinstance(result, AdapterFailure)
            and result.details.code == Code.quota_exceeded
            for result in failures
        )
        # A caller rollback cannot refund a quota reservation already sent upstream.
        async with sessions() as session:
            await session.rollback()
            assert (await session.scalar(select(YouTubeQuotaBucket))).used == 80
        now[0] = reset_time(now[0])
        await clients[0].reserve("search")
        async with sessions() as session:
            assert (await session.scalar(select(YouTubeQuotaBucket))).used == 1
        await engine.dispose()

    asyncio.run(run())


def test_pacific_reset_handles_dst():
    now = datetime(2026, 3, 8, 8, tzinfo=UTC)
    assert reset_time(now) - now == timedelta(hours=23)


@pytest.mark.parametrize(
    "path,status,attempts",
    [
        ("search", 503, 1),
        ("channels", 503, 2),
        ("channels", 403, 1),
        ("channels", 404, 1),
    ],
)
def test_bounded_retries_and_sanitized_errors(
    monkeypatch, caplog, path, status, attempts
):
    calls, reserved, sleeps = [], [], []

    class Quota:
        async def reserve(self, bucket):
            reserved.append(bucket)

        async def defer(self, bucket, seconds):
            pass

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("labelos_api.research.adapters.youtube.asyncio.sleep", sleep)

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": SECRET}})

    adapter = YouTubeAdapter(
        transport=httpx.MockTransport(handler), gate=RequestGate(clock=lambda: 0)
    )
    # The fake clock does not advance during fake sleep; use a no-op local gate.
    adapter.gate.enter = lambda *args: None
    adapter.quota = Quota()
    with pytest.raises(AdapterFailure) as error:
        asyncio.run(adapter.get(path, {}, CredentialPayload({"api_key": SECRET})))
    assert len(calls) == len(reserved) == attempts
    assert len(sleeps) == attempts - 1
    assert SECRET not in str(error.value) + caplog.text
    assert error.value.__context__ is None


def test_youtube_analytics_retention_is_blocked(sessionmaker):
    async def run():
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            metric = await create_metric_definition(
                session,
                workspace.id,
                AnalyticsMetricDefinitionCreate(
                    key="subscribers",
                    display_name="Subscribers",
                    value_type="integer",
                    provider=AnalyticsProviderRef(key="youtube"),
                ),
            )
            payload = AnalyticsObservationCreate(
                metric_definition_id=metric.id,
                target_type="workspace",
                observed_at=datetime.now(UTC),
                value_numeric=100,
            )
            with pytest.raises(AnalyticsRelationshipError, match="display-only"):
                await create_observation(session, workspace.id, payload)
            with pytest.raises(AnalyticsBulkIngestionError):
                await ingest_observations_bulk(session, workspace.id, [payload])

    asyncio.run(run())


def test_migration_requires_explicit_approval_without_touching_existing_tables(
    monkeypatch,
):
    from test_governance_audit import migration_scripts

    migration = migration_scripts().get_revision("202610270100").module
    tables = []
    monkeypatch.setattr(migration.context, "get_x_argument", lambda **kwargs: {})
    monkeypatch.setattr(
        migration.op, "create_table", lambda name, *args: tables.append(name)
    )
    with pytest.raises(RuntimeError, match="Approve"):
        migration.upgrade()
    assert tables == []
    monkeypatch.setattr(
        migration.context,
        "get_x_argument",
        lambda **kwargs: {"youtube_quota_approved": "true"},
    )
    migration.upgrade()
    assert tables == ["youtube_quota_buckets"]
