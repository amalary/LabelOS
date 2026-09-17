"""Committed DB gauges and retained transition totals for the worker log exporter."""

from datetime import UTC, datetime

from labelos_database.models import RealtimeEvent, SchedulingJob
from sqlalchemy import func, select


async def scheduling_metrics(session, workspace_id):
    # Two aggregate queries regardless of job count. No per-job labels, payloads
    # or process counters that could leak rolled-back transactions into metrics.
    now = (
        func.clock_timestamp()
        if session.get_bind().dialect.name == "postgresql"
        else datetime.now(UTC)
    )
    fields = [
        func.count().filter(SchedulingJob.status == status).label(status)
        for status in (
            "pending",
            "claimed",
            "handed_off",
            "blocked",
            "cancelled",
            "superseded",
        )
    ]
    fields.append(
        func.count()
        .filter(SchedulingJob.status == "pending", SchedulingJob.scheduled_for <= now)
        .label("due")
    )
    row = (
        await session.execute(
            select(*fields).where(SchedulingJob.workspace_id == workspace_id)
        )
    ).one()
    result = {key: int(value) for key, value in row._mapping.items()}
    events = (
        await session.execute(
            select(
                func.count()
                .filter(RealtimeEvent.event_type == "marketing.scheduling_job.requeued")
                .label("requeued"),
                func.count()
                .filter(
                    RealtimeEvent.event_type == "marketing.scheduling_job.lease_expired"
                )
                .label("expired"),
            ).where(RealtimeEvent.organization_id == workspace_id)
        )
    ).one()
    result.update({key: int(value) for key, value in events._mapping.items()})
    return result
