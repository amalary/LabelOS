from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from labelos_database.models import Artist, ArtistProfile, WorkspaceMembership
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from labelos_api.auth import CurrentUserContext, SessionDep, get_current_user_context
from labelos_api.authorization import (
    Capability,
    authorization_service,
)
from labelos_api.realtime import RealtimeEventType, RealtimePublisher

router = APIRouter(prefix="/workspaces", tags=["artist-profiles"])


class ArtistProfileCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artist_id: UUID
    universal_profile_id: UUID
    stage_name: str | None = Field(default=None, max_length=200)
    genres: list[str] | None = None
    influences: list[str] | None = None
    imagery: dict[str, Any] | None = None
    dsp_links: dict[str, Any] | None = None
    catalog_references: list[str] | None = None
    creative_metadata: dict[str, Any] | None = None
    career_stage: str | None = Field(default=None, max_length=120)
    audience: dict[str, Any] | None = None
    preferences: dict[str, Any] | None = None


class ArtistProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    universal_profile_id: UUID | None = None
    stage_name: str | None = Field(default=None, max_length=200)
    genres: list[str] | None = None
    influences: list[str] | None = None
    imagery: dict[str, Any] | None = None
    dsp_links: dict[str, Any] | None = None
    catalog_references: list[str] | None = None
    creative_metadata: dict[str, Any] | None = None
    career_stage: str | None = Field(default=None, max_length=120)
    audience: dict[str, Any] | None = None
    preferences: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_update(self) -> "ArtistProfileUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one artist profile field is required")
        return self


class ArtistProfileDetailResponse(BaseModel):
    id: UUID
    artist_id: UUID
    workspace_id: UUID
    universal_profile_id: UUID
    artist_name: str
    stage_name: str | None
    genres: list[str]
    influences: list[str]
    imagery: dict[str, Any]
    dsp_links: dict[str, Any]
    catalog_references: list[str]
    creative_metadata: dict[str, Any]
    career_stage: str | None
    audience: dict[str, Any]
    preferences: dict[str, Any]


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _artist_profile_response(
    artist_profile: ArtistProfile,
) -> ArtistProfileDetailResponse:
    return ArtistProfileDetailResponse(
        id=artist_profile.id,
        artist_id=artist_profile.artist_id,
        workspace_id=artist_profile.artist.organization_id,
        universal_profile_id=artist_profile.universal_profile_id,
        artist_name=artist_profile.artist.name,
        stage_name=artist_profile.stage_name,
        genres=list(artist_profile.genres),
        influences=list(artist_profile.influences),
        imagery=dict(artist_profile.imagery),
        dsp_links=dict(artist_profile.dsp_links),
        catalog_references=list(artist_profile.catalog_references),
        creative_metadata=dict(artist_profile.creative_metadata),
        career_stage=artist_profile.career_stage,
        audience=dict(artist_profile.audience),
        preferences=dict(artist_profile.preferences),
    )


async def _require_active_workspace_membership(
    session: AsyncSession,
    *,
    context: CurrentUserContext,
    workspace_id: UUID,
) -> None:
    has_context_membership = any(
        membership.workspace_id == workspace_id and membership.status == "active"
        for membership in context.memberships
    )
    if not has_context_membership:
        raise _not_found()
    membership_id = await session.scalar(
        select(WorkspaceMembership.id)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.status == "active")
        .join(WorkspaceMembership.profile)
        .where(WorkspaceMembership.profile.has(user_id=context.user.id))
    )
    if membership_id is None:
        raise _not_found()


async def _require_profile_in_workspace(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    profile_id: UUID,
) -> None:
    membership_id = await session.scalar(
        select(WorkspaceMembership.id)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.profile_id == profile_id)
        .where(WorkspaceMembership.status == "active")
    )
    if membership_id is None:
        raise _not_found()


async def _load_artist(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    artist_id: UUID,
) -> Artist | None:
    return await session.scalar(
        select(Artist)
        .options(selectinload(Artist.profile))
        .where(Artist.id == artist_id)
        .where(Artist.organization_id == workspace_id)
    )


async def _load_artist_profile(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    artist_profile_id: UUID,
) -> ArtistProfile | None:
    return await session.scalar(
        select(ArtistProfile)
        .join(ArtistProfile.artist)
        .options(selectinload(ArtistProfile.artist))
        .where(ArtistProfile.id == artist_profile_id)
        .where(Artist.organization_id == workspace_id)
    )


@router.post(
    "/{workspace_id}/artist-profiles",
    response_model=ArtistProfileDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_artist_profile(
    workspace_id: UUID,
    payload: ArtistProfileCreateRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> ArtistProfileDetailResponse:
    await _require_active_workspace_membership(
        session,
        context=context,
        workspace_id=workspace_id,
    )
    if not authorization_service.can(
        context, workspace_id, Capability.artist_profile_edit
    ):
        raise _forbidden("Insufficient capability permission")
    await _require_profile_in_workspace(
        session,
        workspace_id=workspace_id,
        profile_id=payload.universal_profile_id,
    )
    artist = await _load_artist(
        session,
        workspace_id=workspace_id,
        artist_id=payload.artist_id,
    )
    if artist is None:
        raise _not_found()
    if artist.profile is not None:
        raise _conflict("Artist already has an artist profile")

    values = payload.model_dump(exclude={"artist_id"}, exclude_none=True)
    values.setdefault("stage_name", artist.name)
    artist_profile = ArtistProfile(**values)
    artist.profile = artist_profile
    session.add(artist_profile)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise _conflict("Artist already has an artist profile") from exc

    artist_profile_payload = {
        "profileId": str(artist_profile.universal_profile_id),
        "workspaceId": str(workspace_id),
        "artistId": str(artist.id),
        "artistProfileId": str(artist_profile.id),
        "artistName": artist.name,
    }
    await RealtimePublisher(session).publish(
        organization_id=workspace_id,
        event_type=RealtimeEventType.profile_artist_profile_created,
        actor=context.user,
        entity_type="profile",
        entity_id=artist_profile.universal_profile_id,
        payload=artist_profile_payload,
    )
    await RealtimePublisher(session).publish(
        organization_id=workspace_id,
        event_type=RealtimeEventType.profile_artist_updated,
        actor=context.user,
        entity_type="profile",
        entity_id=artist_profile.universal_profile_id,
        payload=artist_profile_payload,
    )
    await session.commit()
    return _artist_profile_response(artist_profile)


@router.get(
    "/{workspace_id}/artist-profiles/{artist_profile_id}",
    response_model=ArtistProfileDetailResponse,
)
async def get_artist_profile(
    workspace_id: UUID,
    artist_profile_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> ArtistProfileDetailResponse:
    await _require_active_workspace_membership(
        session,
        context=context,
        workspace_id=workspace_id,
    )
    if not authorization_service.can(
        context, workspace_id, Capability.artist_profile_view
    ):
        raise _forbidden("Insufficient capability permission")
    artist_profile = await _load_artist_profile(
        session,
        workspace_id=workspace_id,
        artist_profile_id=artist_profile_id,
    )
    if artist_profile is None:
        raise _not_found()
    return _artist_profile_response(artist_profile)


@router.patch(
    "/{workspace_id}/artist-profiles/{artist_profile_id}",
    response_model=ArtistProfileDetailResponse,
)
async def update_artist_profile(
    workspace_id: UUID,
    artist_profile_id: UUID,
    payload: ArtistProfileUpdateRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> ArtistProfileDetailResponse:
    await _require_active_workspace_membership(
        session,
        context=context,
        workspace_id=workspace_id,
    )
    if not authorization_service.can(
        context, workspace_id, Capability.artist_profile_edit
    ):
        raise _forbidden("Insufficient capability permission")
    artist_profile = await _load_artist_profile(
        session,
        workspace_id=workspace_id,
        artist_profile_id=artist_profile_id,
    )
    if artist_profile is None:
        raise _not_found()
    if payload.universal_profile_id is not None:
        await _require_profile_in_workspace(
            session,
            workspace_id=workspace_id,
            profile_id=payload.universal_profile_id,
        )

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(artist_profile, key, value)

    await RealtimePublisher(session).publish(
        organization_id=workspace_id,
        event_type=RealtimeEventType.profile_artist_profile_updated,
        actor=context.user,
        entity_type="profile",
        entity_id=artist_profile.universal_profile_id,
        payload={
            "profileId": str(artist_profile.universal_profile_id),
            "workspaceId": str(workspace_id),
            "artistId": str(artist_profile.artist_id),
            "artistProfileId": str(artist_profile.id),
            "artistName": artist_profile.artist.name,
            "changedFields": sorted(payload.model_fields_set),
        },
    )
    await session.commit()
    return _artist_profile_response(artist_profile)
