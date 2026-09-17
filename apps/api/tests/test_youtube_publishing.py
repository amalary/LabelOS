"""Real SQLite persistence/OAuth refresh; only external HTTP is mocked."""

import asyncio
import hashlib
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from uuid import uuid4

import httpx
import pytest
from labelos_database.models import (
    RealtimeEvent,
    SocialAccountConnection,
)
from sqlalchemy import select, update

from labelos_api.publishing import contracts as domain
from labelos_api.publishing.execution import DeliveryContext
from labelos_api.publishing.providers import (
    ProviderOutcome as Outcome,
)
from labelos_api.publishing.providers import (
    ProviderRegistry,
    ProviderResolutionError,
    publication_request,
)
from labelos_api.publishing.registry import publishing_provider_registry
from labelos_api.publishing.youtube import YouTubePublishingAdapter
from labelos_api.repositories.publishing import PublicationRepository
from labelos_api.repositories.scheduling import snapshot_for
from labelos_api.scheduling.payload import canonical_json, prepare_request
from labelos_api.services.credential_store import (
    CredentialPayload,
    InMemoryCredentialStore,
)
from labelos_api.services.delivery_orchestrator import (
    DeliveryIneligible,
    DeliveryOrchestrator,
)
from labelos_api.social_accounts.providers import (
    SocialAccountProviderRegistry,
    YouTubeDirectProviderConfig,
)
from labelos_api.social_accounts.providers import (
    YouTubeDirectSocialAccountConnectionProvider as OAuthProvider,
)
from test_publishing_persistence import sessions as persistence_sessions  # noqa: F401
from test_publishing_providers import database_test_engine  # noqa: F401
from test_scheduling_persistence import job_for, source

CHANNEL = "UC" + "a" * 22
VIDEO = "aB_12345-67"
ACCESS = "ACCESS_SENTINEL"
REFRESH = "REFRESH_SENTINEL"
RAW = "SENSITIVE_RAW_RESPONSE"
MEDIA = b"approved-video-bytes\x00\xff"
SCOPES = f"{OAuthProvider.SCOPE_YOUTUBE_READONLY} {OAuthProvider.SCOPE_YOUTUBE_UPLOAD}"


@pytest.fixture
def sessions(persistence_sessions):  # noqa: F811
    return persistence_sessions


def success():
    return {
        "kind": "youtube#video",
        "id": VIDEO,
        "snippet": {"channelId": CHANNEL},
        "status": {"uploadStatus": "uploaded", "privacyStatus": "public"},
        "untrusted": RAW,
    }


def api_error(status, reason):
    return httpx.Response(
        status,
        json={
            "error": {
                "code": status,
                "message": RAW,
                "errors": [{"reason": reason, "message": RAW}],
            }
        },
        headers={"Retry-After": "30"},
    )


class Network:
    def __init__(self):
        self.calls = []
        self.upload_response = httpx.Response(200, json=success())
        self.identity_response = httpx.Response(200, json={"items": [{"id": CHANNEL}]})
        self.refresh_response = httpx.Response(
            200, json={"access_token": "NEW_ACCESS", "expires_in": 3600}
        )
        self.on_identity = None
        self.on_refresh = None

    async def handle(self, request):
        self.calls.append(request)
        if request.url.path == "/token":
            assert request.method == "POST"
            if self.on_refresh:
                await self.on_refresh()
            response = self.refresh_response
        elif request.url.path == "/youtube/v3/channels":
            assert request.method == "GET"
            assert dict(request.url.params) == {
                "part": "id",
                "mine": "true",
                "maxResults": "2",
            }
            if self.on_identity:
                await self.on_identity()
            response = self.identity_response
        else:
            assert request.url.host == "www.googleapis.com"
            assert request.url.path == "/upload/youtube/v3/videos"
            assert request.method == "POST"
            assert dict(request.url.params) == {
                "uploadType": "multipart",
                "part": "snippet,status",
            }
            response = self.upload_response
        if isinstance(response, BaseException):
            raise response
        return response

    @property
    def uploads(self):
        return [r for r in self.calls if r.url.path == "/upload/youtube/v3/videos"]


async def setup(
    sessions, monkeypatch, *, expired=False, values=None, connection_values=None
):
    store = InMemoryCredentialStore()
    ref = await store.put(
        CredentialPayload(
            {
                "access_token": ACCESS,
                "refresh_token": REFRESH,
                "scope": SCOPES,
                "token_type": "Bearer",
                **(values or {}),
            }
        )
    )
    async with sessions.begin() as session:
        item, approval, user = await source(session)
        channel = item.channels[0]
        item.copy_text = "Approved title\nApproved description"
        channel.channel = "youtube"
        channel.placement = "video"
        channel.asset_refs = [
            {
                "sha256": hashlib.sha256(MEDIA).hexdigest(),
                "size_bytes": len(MEDIA),
                "media_type": "video/mp4",
            }
        ]
        channel.metadata_json = {"hashtags": ["#Label"]}
        connection = SocialAccountConnection(
            organization_id=item.organization_id,
            **{
                "provider": "youtube",
                "external_account_id": CHANNEL,
                "connection_method": "direct_api",
                "status": "limited",
                "capabilities": ["content_publish"],
                "credential_ref": ref,
                "token_expires_at": datetime.now(UTC)
                + timedelta(hours=-1 if expired else 1),
                **(connection_values or {}),
            },
        )
        session.add(connection)
        await session.flush()
        channel.social_account_connection_id = connection.id
        job = job_for(item, approval, user, social_account_connection_id=connection.id)
        session.add(job)
        await session.flush()
        accepted = prepare_request(
            snapshot=snapshot_for(job),
            job_id=job.id,
            destination_id=connection.id,
            artist_profile_id=None,
            authoring_timezone="UTC",
            correlation_id=uuid4(),
            item=item,
            channel=channel,
            asset_bytes={hashlib.sha256(MEDIA).hexdigest(): MEDIA},
        )
        row = await PublicationRepository(session, item.organization_id).create(
            accepted,
            created_at=datetime.now(UTC),
            destination_identity=hashlib.sha256(
                canonical_json(["youtube", CHANNEL])
            ).hexdigest(),
        )
        context = context_for(row)

    # Only scheduling preparation is substituted; adapter auth, attempts, evidence,
    # transitions and outbox are real. Scheduling authorization has its own suite.
    async def prepared(self, repository, publication_id):
        row = await PublicationRepository(
            repository.session, repository.workspace_id
        ).get(publication_id)
        if row.status not in {"pending", "retryable_failure"}:
            raise DeliveryIneligible("publication_not_executable")
        return context_for(row)

    monkeypatch.setattr(DeliveryOrchestrator, "prepare_execution", prepared)
    network = Network()
    client = httpx.AsyncClient(transport=httpx.MockTransport(network.handle))
    oauth = OAuthProvider(
        config=YouTubeDirectProviderConfig(
            client_id="test-client", client_secret="CLIENT_SECRET_SENTINEL"
        ),
        credential_store=store,
        http_client=client,
    )
    adapter = YouTubePublishingAdapter(
        sessions=sessions, connection_provider=oauth, http_client=client
    )
    request = publication_request(
        context,
        domain.PublicationAttempt(
            id=uuid4(),
            workspace_id=context.workspace_id,
            publication_id=context.publication_id,
            number=1,
            started_at=datetime.now(UTC),
        ),
    )
    return adapter, request, network, store, oauth


def context_for(row):
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


async def execute(sessions, adapter, request):
    return await DeliveryOrchestrator().execute(
        sessions,
        workspace_id=request.workspace_id,
        publication_id=request.publication_id,
        registry=ProviderRegistry({"youtube": adapter}),
    )


def test_upload_and_durable_result(sessions, monkeypatch, caplog):
    async def run():
        adapter, request, network, _, _ = await setup(sessions, monkeypatch)
        result = await execute(sessions, adapter, request)
        assert result.status == "published"
        upload = network.uploads[0]
        assert upload.headers["Authorization"] == f"Bearer {ACCESS}"
        parsed = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {upload.headers['Content-Type']}\r\n\r\n".encode()
            + upload.content
        )
        parts = list(parsed.iter_parts())
        assert json.loads(parts[0].get_payload(decode=True)) == {
            "snippet": {
                "title": "Approved title",
                "description": "Approved title\nApproved description\n\n#Label",
            },
            "status": {"privacyStatus": "public"},
        }
        assert parts[1].get_payload(decode=True) == MEDIA
        assert parts[1].get_content_type() == "video/mp4"
        async with sessions() as session:
            row = await PublicationRepository(session, request.workspace_id).get(
                request.publication_id
            )
            assert row.provider == "youtube"
            assert row.external_post_id == VIDEO
            assert row.transitions[-1].external_post_id == VIDEO
            assert len(row.attempts) == 1
            assert row.transition_version == 2
            events = (await session.scalars(select(RealtimeEvent))).all()
            stored = repr([e.payload for e in events]) + repr(
                row.attempts[-1].observations
            )
            for sentinel in (ACCESS, REFRESH, RAW, "CLIENT_SECRET_SENTINEL"):
                assert sentinel not in stored + repr(result) + caplog.text
        with pytest.raises(DeliveryIneligible):
            await execute(sessions, adapter, request)
        assert len(network.uploads) == 1

    caplog.set_level(logging.DEBUG)
    asyncio.run(run())


@pytest.mark.parametrize("placement", ["video", "shorts"])
def test_supported_placements(sessions, monkeypatch, placement):
    async def run():
        adapter, request, network, _, _ = await setup(sessions, monkeypatch)
        result = await adapter.publish(replace(request, placement=placement))
        assert result.outcome == Outcome.published
        assert len(network.uploads) == 1
        assert b"#Shorts" not in network.uploads[0].content

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        {"placement": "community"},
        {"placement": "live"},
        {"placement": "feed"},
        {"provider": "instagram"},
        {"channel": "tiktok"},
        {"caption": None},
        {"caption": "x" * 101},
        {"caption": "<title>"},
        {"caption": "Title\n" + "\u00e9" * 2500},
        {"caption": "Title\x00"},
        {"media": ()},
    ],
)
def test_local_rejections_have_no_io(sessions, monkeypatch, change):
    async def run():
        adapter, request, network, store, _ = await setup(sessions, monkeypatch)
        store.fail_operations.add("get")
        request = replace(request, **change)
        assert adapter.validate(request) is not None
        assert (await adapter.publish(request)).outcome in {
            Outcome.unsupported,
            Outcome.permanent_failure,
        }
        assert not network.calls

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        {"media_type": "image/jpeg"},
        {"data": b""},
        {"sha256": "0" * 64},
        {"media_type": "video/mp4\r\nInjected: value"},
    ],
)
def test_invalid_media(sessions, monkeypatch, change):
    async def run():
        adapter, request, network, _, _ = await setup(sessions, monkeypatch)
        request = replace(request, media=(replace(request.media[0], **change),))
        assert adapter.validate(request).outcome == Outcome.permanent_failure
        assert not network.calls

    asyncio.run(run())


@pytest.mark.parametrize(
    "connection_values",
    [
        {"status": "disconnected"},
        {"status": "reconnect_required"},
        {"status": "error"},
        {"credential_ref": None},
        {"capabilities": []},
        {"connection_method": "assisted"},
        {"external_account_id": "another"},
    ],
)
def test_connection_rejections_before_network(sessions, monkeypatch, connection_values):
    async def run():
        adapter, request, network, _, _ = await setup(
            sessions, monkeypatch, connection_values=connection_values
        )
        result = await adapter.publish(request)
        assert result.outcome == Outcome.authorization_required
        assert result.confirmed_absent
        assert not network.calls

    asyncio.run(run())


@pytest.mark.parametrize(
    "values",
    [
        {"scope": OAuthProvider.SCOPE_YOUTUBE_READONLY},
        {"scope": OAuthProvider.SCOPE_YOUTUBE_UPLOAD},
        {"scope": ""},
        {"access_token": ""},
        {"token_type": "Basic"},
    ],
)
def test_requires_actual_granted_scopes_and_token(sessions, monkeypatch, values):
    async def run():
        adapter, request, network, _, _ = await setup(
            sessions, monkeypatch, values=values
        )
        assert (
            await adapter.publish(request)
        ).outcome == Outcome.authorization_required
        assert not network.calls

    asyncio.run(run())


def test_workspace_and_authenticated_account_binding(sessions, monkeypatch):
    async def run():
        adapter, request, network, _, _ = await setup(sessions, monkeypatch)
        for wrong in [
            replace(request, workspace_id=uuid4()),
            replace(request, destination_id=uuid4()),
            replace(request, destination_identity="f" * 64),
        ]:
            assert (
                await adapter.publish(wrong)
            ).outcome == Outcome.authorization_required
        assert not network.calls
        network.identity_response = httpx.Response(
            200, json={"items": [{"id": "wrong-channel"}]}
        )
        assert (
            await adapter.publish(request)
        ).outcome == Outcome.authorization_required
        assert not network.uploads

    asyncio.run(run())


def test_refresh_uses_existing_oauth_and_store(sessions, monkeypatch):
    async def run():
        adapter, request, network, store, _ = await setup(
            sessions, monkeypatch, expired=True
        )
        assert (await adapter.publish(request)).outcome == Outcome.published
        assert [r.url.path for r in network.calls] == [
            "/token",
            "/youtube/v3/channels",
            "/upload/youtube/v3/videos",
        ]
        assert b"grant_type=refresh_token" in network.calls[0].content
        assert network.uploads[0].headers["Authorization"] == "Bearer NEW_ACCESS"
        async with sessions() as session:
            connection = await session.get(
                SocialAccountConnection, request.destination_id
            )
            assert connection.token_expires_at.replace(tzinfo=UTC) > datetime.now(UTC)
            values = (await store.get(connection.credential_ref)).expose()
            assert values["access_token"] == "NEW_ACCESS"
            assert values["refresh_token"] == REFRESH
            assert values["scope"] == SCOPES

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure", ["missing_refresh", "revoked", "scope_reduced", "store_unavailable"]
)
def test_refresh_failures_never_upload(sessions, monkeypatch, failure):
    async def run():
        adapter, request, network, store, _ = await setup(
            sessions,
            monkeypatch,
            expired=True,
            values={"refresh_token": ""} if failure == "missing_refresh" else {},
        )
        if failure == "revoked":
            network.refresh_response = httpx.Response(
                400, json={"error": "invalid_grant", "error_description": RAW}
            )
        if failure == "scope_reduced":
            network.refresh_response = httpx.Response(
                200,
                json={
                    "access_token": "NEW",
                    "scope": OAuthProvider.SCOPE_YOUTUBE_READONLY,
                    "expires_in": 3600,
                },
            )
        if failure == "store_unavailable":
            store.fail_operations.add("replace")
        result = await adapter.publish(request)
        assert result.outcome == (
            Outcome.retryable_failure
            if failure == "store_unavailable"
            else Outcome.authorization_required
        )
        assert not network.uploads

    asyncio.run(run())


@pytest.mark.parametrize("during", ["identity", "refresh"])
def test_connection_changed_during_io_blocks_write(sessions, monkeypatch, during):
    async def run():
        adapter, request, network, _, _ = await setup(
            sessions, monkeypatch, expired=during == "refresh"
        )

        async def disconnect():
            async with sessions.begin() as session:
                await session.execute(
                    update(SocialAccountConnection)
                    .where(SocialAccountConnection.id == request.destination_id)
                    .values(status="disconnected")
                )

        setattr(network, "on_" + during, disconnect)
        assert (
            await adapter.publish(request)
        ).outcome == Outcome.authorization_required
        assert not network.uploads

    asyncio.run(run())


@pytest.mark.parametrize(
    "status,reason,outcome",
    [
        (400, "invalidTitle", Outcome.permanent_failure),
        (400, "invalidDescription", Outcome.permanent_failure),
        (400, "uploadLimitExceeded", Outcome.rate_limited),
        (401, "authError", Outcome.authorization_required),
        (403, "insufficientPermissions", Outcome.authorization_required),
        (403, "quotaExceeded", Outcome.rate_limited),
        (429, "rateLimitExceeded", Outcome.rate_limited),
        (500, "backendError", Outcome.ambiguous),
        (400, "unknownFutureError", Outcome.ambiguous),
        (401, "unknownFutureError", Outcome.ambiguous),
    ],
)
def test_error_normalization_and_persistence(
    sessions, monkeypatch, status, reason, outcome
):
    async def run():
        adapter, request, network, _, _ = await setup(sessions, monkeypatch)
        network.upload_response = api_error(status, reason)
        result = await execute(sessions, adapter, request)
        assert result.reason_code == outcome.value
        assert result.retry_after_seconds == (
            30 if outcome == Outcome.rate_limited else None
        )
        assert len(network.uploads) == 1
        async with sessions() as session:
            row = await PublicationRepository(session, request.workspace_id).get(
                request.publication_id
            )
            assert row.status == result.status
            assert row.external_post_id is None
            assert RAW not in repr(row.transitions[-1].__dict__)

    asyncio.run(run())


@pytest.mark.parametrize(
    "response",
    [
        httpx.ReadTimeout(RAW),
        httpx.ConnectError(RAW),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={**success(), "id": "secret\n"}),
        httpx.Response(200, json={**success(), "snippet": {"channelId": "wrong"}}),
        httpx.Response(200, json={**success(), "status": {"uploadStatus": "rejected"}}),
        httpx.Response(302, headers={"Location": "https://evil.example"}),
        httpx.Response(503, json={"message": RAW}),
    ],
)
def test_uncertain_write_blocks_retry_and_reconcile(sessions, monkeypatch, response):
    async def run():
        adapter, request, network, _, _ = await setup(sessions, monkeypatch)
        network.upload_response = response
        assert (
            await execute(sessions, adapter, request)
        ).status == "manual_action_required"
        with pytest.raises(DeliveryIneligible):
            await execute(sessions, adapter, request)
        assert not adapter.capabilities.reconcile
        assert (await adapter.reconcile(request)).outcome == Outcome.unsupported
        assert len(network.uploads) == 1

    asyncio.run(run())


def test_explicit_retry_only_after_confirmed_rejection(sessions, monkeypatch):
    async def run():
        adapter, request, network, _, _ = await setup(sessions, monkeypatch)
        network.upload_response = api_error(403, "quotaExceeded")
        assert (await execute(sessions, adapter, request)).status == "retryable_failure"
        network.upload_response = httpx.Response(200, json=success())
        assert (await execute(sessions, adapter, request)).status == "published"
        async with sessions() as session:
            row = await PublicationRepository(session, request.workspace_id).get(
                request.publication_id
            )
            assert len(row.attempts) == 2
            assert row.external_post_id == VIDEO
        assert len(network.uploads) == 2

    asyncio.run(run())


def test_production_registry_reuses_oauth_provider(sessions, monkeypatch):
    async def run():
        _, _, _, store, oauth = await setup(sessions, monkeypatch)
        registry = publishing_provider_registry(
            sessions=sessions,
            social_account_registry=SocialAccountProviderRegistry([oauth]),
        )
        adapter = registry.resolve("youtube")
        assert adapter._connection_provider is oauth
        assert adapter._store is store
        empty = publishing_provider_registry(
            sessions=sessions, social_account_registry=SocialAccountProviderRegistry()
        )
        with pytest.raises(ProviderResolutionError):
            empty.resolve("youtube")
        with pytest.raises(ProviderResolutionError):
            registry.resolve("instagram")

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["missing", "unavailable"])
def test_credential_store_failures(sessions, monkeypatch, failure):
    async def run():
        adapter, request, network, store, _ = await setup(sessions, monkeypatch)
        if failure == "unavailable":
            store.fail_operations.add("get")
        else:
            async with sessions() as session:
                connection = await session.get(
                    SocialAccountConnection, request.destination_id
                )
            await store.delete(connection.credential_ref)
        result = await adapter.publish(request)
        assert result.outcome == (
            Outcome.retryable_failure
            if failure == "unavailable"
            else Outcome.authorization_required
        )
        assert result.confirmed_absent
        assert not network.calls

    asyncio.run(run())


@pytest.mark.parametrize(
    "response,outcome",
    [
        (httpx.ReadTimeout(RAW), Outcome.retryable_failure),
        (httpx.Response(200, content=b"bad-json"), Outcome.retryable_failure),
        (httpx.Response(401), Outcome.authorization_required),
        (api_error(403, "quotaExceeded"), Outcome.rate_limited),
        (httpx.Response(200, json={"items": []}), Outcome.authorization_required),
        (
            httpx.Response(200, json={"items": [{"id": CHANNEL}, {"id": "other"}]}),
            Outcome.authorization_required,
        ),
    ],
)
def test_identity_errors_prove_no_upload(sessions, monkeypatch, response, outcome):
    async def run():
        adapter, request, network, _, _ = await setup(sessions, monkeypatch)
        network.identity_response = response
        result = await adapter.publish(request)
        assert result.outcome == outcome
        assert result.confirmed_absent
        assert not network.uploads

    asyncio.run(run())


@pytest.mark.parametrize(
    "hint", ["-1", "604801", "tomorrow", "9" * 100, "\uff11\uff12"]
)
def test_invalid_retry_hints_are_not_persisted(sessions, monkeypatch, hint):
    async def run():
        adapter, request, network, _, _ = await setup(sessions, monkeypatch)
        response = api_error(429, "rateLimitExceeded")
        # Non-ASCII cannot be an HTTPX header; use a byte value to exercise it.
        response.headers = httpx.Headers({b"retry-after": hint.encode("utf-8")})
        network.upload_response = response
        result = await adapter.publish(request)
        assert result.outcome == Outcome.rate_limited
        assert result.retry_after_seconds is None

    asyncio.run(run())


def test_cancelled_upload_retains_attempt_and_cannot_be_reexecuted(
    sessions, monkeypatch
):
    async def run():
        adapter, request, network, _, _ = await setup(sessions, monkeypatch)
        network.upload_response = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await execute(sessions, adapter, request)
        async with sessions() as session:
            row = await PublicationRepository(session, request.workspace_id).get(
                request.publication_id
            )
            assert len(row.attempts) == 1
            assert row.transition_version == 1
            assert row.external_post_id is None
        with pytest.raises(DeliveryIneligible):
            await execute(sessions, adapter, request)
        assert len(network.uploads) == 1

    asyncio.run(run())


def test_oversize_and_multiple_assets_fail_before_credentials(sessions, monkeypatch):
    async def run():
        adapter, request, network, store, _ = await setup(sessions, monkeypatch)
        store.fail_operations.add("get")
        media = request.media[0]
        for assets in [
            (media, media),
            (replace(media, data=b"x" * (16 * 1024 * 1024 + 1)),),
        ]:
            result = await adapter.publish(replace(request, media=assets))
            assert result.outcome == Outcome.permanent_failure
        assert not network.calls

    asyncio.run(run())
