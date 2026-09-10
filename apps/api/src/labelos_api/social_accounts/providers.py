from abc import ABC
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from urllib.parse import urlencode, urlparse

import httpx
from labelos_database.models import SocialAccountConnectionMethod

from labelos_api.services.credential_store import (
    CredentialNotFoundError,
    CredentialPayload,
    CredentialStore,
    CredentialStoreError,
    InvalidCredentialReferenceError,
)


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
    third_party_service_unavailable = "third_party_service_unavailable"
    authorization_failed = "authorization_failed"
    insufficient_scope = "insufficient_scope"
    credential_missing = "credential_missing"
    credential_expired = "credential_expired"
    credential_revoked = "credential_revoked"
    refresh_failed = "refresh_failed"
    account_not_found = "account_not_found"
    malformed_provider_response = "malformed_provider_response"
    rate_limited = "rate_limited"
    sync_failed = "sync_failed"


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
    credential_payload: Mapping[str, object] | None = None
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
    _allowed_capabilities = frozenset({"manual_publish"})

    def __init__(self, provider: SocialAccountProviderKey | str) -> None:
        self.provider = SocialAccountProviderKey(canonical_provider_key(provider))

    def default_capabilities(self) -> tuple[str, ...]:
        return ("manual_publish",)

    def normalize_account_identity(
        self,
        identity: SocialAccountIdentity,
    ) -> SocialAccountIdentity:
        normalized = super().normalize_account_identity(identity)
        return SocialAccountIdentity(
            provider=normalized.provider,
            external_account_id=normalized.external_account_id,
            username=_normalize_handle(normalized.username),
            display_name=normalized.display_name,
            profile_url=_validate_profile_url(normalized.profile_url),
        )

    def normalize_capabilities(self, capabilities: Sequence[str] | None) -> list[str]:
        normalized = super().normalize_capabilities(capabilities)
        unsupported = [
            capability
            for capability in normalized
            if capability not in self._allowed_capabilities
        ]
        if unsupported:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.unsupported_connection_method,
                "Assisted social account connections only support manual publishing",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        return normalized

    async def check_connection_health(
        self,
        *,
        credential_ref: str | None,
        token_expires_at: datetime | None = None,
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountHealth:
        return SocialAccountHealth(healthy=True, status="assisted_action_required")


class FakeOAuthSocialAccountConnectionProvider(SocialAccountConnectionProvider):
    """Deterministic OAuth adapter for exercising the generic connection workflow."""

    provider = SocialAccountProviderKey.instagram
    connection_method = SocialAccountConnectionMethod.direct_api

    _scope_capabilities = {
        "publish": "content_publish",
        "account_metrics": "account_analytics_read",
        "post_metrics": "post_analytics_read",
    }

    def default_capabilities(self) -> tuple[str, ...]:
        return (
            "content_publish",
            "account_analytics_read",
            "post_analytics_read",
        )

    def normalize_capabilities(self, capabilities: Sequence[str] | None) -> list[str]:
        normalized = super().normalize_capabilities(capabilities)
        allowed = set(self._scope_capabilities.values())
        unsupported = [
            capability for capability in normalized if capability not in allowed
        ]
        if unsupported:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.malformed_provider_response,
                "Provider returned unsupported social account capabilities",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        return normalized

    async def build_authorization_request(
        self,
        *,
        redirect_uri: str,
        state: str,
        scopes: Sequence[str] = (),
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountAuthorizationRequest:
        from urllib.parse import urlencode

        requested_scopes = tuple(scopes or self._scope_capabilities.keys())
        return SocialAccountAuthorizationRequest(
            authorization_url=(
                "https://fake-oauth.labelos.test/authorize?"
                + urlencode(
                    {
                        "response_type": "code",
                        "client_id": "labelos-fake-client",
                        "redirect_uri": redirect_uri,
                        "scope": " ".join(requested_scopes),
                        "state": state,
                    }
                )
            ),
            state=state,
            scopes=requested_scopes,
        )

    async def complete_oauth_exchange(
        self,
        *,
        code: str,
        redirect_uri: str,
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountCredentialResult:
        normalized_code = code.strip()
        if normalized_code == "exchange-fails":
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.authorization_failed,
                "OAuth authorization code exchange failed",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        if normalized_code == "malformed":
            return SocialAccountCredentialResult(
                credential_payload={"access_token": "fake-access-token"},
                granted_scopes=("publish",),
                provider_metadata={"external_account_id": ""},
            )
        if not normalized_code:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.authorization_failed,
                "OAuth authorization code is required",
                provider=self.provider,
                connection_method=self.connection_method,
            )

        granted_scopes = (
            ("publish",)
            if normalized_code == "partial-scopes"
            else ("publish", "account_metrics", "post_metrics")
        )
        return SocialAccountCredentialResult(
            credential_payload={
                "access_token": f"fake-access-token:{normalized_code}",
                "refresh_token": f"fake-refresh-token:{normalized_code}",
                "token_type": "Bearer",
            },
            granted_scopes=granted_scopes,
            provider_metadata={
                "external_account_id": f"fake-account-{normalized_code}",
                "username": f"fake_{normalized_code.replace('-', '_')}",
                "display_name": "Fake OAuth Account",
                "profile_url": f"https://fake-oauth.labelos.test/{normalized_code}",
            },
        )

    async def retrieve_account_identity(
        self,
        *,
        credential_ref: str | None,
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountIdentity:
        metadata = dict(provider_metadata or {})
        external_account_id = metadata.get("external_account_id")
        if not isinstance(external_account_id, str) or not external_account_id.strip():
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.malformed_provider_response,
                "Provider account identity is malformed",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        return self.normalize_account_identity(
            SocialAccountIdentity(
                provider=self.provider,
                external_account_id=external_account_id,
                username=(
                    metadata.get("username")
                    if isinstance(metadata.get("username"), str)
                    else None
                ),
                display_name=(
                    metadata.get("display_name")
                    if isinstance(metadata.get("display_name"), str)
                    else None
                ),
                profile_url=(
                    metadata.get("profile_url")
                    if isinstance(metadata.get("profile_url"), str)
                    else None
                ),
            )
        )

    def capabilities_for_scopes(self, scopes: Sequence[str]) -> list[str]:
        return self.normalize_capabilities(
            [
                capability
                for scope in scopes
                if (capability := self._scope_capabilities.get(scope.strip()))
            ]
        )


class ThirdPartySocialAccountConnectionProvider(SocialAccountConnectionProvider):
    """Vendor-neutral boundary for social integration service account links.

    The canonical SocialAccountConnection fields remain provider/account-centric:
    provider, connection_method, capabilities, identity, and status. Integration
    service identifiers are adapter-owned metadata and must stay out of draft
    posts, calendars, scheduling code, and other downstream domain surfaces.
    """

    connection_method = SocialAccountConnectionMethod.third_party

    _allowed_capabilities = frozenset(
        {
            "content_publish",
            "account_analytics_read",
            "post_analytics_read",
        }
    )

    def __init__(
        self,
        provider: SocialAccountProviderKey | str,
        *,
        adapter_key: str,
    ) -> None:
        self.provider = SocialAccountProviderKey(canonical_provider_key(provider))
        self.adapter_key = _required_adapter_key(adapter_key)

    def supported_connection_methods(self) -> tuple[SocialAccountConnectionMethod, ...]:
        return (SocialAccountConnectionMethod.third_party,)

    def default_capabilities(self) -> tuple[str, ...]:
        return (
            "content_publish",
            "account_analytics_read",
            "post_analytics_read",
        )

    def normalize_account_identity(
        self,
        identity: SocialAccountIdentity,
    ) -> SocialAccountIdentity:
        normalized = super().normalize_account_identity(identity)
        if normalized.provider != self.provider.value:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.malformed_provider_response,
                "Third-party adapter returned a mismatched social account provider",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        return SocialAccountIdentity(
            provider=normalized.provider,
            external_account_id=_optional_text(normalized.external_account_id),
            username=_normalize_handle(normalized.username),
            display_name=normalized.display_name,
            profile_url=_validate_profile_url(normalized.profile_url),
        )

    def validate_account_input(
        self,
        identity: SocialAccountIdentity,
        *,
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountValidationResult:
        normalized = self.normalize_account_identity(identity)
        if normalized.external_account_id is None:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.malformed_provider_response,
                "Third-party social account identity requires external_account_id",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        metadata = self._adapter_metadata(provider_metadata)
        return SocialAccountValidationResult(
            identity=normalized,
            provider_metadata=metadata,
        )

    def normalize_capabilities(self, capabilities: Sequence[str] | None) -> list[str]:
        normalized = super().normalize_capabilities(capabilities)
        unsupported = [
            capability
            for capability in normalized
            if capability not in self._allowed_capabilities
        ]
        if unsupported:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.malformed_provider_response,
                "Third-party adapter returned unsupported social account capabilities",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        return normalized

    async def check_connection_health(
        self,
        *,
        credential_ref: str | None,
        token_expires_at: datetime | None = None,
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountHealth:
        metadata = self._adapter_metadata(provider_metadata)
        third_party = metadata["third_party"]
        if (
            isinstance(third_party, Mapping)
            and third_party.get("adapter_key")
            and credential_ref is not None
        ):
            return SocialAccountHealth(healthy=True, status="connected")
        return SocialAccountHealth(
            healthy=False,
            status="reconnect_required",
            error_code=SocialAccountProviderErrorCode.credential_missing,
            error_message="Third-party integration credentials are missing",
        )

    def _adapter_metadata(
        self,
        provider_metadata: Mapping[str, object] | None,
    ) -> dict[str, object]:
        metadata = dict(provider_metadata or {})
        raw_third_party = metadata.get("third_party")
        third_party = (
            dict(raw_third_party) if isinstance(raw_third_party, Mapping) else {}
        )
        third_party["adapter_key"] = self.adapter_key
        metadata["third_party"] = third_party
        return metadata


class FakeThirdPartySocialAccountConnectionProvider(
    ThirdPartySocialAccountConnectionProvider
):
    """Deterministic test adapter for the future third-party integration path."""

    _scope_capabilities = {
        "publish": "content_publish",
        "account_metrics": "account_analytics_read",
        "post_metrics": "post_analytics_read",
    }

    def __init__(
        self,
        provider: SocialAccountProviderKey | str = SocialAccountProviderKey.instagram,
    ) -> None:
        super().__init__(provider, adapter_key="fake_test")

    async def build_authorization_request(
        self,
        *,
        redirect_uri: str,
        state: str,
        scopes: Sequence[str] = (),
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountAuthorizationRequest:
        requested_scopes = tuple(scopes or self._scope_capabilities.keys())
        return SocialAccountAuthorizationRequest(
            authorization_url=(
                "https://fake-third-party.labelos.test/connect?"
                + urlencode(
                    {
                        "response_type": "code",
                        "adapter": self.adapter_key,
                        "provider": self.provider.value,
                        "redirect_uri": redirect_uri,
                        "scope": " ".join(requested_scopes),
                        "state": state,
                    }
                )
            ),
            state=state,
            scopes=requested_scopes,
            metadata={"third_party": {"adapter_key": self.adapter_key}},
        )

    async def complete_oauth_exchange(
        self,
        *,
        code: str,
        redirect_uri: str,
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountCredentialResult:
        normalized_code = code.strip()
        if not normalized_code:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.authorization_failed,
                "Third-party authorization code is required",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        if normalized_code == "third-party-denied":
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.authorization_failed,
                "Third-party authorization failed",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        granted_scopes = (
            ("publish",)
            if normalized_code == "third-party-partial"
            else ("publish", "account_metrics", "post_metrics")
        )
        account_key = normalized_code.replace("-", "_")
        metadata = self._adapter_metadata(
            {
                **dict(provider_metadata or {}),
                "external_account_id": (
                    f"{self.provider.value}-third-party-{account_key}"
                ),
                "username": f"third_party_{account_key}",
                "display_name": "Fake Third-Party Account",
                "profile_url": (
                    f"https://fake-third-party.labelos.test/"
                    f"{self.provider.value}/{account_key}"
                ),
                "third_party": {
                    "adapter_key": self.adapter_key,
                    "external_integration_account_id": (
                        f"fake-integration-{account_key}"
                    ),
                    "external_connection_id": f"fake-connection-{account_key}",
                },
            }
        )
        return SocialAccountCredentialResult(
            credential_payload={
                "access_token": f"fake-third-party-access-token:{normalized_code}",
                "refresh_token": f"fake-third-party-refresh-token:{normalized_code}",
                "token_type": "Bearer",
            },
            granted_scopes=granted_scopes,
            provider_metadata=metadata,
        )

    async def retrieve_account_identity(
        self,
        *,
        credential_ref: str | None,
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountIdentity:
        metadata = dict(provider_metadata or {})
        external_account_id = metadata.get("external_account_id")
        if not isinstance(external_account_id, str) or not external_account_id.strip():
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.malformed_provider_response,
                "Third-party adapter account identity is malformed",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        return self.normalize_account_identity(
            SocialAccountIdentity(
                provider=self.provider,
                external_account_id=external_account_id,
                username=(
                    metadata.get("username")
                    if isinstance(metadata.get("username"), str)
                    else None
                ),
                display_name=(
                    metadata.get("display_name")
                    if isinstance(metadata.get("display_name"), str)
                    else None
                ),
                profile_url=(
                    metadata.get("profile_url")
                    if isinstance(metadata.get("profile_url"), str)
                    else None
                ),
            )
        )

    def capabilities_for_scopes(self, scopes: Sequence[str]) -> list[str]:
        return self.normalize_capabilities(
            [
                capability
                for scope in scopes
                if (capability := self._scope_capabilities.get(scope.strip()))
            ]
        )


@dataclass(frozen=True, kw_only=True)
class YouTubeDirectProviderConfig:
    client_id: str
    client_secret: str
    authorization_endpoint: str = "https://accounts.google.com/o/oauth2/v2/auth"
    token_endpoint: str = "https://oauth2.googleapis.com/token"
    revoke_endpoint: str = "https://oauth2.googleapis.com/revoke"
    channels_endpoint: str = "https://www.googleapis.com/youtube/v3/channels"
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.client_id.strip():
            raise ValueError("YouTube OAuth client_id is required")
        if not self.client_secret.strip():
            raise ValueError("YouTube OAuth client_secret is required")


class YouTubeDirectSocialAccountConnectionProvider(SocialAccountConnectionProvider):
    """Direct OAuth adapter for YouTube channel account connections.

    This adapter intentionally resolves connection capabilities only. It does
    not upload videos, publish posts, or retrieve analytics reports.
    """

    provider = SocialAccountProviderKey.youtube
    connection_method = SocialAccountConnectionMethod.direct_api

    SCOPE_YOUTUBE_READONLY = "https://www.googleapis.com/auth/youtube.readonly"
    SCOPE_YOUTUBE_UPLOAD = "https://www.googleapis.com/auth/youtube.upload"
    SCOPE_YT_ANALYTICS_READONLY = (
        "https://www.googleapis.com/auth/yt-analytics.readonly"
    )

    _scope_capabilities = {
        SCOPE_YOUTUBE_UPLOAD: ("content_publish",),
        SCOPE_YT_ANALYTICS_READONLY: (
            "account_analytics_read",
            "post_analytics_read",
        ),
    }

    _default_scopes = (SCOPE_YOUTUBE_READONLY,)
    _supported_scopes = frozenset(
        {
            SCOPE_YOUTUBE_READONLY,
            SCOPE_YOUTUBE_UPLOAD,
            SCOPE_YT_ANALYTICS_READONLY,
        }
    )

    def __init__(
        self,
        *,
        config: YouTubeDirectProviderConfig,
        credential_store: CredentialStore | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self.credential_store = credential_store
        self._http_client = http_client

    def default_capabilities(self) -> tuple[str, ...]:
        return (
            "content_publish",
            "account_analytics_read",
            "post_analytics_read",
        )

    def normalize_account_identity(
        self,
        identity: SocialAccountIdentity,
    ) -> SocialAccountIdentity:
        normalized = super().normalize_account_identity(identity)
        return SocialAccountIdentity(
            provider=normalized.provider,
            external_account_id=normalized.external_account_id,
            username=_optional_text(normalized.username),
            display_name=normalized.display_name,
            profile_url=_validate_profile_url(normalized.profile_url),
        )

    def normalize_capabilities(self, capabilities: Sequence[str] | None) -> list[str]:
        if capabilities is None:
            requested = self.default_capabilities()
        else:
            requested = capabilities
        normalized: list[str] = []
        seen: set[str] = set()
        for capability in requested:
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
        allowed = {
            capability
            for capabilities_for_scope in self._scope_capabilities.values()
            for capability in capabilities_for_scope
        }
        unsupported = [
            capability for capability in normalized if capability not in allowed
        ]
        if unsupported:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.malformed_provider_response,
                "Provider returned unsupported social account capabilities",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        return normalized

    async def build_authorization_request(
        self,
        *,
        redirect_uri: str,
        state: str,
        scopes: Sequence[str] = (),
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountAuthorizationRequest:
        requested_scopes = self._normalize_requested_scopes(scopes)
        query = urlencode(
            {
                "client_id": self.config.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(requested_scopes),
                "state": state,
                "access_type": "offline",
                "include_granted_scopes": "true",
                "prompt": "consent",
            }
        )
        return SocialAccountAuthorizationRequest(
            authorization_url=f"{self.config.authorization_endpoint}?{query}",
            state=state,
            scopes=requested_scopes,
            metadata={"access_type": "offline", "include_granted_scopes": True},
        )

    async def complete_oauth_exchange(
        self,
        *,
        code: str,
        redirect_uri: str,
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountCredentialResult:
        if not code.strip():
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.authorization_failed,
                "OAuth authorization code is required",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        body = await self._post_form_json(
            self.config.token_endpoint,
            data={
                "code": code,
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        credential_payload, granted_scopes, expires_at = self._credential_result(body)
        identity = await self._fetch_identity(credential_payload["access_token"])
        return SocialAccountCredentialResult(
            credential_payload=credential_payload,
            token_expires_at=expires_at,
            granted_scopes=granted_scopes,
            provider_metadata=identity.provider_metadata,
        )

    async def refresh_credentials(
        self,
        *,
        credential_ref: str,
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountCredentialResult:
        if self.credential_store is None:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.provider_unavailable,
                "Credential store is required for YouTube credential refresh",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        credentials = await self._stored_credentials(credential_ref)
        refresh_token = credentials.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token.strip():
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.credential_expired,
                "YouTube refresh token is missing",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        body = await self._post_form_json(
            self.config.token_endpoint,
            data={
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        refreshed_payload, granted_scopes, expires_at = self._credential_result(
            {**credentials, **body, "refresh_token": refresh_token}
        )
        await self.credential_store.replace(
            credential_ref,
            CredentialPayload(refreshed_payload),
        )
        return SocialAccountCredentialResult(
            credential_ref=credential_ref,
            token_expires_at=expires_at,
            granted_scopes=granted_scopes,
            provider_metadata=dict(provider_metadata or {}),
        )

    async def retrieve_account_identity(
        self,
        *,
        credential_ref: str | None,
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountIdentity:
        metadata = dict(provider_metadata or {})
        external_account_id = metadata.get("external_account_id")
        if isinstance(external_account_id, str) and external_account_id.strip():
            return self.normalize_account_identity(
                SocialAccountIdentity(
                    provider=self.provider,
                    external_account_id=external_account_id,
                    username=(
                        metadata.get("handle")
                        if isinstance(metadata.get("handle"), str)
                        else None
                    ),
                    display_name=(
                        metadata.get("display_name")
                        if isinstance(metadata.get("display_name"), str)
                        else None
                    ),
                    profile_url=(
                        metadata.get("profile_url")
                        if isinstance(metadata.get("profile_url"), str)
                        else None
                    ),
                )
            )
        if self.credential_store is None or credential_ref is None:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.malformed_provider_response,
                "YouTube account identity is unavailable",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        credentials = await self._stored_credentials(credential_ref)
        access_token = credentials.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.credential_expired,
                "YouTube access token is missing",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        identity = await self._fetch_identity(access_token)
        return identity.identity

    async def check_connection_health(
        self,
        *,
        credential_ref: str | None,
        token_expires_at: datetime | None = None,
        provider_metadata: Mapping[str, object] | None = None,
    ) -> SocialAccountHealth:
        if token_expires_at is not None and token_expires_at <= datetime.now(UTC):
            return SocialAccountHealth(
                healthy=False,
                status="expired",
                error_code=SocialAccountProviderErrorCode.credential_expired,
                error_message="YouTube access token has expired",
            )
        try:
            await self.retrieve_account_identity(
                credential_ref=credential_ref,
                provider_metadata=provider_metadata,
            )
        except SocialAccountProviderError as exc:
            return SocialAccountHealth(
                healthy=False,
                status="unhealthy",
                error_code=exc.code,
                error_message=str(exc),
            )
        return SocialAccountHealth(healthy=True, status="connected")

    async def disconnect(
        self,
        *,
        credential_ref: str | None,
        provider_metadata: Mapping[str, object] | None = None,
    ) -> None:
        if self.credential_store is None or credential_ref is None:
            return None
        credentials = await self._stored_credentials(credential_ref)
        token = credentials.get("refresh_token") or credentials.get("access_token")
        if isinstance(token, str) and token.strip():
            await self._post_form_json(
                self.config.revoke_endpoint,
                data={"token": token},
                accepts_empty_response=True,
            )
        try:
            await self.credential_store.delete(credential_ref)
        except CredentialNotFoundError:
            return None
        return None

    def capabilities_for_scopes(self, scopes: Sequence[str]) -> list[str]:
        capabilities: list[str] = []
        for scope in self._normalize_granted_scopes(scopes):
            capabilities.extend(self._scope_capabilities.get(scope, ()))
        return self.normalize_capabilities(capabilities)

    def _normalize_requested_scopes(self, scopes: Sequence[str]) -> tuple[str, ...]:
        requested = tuple(scopes or self._default_scopes)
        unknown = [
            scope
            for scope in requested
            if not isinstance(scope, str) or scope.strip() not in self._supported_scopes
        ]
        if unknown:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.insufficient_scope,
                "Unsupported YouTube OAuth scope requested",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        return tuple(dict.fromkeys(scope.strip() for scope in requested))

    def _normalize_granted_scopes(self, scopes: Sequence[str]) -> tuple[str, ...]:
        expanded: list[str] = []
        for scope in scopes:
            if isinstance(scope, str):
                expanded.extend(part for part in scope.split() if part)
        return tuple(dict.fromkeys(expanded))

    def _credential_result(
        self,
        body: Mapping[str, object],
    ) -> tuple[dict[str, object], tuple[str, ...], datetime | None]:
        access_token = body.get("access_token")
        token_type = body.get("token_type")
        if not isinstance(access_token, str) or not access_token.strip():
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.malformed_provider_response,
                "YouTube token response did not include an access token",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        if isinstance(token_type, str) and token_type.lower() != "bearer":
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.malformed_provider_response,
                "YouTube token response used an unsupported token type",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        granted_scopes = self._normalize_granted_scopes(
            (body.get("scope"),) if isinstance(body.get("scope"), str) else ()
        )
        credential_payload: dict[str, object] = {
            "access_token": access_token,
            "token_type": token_type or "Bearer",
            "scope": " ".join(granted_scopes),
        }
        refresh_token = body.get("refresh_token")
        if isinstance(refresh_token, str) and refresh_token.strip():
            credential_payload["refresh_token"] = refresh_token
        expires_in = body.get("expires_in")
        expires_at = None
        if isinstance(expires_in, int) and expires_in > 0:
            expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
            credential_payload["expires_in"] = expires_in
        return credential_payload, granted_scopes, expires_at

    async def _fetch_identity(self, access_token: str) -> SocialAccountValidationResult:
        body = await self._get_json(
            self.config.channels_endpoint,
            params={"part": "snippet", "mine": "true", "maxResults": "1"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        items = body.get("items")
        if not isinstance(items, list):
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.malformed_provider_response,
                "YouTube channel response is malformed",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        if not items:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.account_not_found,
                "Authenticated Google account has no YouTube channel",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        first = items[0]
        if not isinstance(first, Mapping):
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.malformed_provider_response,
                "YouTube channel item is malformed",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        channel_id = first.get("id")
        snippet = first.get("snippet")
        if not isinstance(channel_id, str) or not channel_id.strip():
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.malformed_provider_response,
                "YouTube channel id is missing",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        snippet_map = snippet if isinstance(snippet, Mapping) else {}
        handle = snippet_map.get("customUrl")
        title = snippet_map.get("title")
        thumbnails = snippet_map.get("thumbnails")
        metadata = {
            "external_account_id": channel_id,
            "handle": handle if isinstance(handle, str) else None,
            "display_name": title if isinstance(title, str) else None,
            "profile_url": f"https://www.youtube.com/channel/{channel_id}",
            "thumbnail_url": _default_thumbnail_url(thumbnails),
        }
        return self.validate_account_input(
            SocialAccountIdentity(
                provider=self.provider,
                external_account_id=metadata["external_account_id"],
                username=metadata["handle"],
                display_name=metadata["display_name"],
                profile_url=metadata["profile_url"],
            ),
            provider_metadata={
                key: value for key, value in metadata.items() if value is not None
            },
        )

    async def _stored_credentials(self, credential_ref: str) -> dict[str, object]:
        try:
            if self.credential_store is None:
                raise CredentialNotFoundError()
            return (await self.credential_store.get(credential_ref)).expose()
        except (CredentialNotFoundError, InvalidCredentialReferenceError) as exc:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.credential_missing,
                "Stored YouTube credential material was not found",
                provider=self.provider,
                connection_method=self.connection_method,
            ) from exc
        except CredentialStoreError as exc:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.provider_unavailable,
                "Stored YouTube credential material is unavailable",
                provider=self.provider,
                connection_method=self.connection_method,
            ) from exc

    async def _post_form_json(
        self,
        url: str,
        *,
        data: Mapping[str, str],
        accepts_empty_response: bool = False,
    ) -> Mapping[str, object]:
        response = await self._request(
            "POST",
            url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if accepts_empty_response and not response.content:
            return {}
        return self._response_json(response)

    async def _get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str],
        headers: Mapping[str, str],
    ) -> Mapping[str, object]:
        response = await self._request("GET", url, params=params, headers=headers)
        return self._response_json(response)

    async def _request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        client = self._http_client
        if client is not None:
            response = await client.request(method, url, **kwargs)
        else:
            async with httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
            ) as transient_client:
                response = await transient_client.request(method, url, **kwargs)
        if response.status_code in {400, 401}:
            if self._is_refresh_request(method, url, kwargs.get("data")):
                raise SocialAccountProviderError(
                    self._refresh_failure_code(response),
                    "YouTube credential refresh failed",
                    provider=self.provider,
                    connection_method=self.connection_method,
                )
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.credential_expired,
                "YouTube credential is expired or invalid",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        if response.status_code == 403:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.insufficient_scope,
                "YouTube credential is missing a required permission",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        if response.status_code == 404:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.account_not_found,
                "YouTube account was not found",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        if response.status_code == 429:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.rate_limited,
                "YouTube API rate limit was reached",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        if response.status_code >= 500:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.provider_unavailable,
                "YouTube provider is temporarily unavailable",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.provider_unavailable,
                "YouTube provider request failed",
                provider=self.provider,
                connection_method=self.connection_method,
            ) from exc
        return response

    def _is_refresh_request(
        self,
        method: str,
        url: str,
        data: object,
    ) -> bool:
        return (
            method.upper() == "POST"
            and url == self.config.token_endpoint
            and isinstance(data, Mapping)
            and data.get("grant_type") == "refresh_token"
        )

    def _refresh_failure_code(
        self,
        response: httpx.Response,
    ) -> SocialAccountProviderErrorCode:
        try:
            body = response.json()
        except ValueError:
            body = {}
        if isinstance(body, Mapping) and body.get("error") == "invalid_grant":
            return SocialAccountProviderErrorCode.credential_revoked
        return SocialAccountProviderErrorCode.refresh_failed

    def _response_json(self, response: httpx.Response) -> Mapping[str, object]:
        try:
            body = response.json()
        except ValueError as exc:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.malformed_provider_response,
                "YouTube provider returned malformed JSON",
                provider=self.provider,
                connection_method=self.connection_method,
            ) from exc
        if not isinstance(body, Mapping):
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.malformed_provider_response,
                "YouTube provider returned an unexpected response",
                provider=self.provider,
                connection_method=self.connection_method,
            )
        return body


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


def youtube_direct_provider_from_settings(
    *,
    client_id: str | None,
    client_secret: str | None,
    credential_store: CredentialStore | None = None,
) -> YouTubeDirectSocialAccountConnectionProvider | None:
    if not client_id or not client_secret:
        return None
    return YouTubeDirectSocialAccountConnectionProvider(
        config=YouTubeDirectProviderConfig(
            client_id=client_id,
            client_secret=client_secret,
        ),
        credential_store=credential_store,
    )


def social_account_provider_registry_from_settings(
    *,
    youtube_client_id: str | None,
    youtube_client_secret: str | None,
    credential_store: CredentialStore | None = None,
) -> SocialAccountProviderRegistry:
    registry = default_social_account_provider_registry()
    youtube = youtube_direct_provider_from_settings(
        client_id=youtube_client_id,
        client_secret=youtube_client_secret,
        credential_store=credential_store,
    )
    if youtube is not None:
        registry.register(youtube)
    return registry


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


def _required_adapter_key(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    if not normalized:
        raise ValueError("Third-party social account adapter_key is required")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_handle(value: str | None) -> str | None:
    normalized = _optional_text(value)
    if normalized is None:
        return None
    normalized = normalized.lstrip("@").strip().lower()
    return normalized or None


def _validate_profile_url(value: str | None) -> str | None:
    normalized = _optional_text(value)
    if normalized is None:
        return None
    parsed = urlparse(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise SocialAccountProviderError(
            SocialAccountProviderErrorCode.malformed_provider_response,
            "profile_url must be an absolute HTTP(S) URL without embedded credentials",
        )
    return normalized


def _default_thumbnail_url(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    default = value.get("default")
    if not isinstance(default, Mapping):
        return None
    url = default.get("url")
    return url if isinstance(url, str) and url.strip() else None


provider_registry = default_social_account_provider_registry()


def resolve_social_account_provider(
    provider: SocialAccountProviderKey | str,
    connection_method: SocialAccountConnectionMethod | str,
) -> SocialAccountConnectionProvider:
    return provider_registry.resolve(provider, connection_method)
