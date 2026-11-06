"""Workspace shortlist: human review is separate from expiring source links."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from labelos_database.research_models import ScoutingCandidate, ScoutingSource
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from labelos_api.authorization import Capability, authorization_service


async def authorize_scout(session, workspace_id, actor, *, write=False):
    decision = await authorization_service.decide_capability(
        session,
        actor=actor,
        workspace=workspace_id,
        capability=(
            Capability.ar_scouting_create if write else Capability.ar_scouting_view
        ),
    )
    if not decision.allowed:
        raise HTTPException(403, "Insufficient scouting permission")


async def purge_sources(session, *, now=None):
    """Erase provider identifiers, never human notes/status. Safe to run repeatedly."""
    await session.execute(
        delete(ScoutingSource)
        .execution_options(synchronize_session=False)
        .where(ScoutingSource.expires_at <= (now or datetime.now(UTC)))
    )


async def save_candidate(session, workspace_id: UUID, channel_id: str):
    # The unique source claim is acquired before creating a candidate. Competing
    # PostgreSQL transactions wait for the winner, then return that same record.
    insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    candidate_id = uuid4()
    now = datetime.now(UTC)
    claimed = await session.scalar(
        insert(ScoutingSource)
        .values(
            workspace_id=workspace_id,
            channel_id=channel_id,
            candidate_id=candidate_id,
            expires_at=now + timedelta(days=29),
        )
        .on_conflict_do_nothing(index_elements=["workspace_id", "channel_id"])
        .returning(ScoutingSource.candidate_id)
    )
    if claimed is not None:
        session.add(ScoutingCandidate(id=candidate_id, workspace_id=workspace_id))
        await session.flush()
        return candidate_id, True
    existing = await session.scalar(
        select(ScoutingSource.candidate_id).where(
            ScoutingSource.workspace_id == workspace_id,
            ScoutingSource.channel_id == channel_id,
        )
    )
    if existing is None:
        raise HTTPException(409, "Source was removed; retry save")
    return existing, False


async def candidate_record(session, workspace_id, candidate_id):
    candidate = await session.scalar(
        select(ScoutingCandidate).where(
            ScoutingCandidate.workspace_id == workspace_id,
            ScoutingCandidate.id == candidate_id,
        )
    )
    if candidate is None:
        raise HTTPException(404, "Candidate not found")
    return candidate


async def serialize_candidate(session, candidate):
    source = await session.scalar(
        select(ScoutingSource).where(
            ScoutingSource.workspace_id == candidate.workspace_id,
            ScoutingSource.candidate_id == candidate.id,
            ScoutingSource.expires_at > datetime.now(UTC),
        )
    )
    return {
        "id": candidate.id,
        "label": candidate.label,
        "notes": candidate.notes,
        "status": candidate.status,
        "revision": candidate.revision,
        "created_at": candidate.created_at,
        "channel_id": source.channel_id if source else None,
        "source_expires_at": source.expires_at if source else None,
    }
