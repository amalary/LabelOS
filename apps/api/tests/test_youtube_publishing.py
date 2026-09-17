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
    MarketingContentItem,
    Publication,
    PublicationAttempt,
    PublicationTransition,
    RealtimeEvent,
    SchedulingJob,
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
from labelos_api.publishing.retries import FailureCategory
from labelos_api.publishing.youtube import YouTubePublishingAdapter
from labelos_api.repositories.publishing import PublicationRepository
from labelos_api.repositories.scheduling import snapshot_for
from labelos_api.scheduling.payload import canonical_json, prepare_request
from labelos_api.services import social_account_service as accounts
from labelos_api.services.credential_store import (
    CredentialPayload,
    InMemoryCredentialStore,
)
from labelos_api.services.delivery_orchestrator import (
    DeliveryIneligible,
    DeliveryOrchestrator,
)
from labelos_api.social_accounts.providers import SocialAccountProviderErrorCode as Code
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


async def execute(sessions, adapter, request, **command):
    service = DeliveryOrchestrator()
    if command.get("expected_version") is not None:
        async with sessions() as session:
            row = await PublicationRepository(session, request.workspace_id).get(
                request.publication_id
            )
            if row.next_retry_at:
                service.clock = lambda: row.next_retry_at
    return await service.execute(
        sessions,
        workspace_id=request.workspace_id,
        publication_id=request.publication_id,
        **command,
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
        if failure == "revoked":
            assert result.failure_category == FailureCategory.authentication
        if failure == "scope_reduced":
            assert result.failure_category == FailureCategory.authorization
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
        assert (
            await execute(
                sessions, adapter, request, execution_id=uuid4(), expected_version=2
            )
        ).status == "published"
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
        if isinstance(response, httpx.ReadTimeout):
            assert result.failure_category == FailureCategory.transient_network
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


@pytest.mark.parametrize(
    "condition,status,code,outcome",
    [
        (
            "missing_reference",
            "reconnect_required",
            "credential_missing",
            Outcome.authorization_required,
        ),
        (
            "missing_secret",
            "reconnect_required",
            "credential_missing",
            Outcome.authorization_required,
        ),
        (
            "invalid_reference",
            "reconnect_required",
            "credential_missing",
            Outcome.authorization_required,
        ),
        ("backend_down", "limited", "provider_unavailable", Outcome.retryable_failure),
        (
            "no_refresh",
            "reconnect_required",
            "credential_expired",
            Outcome.authorization_required,
        ),
        (
            "revoked",
            "reconnect_required",
            "credential_revoked",
            Outcome.authorization_required,
        ),
        (
            "refresh_denied",
            "reconnect_required",
            "refresh_failed",
            Outcome.authorization_required,
        ),
        (
            "refresh_timeout",
            "limited",
            "provider_unavailable",
            Outcome.retryable_failure,
        ),
        ("refresh_503", "limited", "provider_unavailable", Outcome.retryable_failure),
        ("refresh_rate_limit", "limited", "rate_limited", Outcome.rate_limited),
        (
            "refresh_malformed",
            "limited",
            "provider_unavailable",
            Outcome.retryable_failure,
        ),
        ("replace_down", "limited", "provider_unavailable", Outcome.retryable_failure),
        (
            "missing_scope",
            "limited",
            "insufficient_scope",
            Outcome.authorization_required,
        ),
        (
            "reduced_scope",
            "limited",
            "insufficient_scope",
            Outcome.authorization_required,
        ),
        (
            "empty_scope",
            "limited",
            "insufficient_scope",
            Outcome.authorization_required,
        ),
        (
            "identity_401",
            "reconnect_required",
            "authorization_failed",
            Outcome.authorization_required,
        ),
        (
            "upload_401",
            "reconnect_required",
            "authorization_failed",
            Outcome.authorization_required,
        ),
        (
            "upload_scope",
            "limited",
            "insufficient_scope",
            Outcome.authorization_required,
        ),
    ],
)
def test_stage6_health_and_secret_safe_persistence(
    sessions, monkeypatch, caplog, condition, status, code, outcome
):
    async def run():
        expired = condition in {
            "no_refresh",
            "revoked",
            "refresh_denied",
            "refresh_timeout",
            "refresh_503",
            "refresh_rate_limit",
            "refresh_malformed",
            "replace_down",
            "reduced_scope",
            "empty_scope",
        }
        adapter, request, network, store, _ = await setup(
            sessions,
            monkeypatch,
            expired=expired,
            values={"refresh_token": ""} if condition == "no_refresh" else {},
            connection_values=(
                {"credential_ref": None} if condition == "missing_reference" else {}
            ),
        )
        connection = await adapter._connection(request)
        ref = connection.credential_ref
        if condition == "missing_secret":
            await store.delete(ref)
        elif condition == "invalid_reference":
            from labelos_api.services.credential_store import (
                InvalidCredentialReferenceError,
            )

            async def invalid(_):
                raise InvalidCredentialReferenceError()

            monkeypatch.setattr(store, "get", invalid)
        elif condition in {"backend_down", "replace_down"}:
            store.fail_operations.add(
                "get" if condition == "backend_down" else "replace"
            )
        elif condition == "missing_scope":
            values = (await store.get(ref)).expose()
            await store.replace(ref, CredentialPayload({**values, "scope": ""}))
        elif condition in {"revoked", "refresh_denied"}:
            network.refresh_response = httpx.Response(
                400,
                json={
                    "error": (
                        "invalid_grant" if condition == "revoked" else "invalid_client"
                    ),
                    "error_description": RAW,
                },
            )
        elif condition == "refresh_timeout":
            network.refresh_response = httpx.ReadTimeout(RAW)
        elif condition in {"refresh_503", "refresh_rate_limit"}:
            network.refresh_response = httpx.Response(
                503 if condition == "refresh_503" else 429
            )
        elif condition == "refresh_malformed":
            network.refresh_response = httpx.Response(200, content=RAW.encode())
        elif condition in {"reduced_scope", "empty_scope"}:
            network.refresh_response = httpx.Response(
                200,
                json={
                    "access_token": "NEW_ACCESS",
                    "expires_in": 3600,
                    "scope": (
                        OAuthProvider.SCOPE_YOUTUBE_READONLY
                        if condition == "reduced_scope"
                        else ""
                    ),
                },
            )
        elif condition == "identity_401":
            network.identity_response = api_error(401, "authError")
        elif condition in {"upload_401", "upload_scope"}:
            network.upload_response = api_error(
                401 if condition == "upload_401" else 403,
                "authError" if condition == "upload_401" else "insufficientPermissions",
            )
        result = await execute(sessions, adapter, request)
        assert result.reason_code == outcome.value
        assert len(network.uploads) == (1 if condition.startswith("upload_") else 0)
        async with sessions() as session:
            row = await session.get(SocialAccountConnection, request.destination_id)
            assert row.status == status
            assert row.last_error_code == code
            assert row.last_health_checked_at is not None
            if code == "insufficient_scope":
                assert "content_publish" not in row.capabilities
            assert row.external_account_id == CHANNEL
            assert row.credential_ref == ref
            stored = repr(result) + caplog.text
            for model in (
                Publication,
                PublicationAttempt,
                PublicationTransition,
                RealtimeEvent,
            ):
                records = (await session.execute(select(model.__table__))).all()
                stored += repr(records)
            stored += repr([row.last_error_message, row.provider_metadata])
            for secret in (
                ACCESS,
                REFRESH,
                RAW,
                "NEW_ACCESS",
                "CLIENT_SECRET_SENTINEL",
                ref,
            ):
                if secret:
                    assert secret not in stored
            assert not any(
                "credential" in column.name or "token" in column.name
                for model in (Publication, PublicationAttempt, PublicationTransition)
                for column in model.__table__.columns
            )

    caplog.set_level(logging.INFO)
    caplog.set_level(logging.DEBUG, logger="labelos_api")
    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        {"status": "disconnected"},
        {"status": "pending"},
        {"status": "error"},
        {"status": "reconnect_required"},
        {"capabilities": []},
        {"last_error_code": "credential_revoked"},
    ],
)
def test_stage6_disabled_connections_never_read_secrets(sessions, monkeypatch, change):
    async def run():
        adapter, request, network, store, _ = await setup(
            sessions,
            monkeypatch,
            connection_values=change,
        )

        async def forbidden(_):
            pytest.fail("unusable connection accessed credential backend")

        monkeypatch.setattr(store, "get", forbidden)
        assert (
            await adapter.publish(request)
        ).outcome == Outcome.authorization_required
        assert not network.calls
        async with sessions() as session:
            row = await session.get(SocialAccountConnection, request.destination_id)
            assert row.last_health_checked_at is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        {"status": "disconnected"},
        {"external_account_id": "replacement"},
        {"credential_ref": "memory://replacement"},
        {"capabilities": []},
    ],
)
@pytest.mark.parametrize(
    "observation", [None, Code.credential_revoked, Code.insufficient_scope]
)
def test_stage6_stale_health_does_not_overwrite_connection(
    sessions, monkeypatch, change, observation
):
    async def run():
        adapter, request, _, _, _ = await setup(sessions, monkeypatch)
        snapshot = await adapter._connection(request)
        async with sessions.begin() as session:
            await session.execute(
                update(SocialAccountConnection)
                .where(
                    SocialAccountConnection.id == request.destination_id,
                )
                .values(**change)
            )
        await adapter._accounts.observe(snapshot, observation)
        async with sessions() as session:
            row = await session.get(SocialAccountConnection, request.destination_id)
            for key, value in change.items():
                assert getattr(row, key) == value
            assert row.last_health_checked_at is None
            assert row.last_error_code is None

    asyncio.run(run())


def test_stage6_workspace_attack_cannot_access_or_change_health(sessions, monkeypatch):
    async def run():
        adapter, request, network, store, _ = await setup(sessions, monkeypatch)
        snapshot = await adapter._connection(request)

        async def forbidden(_):
            pytest.fail("cross-workspace request read credentials")

        monkeypatch.setattr(store, "get", forbidden)
        foreign = uuid4()
        assert (
            await adapter.publish(replace(request, workspace_id=foreign))
        ).outcome == Outcome.authorization_required
        async with sessions() as session:
            assert not await accounts.record_execution_health(
                session,
                expected=replace(snapshot, workspace_id=foreign),
                error_code=Code.credential_revoked,
            )
        assert not network.calls
        async with sessions() as session:
            row = await session.get(SocialAccountConnection, request.destination_id)
            assert row.status == "limited"
            assert row.last_health_checked_at is None

    asyncio.run(run())


def test_stage6_backend_recovery_clears_health(sessions, monkeypatch):
    async def run():
        adapter, request, _, store, _ = await setup(sessions, monkeypatch)
        store.fail_operations.add("get")
        assert (await execute(sessions, adapter, request)).status == "retryable_failure"
        store.fail_operations.clear()
        assert (
            await execute(
                sessions, adapter, request, execution_id=uuid4(), expected_version=2
            )
        ).status == "published"
        async with sessions() as session:
            row = await session.get(SocialAccountConnection, request.destination_id)
            assert row.status == "limited"
            assert row.last_error_code is None
            assert row.last_error_message is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "response", [api_error(401, "authError"), httpx.Response(200, json=success())]
)
def test_stage6_health_storage_failure_preserves_delivery_evidence(
    sessions, monkeypatch, response
):
    async def run():
        from sqlalchemy.exc import OperationalError

        adapter, request, network, _, _ = await setup(sessions, monkeypatch)
        network.upload_response = response

        async def unavailable(*args, **kwargs):
            raise OperationalError(RAW, {}, Exception(ACCESS))

        monkeypatch.setattr(accounts, "record_execution_health", unavailable)
        result = await execute(sessions, adapter, request)
        assert result.reason_code == (
            "published" if response.status_code == 200 else "authorization_required"
        )
        assert len(network.uploads) == 1

    asyncio.run(run())


@pytest.mark.parametrize("expired", [False, True])
def test_stage6_real_delivery_preparation_and_backend_recovery(
    sessions, monkeypatch, expired
):
    async def run():
        from labelos_database.models import MarketingContentItemChannel
        from labelos_database.scheduling import SchedulingUTCDateTime

        # SQLite drops timezone information from the legacy channel timestamp.
        # Match PostgreSQL's UTC read semantics without replacing business checks.
        monkeypatch.setattr(
            MarketingContentItemChannel.__table__.c.scheduled_at,
            "type",
            SchedulingUTCDateTime(),
        )
        prepare_execution = DeliveryOrchestrator.prepare_execution
        adapter, request, network, store, _ = await setup(
            sessions,
            monkeypatch,
            expired=expired,
        )
        monkeypatch.setattr(
            DeliveryOrchestrator, "prepare_execution", prepare_execution
        )
        # Seed a durably accepted Scheduling source. Execution preparation,
        # source authorization, credential checks and evidence persistence are real.
        # This SQLite test does not claim to validate PostgreSQL lock semantics.
        async with sessions.begin() as session:
            publication = await PublicationRepository(
                session, request.workspace_id
            ).get(request.publication_id)
            await session.execute(
                update(MarketingContentItem)
                .where(
                    MarketingContentItem.id == publication.marketing_content_item_id,
                )
                .values(
                    status="approved",
                    approved_revision=1,
                    approval_request_id=publication.approval_request_id,
                )
            )
            await session.execute(
                update(SchedulingJob)
                .where(
                    SchedulingJob.id == publication.scheduling_job_id,
                )
                .values(
                    status="handed_off",
                    handed_off_at=datetime.now(UTC),
                    handoff_receipt_id=publication.receipt_id,
                )
            )
        store.fail_operations.add("get")
        assert (await execute(sessions, adapter, request)).status == "retryable_failure"
        assert not network.calls
        store.fail_operations.clear()
        assert (
            await execute(
                sessions, adapter, request, execution_id=uuid4(), expected_version=2
            )
        ).status == "published"
        assert len(network.uploads) == 1

    asyncio.run(run())


@pytest.mark.parametrize("expiry", [None, datetime.now(UTC) + timedelta(seconds=30)])
def test_stage6_unknown_or_near_expiry_refreshes(sessions, monkeypatch, expiry):
    async def run():
        adapter, request, network, _, _ = await setup(
            sessions,
            monkeypatch,
            connection_values={"token_expires_at": expiry},
        )
        assert (await adapter.publish(request)).outcome == Outcome.published
        assert network.calls[0].url.path == "/token"
        assert len(network.uploads) == 1

    asyncio.run(run())


def test_stage6_revocation_observed_during_reconnect_is_stale(sessions, monkeypatch):
    async def run():
        adapter, request, network, _, _ = await setup(
            sessions, monkeypatch, expired=True
        )

        async def reconnect():
            async with sessions.begin() as session:
                await session.execute(
                    update(SocialAccountConnection)
                    .where(
                        SocialAccountConnection.id == request.destination_id,
                    )
                    .values(credential_ref="memory://replacement")
                )

        network.on_refresh = reconnect
        network.refresh_response = httpx.Response(400, json={"error": "invalid_grant"})
        assert (
            await adapter.publish(request)
        ).outcome == Outcome.authorization_required
        assert not network.uploads
        async with sessions() as session:
            connection = await session.get(
                SocialAccountConnection, request.destination_id
            )
            assert connection.status == "limited"
            assert connection.credential_ref == "memory://replacement"
            assert connection.last_error_code is None

    asyncio.run(run())


def test_stage6_ephemeral_credentials_exclude_refresh_material(sessions, monkeypatch):
    async def run():
        adapter, request, network, _, _ = await setup(sessions, monkeypatch)
        connection = await adapter._connection(request)
        _, credential = await adapter._accounts.credentials(connection)
        assert credential.expose() == {"access_token": ACCESS}
        for secret in (ACCESS, REFRESH, connection.credential_ref, CHANNEL):
            assert secret not in repr(connection) + repr(credential)
        assert not network.calls

    asyncio.run(run())
