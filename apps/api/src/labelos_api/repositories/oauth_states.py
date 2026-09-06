from collections.abc import Mapping
from datetime import datetime

from labelos_database.models import (
    OAuthAuthorizationState,
    OAuthAuthorizationStateStatus,
)
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession


async def create_state(
    session: AsyncSession,
    values: Mapping[str, object],
) -> OAuthAuthorizationState:
    state = OAuthAuthorizationState(**dict(values))
    session.add(state)
    await session.flush()
    return state


async def get_state_by_hash(
    session: AsyncSession,
    state_hash: str,
) -> OAuthAuthorizationState | None:
    return await session.scalar(
        select(OAuthAuthorizationState).where(
            OAuthAuthorizationState.state_hash == state_hash
        )
    )


async def mark_state_terminal(
    session: AsyncSession,
    state: OAuthAuthorizationState,
    *,
    status: OAuthAuthorizationStateStatus,
    consumed_at: datetime | None = None,
) -> OAuthAuthorizationState:
    state.status = status
    if consumed_at is not None:
        state.consumed_at = consumed_at
    await session.flush()
    return state


async def consume_pending_state(
    session: AsyncSession,
    state: OAuthAuthorizationState,
    *,
    consumed_at: datetime,
) -> OAuthAuthorizationState | None:
    result = await session.execute(
        update(OAuthAuthorizationState)
        .where(OAuthAuthorizationState.id == state.id)
        .where(OAuthAuthorizationState.status == OAuthAuthorizationStateStatus.pending)
        .where(OAuthAuthorizationState.consumed_at.is_(None))
        .values(
            status=OAuthAuthorizationStateStatus.consumed,
            consumed_at=consumed_at,
            updated_at=consumed_at,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return None
    await session.refresh(state)
    return state


async def delete_expired_states(
    session: AsyncSession,
    *,
    now: datetime,
) -> int:
    result = await session.execute(
        delete(OAuthAuthorizationState).where(
            (OAuthAuthorizationState.expires_at <= now)
            | (OAuthAuthorizationState.status == OAuthAuthorizationStateStatus.expired)
        )
    )
    await session.flush()
    return result.rowcount or 0
