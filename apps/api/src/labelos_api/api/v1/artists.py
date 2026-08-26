from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from labelos_database.models import WorkspaceMembership
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.auth import (
    CurrentUserContext,
    SessionDep,
    require_active_organization_id,
)
from labelos_api.authorization import Permission, require_permission
from labelos_api.realtime import RealtimeEventType, RealtimePublisher
from labelos_api.repositories import label_resources

router = APIRouter(prefix="/artists", tags=["artists"])


class ArtistCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    stage_name: str | None = Field(default=None, min_length=1, max_length=200)
    genres: list[str] | None = None
    influences: list[str] | None = None
    imagery: dict | None = None
    dsp_links: dict | None = None
    catalog_references: list[str] | None = None
    creative_metadata: dict | None = None
    career_stage: str | None = Field(default=None, max_length=120)
    audience: dict | None = None
    preferences: dict | None = None
    universal_profile_id: UUID | None = None

    @model_validator(mode="after")
    def require_universal_profile_for_artist_module(self) -> "ArtistCreateRequest":
        _require_universal_profile_for_profile_fields(self)
        return self


class ArtistUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    stage_name: str | None = Field(default=None, min_length=1, max_length=200)
    genres: list[str] | None = None
    influences: list[str] | None = None
    imagery: dict | None = None
    dsp_links: dict | None = None
    catalog_references: list[str] | None = None
    creative_metadata: dict | None = None
    career_stage: str | None = Field(default=None, max_length=120)
    audience: dict | None = None
    preferences: dict | None = None
    universal_profile_id: UUID | None = None

    @model_validator(mode="after")
    def require_universal_profile_for_artist_module(self) -> "ArtistUpdateRequest":
        _require_universal_profile_for_profile_fields(self)
        return self


class ArtistProfileResponse(BaseModel):
    id: UUID
    artist_id: UUID
    universal_profile_id: UUID
    stage_name: str | None
    genres: list[str]
    influences: list[str]
    imagery: dict
    dsp_links: dict
    catalog_references: list[str]
    creative_metadata: dict
    career_stage: str | None
    audience: dict
    preferences: dict


class ArtistResponse(BaseModel):
    id: UUID
    name: str
    profile: ArtistProfileResponse | None = None


class ReleaseResponse(BaseModel):
    id: UUID
    title: str
    artist_id: UUID | None


class ArtistsListResponse(BaseModel):
    artists: list[ArtistResponse]


class ArtistReleasesListResponse(BaseModel):
    releases: list[ReleaseResponse]


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


async def _require_profile_workspace_membership(
    session: AsyncSession,
    *,
    organization_id: UUID,
    universal_profile_id: UUID | None,
) -> None:
    if universal_profile_id is None:
        return
    membership_id = await session.scalar(
        select(WorkspaceMembership.id)
        .where(WorkspaceMembership.workspace_id == organization_id)
        .where(WorkspaceMembership.profile_id == universal_profile_id)
        .where(WorkspaceMembership.status == "active")
    )
    if membership_id is None:
        raise _not_found()


def _response_from_artist(artist) -> ArtistResponse:
    profile = artist.profile
    return ArtistResponse(
        id=artist.id,
        name=artist.name,
        profile=(
            ArtistProfileResponse(
                id=profile.id,
                artist_id=profile.artist_id,
                universal_profile_id=profile.universal_profile_id,
                stage_name=profile.stage_name,
                genres=profile.genres,
                influences=profile.influences,
                imagery=profile.imagery,
                dsp_links=profile.dsp_links,
                catalog_references=profile.catalog_references,
                creative_metadata=profile.creative_metadata,
                career_stage=profile.career_stage,
                audience=profile.audience,
                preferences=profile.preferences,
            )
            if profile is not None
            else None
        ),
    )


def _profile_changes(
    payload: ArtistCreateRequest | ArtistUpdateRequest,
) -> dict | None:
    changes = payload.model_dump(
        exclude={"name"},
        exclude_none=True,
    )
    return changes or None


def _require_universal_profile_for_profile_fields(
    payload: ArtistCreateRequest | ArtistUpdateRequest,
) -> None:
    profile_fields = set(payload.model_fields_set) - {"name"}
    if profile_fields and payload.universal_profile_id is None:
        raise ValueError(
            "universal_profile_id is required when creating or updating an "
            "artist profile module"
        )


def _response_from_release(release) -> ReleaseResponse:
    return ReleaseResponse(
        id=release.id,
        title=release.title,
        artist_id=release.artist_id,
    )


@router.get("", response_model=ArtistsListResponse)
async def list_artists(
    session: SessionDep,
    context: Annotated[
        CurrentUserContext,
        Depends(require_permission(Permission.artists_view)),
    ],
    search: str | None = None,
) -> ArtistsListResponse:
    organization_id = require_active_organization_id(context)
    artists = await label_resources.list_artists(
        session,
        organization_id,
        search=search,
    )
    return ArtistsListResponse(
        artists=[_response_from_artist(artist) for artist in artists]
    )


@router.post(
    "",
    response_model=ArtistResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_artist(
    payload: ArtistCreateRequest,
    session: SessionDep,
    context: Annotated[
        CurrentUserContext,
        Depends(require_permission(Permission.artists_manage)),
    ],
) -> ArtistResponse:
    organization_id = require_active_organization_id(context)
    await _require_profile_workspace_membership(
        session,
        organization_id=organization_id,
        universal_profile_id=payload.universal_profile_id,
    )
    try:
        artist = await label_resources.create_artist(
            session,
            organization_id,
            payload.name,
            profile=_profile_changes(payload),
        )
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Artist conflicts with an existing organization record",
        ) from exc
    await RealtimePublisher(session).publish(
        organization_id=organization_id,
        event_type=RealtimeEventType.artist_created,
        actor=context.user,
        entity_type="artist",
        entity_id=artist.id,
        payload={"artist": _response_from_artist(artist).model_dump(mode="json")},
    )
    if artist.profile is not None:
        artist_profile_payload = {
            "profileId": str(artist.profile.universal_profile_id),
            "workspaceId": str(organization_id),
            "artistId": str(artist.id),
            "artistProfileId": str(artist.profile.id),
            "artistName": artist.name,
        }
        await RealtimePublisher(session).publish(
            organization_id=organization_id,
            event_type=RealtimeEventType.profile_artist_profile_created,
            actor=context.user,
            entity_type="profile",
            entity_id=artist.profile.universal_profile_id,
            payload=artist_profile_payload,
        )
        await RealtimePublisher(session).publish(
            organization_id=organization_id,
            event_type=RealtimeEventType.profile_artist_updated,
            actor=context.user,
            entity_type="profile",
            entity_id=artist.profile.universal_profile_id,
            payload=artist_profile_payload,
        )
    await session.commit()
    return _response_from_artist(artist)


@router.get("/{artist_id}", response_model=ArtistResponse)
async def get_artist(
    artist_id: UUID,
    session: SessionDep,
    context: Annotated[
        CurrentUserContext,
        Depends(require_permission(Permission.artists_view)),
    ],
) -> ArtistResponse:
    organization_id = require_active_organization_id(context)
    artist = await label_resources.get_artist(session, organization_id, artist_id)
    if artist is None:
        raise _not_found()
    return _response_from_artist(artist)


@router.put("/{artist_id}", response_model=ArtistResponse)
@router.patch("/{artist_id}", response_model=ArtistResponse)
async def update_artist(
    artist_id: UUID,
    payload: ArtistUpdateRequest,
    session: SessionDep,
    context: Annotated[
        CurrentUserContext,
        Depends(require_permission(Permission.artists_manage)),
    ],
) -> ArtistResponse:
    organization_id = require_active_organization_id(context)
    await _require_profile_workspace_membership(
        session,
        organization_id=organization_id,
        universal_profile_id=payload.universal_profile_id,
    )
    existing_artist = await label_resources.get_artist(
        session,
        organization_id,
        artist_id,
    )
    if existing_artist is None:
        raise _not_found()
    had_artist_profile = existing_artist.profile is not None
    artist = await label_resources.update_artist(
        session,
        organization_id,
        artist_id,
        name=payload.name,
        profile=_profile_changes(payload),
    )
    if artist is None:
        raise _not_found()
    await RealtimePublisher(session).publish(
        organization_id=organization_id,
        event_type=RealtimeEventType.artist_updated,
        actor=context.user,
        entity_type="artist",
        entity_id=artist.id,
        payload={"artist": _response_from_artist(artist).model_dump(mode="json")},
    )
    if artist.profile is not None and _profile_changes(payload) is not None:
        artist_profile_payload = {
            "profileId": str(artist.profile.universal_profile_id),
            "workspaceId": str(organization_id),
            "artistId": str(artist.id),
            "artistProfileId": str(artist.profile.id),
            "artistName": artist.name,
            "changedFields": sorted(_profile_changes(payload) or {}),
        }
        await RealtimePublisher(session).publish(
            organization_id=organization_id,
            event_type=(
                RealtimeEventType.profile_artist_profile_updated
                if had_artist_profile
                else RealtimeEventType.profile_artist_profile_created
            ),
            actor=context.user,
            entity_type="profile",
            entity_id=artist.profile.universal_profile_id,
            payload=artist_profile_payload,
        )
        await RealtimePublisher(session).publish(
            organization_id=organization_id,
            event_type=RealtimeEventType.profile_artist_updated,
            actor=context.user,
            entity_type="profile",
            entity_id=artist.profile.universal_profile_id,
            payload=artist_profile_payload,
        )
    await session.commit()
    return _response_from_artist(artist)


@router.get("/{artist_id}/releases", response_model=ArtistReleasesListResponse)
async def list_artist_releases(
    artist_id: UUID,
    session: SessionDep,
    context: Annotated[
        CurrentUserContext,
        Depends(require_permission(Permission.releases_view)),
    ],
) -> ArtistReleasesListResponse:
    organization_id = require_active_organization_id(context)
    releases = await label_resources.list_artist_releases(
        session,
        organization_id,
        artist_id,
    )
    if releases is None:
        raise _not_found()
    return ArtistReleasesListResponse(
        releases=[_response_from_release(release) for release in releases]
    )


@router.delete("/{artist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_artist(
    artist_id: UUID,
    session: SessionDep,
    context: Annotated[
        CurrentUserContext,
        Depends(require_permission(Permission.artists_manage)),
    ],
) -> Response:
    organization_id = require_active_organization_id(context)
    deleted = await label_resources.delete_artist(session, organization_id, artist_id)
    if not deleted:
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
