import asyncio
import inspect
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from labelos_database.models import SocialAccountConnectionMethod

from labelos_api.services.credential_store import (
    CredentialPayload,
    InMemoryCredentialStore,
)
from labelos_api.social_accounts.providers import (
    AssistedSocialAccountConnectionProvider,
    FakeOAuthSocialAccountConnectionProvider,
    FakeThirdPartySocialAccountConnectionProvider,
    SocialAccountConnectionProvider,
    SocialAccountHealth,
    SocialAccountIdentity,
    SocialAccountProviderError,
    SocialAccountProviderErrorCode,
    SocialAccountProviderKey,
    SocialAccountProviderRegistry,
    YouTubeDirectProviderConfig,
    YouTubeDirectSocialAccountConnectionProvider,
    canonical_provider_key,
    default_social_account_provider_registry,
    social_account_provider_registry_from_settings,
)


class FakeDirectInstagramProvider(SocialAccountConnectionProvider):
    provider = SocialAccountProviderKey.instagram
    connection_method = SocialAccountConnectionMethod.direct_api

    def default_capabilities(self) -> tuple[str, ...]:
        return ("account_analytics_read", "post_analytics_read")

    async def check_connection_health(
        self,
        *,
        credential_ref: str | None,
        token_expires_at=None,
        provider_metadata=None,
    ) -> SocialAccountHealth:
        return SocialAccountHealth(healthy=False, status="expired")


class FailingIdentityProvider(FakeDirectInstagramProvider):
    async def retrieve_account_identity(
        self,
        *,
        credential_ref: str | None,
        provider_metadata=None,
    ) -> SocialAccountIdentity:
        raise SocialAccountProviderError(
            SocialAccountProviderErrorCode.credential_expired,
            "Credential expired",
            provider=self.provider,
            connection_method=self.connection_method,
        )


def test_provider_registry_registers_and_resolves_by_provider_and_method() -> None:
    assisted = AssistedSocialAccountConnectionProvider(
        SocialAccountProviderKey.instagram
    )
    direct = FakeOAuthSocialAccountConnectionProvider()
    third_party = FakeThirdPartySocialAccountConnectionProvider()
    registry = SocialAccountProviderRegistry([assisted, direct, third_party])

    assert registry.resolve("instagram", "assisted") is assisted
    assert registry.resolve("Instagram", "direct_api") is direct
    assert registry.resolve("instagram", "third_party") is third_party
    assert registry.supported_connection_methods("instagram") == (
        SocialAccountConnectionMethod.assisted,
        SocialAccountConnectionMethod.direct_api,
        SocialAccountConnectionMethod.third_party,
    )


def test_provider_registry_rejects_duplicate_registration() -> None:
    registry = SocialAccountProviderRegistry(
        [AssistedSocialAccountConnectionProvider(SocialAccountProviderKey.spotify)]
    )

    with pytest.raises(ValueError):
        registry.register(
            AssistedSocialAccountConnectionProvider(SocialAccountProviderKey.spotify)
        )


def test_default_registry_exposes_safe_provider_keys_without_direct_api_support() -> (
    None
):
    registry = default_social_account_provider_registry()

    for provider in SocialAccountProviderKey:
        adapter = registry.resolve(provider, SocialAccountConnectionMethod.assisted)
        assert adapter.provider == provider

        with pytest.raises(SocialAccountProviderError) as exc_info:
            registry.resolve(provider, SocialAccountConnectionMethod.direct_api)
        assert (
            exc_info.value.code
            == SocialAccountProviderErrorCode.unsupported_connection_method
        )
        with pytest.raises(SocialAccountProviderError) as third_party_exc_info:
            registry.resolve(provider, SocialAccountConnectionMethod.third_party)
        assert (
            third_party_exc_info.value.code
            == SocialAccountProviderErrorCode.unsupported_connection_method
        )


def test_fake_third_party_provider_normalizes_identity_capabilities_and_metadata() -> (
    None
):
    adapter = FakeThirdPartySocialAccountConnectionProvider("Instagram")

    async def run() -> dict[str, object]:
        authorization = await adapter.build_authorization_request(
            redirect_uri="https://labelos.test/social/callback",
            state="third-party-state",
            scopes=["publish", "post_metrics"],
        )
        exchange = await adapter.complete_oauth_exchange(
            code="success",
            redirect_uri="https://labelos.test/social/callback",
            provider_metadata={"third_party": {"region": "test"}},
        )
        identity = await adapter.retrieve_account_identity(
            credential_ref="memory://credentials/fake",
            provider_metadata=exchange.provider_metadata,
        )
        validation = adapter.validate_account_input(
            identity,
            provider_metadata=exchange.provider_metadata,
        )
        return {
            "authorization_url": authorization.authorization_url,
            "authorization_scopes": authorization.scopes,
            "capabilities": adapter.capabilities_for_scopes(exchange.granted_scopes),
            "identity": validation.identity,
            "metadata": validation.provider_metadata,
            "health": await adapter.check_connection_health(
                credential_ref="memory://credentials/fake",
                provider_metadata=validation.provider_metadata,
            ),
        }

    result = asyncio.run(run())
    assert result["authorization_url"].startswith(
        "https://fake-third-party.labelos.test/connect?"
    )
    assert result["authorization_scopes"] == ("publish", "post_metrics")
    assert result["capabilities"] == [
        "content_publish",
        "account_analytics_read",
        "post_analytics_read",
    ]
    assert result["identity"] == SocialAccountIdentity(
        provider="instagram",
        external_account_id="instagram-third-party-success",
        username="third_party_success",
        display_name="Fake Third-Party Account",
        profile_url="https://fake-third-party.labelos.test/instagram/success",
    )
    assert result["metadata"]["third_party"] == {
        "adapter_key": "fake_test",
        "external_integration_account_id": "fake-integration-success",
        "external_connection_id": "fake-connection-success",
    }
    assert result["metadata"]["external_account_id"] == "instagram-third-party-success"
    assert result["health"].healthy is True
    assert result["health"].status == "connected"


def test_configured_registry_exposes_youtube_direct_provider() -> None:
    registry = social_account_provider_registry_from_settings(
        youtube_client_id="youtube-client",
        youtube_client_secret="youtube-secret",
        credential_store=InMemoryCredentialStore(),
    )

    adapter = registry.resolve("youtube", SocialAccountConnectionMethod.direct_api)

    assert isinstance(adapter, YouTubeDirectSocialAccountConnectionProvider)


def test_registry_reports_unsupported_provider_and_method_separately() -> None:
    registry = SocialAccountProviderRegistry(
        [AssistedSocialAccountConnectionProvider(SocialAccountProviderKey.youtube)]
    )

    with pytest.raises(SocialAccountProviderError) as provider_exc:
        registry.resolve("threads", "assisted")
    assert (
        provider_exc.value.code == SocialAccountProviderErrorCode.unsupported_provider
    )

    with pytest.raises(SocialAccountProviderError) as method_exc:
        registry.resolve("youtube", "enterprise_partner")
    assert (
        method_exc.value.code
        == SocialAccountProviderErrorCode.unsupported_connection_method
    )


def test_provider_error_codes_are_normalized() -> None:
    provider = FailingIdentityProvider()

    async def run() -> None:
        with pytest.raises(SocialAccountProviderError) as exc_info:
            await provider.retrieve_account_identity(credential_ref="vault://expired")
        assert exc_info.value.code == SocialAccountProviderErrorCode.credential_expired
        assert exc_info.value.provider == "instagram"
        assert exc_info.value.connection_method == "direct_api"

    asyncio.run(run())


def test_capability_and_identity_normalization() -> None:
    adapter = AssistedSocialAccountConnectionProvider(SocialAccountProviderKey.x)

    assert canonical_provider_key("Twitter") == "x"
    assert adapter.normalize_capabilities(()) == ["manual_publish"]
    assert adapter.normalize_capabilities(["manual_publish", " manual_publish "]) == [
        "manual_publish"
    ]
    with pytest.raises(SocialAccountProviderError):
        adapter.normalize_capabilities(["account_analytics_read"])

    result = adapter.validate_account_input(
        SocialAccountIdentity(
            provider="twitter",
            external_account_id=" ext-1 ",
            username=" @LabelOS ",
            display_name=" Label OS ",
            profile_url=" https://x.com/labelos ",
        ),
        provider_metadata={"source": "manual"},
    )
    assert result.identity == SocialAccountIdentity(
        provider="x",
        external_account_id="ext-1",
        username="labelos",
        display_name="Label OS",
        profile_url="https://x.com/labelos",
    )
    assert result.provider_metadata == {"source": "manual"}


def test_assisted_provider_rejects_unsafe_profile_urls() -> None:
    adapter = AssistedSocialAccountConnectionProvider(
        SocialAccountProviderKey.instagram
    )

    with pytest.raises(SocialAccountProviderError):
        adapter.validate_account_input(
            SocialAccountIdentity(
                provider="instagram",
                username="labelos",
                profile_url="javascript:alert(1)",
            )
        )

    with pytest.raises(SocialAccountProviderError):
        adapter.validate_account_input(
            SocialAccountIdentity(
                provider="instagram",
                username="labelos",
                profile_url="https://user:pass@example.com/labelos",
            )
        )


def test_assisted_provider_health_is_manual_action_required() -> None:
    adapter = AssistedSocialAccountConnectionProvider(SocialAccountProviderKey.tiktok)

    async def run() -> SocialAccountHealth:
        return await adapter.check_connection_health(credential_ref=None)

    health = asyncio.run(run())
    assert health.healthy is True
    assert health.status == "assisted_action_required"


def _youtube_channel_response() -> dict[str, object]:
    return {
        "items": [
            {
                "id": "UC_LABELOS",
                "snippet": {
                    "title": "LabelOS Channel",
                    "customUrl": "@labelos",
                    "thumbnails": {"default": {"url": "https://yt.example/thumb.jpg"}},
                },
            }
        ]
    }


def _youtube_provider(
    handler,
    store: InMemoryCredentialStore | None = None,
) -> tuple[YouTubeDirectSocialAccountConnectionProvider, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = YouTubeDirectSocialAccountConnectionProvider(
        config=YouTubeDirectProviderConfig(
            client_id="youtube-client-id",
            client_secret="youtube-client-secret",
        ),
        credential_store=store or InMemoryCredentialStore(),
        http_client=client,
    )
    return provider, client


def test_youtube_direct_authorization_url_uses_official_google_oauth_parameters() -> (
    None
):
    provider, client = _youtube_provider(lambda request: httpx.Response(500))

    async def run() -> dict[str, object]:
        try:
            authorization = await provider.build_authorization_request(
                redirect_uri="https://labelos.test/oauth/youtube/callback",
                state="state-value",
                scopes=[
                    YouTubeDirectSocialAccountConnectionProvider.SCOPE_YOUTUBE_READONLY
                ],
            )
            query = parse_qs(urlparse(authorization.authorization_url).query)
            return {
                "url": authorization.authorization_url,
                "scopes": authorization.scopes,
                "query": query,
            }
        finally:
            await client.aclose()

    result = asyncio.run(run())
    assert result["url"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert result["scopes"] == (
        YouTubeDirectSocialAccountConnectionProvider.SCOPE_YOUTUBE_READONLY,
    )
    query = result["query"]
    assert query["client_id"] == ["youtube-client-id"]
    assert query["response_type"] == ["code"]
    assert query["access_type"] == ["offline"]
    assert query["include_granted_scopes"] == ["true"]
    assert query["prompt"] == ["consent"]
    assert query["state"] == ["state-value"]


def test_youtube_direct_successful_oauth_exchange_fetches_profile_and_capabilities():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url == "https://oauth2.googleapis.com/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "access-secret",
                    "refresh_token": "refresh-secret",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                    "scope": (
                        "https://www.googleapis.com/auth/youtube.readonly "
                        "https://www.googleapis.com/auth/youtube.upload "
                        "https://www.googleapis.com/auth/yt-analytics.readonly"
                    ),
                },
            )
        assert str(request.url).startswith(
            "https://www.googleapis.com/youtube/v3/channels"
        )
        assert request.headers["authorization"] == "Bearer access-secret"
        return httpx.Response(200, json=_youtube_channel_response())

    provider, client = _youtube_provider(handler)

    async def run() -> dict[str, object]:
        try:
            result = await provider.complete_oauth_exchange(
                code="oauth-code",
                redirect_uri="https://labelos.test/oauth/youtube/callback",
            )
            identity = await provider.retrieve_account_identity(
                credential_ref=None,
                provider_metadata=result.provider_metadata,
            )
            return {
                "credential": result.credential_payload,
                "scopes": result.granted_scopes,
                "capabilities": provider.capabilities_for_scopes(result.granted_scopes),
                "identity": identity,
                "metadata": result.provider_metadata,
                "request_count": len(requests),
            }
        finally:
            await client.aclose()

    result = asyncio.run(run())
    assert result["credential"]["access_token"] == "access-secret"
    assert result["credential"]["refresh_token"] == "refresh-secret"
    assert result["scopes"] == (
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    )
    assert result["capabilities"] == [
        "content_publish",
        "account_analytics_read",
        "post_analytics_read",
    ]
    assert result["identity"].external_account_id == "UC_LABELOS"
    assert result["identity"].username == "@labelos"
    assert result["identity"].display_name == "LabelOS Channel"
    assert result["metadata"]["thumbnail_url"] == "https://yt.example/thumb.jpg"
    assert result["request_count"] == 2


def test_youtube_direct_partial_scope_resolves_only_granted_functionality() -> None:
    provider, client = _youtube_provider(lambda request: httpx.Response(500))

    async def run() -> list[str]:
        try:
            return provider.capabilities_for_scopes(
                [YouTubeDirectSocialAccountConnectionProvider.SCOPE_YOUTUBE_READONLY]
            )
        finally:
            await client.aclose()

    assert asyncio.run(run()) == []


@pytest.mark.parametrize(
    ("status_code", "code"),
    [
        (401, SocialAccountProviderErrorCode.credential_expired),
        (403, SocialAccountProviderErrorCode.insufficient_scope),
        (429, SocialAccountProviderErrorCode.rate_limited),
        (503, SocialAccountProviderErrorCode.provider_unavailable),
    ],
)
def test_youtube_direct_provider_http_errors_are_safe_and_normalized(
    status_code: int,
    code: SocialAccountProviderErrorCode,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": "secret-provider-detail"})

    provider, client = _youtube_provider(handler)

    async def run() -> str:
        try:
            with pytest.raises(SocialAccountProviderError) as exc_info:
                await provider.complete_oauth_exchange(
                    code="oauth-code",
                    redirect_uri="https://labelos.test/oauth/youtube/callback",
                )
            assert exc_info.value.code == code
            return str(exc_info.value)
        finally:
            await client.aclose()

    message = asyncio.run(run())
    assert "secret-provider-detail" not in message
    assert "oauth-code" not in message


def test_youtube_direct_malformed_token_response_is_rejected() -> None:
    provider, client = _youtube_provider(
        lambda request: httpx.Response(200, json={"token_type": "Bearer"})
    )

    async def run() -> None:
        try:
            with pytest.raises(SocialAccountProviderError) as exc_info:
                await provider.complete_oauth_exchange(
                    code="oauth-code",
                    redirect_uri="https://labelos.test/oauth/youtube/callback",
                )
            assert (
                exc_info.value.code
                == SocialAccountProviderErrorCode.malformed_provider_response
            )
        finally:
            await client.aclose()

    asyncio.run(run())


def test_youtube_direct_malformed_profile_response_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        readonly_scope = (
            YouTubeDirectSocialAccountConnectionProvider.SCOPE_YOUTUBE_READONLY
        )
        if request.url == "https://oauth2.googleapis.com/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "access-secret",
                    "token_type": "Bearer",
                    "scope": readonly_scope,
                },
            )
        return httpx.Response(200, json={"items": [{"snippet": {}}]})

    provider, client = _youtube_provider(handler)

    async def run() -> None:
        try:
            with pytest.raises(SocialAccountProviderError) as exc_info:
                await provider.complete_oauth_exchange(
                    code="oauth-code",
                    redirect_uri="https://labelos.test/oauth/youtube/callback",
                )
            assert (
                exc_info.value.code
                == SocialAccountProviderErrorCode.malformed_provider_response
            )
        finally:
            await client.aclose()

    asyncio.run(run())


def test_youtube_direct_health_reports_expired_token_without_http() -> None:
    provider, client = _youtube_provider(lambda request: httpx.Response(500))

    async def run() -> SocialAccountHealth:
        try:
            return await provider.check_connection_health(
                credential_ref="memory://credentials/missing",
                token_expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        finally:
            await client.aclose()

    health = asyncio.run(run())
    assert health.healthy is False
    assert health.status == "expired"
    assert health.error_code == SocialAccountProviderErrorCode.credential_expired


def test_youtube_direct_refresh_replaces_stored_credentials() -> None:
    store = InMemoryCredentialStore()

    def handler(request: httpx.Request) -> httpx.Response:
        readonly_scope = (
            YouTubeDirectSocialAccountConnectionProvider.SCOPE_YOUTUBE_READONLY
        )
        return httpx.Response(
            200,
            json={
                "access_token": "new-access-secret",
                "expires_in": 1800,
                "token_type": "Bearer",
                "scope": readonly_scope,
            },
        )

    provider, client = _youtube_provider(handler, store)

    async def run() -> dict[str, object]:
        readonly_scope = (
            YouTubeDirectSocialAccountConnectionProvider.SCOPE_YOUTUBE_READONLY
        )
        try:
            credential_ref = await store.put(
                CredentialPayload(
                    {
                        "access_token": "old-access-secret",
                        "refresh_token": "refresh-secret",
                        "scope": readonly_scope,
                    }
                )
            )
            result = await provider.refresh_credentials(
                credential_ref=credential_ref,
                provider_metadata={"external_account_id": "UC_LABELOS"},
            )
            return {
                "ref": result.credential_ref,
                "stored": (await store.get(credential_ref)).expose(),
                "scopes": result.granted_scopes,
            }
        finally:
            await client.aclose()

    result = asyncio.run(run())
    assert result["ref"].startswith("memory://credentials/")
    assert result["stored"]["access_token"] == "new-access-secret"
    assert result["stored"]["refresh_token"] == "refresh-secret"
    assert result["scopes"] == (
        YouTubeDirectSocialAccountConnectionProvider.SCOPE_YOUTUBE_READONLY,
    )


def test_youtube_direct_revoke_disconnect_deletes_stored_credentials() -> None:
    store = InMemoryCredentialStore()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"")

    provider, client = _youtube_provider(handler, store)

    async def run() -> dict[str, object]:
        try:
            credential_ref = await store.put(
                CredentialPayload(
                    {
                        "access_token": "access-secret",
                        "refresh_token": "refresh-secret",
                    }
                )
            )
            await provider.disconnect(credential_ref=credential_ref)
            deleted = False
            try:
                await store.get(credential_ref)
            except Exception:
                deleted = True
            return {"deleted": deleted, "requests": requests}
        finally:
            await client.aclose()

    result = asyncio.run(run())
    assert result["deleted"] is True
    assert len(result["requests"]) == 1
    assert str(result["requests"][0].url) == "https://oauth2.googleapis.com/revoke"
    assert b"refresh-secret" in result["requests"][0].content


def test_youtube_direct_safe_logging_does_not_expose_credentials() -> None:
    payload = CredentialPayload(
        {
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
        }
    )
    provider_error = SocialAccountProviderError(
        SocialAccountProviderErrorCode.authorization_failed,
        "YouTube credential is expired or invalid",
        provider="youtube",
        connection_method=SocialAccountConnectionMethod.direct_api,
    )

    serialized = json.dumps(
        {
            "payload": repr(payload),
            "provider_error": str(provider_error),
        }
    )

    assert "access-secret" not in serialized
    assert "refresh-secret" not in serialized
    assert "REDACTED" in serialized


def test_connection_provider_contract_has_no_fastapi_request_dependency() -> None:
    for method_name, method in inspect.getmembers(
        SocialAccountConnectionProvider,
        predicate=inspect.isfunction,
    ):
        if (
            method_name.startswith("__")
            or method_name not in SocialAccountConnectionProvider.__dict__
        ):
            continue
        signature = inspect.signature(method)
        for parameter in signature.parameters.values():
            if parameter.name == "self":
                continue
            assert parameter.annotation is not inspect.Signature.empty
            assert "fastapi" not in repr(parameter.annotation).lower()
        assert "fastapi" not in repr(signature.return_annotation).lower()
