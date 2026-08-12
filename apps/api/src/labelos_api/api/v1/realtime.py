from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from labelos_api.auth import CurrentUserContext, SessionDep, get_current_user_context
from labelos_api.realtime.events import (
    RealtimeEventType,
    RealtimePublisher,
    list_events_after,
    presence_payload,
    realtime_channel,
)
from labelos_api.realtime.security import has_active_membership

router = APIRouter(prefix="/realtime", tags=["realtime"])
logger = logging.getLogger("labelos_api.realtime")
CurrentUserContextDep = Annotated[CurrentUserContext, Depends(get_current_user_context)]

POLL_INTERVAL_SECONDS = 2
MEMBERSHIP_RECHECK_SECONDS = 15
KEEPALIVE_SECONDS = 20


def _sse(event: str, data: dict) -> str:
    payload = json.dumps(data, default=str, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


@router.get("/organizations/{organization_id}/events")
async def organization_events(
    organization_id: UUID,
    session: SessionDep,
    context: CurrentUserContextDep,
    last_event_id: Annotated[UUID | None, Query(alias="lastEventId")] = None,
) -> StreamingResponse:
    if not await has_active_membership(session, context, organization_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization membership required",
        )

    async def stream() -> AsyncIterator[str]:
        cursor = last_event_id
        loops_since_membership_check = 0
        loops_since_keepalive = 0
        publisher = RealtimePublisher(session)
        joined = await publisher.publish(
            organization_id=organization_id,
            event_type=RealtimeEventType.presence_joined,
            actor=context.user,
            entity_type="member",
            entity_id=context.user.id,
            payload=presence_payload(),
        )
        await session.commit()
        cursor = last_event_id or joined.id
        logger.info(
            "Realtime subscription opened",
            extra={
                "organization_id": str(organization_id),
                "channel": realtime_channel(organization_id),
                "user_id": str(context.user.id),
            },
        )
        yield _sse(
            "connected",
            {"channel": realtime_channel(organization_id), "cursor": cursor},
        )

        try:
            while True:
                events = await list_events_after(
                    session,
                    organization_id=organization_id,
                    after_event_id=cursor,
                )
                for event in events:
                    cursor = event.id
                    yield _sse("message", event.model_dump(mode="json"))

                loops_since_membership_check += 1
                loops_since_keepalive += 1
                if (
                    loops_since_membership_check * POLL_INTERVAL_SECONDS
                    >= MEMBERSHIP_RECHECK_SECONDS
                ):
                    has_membership = await has_active_membership(
                        session,
                        context,
                        organization_id,
                    )
                    if not has_membership:
                        yield _sse(
                            "membership_revoked",
                            {"organization_id": str(organization_id)},
                        )
                        break
                    loops_since_membership_check = 0

                if loops_since_keepalive * POLL_INTERVAL_SECONDS >= KEEPALIVE_SECONDS:
                    yield ": keepalive\n\n"
                    loops_since_keepalive = 0

                await asyncio.sleep(POLL_INTERVAL_SECONDS)
        finally:
            try:
                await publisher.publish(
                    organization_id=organization_id,
                    event_type=RealtimeEventType.presence_left,
                    actor=context.user,
                    entity_type="member",
                    entity_id=context.user.id,
                    payload=presence_payload(status="offline"),
                )
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception(
                    "Realtime presence leave publish failed",
                    extra={
                        "organization_id": str(organization_id),
                        "user_id": str(context.user.id),
                    },
                )
            logger.info(
                "Realtime subscription closed",
                extra={
                    "organization_id": str(organization_id),
                    "channel": realtime_channel(organization_id),
                    "user_id": str(context.user.id),
                },
            )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
