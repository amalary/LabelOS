from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from labelos_database.models import RealtimeEvent, User
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("labelos_api.realtime")


class RealtimeEventType(StrEnum):
    organization_updated = "organization.updated"
    member_joined = "member.joined"
    member_updated = "member.updated"
    member_removed = "member.removed"
    artist_created = "artist.created"
    artist_updated = "artist.updated"
    artist_status_changed = "artist.status_changed"
    release_updated = "release.updated"
    campaign_updated = "campaign.updated"
    approval_updated = "approval.updated"
    agent_started = "agent.started"
    agent_completed = "agent.completed"
    agent_failed = "agent.failed"
    presence_joined = "presence.joined"
    presence_left = "presence.left"


class RealtimeActor(BaseModel):
    user_id: UUID
    display_name: str | None = None


class RealtimeEventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    type: RealtimeEventType
    version: int = 1
    channel: str
    organization_id: UUID
    entity_type: str | None = None
    entity_id: str | None = None
    operation_id: str
    actor: RealtimeActor | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


def realtime_channel(organization_id: UUID) -> str:
    return f"organization:{organization_id}"


def _actor_display_name(actor: User | None) -> str | None:
    if actor is None:
        return None
    return actor.display_name or actor.email


def _envelope_from_record(record: RealtimeEvent) -> RealtimeEventEnvelope:
    actor = None
    if record.actor_user_id is not None:
        actor = RealtimeActor(
            user_id=record.actor_user_id,
            display_name=record.actor_display_name,
        )
    return RealtimeEventEnvelope(
        id=record.id,
        type=RealtimeEventType(record.event_type),
        version=record.schema_version,
        channel=record.channel,
        organization_id=record.organization_id,
        entity_type=record.entity_type,
        entity_id=record.entity_id,
        operation_id=record.operation_id,
        actor=actor,
        payload=record.payload,
        created_at=record.created_at,
    )


class RealtimePublisher:
    """Database-backed realtime event outbox.

    Events are inserted in the caller transaction and become visible to SSE readers
    only after the surrounding database commit succeeds.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def publish(
        self,
        *,
        organization_id: UUID,
        event_type: RealtimeEventType,
        actor: User | None,
        entity_type: str | None = None,
        entity_id: UUID | str | None = None,
        payload: dict[str, Any] | None = None,
        operation_id: str | None = None,
    ) -> RealtimeEvent:
        event = RealtimeEvent(
            organization_id=organization_id,
            channel=realtime_channel(organization_id),
            event_type=event_type.value,
            schema_version=1,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            operation_id=operation_id or str(uuid4()),
            actor_user_id=actor.id if actor is not None else None,
            actor_display_name=_actor_display_name(actor),
            payload=payload or {},
        )
        self.session.add(event)
        await self.session.flush()
        logger.info(
            "Realtime event queued",
            extra={
                "event_id": str(event.id),
                "event_type": event.event_type,
                "organization_id": str(event.organization_id),
                "operation": "publish_realtime_event",
                "result": "queued",
                "channel": event.channel,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "user_id": (
                    str(event.actor_user_id)
                    if event.actor_user_id is not None
                    else None
                ),
                "actor_user_id": (
                    str(event.actor_user_id)
                    if event.actor_user_id is not None
                    else None
                ),
                "operation_id": event.operation_id,
            },
        )
        return event


async def list_events_after(
    session: AsyncSession,
    *,
    organization_id: UUID,
    after_event_id: UUID | None,
    limit: int = 100,
) -> list[RealtimeEventEnvelope]:
    statement = (
        select(RealtimeEvent)
        .where(RealtimeEvent.organization_id == organization_id)
        .order_by(RealtimeEvent.created_at.asc(), RealtimeEvent.id.asc())
        .limit(limit)
    )
    if after_event_id is not None:
        current = await session.get(RealtimeEvent, after_event_id)
        if current is not None and current.organization_id == organization_id:
            statement = statement.where(
                (RealtimeEvent.created_at > current.created_at)
                | (
                    (RealtimeEvent.created_at == current.created_at)
                    & (RealtimeEvent.id > current.id)
                )
            )

    records = await session.scalars(statement)
    return [_envelope_from_record(record) for record in records.all()]


def presence_payload(*, status: str = "active") -> dict[str, Any]:
    return {
        "status": status,
        "observed_at": datetime.now(UTC).isoformat(),
    }
