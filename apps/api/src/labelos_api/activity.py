from __future__ import annotations

import logging
from contextlib import suppress
from enum import StrEnum
from typing import Any
from uuid import UUID

from labelos_database.models import ActivityEvent, User
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.logging import get_request_id

logger = logging.getLogger("labelos_api.audit")

_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "invitation_secret",
)


class ActivityEventType(StrEnum):
    organization_created = "organization.created"
    organization_updated = "organization.updated"
    organization_switched = "organization.switched"
    member_invited = "member.invited"
    member_joined = "member.joined"
    member_role_changed = "member.role_changed"
    member_removed = "member.removed"
    artist_created = "artist.created"
    artist_updated = "artist.updated"
    artist_status_changed = "artist.status_changed"


def _safe_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, nested in value.items():
            key_text = str(key)
            if any(part in key_text.lower() for part in _SENSITIVE_KEY_PARTS):
                continue
            sanitized[key_text] = _safe_value(nested)
        return sanitized
    if isinstance(value, list | tuple):
        return [_safe_value(item) for item in value]
    if isinstance(value, str) and len(value) > 2048:
        return f"{value[:2048]}...[TRUNCATED]"
    return value


def _string_or_none(value: UUID | str | None) -> str | None:
    if value is None:
        return None
    return str(value)


async def record_activity_event(
    session: AsyncSession,
    *,
    event_type: ActivityEventType,
    operation: str,
    organization_id: UUID,
    actor: User | None,
    target_user_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: UUID | str | None = None,
    result: str = "success",
    changes: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ActivityEvent:
    event = ActivityEvent(
        organization_id=organization_id,
        event_type=event_type.value,
        operation=operation,
        result=result,
        actor_user_id=actor.id if actor is not None else None,
        target_user_id=target_user_id,
        entity_type=entity_type,
        entity_id=_string_or_none(entity_id),
        changes=_safe_value(changes or {}),
        event_metadata=_safe_value(metadata or {}),
    )
    session.add(event)
    await session.flush()
    _log_activity_event(event)
    return event


def _log_activity_event(event: ActivityEvent) -> None:
    with suppress(Exception):
        logger.info(
            "Activity event recorded",
            extra={
                "request_id": get_request_id(),
                "user_id": (
                    str(event.actor_user_id)
                    if event.actor_user_id is not None
                    else None
                ),
                "organization_id": str(event.organization_id),
                "operation": event.operation,
                "event_id": str(event.id),
                "event_type": event.event_type,
                "result": event.result,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
            },
        )
