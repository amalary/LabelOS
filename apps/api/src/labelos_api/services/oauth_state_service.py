import hashlib
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID

from labelos_database.models import (
    OAuthAuthorizationState,
    OAuthAuthorizationStateStatus,
    SocialAccountConnectionMethod,
)
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.repositories import oauth_states, social_accounts
from labelos_api.services.credential_store import CredentialPayload, CredentialStore
from labelos_api.social_accounts.providers import canonical_provider_key

OAUTH_STATE_TTL = timedelta(minutes=10)
_STATE_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


class OAuthStateError(ValueError):
    """Base error for OAuth state failures with safe public messages."""


class OAuthStateMissingError(OAuthStateError):
    pass


class OAuthStateMalformedError(OAuthStateError):
    pass


class OAuthStateNotFoundError(OAuthStateError):
    pass


class OAuthStateConsumedError(OAuthStateError):
    pass


class OAuthStateExpiredError(OAuthStateError):
    pass


class OAuthStateBindingError(OAuthStateError):
    pass


class OAuthStateRedirectError(OAuthStateError):
    pass


@dataclass(frozen=True, kw_only=True)
class OAuthStateCreate:
    workspace_id: UUID
    actor_user_id: UUID
    provider: str
    connection_method: SocialAccountConnectionMethod | str
    safe_redirect_path: str
    pkce_code_verifier: str | None = None
    ttl: timedelta = OAUTH_STATE_TTL


@dataclass(frozen=True, kw_only=True)
class PendingOAuthAuthorizationState:
    state: str
    expires_at: datetime
    safe_redirect_path: str


@dataclass(frozen=True, kw_only=True)
class OAuthStateConsumption:
    record: OAuthAuthorizationState
    pkce_payload: Mapping[str, object] | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _new_state_nonce() -> str:
    return secrets.token_urlsafe(32)


def _validate_state_nonce(state: str | None) -> str:
    if state is None or not state.strip():
        raise OAuthStateMissingError("OAuth state is required")
    normalized = state.strip()
    if _STATE_NONCE_PATTERN.fullmatch(normalized) is None:
        raise OAuthStateMalformedError("OAuth state is malformed")
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
        raise OAuthStateBindingError("OAuth connection method is unsupported") from exc


def _safe_redirect_path(value: str) -> str:
    normalized = value.strip()
    parsed = urlparse(normalized)
    if (
        not normalized
        or parsed.scheme
        or parsed.netloc
        or not normalized.startswith("/")
        or normalized.startswith("//")
        or "\\" in normalized
    ):
        raise OAuthStateRedirectError("OAuth redirect target is not allowed")
    return normalized


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def create_state(
    session: AsyncSession,
    payload: OAuthStateCreate,
    *,
    credential_store: CredentialStore | None = None,
    now: datetime | None = None,
) -> PendingOAuthAuthorizationState:
    issued_at = _utc(now or _now())
    if payload.ttl <= timedelta(0) or payload.ttl > timedelta(minutes=30):
        raise OAuthStateBindingError("OAuth state ttl must be between 0 and 30 minutes")
    method = _coerce_method(payload.connection_method)
    provider = canonical_provider_key(payload.provider)
    redirect_path = _safe_redirect_path(payload.safe_redirect_path)
    if not await social_accounts.user_is_active_workspace_member(
        session,
        payload.workspace_id,
        payload.actor_user_id,
    ):
        raise OAuthStateBindingError("OAuth actor must belong to the workspace")

    pkce_credential_ref: str | None = None
    if payload.pkce_code_verifier is not None:
        if not payload.pkce_code_verifier.strip():
            raise OAuthStateBindingError("PKCE verifier is required when supplied")
        if credential_store is None:
            raise OAuthStateBindingError("PKCE verifier storage is not configured")
        pkce_credential_ref = await credential_store.put(
            CredentialPayload({"pkce_code_verifier": payload.pkce_code_verifier})
        )

    state = _new_state_nonce()
    expires_at = issued_at + payload.ttl
    await oauth_states.create_state(
        session,
        {
            "organization_id": payload.workspace_id,
            "state_hash": _state_hash(state),
            "actor_user_id": payload.actor_user_id,
            "provider": provider,
            "connection_method": method,
            "status": OAuthAuthorizationStateStatus.pending,
            "expires_at": expires_at,
            "safe_redirect_path": redirect_path,
            "pkce_credential_ref": pkce_credential_ref,
        },
    )
    await session.commit()
    return PendingOAuthAuthorizationState(
        state=state,
        expires_at=expires_at,
        safe_redirect_path=redirect_path,
    )


async def consume_state(
    session: AsyncSession,
    *,
    state: str | None,
    workspace_id: UUID,
    actor_user_id: UUID,
    provider: str,
    connection_method: SocialAccountConnectionMethod | str,
    credential_store: CredentialStore | None = None,
    now: datetime | None = None,
) -> OAuthStateConsumption:
    checked_at = _utc(now or _now())
    normalized_state = _validate_state_nonce(state)
    record = await oauth_states.get_state_by_hash(
        session,
        _state_hash(normalized_state),
    )
    if record is None:
        raise OAuthStateNotFoundError("OAuth state was not found")
    if record.status == OAuthAuthorizationStateStatus.consumed or (
        record.consumed_at is not None
    ):
        raise OAuthStateConsumedError("OAuth state has already been used")
    if record.status == OAuthAuthorizationStateStatus.expired or (
        _utc(record.expires_at) <= checked_at
    ):
        await oauth_states.mark_state_terminal(
            session,
            record,
            status=OAuthAuthorizationStateStatus.expired,
        )
        await session.commit()
        raise OAuthStateExpiredError("OAuth state has expired")

    expected_provider = canonical_provider_key(provider)
    expected_method = _coerce_method(connection_method)
    if (
        record.organization_id != workspace_id
        or record.actor_user_id != actor_user_id
        or record.provider != expected_provider
        or record.connection_method != expected_method
    ):
        raise OAuthStateBindingError("OAuth state binding does not match callback")

    pkce_payload: Mapping[str, object] | None = None
    if record.pkce_credential_ref is not None:
        if credential_store is None:
            raise OAuthStateBindingError("PKCE verifier storage is not configured")
        pkce_payload = (await credential_store.get(record.pkce_credential_ref)).expose()

    consumed = await oauth_states.consume_pending_state(
        session,
        record,
        consumed_at=checked_at,
    )
    if consumed is None:
        raise OAuthStateConsumedError("OAuth state has already been used")
    await session.commit()
    return OAuthStateConsumption(record=consumed, pkce_payload=pkce_payload)


async def safe_redirect_path_for_state(
    session: AsyncSession,
    *,
    state: str | None,
    workspace_id: UUID,
    actor_user_id: UUID,
    provider: str,
    connection_method: SocialAccountConnectionMethod | str,
) -> str | None:
    try:
        normalized_state = _validate_state_nonce(state)
        expected_provider = canonical_provider_key(provider)
        expected_method = _coerce_method(connection_method)
    except OAuthStateError:
        return None

    record = await oauth_states.get_state_by_hash(
        session,
        _state_hash(normalized_state),
    )
    if record is None:
        return None
    if (
        record.organization_id != workspace_id
        or record.actor_user_id != actor_user_id
        or record.provider != expected_provider
        or record.connection_method != expected_method
    ):
        return None
    return record.safe_redirect_path


async def workspace_id_for_state(
    session: AsyncSession,
    *,
    state: str | None,
    actor_user_id: UUID,
    provider: str,
    connection_method: SocialAccountConnectionMethod | str,
) -> UUID | None:
    try:
        normalized_state = _validate_state_nonce(state)
        expected_provider = canonical_provider_key(provider)
        expected_method = _coerce_method(connection_method)
    except OAuthStateError:
        return None

    record = await oauth_states.get_state_by_hash(
        session,
        _state_hash(normalized_state),
    )
    if record is None:
        return None
    if (
        record.actor_user_id != actor_user_id
        or record.provider != expected_provider
        or record.connection_method != expected_method
    ):
        return None
    return record.organization_id


async def cleanup_expired_states(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    deleted = await oauth_states.delete_expired_states(session, now=_utc(now or _now()))
    await session.commit()
    return deleted
