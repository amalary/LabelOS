"""Retire Scheduling jobs atomically with a material content edit."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from labelos_database.models import SchedulingJob, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.authorization import AuthorizationActorInput
from labelos_api.repositories.scheduling import ACTIVE, SchedulingRepository


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

    Approval covers the entire parent revision, so unchanged siblings also retire.
    Physical removal of a referenced channel still fails its history FK and rolls
    back the entire edit. Already handed-off and other terminal jobs stay intact.
    """
    job_ids = list(
        await session.scalars(
            select(SchedulingJob.id)
            .where(
                SchedulingJob.workspace_id == invalidation.workspace_id,
                SchedulingJob.marketing_content_item_id == invalidation.content_item_id,
                SchedulingJob.status.in_(ACTIVE),
            )
            .order_by(SchedulingJob.id)
        )
    )
    if not job_ids:
        return
    user = actor if isinstance(actor, User) else getattr(actor, "user", None)
    if not isinstance(user, User):
        raise ValueError("Content invalidation requires an authenticated author")
    actor_ref = getattr(actor, "authorization_actor", None)
    actor_kind = getattr(actor_ref, "kind", "user")
    actor_key = getattr(actor_ref, "subject", None) or str(user.id)
    # Retirement has no due-window check; it must also fence overdue/expired work.
    repository = SchedulingRepository(
        session, invalidation.workspace_id, lateness_window_seconds=0
    )
    removed = set(invalidation.removed_channel_ids)
    for job_id in job_ids:
        job = await repository.get_job(job_id)
        assert job is not None
        await repository.apply_user_transition(
            job_id,
            operation=(
                "cancel"
                if job.marketing_content_item_channel_id in removed
                else "supersede"
            ),
            operation_id=uuid4(),
            actor_key=actor_key,
            actor_kind=str(actor_kind),
        )
