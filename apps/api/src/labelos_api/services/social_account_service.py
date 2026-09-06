from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
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
    SocialAccountConnectionProvider,
    SocialAccountHealth,
    SocialAccountIdentity,
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

SENSITIVE_SOCIAL_ACCOUNT_EVENT_FIELDS = frozenset(
    {
        "credential_ref",
        "token_expires_at",
    }
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
        provider_metadata=_json_object(
            payload.provider_metadata,
            "provider_metadata",
        ),
    )
    identity = validation_result.identity
    values: dict[str, object] = {
        "provider": identity.provider,
        "connection_method": method,
        "status": _coerce_status(payload.status),
        "capabilities": _normalize_capabilities(payload.capabilities, adapter=adapter),
        "provider_metadata": validation_result.provider_metadata,
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
        _normalize_optional_text(payload.last_error_message),
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
        _normalize_optional_text(payload.last_error_message),
    )
    if payload.provider_metadata is not None:
        values["provider_metadata"] = _json_object(
            payload.provider_metadata,
            "provider_metadata",
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
    username = values.get("username")
    external_account_id = values.get("external_account_id")
    if not isinstance(provider, str):
        return

    if isinstance(username, str):
        existing_username = (
            await social_accounts.find_active_connection_by_provider_username(
                session,
                workspace_id,
                provider=provider,
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
        values["last_error_message"] = _normalize_optional_text(error_message)
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
) -> SocialAccountConnection:
    return await transition_status(
        session,
        workspace_id,
        connection_id,
        SocialAccountConnectionStatus.disconnected,
        actor=actor,
    )


async def check_connection_health(
    session: AsyncSession,
    workspace_id: UUID,
    connection_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
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
    adapter = resolve_social_account_provider(
        connection.provider,
        connection.connection_method,
    )
    return await adapter.check_connection_health(
        credential_ref=connection.credential_ref,
        token_expires_at=connection.token_expires_at,
        provider_metadata=connection.provider_metadata,
    )


def resolve_capabilities(connection: SocialAccountConnection) -> dict[str, bool]:
    return {
        "can_auto_publish": can_auto_publish(connection),
        "requires_manual_publish": requires_manual_publish(connection),
        "supports_manual_metrics": supports_manual_metrics(connection),
        "can_read_account_analytics": can_read_account_analytics(connection),
        "can_read_post_analytics": can_read_post_analytics(connection),
    }
