"""Transaction-local integration point for future durable channel invalidation.

No scheduling persistence or execution exists here. Before introducing jobs,
implement this hook together with history retention and the remaining locking and
unit-of-work prerequisites in the Scheduling Engine contract.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.authorization import AuthorizationActorInput


@dataclass(frozen=True, kw_only=True)
class ContentInvalidation:
    workspace_id: UUID
    content_item_id: UUID
    previous_content_revision: int
    previous_approval_request_id: UUID | None
    previous_channel_ids: tuple[UUID, ...]
    materially_changed_channel_ids: tuple[UUID, ...]
    removed_channel_ids: tuple[UUID, ...]


async def invalidate_content_channels(
    session: AsyncSession,
    invalidation: ContentInvalidation,
    *,
    actor: AuthorizationActorInput | None,
) -> None:
    """Called under the parent lock, before source rows are changed or deleted.

    Future integration must cancel occupying jobs on removed channels and
    supersede all other jobs on the previous parent revision, including unchanged
    siblings. Preserve the old approval identity and terminal history. Writes
    must use this session without committing or dispatching external work; errors
    propagate to the owning service transaction. This foundation hook deliberately
    performs no work and is not evidence of cancellation or durable acceptance.
    """
