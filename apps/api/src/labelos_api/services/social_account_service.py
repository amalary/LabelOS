from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import re
from uuid import UUID

from labelos_database.models import (
    SocialAccountConnection,
    SocialAccountConnectionMethod,
    SocialAccountConnectionStatus,
    User,
)
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.authorization import (
    AuthorizationActorInput,
    AuthorizationResource,
    Capability,
    ResourceKind,
    authorization_service,
)
from labelos_api.realtime import RealtimeEventType, RealtimePublisher
from labelos_api.repositories import social_accounts
from labelos_api.social_accounts.providers import (
    SocialAccountCredentialResult,
    SocialAccountConnectionProvider,
    SocialAccountHealth,
    SocialAccountIdentity,
    SocialAccountMetadataSync,
    SocialAccountProviderError,
    SocialAccountProviderErrorCode,
    SocialAccountProviderRegistry,
    resolve_social_account_provider,
)


class SocialAccountServiceError(ValueError):
    """Base error for social account connection business-rule failures."""


class SocialAccountNotFoundError(SocialAccountServiceError):
    pass


class SocialAccountRelationshipError(SocialAccountServiceError):
    pass


class SocialAccountLifecycleError(SocialAccountServiceError):
    pass


class SocialAccountDuplicateError(SocialAccountServiceError):
    pass


class SocialAccountAuthorizationError(SocialAccountServiceError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


MAX_SOCIAL_ACCOUNT_LIST_LIMIT = 500

SOCIAL_ACCOUNT_CAPABILITY_CONTENT_PUBLISH = "content_publish"
SOCIAL_ACCOUNT_CAPABILITY_MANUAL_PUBLISH = "manual_publish"
SOCIAL_ACCOUNT_CAPABILITY_MANUAL_METRICS = "manual_metrics"
SOCIAL_ACCOUNT_CAPABILITY_ACCOUNT_ANALYTICS_READ = "account_analytics_read"
SOCIAL_ACCOUNT_CAPABILITY_POST_ANALYTICS_READ = "post_analytics_read"

ACTIVE_SOCIAL_ACCOUNT_STATUSES = frozenset(
    {
        SocialAccountConnectionStatus.pending,
        SocialAccountConnectionStatus.connected,
        SocialAccountConnectionStatus.limited,
        SocialAccountConnectionStatus.reconnect_required,
        SocialAccountConnectionStatus.error,
    }
)

HEALTH_RETAIN_CURRENT_STATUS_CODES = frozenset(
    {
        SocialAccountProviderErrorCode.provider_unavailable,
        SocialAccountProviderErrorCode.third_party_service_unavailable,
        SocialAccountProviderErrorCode.rate_limited,
    }
)

HEALTH_RECONNECT_REQUIRED_CODES = frozenset(
    {
        SocialAccountProviderErrorCode.authorization_failed,
        SocialAccountProviderErrorCode.credential_missing,
        SocialAccountProviderErrorCode.credential_revoked,
        SocialAccountProviderErrorCode.refresh_failed,
        SocialAccountProviderErrorCode.account_not_found,
    }
)

HEALTH_ERROR_CODES = frozenset(
    {
        SocialAccountProviderErrorCode.malformed_provider_response,
        SocialAccountProviderErrorCode.sync_failed,
    }
)

SENSITIVE_SOCIAL_ACCOUNT_EVENT_FIELDS = frozenset(
    {
        "credential_ref",
        "token_expires_at",
    }
)
SENSITIVE_PROVIDER_METADATA_KEY_PARTS = frozenset(
    {
        "access_token",
        "authorization",
        "client_secret",
        "code",
        "credential",
        "id_token",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "token",
    }
)
SENSITIVE_ERROR_TEXT_PATTERNS = (
    re.compile(
        r"(?i)\b(access[-_]?token|refresh[-_]?token|id[-_]?token|client[-_]?secret|"
        r"password|private[-_]?key|secret|credential)\b"
        r"(\s*[:=]\s*)([^\s,;]+)"
    ),
    re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._~+/=-]{6,})"),
)

ALLOWED_SOCIAL_ACCOUNT_TRANSITIONS: dict[
    SocialAccountConnectionStatus, frozenset[SocialAccountConnectionStatus]
] = {
    SocialAccountConnectionStatus.pending: frozenset(
        {
            SocialAccountConnectionStatus.connected,
            SocialAccountConnectionStatus.limited,
            SocialAccountConnectionStatus.error,
            SocialAccountConnectionStatus.disconnected,
        }
    ),
    SocialAccountConnectionStatus.connected: frozenset(
        {
            SocialAccountConnectionStatus.limited,
            SocialAccountConnectionStatus.reconnect_required,
            SocialAccountConnectionStatus.error,
            SocialAccountConnectionStatus.disconnected,
        }
    ),
    SocialAccountConnectionStatus.limited: frozenset(
        {
            SocialAccountConnectionStatus.connected,
            SocialAccountConnectionStatus.reconnect_required,
            SocialAccountConnectionStatus.error,
            SocialAccountConnectionStatus.disconnected,
        }
    ),
    SocialAccountConnectionStatus.reconnect_required: frozenset(
        {
            SocialAccountConnectionStatus.connected,
            SocialAccountConnectionStatus.limited,
            SocialAccountConnectionStatus.error,
            SocialAccountConnectionStatus.disconnected,
        }
    ),
    SocialAccountConnectionStatus.error: frozenset(
        {
            SocialAccountConnectionStatus.connected,
            SocialAccountConnectionStatus.limited,
            SocialAccountConnectionStatus.disconnected,
        }
    ),
    SocialAccountConnectionStatus.disconnected: frozenset(),
}


@dataclass(frozen=True, kw_only=True)
class SocialAccountConnectionCreate:
    provider: str
    artist_profile_id: UUID | None = None
    external_account_id: str | None = None
    username: str | None = None
    display_name: str | None = None
    profile_url: str | None = None
    connection_method: SocialAccountConnectionMethod | str = (
        SocialAccountConnectionMethod.assisted
    )
    status: SocialAccountConnectionStatus | str = SocialAccountConnectionStatus.pending
    capabilities: Sequence[str] = ()
    credential_ref: str | None = None
    token_expires_at: datetime | None = None
    last_synced_at: datetime | None = None
    last_health_checked_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    provider_metadata: dict | None = None
    created_by_user_id: UUID | None = None
    created_by_profile_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class SocialAccountConnectionUpdate:
    artist_profile_id: UUID | None = None
    username: str | None = None
    display_name: str | None = None
    profile_url: str | None = None
    capabilities: Sequence[str] | None = None
    token_expires_at: datetime | None = None
    last_synced_at: datetime | None = None
    last_health_checked_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    provider_metadata: dict | None = None
    clear_artist_profile: bool = False
    clear_username: bool = False
    clear_display_name: bool = False
    clear_profile_url: bool = False
    clear_token_expires_at: bool = False
    clear_last_error: bool = False


@dataclass(frozen=True, kw_only=True)
class SocialAccountConnectionQuery:
    provider: str | None = None
    status: SocialAccountConnectionStatus | str | None = None
    artist_profile_id: UUID | None = None
    include_disconnected: bool = True


class DestinationUnavailableReason(StrEnum):
    no_connection = "NO_CONNECTION"
    disconnected = "DISCONNECTED"
    reconnect_required = "RECONNECT_REQUIRED"
    connection_error = "CONNECTION_ERROR"
    missing_capability = "MISSING_CAPABILITY"
    provider_mismatch = "PROVIDER_MISMATCH"
    wrong_artist = "WRONG_ARTIST"
    wrong_workspace = "WRONG_WORKSPACE"


@dataclass(frozen=True, kw_only=True)
class ResolvedDestination:
    account: SocialAccountConnection
    usable: bool
    supports_automatic_publication: bool
    requires_assisted_publication: bool
    can_provide_analytics: bool
    unavailable_reasons: tuple[DestinationUnavailableReason, ...]


@dataclass(frozen=True, kw_only=True)
class DestinationResolution:
    workspace_id: UUID
    provider: str | None
    artist_profile_id: UUID | None
    desired_capability: str | None
    accounts: list[ResolvedDestination]
    unavailable_reasons: tuple[DestinationUnavailableReason, ...] = ()
    requested_account: ResolvedDestination | None = None

    @property
    def usable_accounts(self) -> list[ResolvedDestination]:
        return [account for account in self.accounts if account.usable]


def _now() -> datetime:
    return datetime.now(UTC)


def _actor_user(actor: AuthorizationActorInput | None) -> User | None:
    if isinstance(actor, User):
        return actor
    user = getattr(actor, "user", None)
    return user if isinstance(user, User) else None


def _status_value(status: SocialAccountConnectionStatus | str) -> str:
    return (
        status.value
        if isinstance(status, SocialAccountConnectionStatus)
        else str(status)
    )


def _method_value(method: SocialAccountConnectionMethod | str) -> str:
    return (
        method.value
        if isinstance(method, SocialAccountConnectionMethod)
        else str(method)
    )


def _safe_error_code(
    code: SocialAccountProviderErrorCode | str | None,
) -> str | None:
    if code is None:
        return None
    try:
        return SocialAccountProviderErrorCode(code).value
    except ValueError:
        return "provider_unavailable"


def _safe_error_message(message: str | None) -> str | None:
    normalized = _normalize_optional_text(message)
    if normalized is None:
        return None
    return _redact_sensitive_text(normalized)[:500]


def _redact_sensitive_text(value: str) -> str:
    redacted = SENSITIVE_ERROR_TEXT_PATTERNS[1].sub("Bearer [redacted]", value)
    return SENSITIVE_ERROR_TEXT_PATTERNS[0].sub(r"\1\2[redacted]", redacted)


def _provider_metadata_key_is_sensitive(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_PROVIDER_METADATA_KEY_PARTS)


def _safe_provider_metadata(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            key: _safe_provider_metadata(item)
            for key, item in value.items()
            if not _provider_metadata_key_is_sensitive(str(key))
        }
    if isinstance(value, list):
        return [_safe_provider_metadata(item) for item in value]
    return value


def _safe_provider_metadata_object(value: Mapping[str, object] | dict) -> dict:
    sanitized = _safe_provider_metadata(value)
    if not isinstance(sanitized, dict):
        raise SocialAccountRelationshipError("provider_metadata must be a JSON object")
    return sanitized


def _social_account_event_payload(
    connection: SocialAccountConnection,
    *,
    action: str,
    changed_fields: list[str] | None = None,
    previous_status: str | None = None,
    previous_capabilities: Sequence[str] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "action": action,
        "connectionId": str(connection.id),
        "provider": connection.provider,
        "artistProfileId": (
            str(connection.artist_profile_id)
            if connection.artist_profile_id is not None
            else None
        ),
        "connectionMethod": _method_value(connection.connection_method),
        "status": _status_value(connection.status),
        "externalAccountId": connection.external_account_id,
        "handle": connection.username,
        "displayName": connection.display_name,
        "profileUrl": connection.profile_url,
        "capabilities": list(connection.capabilities or []),
    }
    if changed_fields is not None:
        payload["changedFields"] = ",".join(
            field
            for field in changed_fields
            if field not in SENSITIVE_SOCIAL_ACCOUNT_EVENT_FIELDS
        )
    if previous_status is not None:
        payload["previousStatus"] = previous_status
    if previous_capabilities is not None:
        current = set(connection.capabilities or [])
        previous = set(previous_capabilities)
        payload["addedCapabilities"] = sorted(current - previous)
        payload["removedCapabilities"] = sorted(previous - current)
    return payload


async def _publish_social_account_event(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    event_type: RealtimeEventType,
    actor: AuthorizationActorInput | None,
    connection: SocialAccountConnection,
    payload: dict[str, object] | None = None,
) -> None:
    await RealtimePublisher(session).publish(
        organization_id=workspace_id,
        event_type=event_type,
        actor=_actor_user(actor),
        entity_type="social_account_connection",
        entity_id=connection.id,
        payload=payload
        or _social_account_event_payload(connection, action=event_type.value),
    )


def _normalize_text(value: str | None, field_name: str) -> str:
    if value is None or not value.strip():
        raise SocialAccountRelationshipError(f"{field_name} is required")
    return value.strip()


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _json_object(value: dict | None, field_name: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SocialAccountRelationshipError(f"{field_name} must be a JSON object")
    return value


def _normalize_capabilities(
    capabilities: Sequence[str] | None,
    *,
    adapter: SocialAccountConnectionProvider | None = None,
) -> list[str]:
    if adapter is not None:
        return adapter.normalize_capabilities(capabilities)
    if capabilities is None:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for capability in capabilities:
        if not isinstance(capability, str) or not capability.strip():
            raise SocialAccountRelationshipError(
                "Social account capabilities must be non-empty strings"
            )
        key = capability.strip()
        if key not in seen:
            normalized.append(key)
            seen.add(key)
    return normalized


def _coerce_method(
    value: SocialAccountConnectionMethod | str,
) -> SocialAccountConnectionMethod:
    try:
        return (
            value
            if isinstance(value, SocialAccountConnectionMethod)
            else SocialAccountConnectionMethod(value)
        )
    except ValueError as exc:
        raise SocialAccountRelationshipError(
            "Invalid social account connection method"
        ) from exc


def _coerce_status(
    value: SocialAccountConnectionStatus | str,
) -> SocialAccountConnectionStatus:
    try:
        return (
            value
            if isinstance(value, SocialAccountConnectionStatus)
            else SocialAccountConnectionStatus(value)
        )
    except ValueError as exc:
        raise SocialAccountLifecycleError(
            "Invalid social account connection status"
        ) from exc


def _validate_list_pagination(*, limit: int, offset: int) -> None:
    if limit < 1 or limit > MAX_SOCIAL_ACCOUNT_LIST_LIMIT:
        raise SocialAccountRelationshipError(
            "Social account connection list limit must be between 1 and 500"
        )
    if offset < 0:
        raise SocialAccountRelationshipError(
            "Social account connection list offset must be greater than or equal to 0"
        )


def _normalize_destination_provider(provider: str | None) -> str | None:
    if provider is None:
        return None
    return _normalize_text(provider, "provider").lower()


def _normalize_desired_capability(capability: str | None) -> str | None:
    return _normalize_optional_text(capability)


def supports_capability(
    connection_or_capabilities: SocialAccountConnection | Sequence[str],
    capability: str,
) -> bool:
    capabilities = (
        connection_or_capabilities.capabilities
        if isinstance(connection_or_capabilities, SocialAccountConnection)
        else connection_or_capabilities
    )
    return capability in set(capabilities or [])


def can_auto_publish(
    connection_or_capabilities: SocialAccountConnection | Sequence[str],
) -> bool:
    return supports_capability(
        connection_or_capabilities,
        SOCIAL_ACCOUNT_CAPABILITY_CONTENT_PUBLISH,
    )


def requires_manual_publish(
    connection_or_capabilities: SocialAccountConnection | Sequence[str],
) -> bool:
    return supports_capability(
        connection_or_capabilities,
        SOCIAL_ACCOUNT_CAPABILITY_MANUAL_PUBLISH,
    ) and not can_auto_publish(connection_or_capabilities)


def supports_manual_metrics(
    connection_or_capabilities: SocialAccountConnection | Sequence[str],
) -> bool:
    return supports_capability(
        connection_or_capabilities,
        SOCIAL_ACCOUNT_CAPABILITY_MANUAL_METRICS,
    )


def can_read_account_analytics(
    connection_or_capabilities: SocialAccountConnection | Sequence[str],
) -> bool:
    return supports_capability(
        connection_or_capabilities,
        SOCIAL_ACCOUNT_CAPABILITY_ACCOUNT_ANALYTICS_READ,
    )


def can_read_post_analytics(
    connection_or_capabilities: SocialAccountConnection | Sequence[str],
) -> bool:
    return supports_capability(
        connection_or_capabilities,
        SOCIAL_ACCOUNT_CAPABILITY_POST_ANALYTICS_READ,
    )


def can_provide_analytics(
    connection_or_capabilities: SocialAccountConnection | Sequence[str],
) -> bool:
    return (
        can_read_account_analytics(connection_or_capabilities)
        or can_read_post_analytics(connection_or_capabilities)
        or supports_manual_metrics(connection_or_capabilities)
    )


def _destination_status_reason(
    connection: SocialAccountConnection,
) -> DestinationUnavailableReason | None:
    if connection.status == SocialAccountConnectionStatus.disconnected:
        return DestinationUnavailableReason.disconnected
    if connection.status == SocialAccountConnectionStatus.reconnect_required:
        return DestinationUnavailableReason.reconnect_required
    if connection.status == SocialAccountConnectionStatus.error:
        return DestinationUnavailableReason.connection_error
    if connection.status == SocialAccountConnectionStatus.pending:
        return DestinationUnavailableReason.reconnect_required
    return None


def _resolved_destination(
    connection: SocialAccountConnection,
    *,
    workspace_id: UUID,
    provider: str | None,
    artist_profile_id: UUID | None,
    desired_capability: str | None,
) -> ResolvedDestination:
    reasons: list[DestinationUnavailableReason] = []
    if connection.organization_id != workspace_id:
        reasons.append(DestinationUnavailableReason.wrong_workspace)
    if provider is not None and connection.provider.lower() != provider:
        reasons.append(DestinationUnavailableReason.provider_mismatch)
    if (
        artist_profile_id is not None
        and connection.artist_profile_id is not None
        and connection.artist_profile_id != artist_profile_id
    ):
        reasons.append(DestinationUnavailableReason.wrong_artist)
    status_reason = _destination_status_reason(connection)
    if status_reason is not None:
        reasons.append(status_reason)
    if desired_capability is not None and not supports_capability(
        connection,
        desired_capability,
    ):
        reasons.append(DestinationUnavailableReason.missing_capability)
    return ResolvedDestination(
        account=connection,
        usable=not reasons,
        supports_automatic_publication=can_auto_publish(connection),
        requires_assisted_publication=requires_manual_publish(connection),
        can_provide_analytics=can_provide_analytics(connection),
        unavailable_reasons=tuple(dict.fromkeys(reasons)),
    )


def resolved_destination_for_connection(
    connection: SocialAccountConnection,
    *,
    workspace_id: UUID,
    provider: str | None = None,
    artist_profile_id: UUID | None = None,
    desired_capability: str | None = None,
) -> ResolvedDestination:
    return _resolved_destination(
        connection,
        workspace_id=workspace_id,
        provider=_normalize_destination_provider(provider),
        artist_profile_id=artist_profile_id,
        desired_capability=_normalize_desired_capability(desired_capability),
    )


def _create_values(payload: SocialAccountConnectionCreate) -> dict[str, object]:
    method = _coerce_method(payload.connection_method)
    adapter = resolve_social_account_provider(payload.provider, method)
    validation_result = adapter.validate_account_input(
        SocialAccountIdentity(
            provider=payload.provider,
            external_account_id=payload.external_account_id,
            username=payload.username,
            display_name=payload.display_name,
            profile_url=payload.profile_url,
        ),
        provider_metadata=_safe_provider_metadata_object(
            _json_object(payload.provider_metadata, "provider_metadata")
        ),
    )
    identity = validation_result.identity
    values: dict[str, object] = {
        "provider": identity.provider,
        "connection_method": method,
        "status": _coerce_status(payload.status),
        "capabilities": _normalize_capabilities(payload.capabilities, adapter=adapter),
        "provider_metadata": _safe_provider_metadata_object(
            validation_result.provider_metadata
        ),
    }
    _set_if_not_none(values, "artist_profile_id", payload.artist_profile_id)
    _set_if_not_none(
        values,
        "external_account_id",
        identity.external_account_id,
    )
    _set_if_not_none(values, "username", identity.username)
    _set_if_not_none(
        values,
        "display_name",
        identity.display_name,
    )
    _set_if_not_none(
        values,
        "profile_url",
        identity.profile_url,
    )
    _set_if_not_none(
        values,
        "credential_ref",
        _normalize_optional_text(payload.credential_ref),
    )
    _set_if_not_none(values, "token_expires_at", payload.token_expires_at)
    _set_if_not_none(values, "last_synced_at", payload.last_synced_at)
    _set_if_not_none(
        values,
        "last_health_checked_at",
        payload.last_health_checked_at,
    )
    _set_if_not_none(
        values,
        "last_error_code",
        _normalize_optional_text(payload.last_error_code),
    )
    _set_if_not_none(
        values,
        "last_error_message",
        _safe_error_message(payload.last_error_message),
    )
    _set_if_not_none(values, "created_by_user_id", payload.created_by_user_id)
    _set_if_not_none(values, "created_by_profile_id", payload.created_by_profile_id)
    return values


def _assisted_create_payload(
    payload: SocialAccountConnectionCreate,
) -> SocialAccountConnectionCreate:
    method = _coerce_method(payload.connection_method)
    if method != SocialAccountConnectionMethod.assisted:
        raise SocialAccountRelationshipError(
            "Assisted social account registration requires assisted connection_method"
        )
    return SocialAccountConnectionCreate(
        provider=payload.provider,
        artist_profile_id=payload.artist_profile_id,
        external_account_id=payload.external_account_id,
        username=payload.username,
        display_name=payload.display_name,
        profile_url=payload.profile_url,
        connection_method=SocialAccountConnectionMethod.assisted,
        status=SocialAccountConnectionStatus.connected,
        capabilities=payload.capabilities,
        credential_ref=None,
        token_expires_at=None,
        last_synced_at=payload.last_synced_at,
        last_health_checked_at=payload.last_health_checked_at,
        last_error_code=None,
        last_error_message=None,
        provider_metadata=payload.provider_metadata,
        created_by_user_id=payload.created_by_user_id,
        created_by_profile_id=payload.created_by_profile_id,
    )


def _update_values(
    payload: SocialAccountConnectionUpdate,
    *,
    adapter: SocialAccountConnectionProvider | None = None,
) -> dict[str, object]:
    values: dict[str, object] = {}
    _set_if_not_none(values, "artist_profile_id", payload.artist_profile_id)
    _set_if_not_none(values, "username", _normalize_optional_text(payload.username))
    _set_if_not_none(
        values,
        "display_name",
        _normalize_optional_text(payload.display_name),
    )
    _set_if_not_none(
        values,
        "profile_url",
        _normalize_optional_text(payload.profile_url),
    )
    if payload.capabilities is not None:
        values["capabilities"] = _normalize_capabilities(
            payload.capabilities,
            adapter=adapter,
        )
    _set_if_not_none(values, "token_expires_at", payload.token_expires_at)
    _set_if_not_none(values, "last_synced_at", payload.last_synced_at)
    _set_if_not_none(
        values,
        "last_health_checked_at",
        payload.last_health_checked_at,
    )
    _set_if_not_none(
        values,
        "last_error_code",
        _normalize_optional_text(payload.last_error_code),
    )
    _set_if_not_none(
        values,
        "last_error_message",
        _safe_error_message(payload.last_error_message),
    )
    if payload.provider_metadata is not None:
        values["provider_metadata"] = _safe_provider_metadata_object(
            _json_object(payload.provider_metadata, "provider_metadata")
        )
    if payload.clear_artist_profile:
        values["artist_profile_id"] = None
    if payload.clear_username:
        values["username"] = None
    if payload.clear_display_name:
        values["display_name"] = None
    if payload.clear_profile_url:
        values["profile_url"] = None
    if payload.clear_token_expires_at:
        values["token_expires_at"] = None
    if payload.clear_last_error:
        values["last_error_code"] = None
        values["last_error_message"] = None
    return values


def _set_if_not_none(values: dict[str, object], key: str, value: object | None) -> None:
    if value is not None:
        values[key] = value


def _changed_fields(
    connection: SocialAccountConnection,
    values: Mapping[str, object],
) -> set[str]:
    return {key for key, value in values.items() if getattr(connection, key) != value}


def _assert_transition_allowed(
    current: SocialAccountConnectionStatus,
    next_status: SocialAccountConnectionStatus | str,
    *,
    recovery_succeeded: bool = False,
) -> SocialAccountConnectionStatus:
    normalized = _coerce_status(next_status)
    if normalized == current:
        return normalized
    if (
        current == SocialAccountConnectionStatus.error
        and normalized
        in {
            SocialAccountConnectionStatus.connected,
            SocialAccountConnectionStatus.limited,
        }
        and not recovery_succeeded
    ):
        raise SocialAccountLifecycleError(
            "Recovering from error requires an explicit successful recovery"
        )
    if normalized not in ALLOWED_SOCIAL_ACCOUNT_TRANSITIONS[current]:
        raise SocialAccountLifecycleError(
            f"Cannot transition social account connection from {current.value} "
            f"to {normalized.value}"
        )
    return normalized


async def _require_capability(
    session: AsyncSession,
    *,
    actor: AuthorizationActorInput | None,
    workspace_id: UUID,
    capability: Capability,
) -> None:
    if actor is None:
        return
    decision = await authorization_service.decide_capability(
        session,
        actor=actor,
        workspace=workspace_id,
        capability=capability,
        resource=AuthorizationResource(
            kind=ResourceKind.workspace,
            id=workspace_id,
            workspace_id=workspace_id,
            department="marketing",
        ),
    )
    if not decision.allowed:
        raise SocialAccountAuthorizationError(decision.reason)


async def _validate_relationships(
    session: AsyncSession,
    workspace_id: UUID,
    values: Mapping[str, object],
) -> None:
    artist_profile_id = values.get("artist_profile_id")
    if isinstance(
        artist_profile_id,
        UUID,
    ) and not await social_accounts.artist_profile_in_workspace(
        session,
        workspace_id,
        artist_profile_id,
    ):
        raise SocialAccountRelationshipError(
            "artist_profile_id must belong to workspace"
        )

    created_by_user_id = values.get("created_by_user_id")
    if isinstance(
        created_by_user_id,
        UUID,
    ) and not await social_accounts.user_is_active_workspace_member(
        session,
        workspace_id,
        created_by_user_id,
    ):
        raise SocialAccountRelationshipError(
            "created_by_user_id must belong to an active workspace member"
        )

    created_by_profile_id = values.get("created_by_profile_id")
    if isinstance(
        created_by_profile_id,
        UUID,
    ) and not await social_accounts.profile_is_active_workspace_member(
        session,
        workspace_id,
        created_by_profile_id,
    ):
        raise SocialAccountRelationshipError(
            "created_by_profile_id must belong to an active workspace member"
        )


async def _assert_no_reasonable_duplicate(
    session: AsyncSession,
    workspace_id: UUID,
    values: Mapping[str, object],
) -> None:
    provider = values.get("provider")
    connection_method = values.get("connection_method")
    username = values.get("username")
    external_account_id = values.get("external_account_id")
    if not isinstance(provider, str) or not isinstance(
        connection_method,
        SocialAccountConnectionMethod,
    ):
        return

    if isinstance(username, str):
        existing_username = (
            await social_accounts.find_active_connection_by_provider_username(
                session,
                workspace_id,
                provider=provider,
                connection_method=connection_method,
                username=username,
            )
        )
        if existing_username is not None:
            raise SocialAccountDuplicateError(
                "A social account connection with this provider and username already "
                "exists in the workspace"
            )

    if isinstance(external_account_id, str):
        existing_external = (
            await social_accounts.find_active_connection_by_provider_external_account(
                session,
                workspace_id,
                provider=provider,
                connection_method=connection_method,
                external_account_id=external_account_id,
            )
        )
        if existing_external is not None:
            raise SocialAccountDuplicateError(
                "A social account connection with this provider and external account "
                "already exists in the workspace"
            )


async def _load_connection_for_workspace(
    session: AsyncSession,
    workspace_id: UUID,
    connection_id: UUID,
) -> SocialAccountConnection:
    connection = await social_accounts.get_connection(
        session,
        workspace_id,
        connection_id,
    )
    if connection is None:
        raise SocialAccountNotFoundError("Social account connection not found")
    return connection


def _assert_mutable(connection: SocialAccountConnection) -> None:
    if connection.status == SocialAccountConnectionStatus.disconnected:
        raise SocialAccountLifecycleError(
            "Disconnected social account connections cannot be updated"
        )


async def create_connection(
    session: AsyncSession,
    workspace_id: UUID,
    payload: SocialAccountConnectionCreate,
    *,
    actor: AuthorizationActorInput | None = None,
) -> SocialAccountConnection:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_account_manage,
    )
    values = _create_values(payload)
    _assert_transition_allowed(
        SocialAccountConnectionStatus.pending,
        values["status"],
        recovery_succeeded=True,
    )
    await _validate_relationships(session, workspace_id, values)
    connection = await social_accounts.create_connection(session, workspace_id, values)
    event_type = (
        RealtimeEventType.marketing_social_account_connected
        if connection.status == SocialAccountConnectionStatus.connected
        else RealtimeEventType.marketing_social_account_updated
    )
    await _publish_social_account_event(
        session,
        workspace_id=workspace_id,
        event_type=event_type,
        actor=actor,
        connection=connection,
        payload=_social_account_event_payload(
            connection,
            action=(
                "connected"
                if event_type == RealtimeEventType.marketing_social_account_connected
                else "created"
            ),
        ),
    )
    await session.commit()
    return await _load_connection_for_workspace(session, workspace_id, connection.id)


async def register_assisted_connection(
    session: AsyncSession,
    workspace_id: UUID,
    payload: SocialAccountConnectionCreate,
    *,
    actor: AuthorizationActorInput | None = None,
) -> SocialAccountConnection:
    """Register a manually operated social account as connected.

    Assisted connections are marked connected because LabelOS can route work to
    the destination and prepare manual publishing steps immediately. They do not
    use OAuth credentials, so absence of credentials is not a reconnect signal.
    """

    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_account_manage,
    )
    values = _create_values(_assisted_create_payload(payload))
    await _validate_relationships(session, workspace_id, values)
    await _assert_no_reasonable_duplicate(session, workspace_id, values)
    connection = await social_accounts.create_connection(session, workspace_id, values)
    await _publish_social_account_event(
        session,
        workspace_id=workspace_id,
        event_type=RealtimeEventType.marketing_social_account_connected,
        actor=actor,
        connection=connection,
        payload=_social_account_event_payload(connection, action="connected"),
    )
    await session.commit()
    return await _load_connection_for_workspace(session, workspace_id, connection.id)


async def get_connection(
    session: AsyncSession,
    workspace_id: UUID,
    connection_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> SocialAccountConnection:
    connection = await _load_connection_for_workspace(
        session,
        workspace_id,
        connection_id,
    )
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_account_view,
    )
    return connection


async def list_connections(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    query: SocialAccountConnectionQuery | None = None,
    limit: int = 100,
    offset: int = 0,
) -> social_accounts.SocialAccountConnectionListPage:
    _validate_list_pagination(limit=limit, offset=offset)
    normalized_query = query or SocialAccountConnectionQuery()
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_account_view,
    )
    if (
        normalized_query.artist_profile_id is not None
        and not await social_accounts.artist_profile_in_workspace(
            session,
            workspace_id,
            normalized_query.artist_profile_id,
        )
    ):
        raise SocialAccountRelationshipError(
            "artist_profile_id must belong to workspace"
        )
    return await social_accounts.list_connections(
        session,
        workspace_id,
        provider=(
            _normalize_text(normalized_query.provider, "provider").lower()
            if normalized_query.provider is not None
            else None
        ),
        status=(
            _coerce_status(normalized_query.status)
            if normalized_query.status is not None
            else None
        ),
        artist_profile_id=normalized_query.artist_profile_id,
        include_disconnected=normalized_query.include_disconnected,
        limit=limit,
        offset=offset,
    )


async def resolve_destinations(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    provider: str | None,
    artist_profile_id: UUID | None = None,
    desired_capability: str | None = None,
    requested_connection_id: UUID | None = None,
    actor: AuthorizationActorInput | None = None,
) -> DestinationResolution:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_account_view,
    )
    if (
        artist_profile_id is not None
        and not await social_accounts.artist_profile_in_workspace(
            session,
            workspace_id,
            artist_profile_id,
        )
    ):
        raise SocialAccountRelationshipError(
            "artist_profile_id must belong to workspace"
        )

    normalized_provider = _normalize_destination_provider(provider)
    normalized_capability = _normalize_desired_capability(desired_capability)
    page = await social_accounts.list_connections(
        session,
        workspace_id,
        provider=normalized_provider,
        status=None,
        artist_profile_id=None,
        include_disconnected=True,
        limit=MAX_SOCIAL_ACCOUNT_LIST_LIMIT,
        offset=0,
    )
    accounts = [
        _resolved_destination(
            connection,
            workspace_id=workspace_id,
            provider=normalized_provider,
            artist_profile_id=artist_profile_id,
            desired_capability=normalized_capability,
        )
        for connection in page.items
    ]

    requested_account: ResolvedDestination | None = None
    if requested_connection_id is not None:
        requested_connection = await social_accounts.get_connection_by_id(
            session,
            requested_connection_id,
        )
        if requested_connection is None:
            unavailable_reasons = (DestinationUnavailableReason.no_connection,)
        else:
            requested_account = _resolved_destination(
                requested_connection,
                workspace_id=workspace_id,
                provider=normalized_provider,
                artist_profile_id=artist_profile_id,
                desired_capability=normalized_capability,
            )
            unavailable_reasons = requested_account.unavailable_reasons
    elif not accounts:
        unavailable_reasons = (DestinationUnavailableReason.no_connection,)
    else:
        unavailable_reasons = ()

    return DestinationResolution(
        workspace_id=workspace_id,
        provider=normalized_provider,
        artist_profile_id=artist_profile_id,
        desired_capability=normalized_capability,
        accounts=accounts,
        unavailable_reasons=unavailable_reasons,
        requested_account=requested_account,
    )


async def update_connection(
    session: AsyncSession,
    workspace_id: UUID,
    connection_id: UUID,
    payload: SocialAccountConnectionUpdate,
    *,
    actor: AuthorizationActorInput | None = None,
) -> SocialAccountConnection:
    connection = await _load_connection_for_workspace(
        session,
        workspace_id,
        connection_id,
    )
    _assert_mutable(connection)
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_account_manage,
    )
    adapter = resolve_social_account_provider(
        connection.provider,
        connection.connection_method,
    )
    values = _update_values(payload, adapter=adapter)
    if not values:
        return connection
    await _validate_relationships(session, workspace_id, values)
    changed_fields = _changed_fields(connection, values)
    if not changed_fields:
        return connection
    previous_capabilities = (
        list(connection.capabilities or [])
        if "capabilities" in changed_fields
        else None
    )
    updated = await social_accounts.update_connection(
        session,
        workspace_id,
        connection_id,
        {key: values[key] for key in changed_fields},
    )
    if updated is None:
        raise SocialAccountNotFoundError("Social account connection not found")
    await _publish_social_account_event(
        session,
        workspace_id=workspace_id,
        event_type=RealtimeEventType.marketing_social_account_updated,
        actor=actor,
        connection=updated,
        payload=_social_account_event_payload(
            updated,
            action="updated",
            changed_fields=sorted(changed_fields),
            previous_capabilities=previous_capabilities,
        ),
    )
    await session.commit()
    return updated


async def associate_artist_profile(
    session: AsyncSession,
    workspace_id: UUID,
    connection_id: UUID,
    artist_profile_id: UUID | None,
    *,
    actor: AuthorizationActorInput | None = None,
) -> SocialAccountConnection:
    return await update_connection(
        session,
        workspace_id,
        connection_id,
        SocialAccountConnectionUpdate(
            artist_profile_id=artist_profile_id,
            clear_artist_profile=artist_profile_id is None,
        ),
        actor=actor,
    )


async def transition_status(
    session: AsyncSession,
    workspace_id: UUID,
    connection_id: UUID,
    status: SocialAccountConnectionStatus | str,
    *,
    actor: AuthorizationActorInput | None = None,
    recovery_succeeded: bool = False,
    error_code: str | None = None,
    error_message: str | None = None,
) -> SocialAccountConnection:
    connection = await _load_connection_for_workspace(
        session,
        workspace_id,
        connection_id,
    )
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_account_manage,
    )
    next_status = _assert_transition_allowed(
        connection.status,
        status,
        recovery_succeeded=recovery_succeeded,
    )
    if next_status == connection.status:
        return connection
    previous_status = _status_value(connection.status)
    values: dict[str, object] = {"status": next_status}
    if next_status == SocialAccountConnectionStatus.disconnected:
        values.update(
            {
                "credential_ref": None,
                "token_expires_at": None,
                "last_error_code": None,
                "last_error_message": None,
            }
        )
    elif next_status in {
        SocialAccountConnectionStatus.connected,
        SocialAccountConnectionStatus.limited,
    }:
        values["last_error_code"] = None
        values["last_error_message"] = None
        values["last_health_checked_at"] = _now()
    elif next_status == SocialAccountConnectionStatus.error:
        values["last_error_code"] = _normalize_optional_text(error_code)
        values["last_error_message"] = _safe_error_message(error_message)
        values["last_health_checked_at"] = _now()
    updated = await social_accounts.update_connection(
        session,
        workspace_id,
        connection_id,
        values,
    )
    if updated is None:
        raise SocialAccountNotFoundError("Social account connection not found")
    await _publish_social_account_event(
        session,
        workspace_id=workspace_id,
        event_type=(
            RealtimeEventType.marketing_social_account_disconnected
            if next_status == SocialAccountConnectionStatus.disconnected
            else RealtimeEventType.marketing_social_account_health_changed
        ),
        actor=actor,
        connection=updated,
        payload=_social_account_event_payload(
            updated,
            action=(
                "disconnected"
                if next_status == SocialAccountConnectionStatus.disconnected
                else "health_changed"
            ),
            changed_fields=sorted(values),
            previous_status=previous_status,
        ),
    )
    await session.commit()
    return updated


async def disconnect_connection(
    session: AsyncSession,
    workspace_id: UUID,
    connection_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    provider_registry: SocialAccountProviderRegistry | None = None,
) -> SocialAccountConnection:
    connection = await _load_connection_for_workspace(
        session,
        workspace_id,
        connection_id,
    )
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_account_manage,
    )
    if connection.status == SocialAccountConnectionStatus.disconnected:
        return connection
    adapter = (
        provider_registry.resolve(connection.provider, connection.connection_method)
        if provider_registry is not None
        else resolve_social_account_provider(
            connection.provider,
            connection.connection_method,
        )
    )
    await adapter.disconnect(
        credential_ref=connection.credential_ref,
        provider_metadata=connection.provider_metadata,
    )
    return await transition_status(
        session,
        workspace_id,
        connection_id,
        SocialAccountConnectionStatus.disconnected,
        actor=actor,
    )


def _provider_registry_adapter(
    connection: SocialAccountConnection,
    provider_registry: SocialAccountProviderRegistry | None,
) -> SocialAccountConnectionProvider:
    if provider_registry is not None:
        return provider_registry.resolve(
            connection.provider, connection.connection_method
        )
    return resolve_social_account_provider(
        connection.provider,
        connection.connection_method,
    )


def _capabilities_for_adapter_scopes(
    adapter: SocialAccountConnectionProvider,
    scopes: Sequence[str],
) -> list[str]:
    mapper = getattr(adapter, "capabilities_for_scopes", None)
    if callable(mapper):
        return adapter.normalize_capabilities(mapper(scopes))
    return adapter.normalize_capabilities(adapter.default_capabilities())


def _status_from_health(
    connection: SocialAccountConnection,
    health: SocialAccountHealth,
) -> SocialAccountConnectionStatus:
    if health.healthy:
        if health.status == SocialAccountConnectionStatus.limited.value:
            return SocialAccountConnectionStatus.limited
        return SocialAccountConnectionStatus.connected

    code = health.error_code
    if code == SocialAccountProviderErrorCode.insufficient_scope:
        return SocialAccountConnectionStatus.limited
    if code in HEALTH_RECONNECT_REQUIRED_CODES:
        return SocialAccountConnectionStatus.reconnect_required
    if code in HEALTH_RETAIN_CURRENT_STATUS_CODES:
        return connection.status
    if code in HEALTH_ERROR_CODES:
        return SocialAccountConnectionStatus.error

    try:
        return SocialAccountConnectionStatus(health.status)
    except ValueError:
        return SocialAccountConnectionStatus.error


def _health_values(
    connection: SocialAccountConnection,
    health: SocialAccountHealth,
    *,
    checked_at: datetime,
) -> dict[str, object]:
    next_status = _status_from_health(connection, health)
    values: dict[str, object] = {
        "status": next_status,
        "last_health_checked_at": checked_at,
    }
    if health.healthy:
        values["last_error_code"] = None
        values["last_error_message"] = None
    else:
        values["last_error_code"] = _safe_error_code(health.error_code)
        values["last_error_message"] = _safe_error_message(health.error_message)
    if health.provider_metadata:
        values["provider_metadata"] = {
            **dict(connection.provider_metadata or {}),
            **_safe_provider_metadata_object(health.provider_metadata),
        }
    return values


async def _persist_connection_health(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    connection: SocialAccountConnection,
    health: SocialAccountHealth,
    actor: AuthorizationActorInput | None,
    checked_at: datetime | None = None,
) -> SocialAccountConnection:
    observed_at = checked_at or _now()
    values = _health_values(connection, health, checked_at=observed_at)
    changed_fields = _changed_fields(connection, values)
    if not changed_fields:
        return connection

    previous_status = _status_value(connection.status)
    previous_error_code = connection.last_error_code
    previous_error_message = connection.last_error_message
    updated = await social_accounts.update_connection(
        session,
        workspace_id,
        connection.id,
        {key: values[key] for key in changed_fields},
    )
    if updated is None:
        raise SocialAccountNotFoundError("Social account connection not found")

    meaningful_health_change = bool(
        {
            "status",
            "last_error_code",
            "last_error_message",
            "provider_metadata",
        }
        & changed_fields
    )
    if meaningful_health_change:
        payload = _social_account_event_payload(
            updated,
            action="health_changed",
            changed_fields=sorted(changed_fields),
            previous_status=previous_status,
        )
        payload["healthStatus"] = health.status
        payload["healthy"] = health.healthy
        payload["previousErrorCode"] = previous_error_code
        payload["previousErrorMessage"] = _safe_error_message(previous_error_message)
        await _publish_social_account_event(
            session,
            workspace_id=workspace_id,
            event_type=RealtimeEventType.marketing_social_account_health_changed,
            actor=actor,
            connection=updated,
            payload=payload,
        )
    await session.commit()
    return updated


def _health_from_provider_error(exc: SocialAccountProviderError) -> SocialAccountHealth:
    return SocialAccountHealth(
        healthy=False,
        status="unhealthy",
        error_code=exc.code,
        error_message=str(exc),
    )


async def refresh_credentials(
    session: AsyncSession,
    workspace_id: UUID,
    connection_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    provider_registry: SocialAccountProviderRegistry | None = None,
) -> SocialAccountConnection:
    connection = await _load_connection_for_workspace(
        session,
        workspace_id,
        connection_id,
    )
    _assert_mutable(connection)
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_account_manage,
    )
    if connection.connection_method == SocialAccountConnectionMethod.assisted:
        health = SocialAccountHealth(healthy=True, status="assisted_action_required")
        return await _persist_connection_health(
            session,
            workspace_id=workspace_id,
            connection=connection,
            health=health,
            actor=actor,
        )
    if connection.credential_ref is None:
        health = SocialAccountHealth(
            healthy=False,
            status="reconnect_required",
            error_code=SocialAccountProviderErrorCode.credential_missing,
            error_message="Connection credentials are missing",
        )
        return await _persist_connection_health(
            session,
            workspace_id=workspace_id,
            connection=connection,
            health=health,
            actor=actor,
        )

    adapter = _provider_registry_adapter(connection, provider_registry)
    try:
        result = await adapter.refresh_credentials(
            credential_ref=connection.credential_ref,
            provider_metadata=connection.provider_metadata,
        )
    except SocialAccountProviderError as exc:
        health = _health_from_provider_error(exc)
        return await _persist_connection_health(
            session,
            workspace_id=workspace_id,
            connection=connection,
            health=health,
            actor=actor,
        )

    values = _credential_recovery_values(connection, adapter, result)
    updated = await social_accounts.update_connection(
        session,
        workspace_id,
        connection_id,
        values,
    )
    if updated is None:
        raise SocialAccountNotFoundError("Social account connection not found")
    await _publish_health_recovered_event(
        session,
        workspace_id=workspace_id,
        actor=actor,
        connection=updated,
        previous_status=_status_value(connection.status),
        changed_fields=sorted(_changed_fields(connection, values)),
    )
    await session.commit()
    return updated


def _credential_recovery_values(
    connection: SocialAccountConnection,
    adapter: SocialAccountConnectionProvider,
    result: SocialAccountCredentialResult,
) -> dict[str, object]:
    capabilities = (
        _capabilities_for_adapter_scopes(adapter, result.granted_scopes)
        if result.granted_scopes
        else list(connection.capabilities or [])
    )
    status = (
        SocialAccountConnectionStatus.connected
        if capabilities == list(adapter.default_capabilities())
        else SocialAccountConnectionStatus.limited
    )
    values: dict[str, object] = {
        "status": status,
        "credential_ref": result.credential_ref or connection.credential_ref,
        "token_expires_at": result.token_expires_at or connection.token_expires_at,
        "capabilities": adapter.normalize_capabilities(capabilities),
        "last_health_checked_at": _now(),
        "last_error_code": None,
        "last_error_message": None,
    }
    if result.provider_metadata:
        values["provider_metadata"] = {
            **dict(connection.provider_metadata or {}),
            **_safe_provider_metadata_object(result.provider_metadata),
        }
    return values


async def _publish_health_recovered_event(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    actor: AuthorizationActorInput | None,
    connection: SocialAccountConnection,
    previous_status: str,
    changed_fields: list[str],
) -> None:
    payload = _social_account_event_payload(
        connection,
        action="health_changed",
        changed_fields=changed_fields,
        previous_status=previous_status,
    )
    payload["healthStatus"] = "connected"
    payload["healthy"] = True
    await _publish_social_account_event(
        session,
        workspace_id=workspace_id,
        event_type=RealtimeEventType.marketing_social_account_health_changed,
        actor=actor,
        connection=connection,
        payload=payload,
    )


async def check_connection_health(
    session: AsyncSession,
    workspace_id: UUID,
    connection_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    provider_registry: SocialAccountProviderRegistry | None = None,
) -> SocialAccountHealth:
    connection = await _load_connection_for_workspace(
        session,
        workspace_id,
        connection_id,
    )
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_account_view,
    )
    if connection.status == SocialAccountConnectionStatus.disconnected:
        return SocialAccountHealth(healthy=False, status="disconnected")
    if (
        connection.connection_method == SocialAccountConnectionMethod.direct_api
        and connection.credential_ref is None
    ):
        health = SocialAccountHealth(
            healthy=False,
            status="reconnect_required",
            error_code=SocialAccountProviderErrorCode.credential_missing,
            error_message="Connection credentials are missing",
        )
        await _persist_connection_health(
            session,
            workspace_id=workspace_id,
            connection=connection,
            health=health,
            actor=actor,
        )
        return health
    adapter = _provider_registry_adapter(connection, provider_registry)
    health = await adapter.check_connection_health(
        credential_ref=connection.credential_ref,
        token_expires_at=connection.token_expires_at,
        provider_metadata=connection.provider_metadata,
    )
    if (
        connection.connection_method != SocialAccountConnectionMethod.assisted
        and health.error_code == SocialAccountProviderErrorCode.credential_expired
    ):
        recovered = await refresh_credentials(
            session,
            workspace_id,
            connection.id,
            actor=actor,
            provider_registry=provider_registry,
        )
        return SocialAccountHealth(
            healthy=(
                recovered.last_error_code is None
                and recovered.status
                in {
                    SocialAccountConnectionStatus.connected,
                    SocialAccountConnectionStatus.limited,
                }
            ),
            status=recovered.status.value,
            error_code=(
                SocialAccountProviderErrorCode(recovered.last_error_code)
                if recovered.last_error_code
                else None
            ),
            error_message=recovered.last_error_message,
        )
    await _persist_connection_health(
        session,
        workspace_id=workspace_id,
        connection=connection,
        health=health,
        actor=actor,
    )
    return health


async def sync_account_metadata(
    session: AsyncSession,
    workspace_id: UUID,
    connection_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    provider_registry: SocialAccountProviderRegistry | None = None,
) -> SocialAccountConnection:
    connection = await _load_connection_for_workspace(
        session,
        workspace_id,
        connection_id,
    )
    _assert_mutable(connection)
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_account_manage,
    )
    if (
        connection.connection_method == SocialAccountConnectionMethod.direct_api
        and connection.credential_ref is None
    ):
        health = SocialAccountHealth(
            healthy=False,
            status="reconnect_required",
            error_code=SocialAccountProviderErrorCode.credential_missing,
            error_message="Connection credentials are missing",
        )
        return await _persist_connection_health(
            session,
            workspace_id=workspace_id,
            connection=connection,
            health=health,
            actor=actor,
        )
    adapter = _provider_registry_adapter(connection, provider_registry)
    try:
        result = await adapter.synchronize_account_metadata(
            credential_ref=connection.credential_ref,
            provider_metadata=connection.provider_metadata,
        )
    except SocialAccountProviderError as exc:
        health = SocialAccountHealth(
            healthy=False,
            status="sync_failed",
            error_code=exc.code,
            error_message=str(exc),
        )
        return await _persist_connection_health(
            session,
            workspace_id=workspace_id,
            connection=connection,
            health=health,
            actor=actor,
        )
    return await _apply_metadata_sync(
        session,
        workspace_id=workspace_id,
        connection=connection,
        adapter=adapter,
        result=result,
        actor=actor,
    )


async def _apply_metadata_sync(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    connection: SocialAccountConnection,
    adapter: SocialAccountConnectionProvider,
    result: SocialAccountMetadataSync,
    actor: AuthorizationActorInput | None,
) -> SocialAccountConnection:
    values: dict[str, object] = {
        "last_synced_at": _now(),
        "last_error_code": None,
        "last_error_message": None,
    }
    if result.identity is not None:
        validation = adapter.validate_account_input(
            result.identity,
            provider_metadata={
                **dict(connection.provider_metadata or {}),
                **_safe_provider_metadata_object(result.provider_metadata),
            },
        )
        values.update(
            {
                "external_account_id": validation.identity.external_account_id,
                "username": validation.identity.username,
                "display_name": validation.identity.display_name,
                "profile_url": validation.identity.profile_url,
                "provider_metadata": _safe_provider_metadata_object(
                    validation.provider_metadata
                ),
            }
        )
    elif result.provider_metadata:
        values["provider_metadata"] = {
            **dict(connection.provider_metadata or {}),
            **_safe_provider_metadata_object(result.provider_metadata),
        }
    if result.capabilities:
        values["capabilities"] = adapter.normalize_capabilities(result.capabilities)

    changed_fields = _changed_fields(connection, values)
    if not changed_fields:
        return connection
    updated = await social_accounts.update_connection(
        session,
        workspace_id,
        connection.id,
        {key: values[key] for key in changed_fields},
    )
    if updated is None:
        raise SocialAccountNotFoundError("Social account connection not found")
    await _publish_social_account_event(
        session,
        workspace_id=workspace_id,
        event_type=RealtimeEventType.marketing_social_account_updated,
        actor=actor,
        connection=updated,
        payload=_social_account_event_payload(
            updated,
            action="synced",
            changed_fields=sorted(changed_fields),
        ),
    )
    await session.commit()
    return updated


def resolve_capabilities(connection: SocialAccountConnection) -> dict[str, bool]:
    return {
        "can_auto_publish": can_auto_publish(connection),
        "requires_manual_publish": requires_manual_publish(connection),
        "supports_manual_metrics": supports_manual_metrics(connection),
        "can_read_account_analytics": can_read_account_analytics(connection),
        "can_read_post_analytics": can_read_post_analytics(connection),
    }
