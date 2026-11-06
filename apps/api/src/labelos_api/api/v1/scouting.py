"""Persistent human review; no provider titles, counters or snapshots in SQL."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from labelos_database.models import AnalyticsProvider, CollectionRun
from labelos_database.research_models import ScoutingCandidate, ScoutingSource
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, update

from labelos_api.auth import (
    CurrentUserContext,
    SessionDep,
    SettingsDep,
    get_current_user_context,
)
from labelos_api.research.adapters.youtube import CHANNEL_ID
from labelos_api.research.youtube_cache import DISPLAY_CACHE
from labelos_api.services.governance_service import GovernanceError, GovernanceForbidden
from labelos_api.services.scouting_service import (
    authorize_scout,
    candidate_record,
    purge_sources,
    save_candidate,
    serialize_candidate,
)
from labelos_api.services.scouting_setup import prepare_local_session

router = APIRouter(prefix="/workspaces/{workspace_id}/scouting", tags=["A&R scouting"])
Actor = Annotated[CurrentUserContext, Depends(get_current_user_context)]
ReviewStatus = Literal["new", "reviewing", "shortlisted", "passed"]


class SaveCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel_id: str = Field(pattern=f"^{CHANNEL_ID}$")


class EditCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    label: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=10000)
    status: ReviewStatus | None = None


async def boundary(workspace_id, session, actor, response, *, write=False):
    response.headers["Cache-Control"] = "no-store"
    await authorize_scout(session, workspace_id, actor, write=write)


@router.post("/local-session")
async def local_session(
    workspace_id: UUID,
    session: SessionDep,
    settings: SettingsDep,
    actor: Actor,
    response: Response,
):
    response.headers["Cache-Control"] = "no-store"
    if not settings.is_development and not settings.is_test:
        raise HTTPException(404, "Not found")
    try:
        run, created = await prepare_local_session(session, workspace_id, actor)
        result = {"id": run.id, "label": run.run_key}
        await session.commit()
    except GovernanceForbidden:
        await session.rollback()
        raise HTTPException(403, "Governance management permission required") from None
    except GovernanceError:
        await session.rollback()
        raise HTTPException(409, "Could not prepare local research session") from None
    response.status_code = 201 if created else 200
    return result


@router.get("/runs")
async def runs(
    workspace_id: UUID, session: SessionDep, actor: Actor, response: Response
):
    await boundary(workspace_id, session, actor, response)
    rows = await session.scalars(
        select(CollectionRun)
        .join(AnalyticsProvider, CollectionRun.source_id == AnalyticsProvider.id)
        .where(
            CollectionRun.organization_id == workspace_id,
            AnalyticsProvider.organization_id == workspace_id,
            AnalyticsProvider.key == "youtube",
            CollectionRun.status == "running",
        )
        .order_by(CollectionRun.created_at.desc())
        .limit(25)
    )
    return [{"id": row.id, "label": row.run_key} for row in rows]


@router.get("/candidates")
async def candidates(
    workspace_id: UUID,
    session: SessionDep,
    actor: Actor,
    response: Response,
    status: ReviewStatus | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    await boundary(workspace_id, session, actor, response)
    query = select(ScoutingCandidate).where(
        ScoutingCandidate.workspace_id == workspace_id
    )
    if status:
        query = query.where(ScoutingCandidate.status == status)
    rows = await session.scalars(
        query.order_by(ScoutingCandidate.created_at.desc(), ScoutingCandidate.id)
        .offset(offset)
        .limit(limit)
    )
    return [await serialize_candidate(session, row) for row in rows]


@router.post("/candidates")
async def save(
    payload: SaveCandidate,
    workspace_id: UUID,
    session: SessionDep,
    actor: Actor,
    response: Response,
):
    await boundary(workspace_id, session, actor, response, write=True)
    await purge_sources(session)
    candidate_id, created = await save_candidate(
        session, workspace_id, payload.channel_id
    )
    result = await serialize_candidate(
        session, await candidate_record(session, workspace_id, candidate_id)
    )
    await session.commit()
    response.status_code = 201 if created else 200
    return result


@router.get("/candidates/{candidate_id}")
async def detail(
    candidate_id: UUID,
    workspace_id: UUID,
    session: SessionDep,
    actor: Actor,
    response: Response,
):
    await boundary(workspace_id, session, actor, response)
    return await serialize_candidate(
        session, await candidate_record(session, workspace_id, candidate_id)
    )


@router.patch("/candidates/{candidate_id}")
async def edit(
    payload: EditCandidate,
    candidate_id: UUID,
    workspace_id: UUID,
    session: SessionDep,
    actor: Actor,
    response: Response,
):
    await boundary(workspace_id, session, actor, response, write=True)
    await candidate_record(session, workspace_id, candidate_id)
    values = payload.model_dump(exclude={"revision"}, exclude_unset=True)
    if not values or any(value is None for value in values.values()):
        raise HTTPException(422, "Provide non-null review fields")
    result = await session.execute(
        update(ScoutingCandidate)
        .where(
            ScoutingCandidate.id == candidate_id,
            ScoutingCandidate.workspace_id == workspace_id,
            ScoutingCandidate.revision == payload.revision,
        )
        .values(**values, revision=payload.revision + 1)
    )
    if result.rowcount != 1:
        raise HTTPException(409, "Candidate changed; reopen before editing")
    await session.commit()
    return await serialize_candidate(
        session, await candidate_record(session, workspace_id, candidate_id)
    )


@router.delete("/candidates/{candidate_id}/source", status_code=204)
async def forget_source(
    candidate_id: UUID,
    workspace_id: UUID,
    session: SessionDep,
    actor: Actor,
    response: Response,
):
    await boundary(workspace_id, session, actor, response, write=True)
    await candidate_record(session, workspace_id, candidate_id)
    await session.execute(
        delete(ScoutingSource).where(
            ScoutingSource.candidate_id == candidate_id,
            ScoutingSource.workspace_id == workspace_id,
        )
    )
    await session.commit()
    DISPLAY_CACHE.clear_workspace(workspace_id)


@router.delete("/candidates/{candidate_id}", status_code=204)
async def remove(
    candidate_id: UUID,
    workspace_id: UUID,
    session: SessionDep,
    actor: Actor,
    response: Response,
):
    await boundary(workspace_id, session, actor, response, write=True)
    candidate = await candidate_record(session, workspace_id, candidate_id)
    await session.execute(
        delete(ScoutingSource).where(
            ScoutingSource.candidate_id == candidate_id,
            ScoutingSource.workspace_id == workspace_id,
        )
    )
    await session.delete(candidate)
    await session.commit()
    DISPLAY_CACHE.clear_workspace(workspace_id)
