"""Bounded public MusicBrainz metadata; no credentials or raw payload ingestion."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from labelos_api.auth import (
    CurrentUserContext,
    SessionDep,
    SettingsDep,
    get_current_user_context,
)
from labelos_api.exceptions import MusicBrainzResearchError
from labelos_api.research.adapters.musicbrainz import MBID
from labelos_api.research.contracts import (
    ArtistLookupRequest,
    ArtistLookupResponse,
    ArtistSearchRequest,
    ArtistSearchResponse,
    CatalogLookupRequest,
    CatalogLookupResponse,
)
from labelos_api.research.errors import ProviderError
from labelos_api.research.musicbrainz import MusicBrainzNotConfigured
from labelos_api.services.governance_service import (
    GovernanceConflict,
    GovernanceError,
    GovernanceForbidden,
    GovernanceNotFound,
)
from labelos_api.services.musicbrainz_research_service import MusicBrainzResearchService

router = APIRouter(
    prefix="/workspaces/{workspace_id}/research/musicbrainz/runs/{run_id}",
    tags=["MusicBrainz research"],
)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=100)
    cursor: str | None = Field(default=None, pattern=r"^[0-9]{1,9}$")


class LookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artist_id: str = Field(pattern=f"^{MBID}$")


class CatalogRequest(LookupRequest):
    resource: Literal["release", "track"]
    limit: int = Field(default=10, ge=1, le=100)
    cursor: str | None = Field(default=None, pattern=r"^[0-9]{1,9}$")


async def authorized_client(
    workspace_id: UUID,
    run_id: UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    response: Response,
):
    response.headers["Cache-Control"] = "no-store"
    service = MusicBrainzResearchService(session, workspace_id, actor=actor)
    try:
        yield await service.client_for_run(run_id, settings)
    except GovernanceForbidden:
        raise HTTPException(403, "Insufficient research permission") from None
    except GovernanceNotFound:
        raise HTTPException(404, "Collection not found in workspace") from None
    except (GovernanceConflict, GovernanceError):
        raise HTTPException(409, "Collection is not eligible for research") from None
    except MusicBrainzNotConfigured:
        raise HTTPException(503, "MusicBrainz research is not configured") from None
    except ProviderError as exc:
        details = exc.failure.details
        code = details.code.value
        status = {
            "data_unavailable": 404,
            "invalid_request": 422,
            "rate_limited": 429,
            "quota_exceeded": 429,
            "timeout": 504,
            "provider_unavailable": 503,
        }.get(code, 502)
        headers = {"Cache-Control": "no-store"}
        if details.retry_after_seconds is not None:
            headers["Retry-After"] = str(details.retry_after_seconds)
        raise MusicBrainzResearchError(
            status, {"code": code}, headers=headers
        ) from None
    finally:
        # Release collection/version locks; do not persist upstream responses.
        await session.rollback()


Client = Annotated[tuple, Depends(authorized_client, scope="function")]


@router.post("/search", response_model=ArtistSearchResponse)
async def search(payload: SearchRequest, bound: Client):
    client, context = bound
    return await client.search_artists(
        ArtistSearchRequest(**payload.model_dump()), context=context
    )


@router.post("/lookup", response_model=ArtistLookupResponse)
async def lookup(payload: LookupRequest, bound: Client):
    client, context = bound
    return await client.lookup_artist(
        ArtistLookupRequest(artist_id=payload.artist_id), context=context
    )


@router.post("/catalog", response_model=CatalogLookupResponse)
async def catalog(payload: CatalogRequest, bound: Client):
    client, context = bound
    return await client.lookup_catalog(
        CatalogLookupRequest(**payload.model_dump()), context=context
    )
