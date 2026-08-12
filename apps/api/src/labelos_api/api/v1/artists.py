from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from labelos_api.activity import ActivityEventType, record_activity_event
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


class ArtistUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ArtistResponse(BaseModel):
    id: UUID
    name: str


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


def _response_from_artist(artist) -> ArtistResponse:
    return ArtistResponse(id=artist.id, name=artist.name)


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
    try:
        artist = await label_resources.create_artist(
            session,
            organization_id,
            payload.name,
        )
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Artist conflicts with an existing organization record",
        ) from exc
    await record_activity_event(
        session,
        event_type=ActivityEventType.artist_created,
        operation="create_artist",
        organization_id=organization_id,
        actor=context.user,
        entity_type="artist",
        entity_id=artist.id,
        changes={"name": {"from": None, "to": artist.name}},
    )
    await RealtimePublisher(session).publish(
        organization_id=organization_id,
        event_type=RealtimeEventType.artist_created,
        actor=context.user,
        entity_type="artist",
        entity_id=artist.id,
        payload={"artist": _response_from_artist(artist).model_dump(mode="json")},
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
    existing_artist = await label_resources.get_artist(
        session,
        organization_id,
        artist_id,
    )
    if existing_artist is None:
        raise _not_found()
    previous_name = existing_artist.name
    artist = await label_resources.update_artist(
        session,
        organization_id,
        artist_id,
        name=payload.name,
    )
    if artist is None:
        raise _not_found()
    await record_activity_event(
        session,
        event_type=ActivityEventType.artist_updated,
        operation="update_artist",
        organization_id=organization_id,
        actor=context.user,
        entity_type="artist",
        entity_id=artist.id,
        changes={"name": {"from": previous_name, "to": artist.name}},
    )
    await RealtimePublisher(session).publish(
        organization_id=organization_id,
        event_type=RealtimeEventType.artist_updated,
        actor=context.user,
        entity_type="artist",
        entity_id=artist.id,
        payload={"artist": _response_from_artist(artist).model_dump(mode="json")},
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
