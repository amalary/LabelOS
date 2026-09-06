from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from labelos_database.models import (
    SocialAccountConnection,
    SocialAccountConnectionMethod,
    SocialAccountConnectionStatus,
)
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.auth import CurrentUserContext
from labelos_api.authorization import (
    Capability,
)
from labelos_api.realtime import RealtimeEventType
from labelos_api.repositories import social_accounts
from labelos_api.services import oauth_state_service, social_account_service
from labelos_api.services.credential_store import (
    CredentialPayload,
    CredentialStore,
    CredentialStoreError,
)
from labelos_api.services.oauth_state_service import OAuthStateCreate
from labelos_api.services.social_account_service import (
    SocialAccountDuplicateError,
)
from labelos_api.social_accounts.providers import (
    SocialAccountConnectionProvider,
    SocialAccountProviderError,
    SocialAccountProviderErrorCode,
    SocialAccountProviderRegistry,
)


class OAuthConnectionError(ValueError):
    """Base OAuth lifecycle error with no credential-bearing details."""


class OAuthProviderDeniedError(OAuthConnectionError):
    pass


class OAuthCredentialStorageError(OAuthConnectionError):
    pass


@dataclass(frozen=True, kw_only=True)
class OAuthConnectionStart:
    provider: str
    redirect_uri: str
    safe_redirect_path: str
    scopes: Sequence[str] = ()
    connection_method: SocialAccountConnectionMethod | str = (
        SocialAccountConnectionMethod.direct_api
    )
    provider_metadata: Mapping[str, object] | None = None


@dataclass(frozen=True, kw_only=True)
class OAuthConnectionCallback:
    provider: str
    redirect_uri: str
    state: str | None
    code: str | None = None
    error: str | None = None
    connection_method: SocialAccountConnectionMethod | str = (
        SocialAccountConnectionMethod.direct_api
    )
    provider_metadata: Mapping[str, object] | None = None


@dataclass(frozen=True, kw_only=True)
class OAuthConnectionStartResult:
    authorization_url: str
    state: str
    expires_at: object
    scopes: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class OAuthConnectionCallbackResult:
    connection: SocialAccountConnection
    safe_redirect_path: str
    created: bool


async def start_oauth_connection(
    session: AsyncSession,
    workspace_id: UUID,
    payload: OAuthConnectionStart,
    *,
    actor: CurrentUserContext,
    credential_store: CredentialStore,
    provider_registry: SocialAccountProviderRegistry,
) -> OAuthConnectionStartResult:
    await social_account_service._require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_account_manage,
    )
    adapter = provider_registry.resolve(payload.provider, payload.connection_method)
    pending = await oauth_state_service.create_state(
        session,
        OAuthStateCreate(
            workspace_id=workspace_id,
            actor_user_id=actor.user.id,
            provider=payload.provider,
            connection_method=payload.connection_method,
            safe_redirect_path=payload.safe_redirect_path,
        ),
        credential_store=credential_store,
    )
    authorization = await adapter.build_authorization_request(
        redirect_uri=payload.redirect_uri,
        state=pending.state,
        scopes=payload.scopes,
        provider_metadata=payload.provider_metadata,
    )
    return OAuthConnectionStartResult(
        authorization_url=authorization.authorization_url,
        state=authorization.state,
        expires_at=pending.expires_at,
        scopes=authorization.scopes,
    )


async def complete_oauth_connection(
    session: AsyncSession,
    workspace_id: UUID,
    payload: OAuthConnectionCallback,
    *,
    actor: CurrentUserContext,
    credential_store: CredentialStore,
    provider_registry: SocialAccountProviderRegistry,
) -> OAuthConnectionCallbackResult:
    await social_account_service._require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.marketing_account_manage,
    )
    adapter = provider_registry.resolve(payload.provider, payload.connection_method)
    consumed = await oauth_state_service.consume_state(
        session,
        state=payload.state,
        workspace_id=workspace_id,
        actor_user_id=actor.user.id,
        provider=payload.provider,
        connection_method=payload.connection_method,
        credential_store=credential_store,
    )
    if payload.error is not None:
        raise OAuthProviderDeniedError("OAuth authorization was denied")
    if payload.code is None or not payload.code.strip():
        raise SocialAccountProviderError(
            SocialAccountProviderErrorCode.authorization_failed,
            "OAuth authorization code is required",
            provider=payload.provider,
            connection_method=payload.connection_method,
        )

    exchange = await adapter.complete_oauth_exchange(
        code=payload.code,
        redirect_uri=payload.redirect_uri,
        provider_metadata=payload.provider_metadata,
    )
    credential_ref = exchange.credential_ref
    if credential_ref is None:
        if exchange.credential_payload is None:
            raise SocialAccountProviderError(
                SocialAccountProviderErrorCode.malformed_provider_response,
                "Provider did not return credential material",
                provider=payload.provider,
                connection_method=payload.connection_method,
            )
        try:
            credential_ref = await credential_store.put(
                CredentialPayload(exchange.credential_payload)
            )
        except CredentialStoreError as exc:
            raise OAuthCredentialStorageError("Credential storage failed") from exc

    identity = await adapter.retrieve_account_identity(
        credential_ref=credential_ref,
        provider_metadata=exchange.provider_metadata,
    )
    capabilities = _capabilities_for_scopes(adapter, exchange.granted_scopes)
    status = (
        SocialAccountConnectionStatus.connected
        if capabilities == list(adapter.default_capabilities())
        else SocialAccountConnectionStatus.limited
    )
    validation = adapter.validate_account_input(
        identity,
        provider_metadata=_connection_metadata(exchange.provider_metadata),
    )
    values = {
        "provider": validation.identity.provider,
        "external_account_id": validation.identity.external_account_id,
        "username": validation.identity.username,
        "display_name": validation.identity.display_name,
        "profile_url": validation.identity.profile_url,
        "connection_method": payload.connection_method,
        "status": status,
        "capabilities": adapter.normalize_capabilities(capabilities),
        "credential_ref": credential_ref,
        "token_expires_at": exchange.token_expires_at,
        "last_health_checked_at": consumed.record.consumed_at,
        "provider_metadata": validation.provider_metadata,
        "created_by_user_id": actor.user.id,
        "created_by_profile_id": _current_profile_id(actor, workspace_id),
    }
    await social_account_service._validate_relationships(session, workspace_id, values)
    connection, created = await _create_or_update_connection(
        session,
        workspace_id,
        values,
        actor=actor,
    )
    return OAuthConnectionCallbackResult(
        connection=connection,
        safe_redirect_path=consumed.record.safe_redirect_path,
        created=created,
    )


def _capabilities_for_scopes(
    adapter: SocialAccountConnectionProvider,
    scopes: Sequence[str],
) -> list[str]:
    mapper = getattr(adapter, "capabilities_for_scopes", None)
    if callable(mapper):
        return list(mapper(scopes))
    return adapter.normalize_capabilities(adapter.default_capabilities())


def _connection_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in metadata.items()
        if key not in {"access_token", "refresh_token", "id_token", "token"}
    }


def _current_profile_id(actor: CurrentUserContext, workspace_id: UUID) -> UUID | None:
    for membership in actor.workspace_memberships:
        if membership.workspace_id == workspace_id:
            return getattr(membership, "profile_id", None)
    return None


async def _create_or_update_connection(
    session: AsyncSession,
    workspace_id: UUID,
    values: Mapping[str, object],
    *,
    actor: CurrentUserContext,
) -> tuple[SocialAccountConnection, bool]:
    provider = values["provider"]
    external_account_id = values.get("external_account_id")
    existing = None
    if isinstance(provider, str) and isinstance(external_account_id, str):
        existing = (
            await social_accounts.find_active_connection_by_provider_external_account(
                session,
                workspace_id,
                provider=provider,
                external_account_id=external_account_id,
            )
        )
    if existing is None:
        await social_account_service._assert_no_reasonable_duplicate(
            session,
            workspace_id,
            values,
        )
        created = await social_accounts.create_connection(session, workspace_id, values)
        await social_account_service._publish_social_account_event(
            session,
            workspace_id=workspace_id,
            event_type=RealtimeEventType.marketing_social_account_connected,
            actor=actor,
            connection=created,
            payload=social_account_service._social_account_event_payload(
                created,
                action="connected",
            ),
        )
        await session.commit()
        return created, True

    updated = await social_accounts.update_connection(
        session,
        workspace_id,
        existing.id,
        {
            key: value
            for key, value in values.items()
            if key
            in {
                "username",
                "display_name",
                "profile_url",
                "status",
                "capabilities",
                "credential_ref",
                "token_expires_at",
                "last_health_checked_at",
                "last_error_code",
                "last_error_message",
                "provider_metadata",
            }
        },
    )
    if updated is None:
        raise SocialAccountDuplicateError("Social account connection update failed")
    await social_account_service._publish_social_account_event(
        session,
        workspace_id=workspace_id,
        event_type=RealtimeEventType.marketing_social_account_connected,
        actor=actor,
        connection=updated,
        payload=social_account_service._social_account_event_payload(
            updated,
            action="connected",
        ),
    )
    await session.commit()
    return updated, False
