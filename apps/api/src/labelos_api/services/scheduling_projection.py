"""One bounded batch read of operational state, independent of planned dates."""

from datetime import UTC, datetime

from labelos_database.models import SchedulingJob
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import load_only

from labelos_api.scheduling.events import job_correlation_id


class SchedulingJobProjection(BaseModel):
    job_id: str
    status: str
    active: bool
    intent_matches: bool
    scheduled_for: datetime
    schedule_timezone: str
    blocked_reason_code: str | None
    transition_version: int
    correlation_id: str


def _utc(value):
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


async def load_scheduling_projections(session, workspace_id, items):
    channels = {
        channel.id: (item, channel)
        for item in items
        for channel in item.channels
        if item.organization_id == workspace_id
    }
    if not channels:
        return {}
    # Rank before filtering state so cancelled/superseded work never reveals an
    # older execution indicator. A new row only exists after explicit activation.
    ranked = (
        select(
            SchedulingJob.id,
            func.row_number()
            .over(
                partition_by=SchedulingJob.marketing_content_item_channel_id,
                order_by=(SchedulingJob.created_at.desc(), SchedulingJob.id.desc()),
            )
            .label("rank"),
        )
        .where(
            SchedulingJob.workspace_id == workspace_id,
            SchedulingJob.marketing_content_item_channel_id.in_(channels),
        )
        .subquery()
    )
    jobs = await session.scalars(
        select(SchedulingJob)
        .options(
            load_only(
                SchedulingJob.id,
                SchedulingJob.marketing_content_item_id,
                SchedulingJob.marketing_content_item_channel_id,
                SchedulingJob.authorized_content_revision,
                SchedulingJob.schedule_generation,
                SchedulingJob.scheduled_for,
                SchedulingJob.schedule_timezone,
                SchedulingJob.social_account_connection_id,
                SchedulingJob.status,
                SchedulingJob.blocked_reason_code,
                SchedulingJob.transition_version,
                SchedulingJob.idempotency_key,
                raiseload=True,
            )
        )
        .join(ranked, ranked.c.id == SchedulingJob.id)
        .where(ranked.c.rank == 1, SchedulingJob.workspace_id == workspace_id)
        .execution_options(populate_existing=True)
    )
    result = {}
    for job in jobs:
        item, channel = channels[job.marketing_content_item_channel_id]
        matches = (
            job.marketing_content_item_id == item.id
            and job.authorized_content_revision == item.content_revision
            and job.schedule_generation == channel.schedule_generation
            and job.scheduled_for == _utc(channel.scheduled_at)
            and job.schedule_timezone == channel.schedule_timezone
            and job.social_account_connection_id == channel.social_account_connection_id
        )
        result[channel.id] = SchedulingJobProjection(
            job_id=str(job.id),
            status=job.status.value,
            active=matches and job.status in ("pending", "claimed", "blocked"),
            intent_matches=matches,
            scheduled_for=job.scheduled_for,
            schedule_timezone=job.schedule_timezone,
            blocked_reason_code=job.blocked_reason_code,
            transition_version=job.transition_version,
            correlation_id=str(job_correlation_id(job)),
        )
    return result
