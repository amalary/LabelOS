"""Actual upload/approval APIs and both production workers; external I/O mocked."""

import asyncio
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from functools import partial
from uuid import uuid4

import httpx
import pytest
from labelos_database.capabilities import Capability
from labelos_database.models import (
    MarketingMediaAsset,
    Publication,
    PublicationAttempt,
    RealtimeEvent,
    SchedulingExecutionControl,
    SocialAccountConnection,
)
from sqlalchemy import delete, func, select, update

from labelos_api import publishing_worker, scheduling_worker
from labelos_api.api.v1 import scheduling as scheduling_api
from labelos_api.services.credential_store import (
    CredentialPayload,
    InMemoryCredentialStore,
)
from test_marketing_content_api import (  # noqa: F401
    _approval_submit_base,
    _approvals_base,
    _base,
    _set_context,
)
from test_marketing_content_api import (
    marketing_content_client as marketing_content_client,
)
from test_marketing_media import MEDIA, draft, upload
from test_scheduling_publishing_composition_postgres import sweep
from test_scheduling_worker import ASYNC_CLIENT
from test_scheduling_worker import tokens as tokens
from test_scheduling_worker import worker_settings as worker_settings
from test_youtube_publishing import CHANNEL, SCOPES, VIDEO, Network


@pytest.fixture
def database_test_engine(postgres_test_engine):
    return postgres_test_engine


@pytest.mark.parametrize(
    "shared,fault", [(True, None), (False, None), (True, "missing"), (False, "corrupt")]
)
def test_uploaded_approved_video_reaches_real_youtube_adapter_once(
    marketing_content_client,
    monkeypatch,
    worker_settings,
    tokens,
    shared,
    fault,  # noqa: F811
):
    client, sessions, seeded = marketing_content_client
    settings = worker_settings.model_copy(
        update={
            "delivery_receiver_backend": "publishing",
            "scheduling_execution_enabled": True,
            "publishing_execution_enabled": True,
            "credential_store_backend": "gcp-secret-manager",
            "credential_store_gcp_project_id": "test-project",
            "youtube_oauth_client_id": "test-client",
            "youtube_oauth_client_secret": "test-secret",
            "scheduling_worker_workspace_id": seeded.workspace_id,
            "publishing_worker_workspace_id": seeded.workspace_id,
        }
    )
    monkeypatch.setattr(scheduling_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(scheduling_api, "get_settings", lambda: settings)
    for host in (scheduling_worker, publishing_worker):
        monkeypatch.setattr(host, "get_sessionmaker", lambda _: sessions)
    store = InMemoryCredentialStore()
    monkeypatch.setattr(publishing_worker, "build_credential_store", lambda _: store)

    async def connect():
        ref = await store.put(
            CredentialPayload(
                {
                    "access_token": "test-access",
                    "refresh_token": "test-refresh",
                    "scope": SCOPES,
                    "token_type": "Bearer",
                }
            )
        )
        async with sessions.begin() as session:
            connection = SocialAccountConnection(
                organization_id=seeded.workspace_id,
                provider="youtube",
                external_account_id=CHANNEL,
                connection_method="direct_api",
                status="limited",
                capabilities=["content_publish"],
                credential_ref=ref,
                token_expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            session.add(connection)
            session.add(
                SchedulingExecutionControl(
                    workspace_id=seeded.workspace_id, execution_enabled=True
                )
            )
            await session.flush()
            return connection.id

    connection_id = asyncio.run(connect())
    item, path = draft(client, seeded)
    response = upload(client, path)
    assert response.status_code == 200
    ref = response.json()
    due = datetime.now(UTC) + timedelta(seconds=15)
    response = client.patch(
        f"{_base(seeded)}/{item['id']}",
        json={
            "copy_text": "Approved video title",
            "asset_refs": [ref] if shared else [],
            "channels": [
                {
                    "channel": "youtube",
                    "placement": "video",
                    "social_account_connection_id": str(connection_id),
                    "asset_refs": [] if shared else [ref],
                    "schedule_timezone": "UTC",
                    "schedule_local_time": due.replace(tzinfo=None).isoformat(),
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    item = response.json()
    submitted = client.post(_approval_submit_base(seeded, item["id"]), json={})
    assert submitted.status_code == 201, submitted.text
    _set_context(
        client,
        seeded,
        user_id=seeded.approver_user_id,
        email="marketing-approver-profile@example.com",
        capability_permissions=(
            Capability.marketing_content_view.value,
            Capability.marketing_content_approve.value,
        ),
        department_access=("marketing",),
    )
    approved = client.post(
        f"{_approvals_base(seeded)}/{submitted.json()['id']}/decisions",
        json={"action": "approved"},
    )
    assert approved.status_code == 200, approved.text
    _set_context(client, seeded)
    channel = item["channels"][0]
    activated = client.post(
        f"/api/v1/workspaces/{seeded.workspace_id}/marketing-content/{item['id']}/channels/{channel['id']}/scheduling/activate",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "expected_content_revision": item["content_revision"],
            "expected_schedule_generation": channel["schedule_generation"],
        },
    )
    assert activated.status_code == 200, activated.text

    async def run():
        if fault:
            async with sessions.begin() as session:
                if fault == "missing":
                    await session.execute(delete(MarketingMediaAsset))
                else:
                    await session.execute(
                        update(MarketingMediaAsset).values(data=b"x" * len(MEDIA))
                    )
        await asyncio.sleep(max(0, (due - datetime.now(UTC)).total_seconds()) + 0.05)
        token = tokens()
        result = await sweep(token)
        assert result.status_code == 200, result.text
        if fault:
            assert result.json()["outcomes"] == {"handoff_contract_violation": 1}
            async with sessions() as session:
                assert (
                    await session.scalar(select(func.count()).select_from(Publication))
                    == 0
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(PublicationAttempt)
                    )
                    == 0
                )
            assert (await publishing_worker.run_sweep(settings))["claimed"] == 0
            return
        assert result.json()["outcomes"] == {"handed_off": 1}
        assert (await sweep(token)).json()["claimed"] == 0
        async with sessions() as session:
            row = await session.scalar(select(Publication))
            assert row.status == "pending"
            assert (
                await session.scalar(
                    select(func.count()).select_from(PublicationAttempt)
                )
                == 0
            )
        # Accepted bytes belong to Publishing and survive source-store loss.
        async with sessions.begin() as session:
            await session.execute(delete(MarketingMediaAsset))
        network = Network()
        # Real registry, OAuth provider, adapter, orchestrator, receiver and workers.
        # Swap only outbound Google HTTP after the workload-authenticated handoff.
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            partial(ASYNC_CLIENT, transport=httpx.MockTransport(network.handle)),
        )
        result = await publishing_worker.run_sweep(settings)
        assert result["outcomes"] == {"published": 1}, result
        assert (await publishing_worker.run_sweep(settings))["claimed"] == 0
        assert len(network.uploads) == 1
        outgoing = network.uploads[0]
        parsed = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {outgoing.headers['Content-Type']}\r\n\r\n".encode()
            + outgoing.content
        )
        assert list(parsed.iter_parts())[1].get_payload(decode=True) == MEDIA
        async with sessions() as session:
            row = await session.scalar(select(Publication))
            assert row.status == "published" and row.external_post_id == VIDEO
            assert (
                await session.scalar(
                    select(func.count()).select_from(PublicationAttempt)
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(RealtimeEvent)
                    .where(RealtimeEvent.event_type == "marketing.publication.changed")
                )
                >= 2
            )

    asyncio.run(run())
    if fault:
        return
    history = client.get(
        f"/api/v1/workspaces/{seeded.workspace_id}/publications?content_item_id={item['id']}"
    )
    assert history.status_code == 200, history.text
    assert history.json()["publications"][0]["delivery_status"] == "published"
    current = client.get(f"{_base(seeded)}/{item['id']}").json()
    assert current["content_revision"] == item["content_revision"]
    assert current["channels"][0]["published_at"] is None
