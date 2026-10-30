"""Read-only public channel data; no analytics ingestion or derived scores."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from labelos_database.research_models import ScoutingSource
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete

from labelos_api.auth import (
    CurrentUserContext,
    SessionDep,
    SettingsDep,
    get_current_user_context,
)
from labelos_api.exceptions import YouTubeResearchError
from labelos_api.research.adapters.youtube import CHANNEL_ID, YouTubeAdapter
from labelos_api.research.contracts import (
    ArtistLookupRequest,
    ArtistLookupResponse,
    ArtistSearchRequest,
    ArtistSearchResponse,
    CollectionContext,
    NormalizedArtist,
    NormalizedObservation,
    ObservationsRequest,
    ObservationsResponse,
    ResourceRef,
)
from labelos_api.research.errors import ProviderError
from labelos_api.research.youtube_cache import DISPLAY_CACHE
from labelos_api.services.credential_store import CredentialStoreError
from labelos_api.services.governance_service import (
    GovernanceConflict,
    GovernanceError,
    GovernanceForbidden,
    GovernanceNotFound,
)
from labelos_api.services.youtube_research_service import (
    ResearchNotConfigured,
    YouTubeResearchService,
)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/research/youtube/runs/{run_id}",
    tags=["YouTube research"],
)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)
    cursor: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_=-]{1,500}$")


class ChannelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel_id: str = Field(pattern=f"^{CHANNEL_ID}$")


class ChannelDisplay(BaseModel):
    context: CollectionContext
    artist: NormalizedArtist
    items: tuple[NormalizedObservation, ...]


async def authorized_client(
    workspace_id: UUID,
    run_id: UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    response: Response,
):
    response.headers["Cache-Control"] = "no-store"
    service = YouTubeResearchService(session, workspace_id, actor=actor)
    try:
        yield await service.client_for_run(run_id, settings)
    except GovernanceForbidden:
        raise HTTPException(403, "Insufficient governance permission") from None
    except GovernanceNotFound:
        raise HTTPException(404, "Collection not found in workspace") from None
    except GovernanceConflict:
        raise HTTPException(
            409, "Collection is not eligible for YouTube research"
        ) from None
    except GovernanceError:
        raise HTTPException(409, "Collection documentation is not eligible") from None
    except ResearchNotConfigured:
        raise HTTPException(
            503, "YouTube research is not configured for this workspace"
        ) from None
    except CredentialStoreError:
        raise HTTPException(503, "YouTube credential store is unavailable") from None
    except ProviderError as exc:
        details = exc.failure.details
        code = details.code.value
        status = {
            "data_unavailable": 404,
            "invalid_request": 422,
            "rate_limited": 429,
            "quota_exceeded": 429,
            "timeout": 504,
            "authentication_failed": 503,
            "provider_unavailable": 503,
        }.get(code, 502)
        headers = {"Cache-Control": "no-store"}
        if details.retry_after_seconds is not None:
            headers["Retry-After"] = str(details.retry_after_seconds)
        raise YouTubeResearchError(status, {"code": code}, headers=headers) from None
    finally:
        # Release the run/version locks after the request, including cancellation.
        # No provider payloads, counters, or analytics rows are persisted here.
        await session.rollback()


Client = Annotated[tuple, Depends(authorized_client, scope="function")]


@router.delete("/display-cache", status_code=204)
async def clear_display_cache(bound: Client):
    _, context = bound
    DISPLAY_CACHE.clear_workspace(context.workspace_id)
    # Other replicas' volatile entries expire within 60 seconds. No background
    # refresh exists, and no provider payload is retained in database backups.
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.post("/search", response_model=ArtistSearchResponse)
async def search(payload: SearchRequest, bound: Client):
    client, context = bound
    return await client.search_artists(
        ArtistSearchRequest(**payload.model_dump()), context=context
    )


@router.post("/lookup", response_model=ArtistLookupResponse)
async def lookup(payload: ChannelRequest, bound: Client):
    client, context = bound
    return await client.lookup_artist(
        ArtistLookupRequest(artist_id=payload.channel_id), context=context
    )


@router.post("/observations", response_model=ObservationsResponse)
async def observations(payload: ChannelRequest, bound: Client):
    client, context = bound
    now = datetime.now(UTC)
    return await client.observations(
        ObservationsRequest(
            subject=ResourceRef(resource="artist", external_id=payload.channel_id),
            metric_keys=tuple(YouTubeAdapter.metrics),
            limit=3,
            start_at=now - timedelta(minutes=1),
            end_at=now + timedelta(minutes=1),
        ),
        context=context,
    )


@router.post("/channel", response_model=ChannelDisplay)
async def channel_display(payload: ChannelRequest, bound: Client, session: SessionDep):
    client, context = bound
    DISPLAY_CACHE.clear_workspace(context.workspace_id)
    # One upstream channels.list response for both metadata and counters. The
    # adapter's row is request-scoped and discarded when this request completes.
    try:
        artist = await client.client.lookup_artist(
            ArtistLookupRequest(artist_id=payload.channel_id), context=context
        )
    except ProviderError as exc:
        if exc.failure.details.code.value == "data_unavailable":
            await session.execute(
                delete(ScoutingSource).where(
                    ScoutingSource.workspace_id == context.workspace_id,
                    ScoutingSource.channel_id == payload.channel_id,
                )
            )
            await session.commit()
        raise
    counters = await observations(payload, bound)
    return ChannelDisplay(context=context, artist=artist.artist, items=counters.items)
