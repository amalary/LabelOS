from datetime import datetime
from typing import Annotated, Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from labelos_database.models import (
    SocialAccountConnection,
    SocialAccountConnectionStatus,
    WorkspaceMembership,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from labelos_api.auth import CurrentUserContext, SessionDep, get_current_user_context
from labelos_api.services import social_account_service
from labelos_api.services.social_account_service import (
    SocialAccountAuthorizationError,
    SocialAccountConnectionCreate,
    SocialAccountConnectionQuery,
    SocialAccountConnectionUpdate,
    SocialAccountDuplicateError,
    SocialAccountLifecycleError,
    SocialAccountNotFoundError,
    SocialAccountRelationshipError,
)
from labelos_api.social_accounts.providers import SocialAccountProviderError

router = APIRouter(prefix="/workspaces", tags=["social-account-connections"])

SENSITIVE_METADATA_KEY_PARTS = frozenset(
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


class SocialAccountConnectionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=80)
    artist_profile_id: UUID | None = None
    external_account_id: str | None = Field(default=None, max_length=255)
    handle: str | None = Field(default=None, min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    profile_url: str | None = Field(default=None, max_length=2048)
    capabilities: list[str] | None = None
    provider_metadata: dict[str, Any] | None = None


class SocialAccountConnectionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artist_profile_id: UUID | None = None
    handle: str | None = Field(default=None, min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    profile_url: str | None = Field(default=None, max_length=2048)
    capabilities: list[str] | None = None
    provider_metadata: dict[str, Any] | None = None

    @field_validator("provider_metadata")
    @classmethod
    def require_metadata_object(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        return value

    @model_validator(mode="after")
    def require_update(self) -> "SocialAccountConnectionUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one social account connection field is required")
        return self


class SocialAccountArtistAssociationResponse(BaseModel):
    artist_profile_id: UUID
    artist_id: UUID
    artist_name: str
    stage_name: str | None


class SocialAccountCapabilitiesResponse(BaseModel):
    can_auto_publish: bool
    requires_manual_publish: bool
    supports_manual_metrics: bool
    can_read_account_analytics: bool
    can_read_post_analytics: bool


class SocialAccountConnectionResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    provider: str
    external_account_id: str | None
    handle: str | None
    display_name: str | None
    profile_url: str | None
    artist_association: SocialAccountArtistAssociationResponse | None
    connection_method: str
    status: SocialAccountConnectionStatus
    capabilities: list[str]
    resolved_capabilities: SocialAccountCapabilitiesResponse
    token_expires_at: datetime | None
    last_synced_at: datetime | None
    last_health_checked_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    provider_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SocialAccountConnectionListResponse(BaseModel):
    social_account_connections: list[SocialAccountConnectionResponse]
    total: int
    limit: int
    offset: int


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _raise_capability_denial(reason: str) -> NoReturn:
    if reason in {"invalid_resource_scope", "membership_not_found"}:
        raise _not_found()
    if reason == "insufficient_department_access":
        raise _forbidden("Insufficient department access")
    raise _forbidden("Insufficient capability permission")


def _service_error(
    exc: (
        SocialAccountAuthorizationError
        | SocialAccountDuplicateError
        | SocialAccountLifecycleError
        | SocialAccountNotFoundError
        | SocialAccountProviderError
        | SocialAccountRelationshipError
    ),
) -> NoReturn:
    if isinstance(exc, SocialAccountAuthorizationError):
        _raise_capability_denial(exc.reason)
    if isinstance(exc, SocialAccountNotFoundError):
        raise _not_found() from exc
    if isinstance(exc, SocialAccountDuplicateError):
        raise _conflict(str(exc)) from exc
    if isinstance(exc, SocialAccountLifecycleError):
        raise _conflict(str(exc)) from exc
    raise _bad_request(str(exc)) from exc


async def _current_workspace_membership(
    session: SessionDep,
    *,
    context: CurrentUserContext,
    workspace_id: UUID,
) -> WorkspaceMembership | None:
    return await session.scalar(
        select(WorkspaceMembership)
        .join(WorkspaceMembership.profile)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.status == "active")
        .where(WorkspaceMembership.profile.has(user_id=context.user.id))
    )


def _safe_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _safe_metadata(item)
            for key, item in value.items()
            if not _is_sensitive_metadata_key(str(key))
        }
    if isinstance(value, list):
        return [_safe_metadata(item) for item in value]
    return value


def _is_sensitive_metadata_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_METADATA_KEY_PARTS)


def _create_payload(
    payload: SocialAccountConnectionCreateRequest,
    *,
    context: CurrentUserContext,
    created_by_profile_id: UUID,
) -> SocialAccountConnectionCreate:
    return SocialAccountConnectionCreate(
        provider=payload.provider,
        artist_profile_id=payload.artist_profile_id,
        external_account_id=payload.external_account_id,
        username=payload.handle,
        display_name=payload.display_name,
        profile_url=payload.profile_url,
        capabilities=payload.capabilities or (),
        provider_metadata=payload.provider_metadata,
        created_by_user_id=context.user.id,
        created_by_profile_id=created_by_profile_id,
    )


def _update_payload(
    payload: SocialAccountConnectionUpdateRequest,
) -> SocialAccountConnectionUpdate:
    fields = payload.model_fields_set
    values = payload.model_dump(exclude_unset=True)
    return SocialAccountConnectionUpdate(
        artist_profile_id=payload.artist_profile_id,
        username=values.get("handle"),
        display_name=values.get("display_name"),
        profile_url=values.get("profile_url"),
        capabilities=payload.capabilities if "capabilities" in fields else None,
        provider_metadata=(
            payload.provider_metadata if "provider_metadata" in fields else None
        ),
        clear_artist_profile=(
            "artist_profile_id" in fields and payload.artist_profile_id is None
        ),
        clear_username=("handle" in fields and payload.handle is None),
        clear_display_name=("display_name" in fields and payload.display_name is None),
        clear_profile_url=("profile_url" in fields and payload.profile_url is None),
    )


def _artist_association(
    connection: SocialAccountConnection,
) -> SocialAccountArtistAssociationResponse | None:
    if connection.artist_profile_id is None or connection.artist_profile is None:
        return None
    return SocialAccountArtistAssociationResponse(
        artist_profile_id=connection.artist_profile.id,
        artist_id=connection.artist_profile.artist_id,
        artist_name=connection.artist_profile.artist.name,
        stage_name=connection.artist_profile.stage_name,
    )


def _connection_response(
    connection: SocialAccountConnection,
) -> SocialAccountConnectionResponse:
    return SocialAccountConnectionResponse(
        id=connection.id,
        workspace_id=connection.organization_id,
        provider=connection.provider,
        external_account_id=connection.external_account_id,
        handle=connection.username,
        display_name=connection.display_name,
        profile_url=connection.profile_url,
        artist_association=_artist_association(connection),
        connection_method=connection.connection_method.value,
        status=connection.status,
        capabilities=list(connection.capabilities),
        resolved_capabilities=SocialAccountCapabilitiesResponse(
            **social_account_service.resolve_capabilities(connection)
        ),
        token_expires_at=connection.token_expires_at,
        last_synced_at=connection.last_synced_at,
        last_health_checked_at=connection.last_health_checked_at,
        last_error_code=connection.last_error_code,
        last_error_message=connection.last_error_message,
        provider_metadata=_safe_metadata(connection.provider_metadata),
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


def _list_response(page) -> SocialAccountConnectionListResponse:
    return SocialAccountConnectionListResponse(
        social_account_connections=[
            _connection_response(connection) for connection in page.items
        ],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{workspace_id}/social-account-connections",
    response_model=SocialAccountConnectionListResponse,
)
async def list_social_account_connections(
    workspace_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    provider: str | None = None,
    status_filter: Annotated[
        SocialAccountConnectionStatus | None,
        Query(alias="status"),
    ] = None,
    artist_profile_id: UUID | None = None,
    include_disconnected: bool = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SocialAccountConnectionListResponse:
    try:
        page = await social_account_service.list_connections(
            session,
            workspace_id,
            actor=context,
            query=SocialAccountConnectionQuery(
                provider=provider,
                status=status_filter,
                artist_profile_id=artist_profile_id,
                include_disconnected=include_disconnected,
            ),
            limit=limit,
            offset=offset,
        )
    except (
        SocialAccountAuthorizationError,
        SocialAccountLifecycleError,
        SocialAccountProviderError,
        SocialAccountRelationshipError,
    ) as exc:
        _service_error(exc)
    return _list_response(page)


@router.post(
    "/{workspace_id}/social-account-connections",
    response_model=SocialAccountConnectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_assisted_social_account_connection(
    workspace_id: UUID,
    payload: SocialAccountConnectionCreateRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> SocialAccountConnectionResponse:
    membership = await _current_workspace_membership(
        session,
        context=context,
        workspace_id=workspace_id,
    )
    if membership is None:
        raise _not_found()
    try:
        connection = await social_account_service.register_assisted_connection(
            session,
            workspace_id,
            _create_payload(
                payload,
                context=context,
                created_by_profile_id=membership.profile_id,
            ),
            actor=context,
        )
    except (
        SocialAccountAuthorizationError,
        SocialAccountDuplicateError,
        SocialAccountProviderError,
        SocialAccountRelationshipError,
    ) as exc:
        _service_error(exc)
    return _connection_response(connection)


@router.get(
    "/{workspace_id}/social-account-connections/{connection_id}",
    response_model=SocialAccountConnectionResponse,
)
async def get_social_account_connection(
    workspace_id: UUID,
    connection_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> SocialAccountConnectionResponse:
    try:
        connection = await social_account_service.get_connection(
            session,
            workspace_id,
            connection_id,
            actor=context,
        )
    except (SocialAccountAuthorizationError, SocialAccountNotFoundError) as exc:
        _service_error(exc)
    return _connection_response(connection)


@router.patch(
    "/{workspace_id}/social-account-connections/{connection_id}",
    response_model=SocialAccountConnectionResponse,
)
async def update_social_account_connection(
    workspace_id: UUID,
    connection_id: UUID,
    payload: SocialAccountConnectionUpdateRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> SocialAccountConnectionResponse:
    try:
        connection = await social_account_service.update_connection(
            session,
            workspace_id,
            connection_id,
            _update_payload(payload),
            actor=context,
        )
    except (
        SocialAccountAuthorizationError,
        SocialAccountLifecycleError,
        SocialAccountNotFoundError,
        SocialAccountProviderError,
        SocialAccountRelationshipError,
    ) as exc:
        _service_error(exc)
    return _connection_response(connection)


@router.post(
    "/{workspace_id}/social-account-connections/{connection_id}/disconnect",
    response_model=SocialAccountConnectionResponse,
)
async def disconnect_social_account_connection(
    workspace_id: UUID,
    connection_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> SocialAccountConnectionResponse:
    try:
        connection = await social_account_service.disconnect_connection(
            session,
            workspace_id,
            connection_id,
            actor=context,
        )
    except (
        SocialAccountAuthorizationError,
        SocialAccountLifecycleError,
        SocialAccountNotFoundError,
    ) as exc:
        _service_error(exc)
    return _connection_response(connection)
