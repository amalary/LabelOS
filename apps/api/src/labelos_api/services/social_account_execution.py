"""Credential readiness for trusted, workspace-scoped external execution.

Social Accounts owns this boundary and all credential lifecycle work. Callers get
an ephemeral, repr-safe payload, never credential material for durable delivery.
No SQL transaction spans credential-backend or OAuth provider I/O.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labelos_api.services import social_account_service as accounts
from labelos_api.services.credential_store import (
    CredentialNotFoundError,
    CredentialPayload,
    CredentialStore,
    CredentialStoreError,
    InvalidCredentialReferenceError,
)
from labelos_api.social_accounts.providers import (
    SocialAccountConnectionProvider,
    SocialAccountProviderError,
)
from labelos_api.social_accounts.providers import (
    SocialAccountProviderErrorCode as Code,
)


class ExecutionCredentialError(ValueError):
    def __init__(self, code: Code):
        super().__init__(code.value)
        self.code = code


class SocialAccountExecution:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        provider: SocialAccountConnectionProvider,
        credential_store: CredentialStore,
        required_scopes: frozenset[str],
    ):
        self.sessions = sessions
        self.provider = provider
        self.store = credential_store
        self.required_scopes = required_scopes

    async def connection(
        self,
        *,
        workspace_id: UUID,
        destination_id: UUID,
        destination_identity: str,
    ) -> accounts.ExecutionConnectionSnapshot:
        async with self.sessions() as session:
            return await accounts.load_execution_connection(
                session,
                workspace_id=workspace_id,
                connection_id=destination_id,
                provider=self.provider.provider,
                connection_method=self.provider.connection_method,
                destination_identity=destination_identity,
                required_capability=accounts.SOCIAL_ACCOUNT_CAPABILITY_CONTENT_PUBLISH,
            )

    async def observe(
        self,
        connection: accounts.ExecutionConnectionSnapshot,
        code: Code | None,
    ) -> None:
        # Health persistence must never erase authoritative provider evidence.
        # Stale observations are ignored by the canonical service's guarded API.
        try:
            async with self.sessions() as session:
                await accounts.record_execution_health(
                    session,
                    expected=connection,
                    error_code=code,
                )
        except SQLAlchemyError:
            pass

    async def credentials(
        self,
        connection: accounts.ExecutionConnectionSnapshot,
    ) -> tuple[accounts.ExecutionConnectionSnapshot, CredentialPayload]:
        try:
            if not connection.credential_ref:
                raise ExecutionCredentialError(Code.credential_missing)
            values = (await self.store.get(connection.credential_ref)).expose()
            self._validate_grants(values)
            expiry = connection.token_expires_at
            if expiry is not None and expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            if expiry is None or expiry <= datetime.now(UTC) + timedelta(seconds=60):
                refresh_token = values.get("refresh_token")
                if not isinstance(refresh_token, str) or not refresh_token.strip():
                    raise ExecutionCredentialError(Code.credential_expired)
                result = await self.provider.refresh_credentials(
                    credential_ref=connection.credential_ref,
                )
                if result.credential_ref != connection.credential_ref:
                    raise ExecutionCredentialError(Code.refresh_failed)
                # Persist authoritative grants even if reduced, before rejecting use.
                async with self.sessions() as session:
                    refreshed = await accounts.apply_execution_refresh(
                        session,
                        expected=connection,
                        adapter=self.provider,
                        result=result,
                    )
                    if refreshed is None:
                        raise accounts.ExecutionConnectionError("connection_changed")
                connection = refreshed
                values = (await self.store.get(result.credential_ref)).expose()
                self._validate_grants(values)
                expiry = connection.token_expires_at
                if expiry is not None and expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=UTC)
                if expiry is None or expiry <= datetime.now(UTC):
                    raise ExecutionCredentialError(Code.refresh_failed)
            token = values.get("access_token")
            if not isinstance(token, str) or not token.strip():
                raise ExecutionCredentialError(Code.credential_missing)
            # Execution needs only the access token. Refresh material stays here.
            return connection, CredentialPayload({"access_token": token})
        except (CredentialNotFoundError, InvalidCredentialReferenceError):
            code = Code.credential_missing
        except (CredentialStoreError, httpx.HTTPError):
            code = Code.provider_unavailable
        except SocialAccountProviderError as exc:
            code = exc.code
            if code == Code.malformed_provider_response:
                code = Code.provider_unavailable
        except ExecutionCredentialError as exc:
            code = exc.code
        await self.observe(connection, code)
        raise ExecutionCredentialError(code) from None

    def _validate_grants(self, values: dict) -> None:
        scope = values.get("scope")
        if not isinstance(scope, str) or not self.required_scopes.issubset(
            scope.split()
        ):
            raise ExecutionCredentialError(Code.insufficient_scope)
        if str(values.get("token_type", "Bearer")).lower() != "bearer":
            raise ExecutionCredentialError(Code.authorization_failed)
