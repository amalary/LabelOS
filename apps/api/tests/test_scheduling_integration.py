"""Calendar projections and transactional observability on SQLite and PostgreSQL."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from labelos_database.models import (
    ApprovalRequest,
    CampaignMilestone,
    MarketingContentItemChannel,
    MarketingContentItemStatus,
    RealtimeEvent,
    SchedulingJobTransition,
    SocialAccountConnection,
)
from sqlalchemy import event, func, select

from labelos_api.api.v1.campaign_calendar import _event_response
from labelos_api.api.v1.marketing_content import _channel_response
from labelos_api.realtime.events import list_events_after
from labelos_api.scheduling.events import (
    job_correlation_id,
    publish_transition,
    transition_events,
)
from labelos_api.scheduling.metrics import scheduling_metrics
from labelos_api.services.campaign_calendar_service import (
    CampaignCalendarEventQuery,
    list_campaign_calendar_events,
)
from labelos_api.services.scheduling_eligibility import evaluate_content_batch
from labelos_api.services.scheduling_projection import load_scheduling_projections
from test_scheduling_persistence import NOW, job_for, source
from test_scheduling_persistence import sessions as sessions  # noqa: F401


@pytest.mark.parametrize(
    "status,active",
    [
        ("pending", True),
        ("claimed", True),
        ("blocked", True),
        ("handed_off", False),
        ("cancelled", False),
        ("superseded", False),
    ],
)
def test_projection_preserves_calendar_events_and_publication(sessions, status, active):
    async def run():
        async with sessions.begin() as session:
            item, approval, user = await source(session)
            channel = item.channels[0]
            item.status = MarketingContentItemStatus.approved
            item.approved_revision = 1
            item.approved_at = NOW - timedelta(days=3)
            item.approval_requested_at = NOW - timedelta(days=4)
            item.approval_request_id = approval.id
            approval.submitted_at = item.approval_requested_at
            approval.resolved_at = item.approved_at
            destination = SocialAccountConnection(
                organization_id=item.organization_id, provider="instagram"
            )
            session.add(destination)
            await session.flush()
            channel.social_account_connection_id = destination.id
            session.add(
                CampaignMilestone(
                    campaign_id=item.campaign_id, title="Launch", target_date=NOW.date()
                )
            )
            workspace = item.organization_id
            query = CampaignCalendarEventQuery(
                start=NOW - timedelta(days=10),
                end=NOW + timedelta(days=10),
                timezone="America/Los_Angeles",
                include_published=True,
            )
            before = await list_campaign_calendar_events(
                session, workspace, query=query
            )
            values = {"status": status, "social_account_connection_id": destination.id}
            if status == "claimed":
                values.update(
                    fencing_token=1,
                    claimed_by="private-worker",
                    claimed_at=NOW,
                    claim_expires_at=NOW + timedelta(minutes=1),
                )
            if status == "blocked":
                values.update(
                    blocked_reason_code="connection_unavailable", blocked_at=NOW
                )
            if status == "handed_off":
                values.update(handed_off_at=NOW, handoff_receipt_id=uuid4())
            if status == "cancelled":
                values.update(
                    cancelled_at=NOW, cancellation_reason="private-cancellation"
                )
            job = job_for(item, approval, user, **values)
            session.add(job)
            await session.flush()
            assert (await scheduling_metrics(session, workspace))[status] == 1
            after = await list_campaign_calendar_events(session, workspace, query=query)
            assert [(e.id, e.event_type, e.starts_at) for e in after.events] == [
                (e.id, e.event_type, e.starts_at) for e in before.events
            ]
            assert len({e.id for e in after.events}) == len(after.events)
            scheduled = next(
                e
                for e in after.events
                if e.event_type == "marketing.content.channel_scheduled"
            )
            projection = scheduled.channel.scheduling_job
            assert projection.status == status and projection.active is active
            wire = _event_response(scheduled).model_dump(mode="json")
            assert wire["channel"]["scheduling_job"]["job_id"] == str(job.id)
            assert wire["channel"]["scheduling_job"]["active"] is active
            assert projection.intent_matches
            assert scheduled.starts_at == "2026-09-15T05:00:00-07:00"
            assert (
                next(
                    e
                    for e in after.events
                    if e.event_type == "marketing.content.scheduled"
                ).starts_at
                == "2026-09-14T05:00:00-07:00"
            )
            assert any(
                e.event_type == "campaign.milestone.target" for e in after.events
            )
            assert any(
                e.event_type == "marketing.content.approved" for e in after.events
            )
            assert any(
                e.event_type == "marketing.content.channel_published"
                for e in after.events
            )
            readiness = (await evaluate_content_batch(session, workspace, [item]))[
                item.id
            ]
            content_channel = _channel_response(
                channel, readiness.channels[channel.id], readiness.jobs[channel.id]
            )
            assert content_channel.scheduling_job == projection
            assert content_channel.scheduled_at == NOW
            assert content_channel.published_at == NOW - timedelta(days=2)
            # No publication evidence means no publication event, even handed off.
            channel.published_at = None
            await session.flush()
            no_publication = await list_campaign_calendar_events(
                session, workspace, query=query
            )
            assert not any(
                e.event_type.endswith("published") for e in no_publication.events
            )

    asyncio.run(run())


def test_latest_projection_batch_is_scoped_constant_and_read_only(sessions):
    async def run():
        async with sessions.begin() as session:
            item, approval, user = await source(session)
            old = job_for(item, approval, user, status="superseded", created_at=NOW)
            session.add(old)
            await session.flush()
            rows = await load_scheduling_projections(
                session, item.organization_id, [item]
            )
            assert not rows[item.channels[0].id].active
            # A material edit alone never manufactures a replacement job.
            item.content_revision = 2
            item.channels[0].schedule_generation = 2
            await session.flush()
            rows = await load_scheduling_projections(
                session, item.organization_id, [item]
            )
            assert rows[item.channels[0].id].job_id == str(old.id)
            assert not rows[item.channels[0].id].intent_matches
            approval2 = ApprovalRequest(
                organization_id=item.organization_id,
                resource_type="marketing_content_item",
                resource_id=item.id,
                resource_revision=2,
                title="Reapproved",
                status="approved",
            )
            session.add(approval2)
            await session.flush()
            replacement = job_for(
                item,
                approval2,
                user,
                authorized_content_revision=2,
                schedule_generation=2,
                supersedes_job_id=old.id,
                lineage_root_job_id=old.id,
                created_at=NOW + timedelta(seconds=1),
            )
            session.add(replacement)
            await session.flush()
            statements = []

            def record(_c, _cursor, sql, *_args):
                statements.append(sql)

            engine = session.bind.sync_engine
            event.listen(engine, "before_cursor_execute", record)
            try:
                for size in (1, 21):
                    if size > 1:
                        for _ in range(20):
                            channel = MarketingContentItemChannel(
                                channel="instagram",
                                placement=str(uuid4()),
                                scheduled_at=NOW,
                                schedule_timezone="UTC",
                                schedule_generation=2,
                            )
                            item.channels.append(channel)
                            await session.flush()
                            session.add(
                                job_for(
                                    item,
                                    approval2,
                                    user,
                                    authorized_content_revision=2,
                                    schedule_generation=2,
                                    marketing_content_item_channel_id=channel.id,
                                )
                            )
                        await session.flush()
                    statements.clear()
                    rows = await load_scheduling_projections(
                        session, item.organization_id, [item]
                    )
                    assert len(rows) == size
                    assert len(statements) == 1
                    assert all(
                        field not in statements[0]
                        for field in (
                            "blocked_metadata",
                            "cancellation_reason",
                            "claimed_by",
                        )
                    )
                    assert rows[item.channels[0].id].job_id == str(replacement.id)
                    assert rows[item.channels[0].id].active
                    assert not session.dirty
            finally:
                event.remove(engine, "before_cursor_execute", record)
            assert await load_scheduling_projections(session, uuid4(), [item]) == {}

    asyncio.run(run())


@pytest.mark.parametrize(
    "operation,status,expired,unavailable,expected",
    [
        ("activate", "pending", False, False, {"activated"}),
        ("claim", "claimed", False, False, {"claimed"}),
        ("accept_delivery", "handed_off", False, False, {"handed_off"}),
        ("block", "blocked", False, False, {"blocked"}),
        ("cancel", "cancelled", False, False, {"cancelled"}),
        ("supersede", "superseded", False, False, {"superseded"}),
        ("recover_claim", "pending", True, False, {"lease_expired", "requeued"}),
        ("block", "blocked", True, False, {"lease_expired", "blocked"}),
        ("recover_claim", "pending", False, True, {"handoff_unavailable", "requeued"}),
        ("block", "blocked", False, True, {"handoff_unavailable", "blocked"}),
    ],
)
def test_transition_event_types(operation, status, expired, unavailable, expected):
    events = transition_events(
        operation, lease_expired=expired, unavailable=unavailable
    )
    assert {e.value.rsplit(".", 1)[-1] for e in events} == expected


def test_outbox_replay_redaction_correlation_and_rollback(sessions):
    async def run():
        async with sessions.begin() as session:
            item, approval, user = await source(session)
            job = job_for(item, approval, user)
            session.add(job)
            await session.flush()
            workspace = item.organization_id
            transition = SchedulingJobTransition(
                job_id=job.id,
                workspace_id=workspace,
                marketing_content_item_id=item.id,
                transition_version=1,
                operation_id=uuid4(),
                operation="activate",
                to_status=job.status,
                actor_kind="worker",
                actor_key="PRIVATE_TOKEN",
                reason_code="PRIVATE_COPY",
                created_at=NOW,
            )
            session.add(transition)
            types = transition_events("activate")
            await publish_transition(session, job, transition, types)
            await publish_transition(session, job, transition, types)
        async with sessions() as session:
            events = await list_events_after(
                session, organization_id=workspace, after_event_id=None
            )
            assert len(events) == 1
            payload = events[0].payload
            assert payload["correlationId"] == str(job_correlation_id(job))
            assert payload["operationId"] == str(transition.operation_id)
            assert "PRIVATE" not in json.dumps(payload)
            assert payload["reasonCode"] is None
            assert (
                await list_events_after(
                    session, organization_id=uuid4(), after_event_id=None
                )
                == []
            )
            assert (
                await list_events_after(
                    session, organization_id=workspace, after_event_id=events[0].id
                )
                == []
            )
            # The outbox insert is undone even after flush and within a savepoint.
            with pytest.raises(RuntimeError):
                async with session.begin_nested():
                    await publish_transition(
                        session, job, transition, transition_events("claim")
                    )
                    raise RuntimeError("rollback")
            assert (
                await session.scalar(select(func.count()).select_from(RealtimeEvent))
                == 1
            )
            metrics = await scheduling_metrics(session, workspace)
            assert metrics == dict(
                pending=1,
                due=1,
                claimed=0,
                handed_off=0,
                blocked=0,
                cancelled=0,
                superseded=0,
                requeued=0,
                expired=0,
            )
            assert all(
                value == 0
                for value in (await scheduling_metrics(session, uuid4())).values()
            )

    asyncio.run(run())


@pytest.mark.parametrize("hour,offset", [(5, -4), (6, -5)])
def test_calendar_projection_preserves_both_dst_fold_instants(sessions, hour, offset):
    async def run():
        instant = datetime(2026, 11, 1, hour, 30, tzinfo=UTC)
        async with sessions.begin() as session:
            item, approval, user = await source(session)
            channel = item.channels[0]
            channel.scheduled_at = instant
            channel.schedule_timezone = "America/New_York"
            channel.schedule_local_time = "2026-11-01T01:30:00"
            channel.schedule_offset_seconds = offset * 3600
            session.add(
                job_for(
                    item,
                    approval,
                    user,
                    scheduled_for=instant,
                    schedule_timezone="America/New_York",
                )
            )
            await session.flush()
            page = await list_campaign_calendar_events(
                session,
                item.organization_id,
                query=CampaignCalendarEventQuery(
                    start=instant - timedelta(hours=1),
                    end=instant + timedelta(hours=1),
                    timezone="America/New_York",
                    event_types=("marketing.content.channel_scheduled",),
                ),
            )
            assert len(page.events) == 1
            scheduled = page.events[0]
            assert scheduled.starts_at == f"2026-11-01T01:30:00-0{-offset}:00"
            assert scheduled.channel.scheduling_job.scheduled_for == instant
            assert scheduled.channel.scheduling_job.intent_matches

    asyncio.run(run())
