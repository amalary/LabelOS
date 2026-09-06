from abc import ABC
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from labelos_database.models import SocialAccountConnectionMethod


class SocialAccountProviderKey(StrEnum):
    instagram = "instagram"
    facebook = "facebook"
    tiktok = "tiktok"
    youtube = "youtube"
    spotify = "spotify"
    x = "x"


class SocialAccountProviderErrorCode(StrEnum):
    unsupported_provider = "unsupported_provider"
    unsupported_connection_method = "unsupported_connection_method"
    provider_unavailable = "provider_unavailable"
    authorization_failed = "authorization_failed"
    insufficient_scope = "insufficient_scope"
    credential_expired = "credential_expired"
    account_not_found = "account_not_found"
    malformed_provider_response = "malformed_provider_response"


class SocialAccountProviderError(ValueError):
    """Provider-neutral connection error suitable for service/API normalization."""

    def __init__(
        self,
        code: SocialAccountProviderErrorCode | str,
        message: str,
        *,
        provider: str | None = None,
        connection_method: SocialAccountConnectionMethod | str | None = None,
    ) -> None:
        normalized_code = (
            code
            if isinstance(code, SocialAccountProviderErrorCode)
            else SocialAccountProviderErrorCode(code)
        )
        super().__init__(message)
        self.code = normalized_code
        self.provider = provider
        self.connection_method = (
            connection_method.value
            if isinstance(connection_method, SocialAccountConnectionMethod)
            else connection_method
        )


@dataclass(frozen=True, kw_only=True)
class SocialAccountIdentity:
    provider: str
    external_account_id: str | None = None
    username: str | None = None
    display_name: str | None = None
    profile_url: str | None = None


@dataclass(frozen=True, kw_only=True)
class SocialAccountValidationResult:
    identity: SocialAccountIdentity
    provider_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class SocialAccountAuthorizationRequest:
    authorization_url: str
    state: str
    scopes: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class SocialAccountCredentialResult:
    credential_ref: str | None = None
    token_expires_at: datetime | None = None
    granted_scopes: tuple[str, ...] = ()
    provider_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class SocialAccountHealth:
    healthy: bool
    status: str = "unknown"
    error_code: SocialAccountProviderErrorCode | None = None
    error_message: str | None = None
    provider_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class SocialAccountMetadataSync:
    identity: SocialAccountIdentity | None = None
    capabilities: tuple[str, ...] = ()
    provider_metadata: dict[str, object] = field(default_factory=dict)


class SocialAccountConnectionProvider(ABC):
    """Provider-neutral contract for account connection lifecycle behavior.

    Publishing and analytics operations intentionally do not live here. Future
    content delivery and metrics retrieval should use separate provider contracts
    that can depend on a connected account without coupling connection setup to
    publishing/analytics semantics.
    """

    provider: SocialAccountProviderKey
    connection_method: SocialAccountConnectionMethod

    def validate_account_input(
        self,
        identity: SocialAccountIdentity,
        *,
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountValidationResult:
        return SocialAccountValidationResult(
            identity=self.normalize_account_identity(identity),
            provider_metadata=dict(provider_metadata or {}),
        )

    def supported_connection_methods(self) -> tuple[SocialAccountConnectionMethod, ...]:
        return (self.connection_method,)

    def default_capabilities(self) -> tuple[str, ...]:
        return ()

    def normalize_capabilities(self, capabilities: Sequence[str] | None) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for capability in capabilities or self.default_capabilities():
            if not isinstance(capability, str) or not capability.strip():
                raise SocialAccountProviderError(
                    SocialAccountProviderErrorCode.malformed_provider_response,
                    "Social account capabilities must be non-empty strings",
                    provider=self.provider,
                    connection_method=self.connection_method,
                )
            key = capability.strip()
            if key not in seen:
                normalized.append(key)
                seen.add(key)
        return normalized

    def normalize_account_identity(
        self,
        identity: SocialAccountIdentity,
    ) -> SocialAccountIdentity:
        return SocialAccountIdentity(
            provider=canonical_provider_key(identity.provider),
            external_account_id=_optional_text(identity.external_account_id),
            username=_optional_text(identity.username),
            display_name=_optional_text(identity.display_name),
            profile_url=_optional_text(identity.profile_url),
        )

    async def build_authorization_request(
        self,
        *,
        redirect_uri: str,
        state: str,
        scopes: Sequence[str] = (),
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountAuthorizationRequest:
        raise SocialAccountProviderError(
            SocialAccountProviderErrorCode.provider_unavailable,
            "Authorization is not implemented for this provider connection method",
            provider=self.provider,
            connection_method=self.connection_method,
        )

    async def complete_oauth_exchange(
        self,
        *,
        code: str,
        redirect_uri: str,
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountCredentialResult:
        raise SocialAccountProviderError(
            SocialAccountProviderErrorCode.provider_unavailable,
            "OAuth exchange is not implemented for this provider connection method",
            provider=self.provider,
            connection_method=self.connection_method,
        )

    async def refresh_credentials(
        self,
        *,
        credential_ref: str,
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountCredentialResult:
        raise SocialAccountProviderError(
            SocialAccountProviderErrorCode.provider_unavailable,
            "Credential refresh is not implemented for this provider connection method",
            provider=self.provider,
            connection_method=self.connection_method,
        )

    async def retrieve_account_identity(
        self,
        *,
        credential_ref: str | None,
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountIdentity:
        raise SocialAccountProviderError(
            SocialAccountProviderErrorCode.provider_unavailable,
            "Account identity retrieval is not implemented for this provider "
            "connection method",
            provider=self.provider,
            connection_method=self.connection_method,
        )

    async def check_connection_health(
        self,
        *,
        credential_ref: str | None,
        token_expires_at: datetime | None = None,
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountHealth:
        return SocialAccountHealth(healthy=True, status="not_applicable")

    async def synchronize_account_metadata(
        self,
        *,
        credential_ref: str | None,
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountMetadataSync:
        return SocialAccountMetadataSync(
            provider_metadata=dict(provider_metadata or {})
        )

    async def disconnect(
        self,
        *,
        credential_ref: str | None,
        provider_metadata: Mapping[str, object] | None = None,
    ) -> None:
        return None


class AssistedSocialAccountConnectionProvider(SocialAccountConnectionProvider):
    connection_method = SocialAccountConnectionMethod.assisted

    def __init__(self, provider: SocialAccountProviderKey | str) -> None:
        self.provider = SocialAccountProviderKey(canonical_provider_key(provider))

    def default_capabilities(self) -> tuple[str, ...]:
        return ("manual_publish",)


class SocialAccountProviderRegistry:
    def __init__(
        self,
        adapters: Sequence[SocialAccountConnectionProvider] = (),
    ) -> None:
        self._adapters: dict[
            tuple[SocialAccountProviderKey, SocialAccountConnectionMethod],
            SocialAccountConnectionProvider,
        ] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(
        self,
        adapter: SocialAccountConnectionProvider,
        *,
        replace: bool = False,
    ) -> None:
        key = (
            SocialAccountProviderKey(canonical_provider_key(adapter.provider)),
            _coerce_connection_method(adapter.connection_method),
        )
        if key in self._adapters and not replace:
            raise ValueError(
                f"Social account provider adapter already registered: "
                f"{key[0].value}+{key[1].value}"
            )
        self._adapters[key] = adapter

    def resolve(
        self,
        provider: SocialAccountProviderKey | str,
        connection_method: SocialAccountConnectionMethod | str,
    ) -> SocialAccountConnectionProvider:
        provider_key = _coerce_provider_key(provider)
        method = _coerce_connection_method(connection_method)
        adapter = self._adapters.get((provider_key, method))
        if adapter is None:
            if any(key_provider == provider_key for key_provider, _ in self._adapters):
                raise SocialAccountProviderError(
                    SocialAccountProviderErrorCode.unsupported_connection_method,
                    "Unsupported social account connection method",
                    provider=provider_key.value,
                    connection_method=method,
                )
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.unsupported_provider,
                "Unsupported social account provider",
                provider=provider_key.value,
                connection_method=method,
            )
        return adapter

    def supported_connection_methods(
        self,
        provider: SocialAccountProviderKey | str,
    ) -> tuple[SocialAccountConnectionMethod, ...]:
        provider_key = _coerce_provider_key(provider)
        methods = sorted(
            (
                method
                for adapter_provider, method in self._adapters
                if adapter_provider == provider_key
            ),
            key=lambda method: method.value,
        )
        if not methods:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.unsupported_provider,
                "Unsupported social account provider",
                provider=provider_key.value,
            )
        return tuple(methods)


def canonical_provider_key(provider: SocialAccountProviderKey | str) -> str:
    raw = provider.value if isinstance(provider, SocialAccountProviderKey) else provider
    normalized = raw.strip().lower().replace("-", "_")
    aliases = {
        "twitter": "x",
        "twitter_x": "x",
    }
    normalized = aliases.get(normalized, normalized)
    try:
        return SocialAccountProviderKey(normalized).value
    except ValueError as exc:
        raise SocialAccountProviderError(
            SocialAccountProviderErrorCode.unsupported_provider,
            "Unsupported social account provider",
            provider=normalized,
        ) from exc


def default_social_account_provider_registry() -> SocialAccountProviderRegistry:
    return SocialAccountProviderRegistry(
        [
            AssistedSocialAccountConnectionProvider(provider)
            for provider in SocialAccountProviderKey
        ]
    )


def _coerce_provider_key(
    provider: SocialAccountProviderKey | str,
) -> SocialAccountProviderKey:
    return SocialAccountProviderKey(canonical_provider_key(provider))


def _coerce_connection_method(
    connection_method: SocialAccountConnectionMethod | str,
) -> SocialAccountConnectionMethod:
    try:
        return (
            connection_method
            if isinstance(connection_method, SocialAccountConnectionMethod)
            else SocialAccountConnectionMethod(connection_method)
        )
    except ValueError as exc:
        raise SocialAccountProviderError(
            SocialAccountProviderErrorCode.unsupported_connection_method,
            "Unsupported social account connection method",
            connection_method=str(connection_method),
        ) from exc


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


provider_registry = default_social_account_provider_registry()


def resolve_social_account_provider(
    provider: SocialAccountProviderKey | str,
    connection_method: SocialAccountConnectionMethod | str,
) -> SocialAccountConnectionProvider:
    return provider_registry.resolve(provider, connection_method)
