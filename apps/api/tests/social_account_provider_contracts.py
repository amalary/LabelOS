import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from labelos_database.models import SocialAccountConnectionMethod

from labelos_api.services.credential_store import (
    CredentialPayload,
    InMemoryCredentialStore,
)
from labelos_api.social_accounts.providers import (
    SocialAccountAuthorizationRequest,
    SocialAccountConnectionProvider,
    SocialAccountCredentialResult,
    SocialAccountHealth,
    SocialAccountIdentity,
    SocialAccountProviderError,
    SocialAccountProviderErrorCode,
    SocialAccountProviderRegistry,
)

SECRET_METADATA_KEYS = frozenset(
    {"access_token", "refresh_token", "id_token", "token", "client_secret"}
)
SECRET_SENTINELS = (
    "contract-access-secret",
    "contract-refresh-secret",
    "contract-client-secret",
    "contract-oauth-code",
)


@dataclass(frozen=True, kw_only=True)
class OAuthContract:
    scopes: tuple[str, ...]
    exchange_code: str
    expected_capabilities: tuple[str, ...]
    refresh_seed_credentials: Mapping[str, object] | None = None
    expected_refreshed_access_token: str | None = None


@dataclass(frozen=True, kw_only=True)
class ProviderContractCase:
    name: str
    provider: SocialAccountConnectionProvider
    provider_key: str
    connection_method: SocialAccountConnectionMethod
    identity_input: SocialAccountIdentity
    expected_identity: SocialAccountIdentity
    input_metadata: Mapping[str, object]
    expected_metadata_subset: Mapping[str, object]
    expected_capabilities: tuple[str, ...]
    unsupported_capability: str
    health_credential_ref: str | None = None
    health_token_expires_at: datetime | None = None
    expected_health_statuses: tuple[str, ...] = (
        "connected",
        "assisted_action_required",
        "not_applicable",
    )
    oauth: OAuthContract | None = None
    cleanup: Callable[[], Awaitable[None]] | None = None


def run_provider_contract(case: ProviderContractCase) -> None:
    async def run() -> None:
        try:
            _assert_registration_contract(case)
            _assert_identity_contract(case)
            _assert_capability_contract(case)
            await _assert_health_contract(case)
            await _assert_disconnect_contract(case)
            await _assert_error_contract(case)
            if case.oauth is not None:
                await _assert_oauth_contract(case)
        finally:
            if case.cleanup is not None:
                await case.cleanup()

    asyncio.run(run())


def _assert_registration_contract(case: ProviderContractCase) -> None:
    registry = SocialAccountProviderRegistry([case.provider])

    assert case.provider.provider.value == case.provider_key
    assert case.provider.connection_method == case.connection_method
    assert case.provider.supported_connection_methods() == (case.connection_method,)
    assert registry.resolve(case.provider_key, case.connection_method) is case.provider
    assert registry.supported_connection_methods(case.provider_key) == (
        case.connection_method,
    )


def _assert_identity_contract(case: ProviderContractCase) -> None:
    validation = case.provider.validate_account_input(
        case.identity_input,
        provider_metadata=case.input_metadata,
    )

    assert validation.identity == case.expected_identity
    assert isinstance(validation.provider_metadata, dict)
    assert_metadata_contains(
        validation.provider_metadata,
        case.expected_metadata_subset,
    )
    assert_no_secret_boundary_leak(validation.provider_metadata)


def _assert_capability_contract(case: ProviderContractCase) -> None:
    normalized = case.provider.normalize_capabilities(case.expected_capabilities)
    assert normalized == list(case.expected_capabilities)
    assert case.provider.normalize_capabilities(
        [*case.expected_capabilities, *case.expected_capabilities]
    ) == list(case.expected_capabilities)

    try:
        case.provider.normalize_capabilities([case.unsupported_capability])
    except SocialAccountProviderError as exc:
        assert exc.code in {
            SocialAccountProviderErrorCode.malformed_provider_response,
            SocialAccountProviderErrorCode.unsupported_connection_method,
            SocialAccountProviderErrorCode.insufficient_scope,
        }
        assert exc.provider == case.provider_key
        assert exc.connection_method == case.connection_method.value
        assert_no_secret_boundary_leak({"message": str(exc)})
    else:
        raise AssertionError(
            f"{case.name} accepted unsupported capability "
            f"{case.unsupported_capability!r}"
        )


async def _assert_health_contract(case: ProviderContractCase) -> None:
    health = await case.provider.check_connection_health(
        credential_ref=case.health_credential_ref,
        token_expires_at=case.health_token_expires_at,
        provider_metadata=case.input_metadata,
    )

    assert isinstance(health, SocialAccountHealth)
    assert isinstance(health.healthy, bool)
    assert health.status in case.expected_health_statuses
    if health.error_code is not None:
        assert isinstance(health.error_code, SocialAccountProviderErrorCode)
    assert_no_secret_boundary_leak(
        {
            "status": health.status,
            "message": health.error_message,
            "metadata": health.provider_metadata,
        }
    )


async def _assert_disconnect_contract(case: ProviderContractCase) -> None:
    result = await case.provider.disconnect(
        credential_ref=None,
        provider_metadata=case.input_metadata,
    )
    assert result is None


async def _assert_error_contract(case: ProviderContractCase) -> None:
    try:
        await case.provider.retrieve_account_identity(
            credential_ref=None,
            provider_metadata={},
        )
    except SocialAccountProviderError as exc:
        assert isinstance(exc.code, SocialAccountProviderErrorCode)
        assert exc.provider == case.provider_key
        assert exc.connection_method == case.connection_method.value
        assert_no_secret_boundary_leak({"message": str(exc)})
    else:
        raise AssertionError(f"{case.name} accepted missing account identity metadata")


async def _assert_oauth_contract(case: ProviderContractCase) -> None:
    assert case.oauth is not None
    redirect_uri = "https://labelos.test/oauth/social/callback"
    state = f"{case.name}-state"

    authorization = await case.provider.build_authorization_request(
        redirect_uri=redirect_uri,
        state=state,
        scopes=case.oauth.scopes,
        provider_metadata=case.input_metadata,
    )
    _assert_authorization_request_contract(
        authorization,
        redirect_uri=redirect_uri,
        state=state,
        scopes=case.oauth.scopes,
    )

    exchange = await case.provider.complete_oauth_exchange(
        code=case.oauth.exchange_code,
        redirect_uri=redirect_uri,
        provider_metadata=case.input_metadata,
    )
    assert isinstance(exchange, SocialAccountCredentialResult)
    assert exchange.credential_ref is None or isinstance(exchange.credential_ref, str)
    assert (
        exchange.credential_payload is not None or exchange.credential_ref is not None
    )
    assert_no_secret_boundary_leak(exchange.provider_metadata)

    identity = await case.provider.retrieve_account_identity(
        credential_ref=exchange.credential_ref,
        provider_metadata=exchange.provider_metadata,
    )
    assert identity.provider == case.provider_key
    assert identity.external_account_id

    mapper = getattr(case.provider, "capabilities_for_scopes", None)
    assert callable(mapper)
    assert mapper(exchange.granted_scopes) == list(case.oauth.expected_capabilities)

    if (
        case.oauth.refresh_seed_credentials is not None
        and case.oauth.expected_refreshed_access_token is not None
    ):
        await _assert_refresh_contract(case, case.oauth)


async def _assert_refresh_contract(
    case: ProviderContractCase,
    oauth: OAuthContract,
) -> None:
    store = getattr(case.provider, "credential_store", None)
    assert isinstance(store, InMemoryCredentialStore)

    credential_ref = await store.put(CredentialPayload(oauth.refresh_seed_credentials))
    refreshed = await case.provider.refresh_credentials(
        credential_ref=credential_ref,
        provider_metadata=case.input_metadata,
    )

    assert refreshed.credential_ref == credential_ref
    stored = (await store.get(credential_ref)).expose()
    assert stored["access_token"] == oauth.expected_refreshed_access_token
    assert_no_secret_boundary_leak(refreshed.provider_metadata)


def _assert_authorization_request_contract(
    authorization: SocialAccountAuthorizationRequest,
    *,
    redirect_uri: str,
    state: str,
    scopes: Sequence[str],
) -> None:
    assert authorization.state == state
    assert authorization.scopes == tuple(scopes)
    assert authorization.authorization_url.startswith("https://")
    assert_no_secret_boundary_leak(
        {
            "url": authorization.authorization_url,
            "metadata": authorization.metadata,
        }
    )

    query = parse_qs(urlparse(authorization.authorization_url).query)
    assert query["state"] == [state]
    assert query["redirect_uri"] == [redirect_uri]
    assert " ".join(scopes) in query.get("scope", [])


def assert_metadata_contains(
    metadata: Mapping[str, object],
    expected_subset: Mapping[str, object],
) -> None:
    for key, expected in expected_subset.items():
        assert metadata.get(key) == expected


def assert_no_secret_boundary_leak(value: object) -> None:
    serialized = json.dumps(value, default=str, sort_keys=True)
    for key in SECRET_METADATA_KEYS:
        assert f'"{key}"' not in serialized
    for secret in SECRET_SENTINELS:
        assert secret not in serialized
