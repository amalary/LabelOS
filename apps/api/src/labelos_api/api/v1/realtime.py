from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Annotated
from uuid import UUID

from anyio import CancelScope
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from labelos_database.models import User
from starlette.types import Receive, Scope, Send

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


class RealtimeStreamingResponse(StreamingResponse):
    body_iterator: AsyncGenerator[str, None]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            # A failed send can leave the generator suspended at yield. Close it
            # before FastAPI releases the request session, even on cancellation.
            with CancelScope(shield=True):
                await self.body_iterator.aclose()


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

    actor_id = context.user.id

    async def stream() -> AsyncGenerator[str, None]:
        cursor = last_event_id
        loops_since_membership_check = 0
        loops_since_keepalive = 0
        publisher = RealtimePublisher(session)
        joined = await publisher.publish(
            organization_id=organization_id,
            event_type=RealtimeEventType.presence_joined,
            actor=context.user,
            entity_type="member",
            entity_id=actor_id,
            payload=presence_payload(),
        )
        await session.commit()
        cursor = last_event_id or joined.id
        logger.info(
            "Realtime subscription opened",
            extra={
                "organization_id": str(organization_id),
                "channel": realtime_channel(organization_id),
                "user_id": str(actor_id),
            },
        )
        try:
            yield _sse(
                "connected",
                {"channel": realtime_channel(organization_id), "cursor": cursor},
            )
            while True:
                # Finish the short transaction before honoring client disconnect.
                # Never keep this shield active across a yield or the idle wait.
                with CancelScope(shield=True):
                    events = await list_events_after(
                        session,
                        organization_id=organization_id,
                        after_event_id=cursor,
                    )
                    loops_since_membership_check += 1
                    loops_since_keepalive += 1
                    has_membership = True
                    if (
                        loops_since_membership_check * POLL_INTERVAL_SECONDS
                        >= MEMBERSHIP_RECHECK_SECONDS
                    ):
                        has_membership = await has_active_membership(
                            session,
                            context,
                            organization_id,
                        )
                        loops_since_membership_check = 0

                    # Release the connection before yielding or sleeping.
                    await session.commit()
                if not has_membership:
                    yield _sse(
                        "membership_revoked",
                        {"organization_id": str(organization_id)},
                    )
                    break
                for event in events:
                    cursor = event.id
                    yield _sse("message", event.model_dump(mode="json"))

                if loops_since_keepalive * POLL_INTERVAL_SECONDS >= KEEPALIVE_SECONDS:
                    yield ": keepalive\n\n"
                    loops_since_keepalive = 0

                await asyncio.sleep(POLL_INTERVAL_SECONDS)
        finally:
            with CancelScope(shield=True):
                try:
                    # A cancelled query may have invalidated its connection.
                    # Reset the transaction and reload any expired actor first.
                    await session.rollback()
                    actor = await session.get(User, actor_id)
                    await publisher.publish(
                        organization_id=organization_id,
                        event_type=RealtimeEventType.presence_left,
                        actor=actor,
                        entity_type="member",
                        entity_id=actor_id,
                        payload=presence_payload(status="offline"),
                    )
                    await session.commit()
                except Exception as error:
                    await session.rollback()
                    logger.error(
                        "Realtime presence leave publish failed",
                        extra={
                            "organization_id": str(organization_id),
                            "user_id": str(actor_id),
                            "error_type": type(error).__name__,
                        },
                    )
            logger.info(
                "Realtime subscription closed",
                extra={
                    "organization_id": str(organization_id),
                    "channel": realtime_channel(organization_id),
                    "user_id": str(actor_id),
                },
            )

    return RealtimeStreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
