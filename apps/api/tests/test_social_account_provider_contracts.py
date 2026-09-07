import httpx
import pytest
from labelos_database.models import SocialAccountConnectionMethod

from labelos_api.services.credential_store import InMemoryCredentialStore
from labelos_api.social_accounts.providers import (
    AssistedSocialAccountConnectionProvider,
    FakeOAuthSocialAccountConnectionProvider,
    FakeThirdPartySocialAccountConnectionProvider,
    SocialAccountIdentity,
    SocialAccountProviderKey,
    YouTubeDirectProviderConfig,
    YouTubeDirectSocialAccountConnectionProvider,
)
from social_account_provider_contracts import (
    OAuthContract,
    ProviderContractCase,
    run_provider_contract,
)


def _youtube_channel_response() -> dict[str, object]:
    return {
        "items": [
            {
                "id": "UC_CONTRACT",
                "snippet": {
                    "title": "Contract Channel",
                    "customUrl": "@contract",
                    "thumbnails": {
                        "default": {"url": "https://youtube.test/thumb.jpg"}
                    },
                },
            }
        ]
    }


def _youtube_contract_case() -> ProviderContractCase:
    store = InMemoryCredentialStore()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if str(request.url) == "https://oauth2.googleapis.com/token":
            body = request.content.decode("utf-8")
            if "grant_type=refresh_token" in body:
                return httpx.Response(
                    200,
                    json={
                        "access_token": "contract-refreshed-access-secret",
                        "expires_in": 1800,
                        "token_type": "Bearer",
                        "scope": (
                            "https://www.googleapis.com/auth/youtube.upload "
                            "https://www.googleapis.com/auth/yt-analytics.readonly"
                        ),
                    },
                )
            return httpx.Response(
                200,
                json={
                    "access_token": "contract-access-secret",
                    "refresh_token": "contract-refresh-secret",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                    "scope": (
                        "https://www.googleapis.com/auth/youtube.upload "
                        "https://www.googleapis.com/auth/yt-analytics.readonly"
                    ),
                },
            )
        if str(request.url) == "https://oauth2.googleapis.com/revoke":
            return httpx.Response(200, content=b"")
        return httpx.Response(200, json=_youtube_channel_response())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = YouTubeDirectSocialAccountConnectionProvider(
        config=YouTubeDirectProviderConfig(
            client_id="contract-youtube-client",
            client_secret="contract-client-secret",
        ),
        credential_store=store,
        http_client=client,
    )

    return ProviderContractCase(
        name="youtube-direct",
        provider=provider,
        provider_key="youtube",
        connection_method=SocialAccountConnectionMethod.direct_api,
        identity_input=SocialAccountIdentity(
            provider="YouTube",
            external_account_id=" UC_CONTRACT ",
            username=" @contract ",
            display_name=" Contract Channel ",
            profile_url=" https://www.youtube.com/channel/UC_CONTRACT ",
        ),
        expected_identity=SocialAccountIdentity(
            provider="youtube",
            external_account_id="UC_CONTRACT",
            username="@contract",
            display_name="Contract Channel",
            profile_url="https://www.youtube.com/channel/UC_CONTRACT",
        ),
        input_metadata={
            "external_account_id": "UC_CONTRACT",
            "handle": "@contract",
            "display_name": "Contract Channel",
            "profile_url": "https://www.youtube.com/channel/UC_CONTRACT",
        },
        expected_metadata_subset={"external_account_id": "UC_CONTRACT"},
        expected_capabilities=(
            "content_publish",
            "account_analytics_read",
            "post_analytics_read",
        ),
        unsupported_capability="manual_publish",
        health_credential_ref=None,
        expected_health_statuses=("connected",),
        oauth=OAuthContract(
            scopes=(
                YouTubeDirectSocialAccountConnectionProvider.SCOPE_YOUTUBE_UPLOAD,
                YouTubeDirectSocialAccountConnectionProvider.SCOPE_YT_ANALYTICS_READONLY,
            ),
            exchange_code="success",
            expected_capabilities=(
                "content_publish",
                "account_analytics_read",
                "post_analytics_read",
            ),
            refresh_seed_credentials={
                "access_token": "old-contract-access-secret",
                "refresh_token": "contract-refresh-secret",
                "scope": (
                    "https://www.googleapis.com/auth/youtube.upload "
                    "https://www.googleapis.com/auth/yt-analytics.readonly"
                ),
            },
            expected_refreshed_access_token="contract-refreshed-access-secret",
        ),
        cleanup=client.aclose,
    )


def _contract_cases() -> list[ProviderContractCase]:
    return [
        ProviderContractCase(
            name="assisted-x",
            provider=AssistedSocialAccountConnectionProvider(
                SocialAccountProviderKey.x
            ),
            provider_key="x",
            connection_method=SocialAccountConnectionMethod.assisted,
            identity_input=SocialAccountIdentity(
                provider="Twitter",
                external_account_id=" assisted-1 ",
                username=" @Contract ",
                display_name=" Contract Account ",
                profile_url=" https://x.com/contract ",
            ),
            expected_identity=SocialAccountIdentity(
                provider="x",
                external_account_id="assisted-1",
                username="contract",
                display_name="Contract Account",
                profile_url="https://x.com/contract",
            ),
            input_metadata={"source": "manual-entry"},
            expected_metadata_subset={"source": "manual-entry"},
            expected_capabilities=("manual_publish",),
            unsupported_capability="content_publish",
            expected_health_statuses=("assisted_action_required",),
        ),
        ProviderContractCase(
            name="fake-direct-oauth",
            provider=FakeOAuthSocialAccountConnectionProvider(),
            provider_key="instagram",
            connection_method=SocialAccountConnectionMethod.direct_api,
            identity_input=SocialAccountIdentity(
                provider="Instagram",
                external_account_id=" direct-1 ",
                username=" Contract_Direct ",
                display_name=" Contract Direct ",
                profile_url=" https://instagram.test/contract ",
            ),
            expected_identity=SocialAccountIdentity(
                provider="instagram",
                external_account_id="direct-1",
                username="Contract_Direct",
                display_name="Contract Direct",
                profile_url="https://instagram.test/contract",
            ),
            input_metadata={"external_account_id": "direct-1"},
            expected_metadata_subset={"external_account_id": "direct-1"},
            expected_capabilities=(
                "content_publish",
                "account_analytics_read",
                "post_analytics_read",
            ),
            unsupported_capability="manual_publish",
            expected_health_statuses=("not_applicable",),
            oauth=OAuthContract(
                scopes=("publish", "account_metrics", "post_metrics"),
                exchange_code="success",
                expected_capabilities=(
                    "content_publish",
                    "account_analytics_read",
                    "post_analytics_read",
                ),
            ),
        ),
        _youtube_contract_case(),
        ProviderContractCase(
            name="fake-third-party",
            provider=FakeThirdPartySocialAccountConnectionProvider(
                SocialAccountProviderKey.instagram
            ),
            provider_key="instagram",
            connection_method=SocialAccountConnectionMethod.third_party,
            identity_input=SocialAccountIdentity(
                provider="Instagram",
                external_account_id=" third-party-1 ",
                username=" @Third_Party ",
                display_name=" Contract Third Party ",
                profile_url=" https://third-party.test/contract ",
            ),
            expected_identity=SocialAccountIdentity(
                provider="instagram",
                external_account_id="third-party-1",
                username="third_party",
                display_name="Contract Third Party",
                profile_url="https://third-party.test/contract",
            ),
            input_metadata={
                "external_account_id": "third-party-1",
                "third_party": {
                    "external_integration_account_id": "integration-1",
                    "external_connection_id": "connection-1",
                },
            },
            expected_metadata_subset={
                "external_account_id": "third-party-1",
                "third_party": {
                    "adapter_key": "fake_test",
                    "external_integration_account_id": "integration-1",
                    "external_connection_id": "connection-1",
                },
            },
            expected_capabilities=(
                "content_publish",
                "account_analytics_read",
                "post_analytics_read",
            ),
            unsupported_capability="manual_publish",
            health_credential_ref="memory://credentials/fake-third-party",
            expected_health_statuses=("connected",),
            oauth=OAuthContract(
                scopes=("publish", "account_metrics", "post_metrics"),
                exchange_code="success",
                expected_capabilities=(
                    "content_publish",
                    "account_analytics_read",
                    "post_analytics_read",
                ),
            ),
        ),
    ]


@pytest.mark.parametrize("case", _contract_cases(), ids=lambda case: case.name)
def test_social_account_provider_contract(case: ProviderContractCase) -> None:
    run_provider_contract(case)
