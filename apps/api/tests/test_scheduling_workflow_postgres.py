"""Production-readiness workflow through real authoring/approval transactions."""

import asyncio
from datetime import timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from labelos_database.capabilities import Capability
from labelos_database.models import (
    MarketingContentItem,
    MarketingContentItemChannel,
    OrganizationMembership,
    RealtimeEvent,
    SchedulingExecutionControl,
    SchedulingJob,
    SchedulingJobTransition,
    SocialAccountConnection,
)
from sqlalchemy import func, select, update

from labelos_api.repositories.scheduling import SchedulingConflict
from labelos_api.scheduling.contracts import SchedulingFeatureControls
from labelos_api.scheduling.metrics import scheduling_metrics
from labelos_api.services import marketing_content_service as content
from labelos_api.services.content_transactions import (
    ApprovalTransaction,
    MarketingContentTransaction,
)
from labelos_api.services.scheduling_activation import (
    ActivateChannelSchedule,
    SchedulingActivationRejected,
)
from labelos_api.services.scheduling_commands import SchedulingCommandService
from labelos_api.services.scheduling_handoff import accept_scheduling_handoff
from labelos_api.services.scheduling_processor import SchedulingExecutionRefused
from labelos_api.services.scheduling_projection import load_scheduling_projections
from test_approval_service import _agent_actor, _seed
from test_scheduling_activation import ENABLED
from test_scheduling_handoff_postgres import inbox
from test_scheduling_processor_postgres import (
    RecordingReceiver,
    processor,
    ready,
    reserve,
)
from test_scheduling_processor_postgres import sessions as sessions  # noqa: F401
from test_scheduling_repository import repo
from test_scheduling_repository import sessions as repository_sessions  # noqa: F401


def command_service(session, seed):
    return SchedulingCommandService(
        session,
        seed.organization_id,
        actor=seed.submitter,
        controls=ENABLED,
        lateness_window_seconds=300,
    )


async def approve(session, seed, item_id):
    request = await ApprovalTransaction(
        session, seed.organization_id, actor=seed.submitter
    ).submit_resource_for_approval("marketing_content_item", item_id)
    await ApprovalTransaction(
        session, seed.organization_id, actor=seed.reviewer
    ).approve_request(request.id)
    return request.id


async def author(sessions):
    async with sessions.begin() as session:
        seed = await _seed(session)
        membership = await session.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == seed.submitter.id
            )
        )
        membership.capability_permissions = [
            *membership.capability_permissions,
            Capability.marketing_content_schedule.value,
        ]
        now = await session.scalar(select(func.clock_timestamp()))
        due = now + timedelta(seconds=20)
        destinations = [
            SocialAccountConnection(
                organization_id=seed.organization_id,
                provider="instagram",
                status="connected",
                capabilities=["content_publish"],
            )
            for _ in range(4)
        ]
        session.add_all(destinations)
        session.add(
            SchedulingExecutionControl(
                workspace_id=seed.organization_id, execution_enabled=True
            )
        )
        await session.flush()
        channels = []
        for index, zone in enumerate(
            ["UTC", "Asia/Kathmandu", "America/New_York", "Pacific/Auckland"]
        ):
            instant = due if index < 3 else due + timedelta(hours=1)
            channels.append(
                content.MarketingContentChannelCreate(
                    channel="instagram",
                    placement=f"placement-{index}",
                    social_account_connection_id=destinations[index].id,
                    schedule_timezone=zone,
                    schedule_local_time=instant.astimezone(ZoneInfo(zone))
                    .replace(tzinfo=None)
                    .isoformat(),
                )
            )
        item = await MarketingContentTransaction(
            session, seed.organization_id, actor=seed.submitter
        ).create_content_item(
            content.MarketingContentItemCreate(
                campaign_id=seed.campaign_id,
                title="Scheduling audit",
                content_type="caption",
                copy_text="PRIVATE_APPROVED_COPY",
                scheduled_at=now,
                channels=channels,
            )
        )
        channel_ids = tuple(
            row.id for row in sorted(item.channels, key=lambda row: row.placement)
        )
        assert len(set(channel_ids)) == 4
        assert (
            await session.scalar(select(func.count()).select_from(SchedulingJob)) == 0
        )
        await approve(session, seed, item.id)
        return seed, item.id, channel_ids, due


async def activate(session, seed, item_id, channel_id, operation_id=None):
    item = await session.get(MarketingContentItem, item_id)
    channel = await session.get(MarketingContentItemChannel, channel_id)
    return await command_service(session, seed).activate_command(
        ActivateChannelSchedule(
            content_item_id=item_id,
            channel_id=channel_id,
            operation_id=operation_id or uuid4(),
            expected_content_revision=item.content_revision,
            expected_schedule_generation=channel.schedule_generation,
        )
    )


async def wait_until_due(sessions, instant):
    async with sessions() as session:
        now = await session.scalar(select(func.clock_timestamp()))
    await asyncio.sleep(max(0, (instant - now).total_seconds()) + 0.05)


def test_complete_authoring_activation_and_delivery_boundary(sessions):
    async def run():
        seed, item_id, channels, due = await author(sessions)
        workspace = seed.organization_id
        async with sessions.begin() as session:
            key = uuid4()
            original = await activate(session, seed, item_id, channels[0], key)
            assert (
                await activate(session, seed, item_id, channels[0], key)
            ).id == original.id
            assert (
                await session.scalar(select(func.count()).select_from(SchedulingJob))
                == 1
            )
        # A sibling time edit invalidates parent approval and retires the first job.
        async with sessions.begin() as session:
            await MarketingContentTransaction(
                session, workspace, actor=seed.submitter
            ).update_channel(
                item_id,
                channels[1],
                content.MarketingContentChannelUpdate(
                    schedule_timezone="Asia/Kathmandu",
                    schedule_local_time=(due + timedelta(seconds=1))
                    .astimezone(ZoneInfo("Asia/Kathmandu"))
                    .replace(tzinfo=None)
                    .isoformat(),
                ),
            )
            item = await session.get(MarketingContentItem, item_id)
            assert item.content_revision == 2 and item.approved_at is None
            assert (
                await session.get(SchedulingJob, original.id)
            ).status == "superseded"
            await session.refresh(item, ["channels"])
            assert {row.id for row in item.channels} == set(channels)
            with pytest.raises(SchedulingActivationRejected, match="stale_approval"):
                await activate(session, seed, item_id, channels[1])
            await approve(session, seed, item_id)
            replacement = await command_service(session, seed).job_command(
                original.id,
                operation="replace",
                operation_id=uuid4(),
                expected_content_revision=2,
                expected_schedule_generation=1,
            )
            assert replacement.supersedes_job_id == original.id
            assert replacement.lineage_root_job_id == original.id
            jobs = [replacement]
            for channel in channels[1:]:
                jobs.append(await activate(session, seed, item_id, channel))
            await command_service(session, seed).job_command(
                jobs[2].id, operation="cancel", operation_id=uuid4()
            )
        receiver = RecordingReceiver()
        runners = [processor(sessions, workspace, receiver=receiver) for _ in range(2)]
        await wait_until_due(sessions, due + timedelta(seconds=1))
        results = await asyncio.gather(*(runner.run(workspace) for runner in runners))
        assert sum(result.claimed for result in results) == 2
        assert sum(result.outcomes.get("handed_off", 0) for result in results) == 2
        async with sessions.begin() as session:
            assert (await session.get(SchedulingJob, jobs[2].id)).status == "cancelled"
            assert (await session.get(SchedulingJob, jobs[3].id)).status == "pending"
            assert (await session.get(SchedulingJob, jobs[3].id)).fencing_token == 0
            assert await session.scalar(select(func.count()).select_from(inbox)) == 2
            claims = list(
                await session.scalars(
                    select(SchedulingJobTransition).where(
                        SchedulingJobTransition.operation == "claim"
                    )
                )
            )
            assert len(claims) == len({row.job_id for row in claims}) == 2
            # Lose the caller acknowledgement after durable acceptance, then replay.
            request = receiver.requests[0]
            receipt = await accept_scheduling_handoff(
                repo(session, workspace),
                receiver=receiver,
                request=request,
                expected_worker=runners[0].worker.worker_id,
                expected_fencing_token=0,
                controls=ENABLED,
            )
            saved = await session.get(SchedulingJob, request.job_id)
            assert receipt.receipt_id == saved.handoff_receipt_id
            assert await session.scalar(select(func.count()).select_from(inbox)) == 2
        # Cancellation recovery requires a real edit and a new approval.
        async with sessions.begin() as session:
            next_due = await session.scalar(select(func.clock_timestamp())) + timedelta(
                seconds=4
            )
            await MarketingContentTransaction(
                session, workspace, actor=seed.submitter
            ).update_channel(
                item_id,
                channels[2],
                content.MarketingContentChannelUpdate(
                    schedule_timezone="UTC",
                    schedule_local_time=next_due.replace(tzinfo=None).isoformat(),
                ),
            )
            await approve(session, seed, item_id)
            replacement = await command_service(session, seed).job_command(
                jobs[2].id,
                operation="replace",
                operation_id=uuid4(),
                expected_content_revision=3,
                expected_schedule_generation=2,
            )
            assert replacement.supersedes_job_id == jobs[2].id
            await session.execute(
                update(SocialAccountConnection)
                .where(
                    SocialAccountConnection.id
                    == replacement.social_account_connection_id
                )
                .values(status="disconnected")
            )
        await wait_until_due(sessions, next_due)
        assert (await runners[0].run(workspace)).outcomes == {
            "connection_unavailable": 1
        }
        with pytest.raises(SchedulingExecutionRefused, match="execution_disabled"):
            await processor(
                sessions, workspace, controls=SchedulingFeatureControls()
            ).run(workspace)
        # A second workspace's due work remains untouched by this workspace sweep.
        other, other_jobs = await ready(sessions)
        assert (await runners[0].run(workspace)).claimed == 0
        async with sessions() as session:
            assert await repo(session, workspace).get_job(other_jobs[0].id) is None
            assert (
                await session.get(SchedulingJob, other_jobs[0].id)
            ).status == "pending"
            metrics = await scheduling_metrics(session, workspace)
            assert metrics["handed_off"] == 2 and metrics["blocked"] == 1
            item = await session.get(MarketingContentItem, item_id)
            await session.refresh(item, ["channels"])
            projections = await load_scheduling_projections(session, workspace, [item])
            assert projections[channels[2]].status == "blocked"
            assert item.published_at is None
            assert all(
                row.published_at is None
                and row.external_post_id is None
                and row.external_url is None
                for row in item.channels
            )
            events = list(
                await session.scalars(
                    select(RealtimeEvent).where(
                        RealtimeEvent.organization_id == workspace
                    )
                )
            )
            assert not any(
                row.event_type == "marketing.content.published" for row in events
            )
            assert any(
                row.event_type == "marketing.scheduling_job.superseded"
                for row in events
            )
            assert other != workspace

    asyncio.run(run())


@pytest.mark.parametrize("state", ["pending", "claimed", "blocked"])
@pytest.mark.parametrize("rollback", [False, True])
def test_material_edit_retires_all_siblings_atomically(sessions, state, rollback):
    async def run():
        seed, item_id, channels, _ = await author(sessions)
        workspace = seed.organization_id
        async with sessions.begin() as session:
            jobs = [
                await activate(session, seed, item_id, channel) for channel in channels
            ]
            if state == "blocked":
                for job in jobs:
                    await repo(session, workspace).block_job(
                        job.id, reason="connection_unavailable", actor_key="validator"
                    )
        runner = processor(sessions, workspace)
        if state == "claimed":
            await wait_until_due(sessions, jobs[0].scheduled_for)
            claims = await reserve(runner, workspace)
            assert len(claims) == 3
        async with sessions() as session:
            await MarketingContentTransaction(
                session, workspace, actor=_agent_actor(seed.submitter)
            ).update_content_item(
                item_id,
                content.MarketingContentItemUpdate(
                    copy_text="Edited", material_change=True
                ),
            )
            if rollback:
                await session.rollback()
            else:
                await session.commit()
        async with sessions() as session:
            saved = list(await session.scalars(select(SchedulingJob)))
            if rollback:
                assert all(row.status != "superseded" for row in saved)
                assert (
                    await session.get(MarketingContentItem, item_id)
                ).content_revision == 1
            else:
                assert all(row.status == "superseded" for row in saved)
                history = list(
                    await session.scalars(
                        select(SchedulingJobTransition).where(
                            SchedulingJobTransition.operation == "supersede"
                        )
                    )
                )
                assert len(history) == 4
                assert all(row.actor_kind == "ai_agent" for row in history)
                assert all(row.actor_key.startswith("agent:") for row in history)
        if state == "claimed" and not rollback:
            with pytest.raises(SchedulingConflict, match="claim_lost"):
                await runner.process_claim(workspace, claims[0])
            assert not runner.receiver.requests

    asyncio.run(run())
