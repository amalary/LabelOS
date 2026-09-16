"""Activation uses real PostgreSQL locks, authorization and transactional writes."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from labelos_database.capabilities import Capability
from labelos_database.models import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalRequestStage,
    Artist,
    ArtistProfile,
    Campaign,
    MarketingContentItem,
    MarketingContentItemChannel,
    RealtimeEvent,
    SchedulingJob,
    SchedulingJobTransition,
    SocialAccountConnection,
    UniversalProfile,
    User,
)
from sqlalchemy import event, func, select, text, update

from labelos_api.realtime import RealtimePublisher
from labelos_api.repositories.scheduling import SchedulingConflict
from labelos_api.scheduling.contracts import SchedulingFeatureControls
from labelos_api.services import marketing_content_service as content
from labelos_api.services import scheduling_activation
from labelos_api.services.marketing_content_service import (
    MarketingContentAuthorizationError,
)
from labelos_api.services.scheduling_activation import (
    ActivateChannelSchedule,
    SchedulingActivationRejected,
    SchedulingActivationService,
    activate_channel_schedule,
)
from test_approval_service import _agent_actor, _seed_actor
from test_marketing_content_postgres import wait_until_blocked
from test_scheduling_repository import seed
from test_scheduling_repository import sessions as sessions

ENABLED = SchedulingFeatureControls(
    authoring_enabled=True, execution_enabled=True, delivery_receiver_configured=True
)
OUTPUTS = (SchedulingJob, SchedulingJobTransition, RealtimeEvent)


async def prepare(session, *, seconds_ago=-3600):
    workspace, activations, _ = await seed(
        session, activate=False, seconds_ago=seconds_ago
    )
    activation = activations[0]
    session.add(
        ApprovalRequestStage(
            approval_request_id=activation.snapshot.approval_request_id,
            stage_order=1,
            required_capability="marketing.content.approve",
            status="approved",
        )
    )
    await session.execute(
        update(MarketingContentItemChannel)
        .where(MarketingContentItemChannel.id == activation.snapshot.channel_id)
        .values(
            schedule_local_time=activation.snapshot.scheduled_for.replace(
                tzinfo=None
            ).isoformat(),
            schedule_offset_seconds=0,
        )
    )
    actor, _ = await _seed_actor(
        session,
        workspace=workspace,
        email=f"{uuid4()}@test.com",
        capabilities=(Capability.marketing_content_schedule.value,),
    )
    await session.execute(
        update(SocialAccountConnection)
        .values(
            status="connected",
            connection_method="direct_api",
            capabilities=["content_publish"],
        )
        .where(SocialAccountConnection.id == activation.destination_id)
    )
    command = ActivateChannelSchedule(
        content_item_id=activation.snapshot.content_item_id,
        channel_id=activation.snapshot.channel_id,
        operation_id=uuid4(),
        expected_content_revision=1,
        expected_schedule_generation=1,
    )
    return workspace, actor, command, activation


def service(session, workspace, actor, *, controls=ENABLED):
    return SchedulingActivationService(
        session,
        workspace.id,
        actor=actor,
        controls=controls,
        lateness_window_seconds=300,
    )


async def counts(session):
    return tuple(
        [await session.scalar(select(func.count()).select_from(t)) for t in OUTPUTS]
    )


async def intent(session, command):
    return (
        (
            await session.execute(
                select(MarketingContentItem.__table__).where(
                    MarketingContentItem.id == command.content_item_id
                )
            )
        )
        .mappings()
        .one(),
        (
            await session.execute(
                select(MarketingContentItemChannel.__table__).where(
                    MarketingContentItemChannel.id == command.channel_id
                )
            )
        )
        .mappings()
        .one(),
    )


def test_success_replay_immutable_intent_and_no_credentials(sessions):
    async def run():
        async with sessions.begin() as session:
            workspace, actor, command, activation = await prepare(session)
        statements = []
        engine = sessions.kw["bind"].sync_engine

        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.lower())

        event.listen(engine, "before_cursor_execute", capture)
        try:
            async with sessions() as session:
                before = await intent(session, command)
                job = await activate_channel_schedule(
                    session,
                    workspace.id,
                    command,
                    actor=actor,
                    controls=ENABLED,
                    lateness_window_seconds=300,
                )
                assert await intent(session, command) == before
                assert job.status == "pending"
                assert job.scheduled_for == activation.snapshot.scheduled_for
                assert job.schedule_timezone == "UTC"
                assert (
                    job.approval_request_id == activation.snapshot.approval_request_id
                )
                assert job.authorized_content_revision == job.schedule_generation == 1
                assert job.social_account_connection_id == activation.destination_id
                assert job.created_by_user_id == actor.id
                assert (
                    job.idempotency_key
                    == f"labelos:scheduling:v1:{workspace.id}:{job.id}"
                )
                replay = await service(session, workspace, actor).activate(command)
                assert replay.id == job.id
                assert await counts(session) == (1, 1, 1)
                audit = await session.scalar(select(SchedulingJobTransition))
                assert audit.operation == "activate" and audit.actor_key == str(
                    actor.id
                )
                outbox = await session.scalar(select(RealtimeEvent))
                assert outbox.operation_id == str(command.operation_id)
                assert outbox.payload["schedulingJobId"] == str(job.id)
                await session.commit()
            # Completed history must replay even after source approval is revoked.
            async with sessions.begin() as session:
                await session.execute(
                    update(SchedulingJob).values(
                        status="cancelled",
                        cancelled_at=func.clock_timestamp(),
                        cancellation_reason="user_cancelled",
                    )
                )
                await session.execute(
                    update(MarketingContentItem).values(
                        content_revision=2, approved_revision=None, status="draft"
                    )
                )
            async with sessions.begin() as session:
                replay = await service(
                    session, workspace, actor, controls=SchedulingFeatureControls()
                ).activate(command)
                assert replay.id == job.id and replay.status == "cancelled"
                assert await counts(session) == (1, 1, 1)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        account_reads = [
            sql for sql in statements if "from social_account_connections" in sql
        ]
        assert account_reads
        assert all(
            "credential" not in sql and "provider_metadata" not in sql
            for sql in account_reads
        )

    asyncio.run(run())


@pytest.mark.parametrize("context", ["campaign", "content_override", "wrong_artist"])
def test_destination_artist_context(sessions, context):
    async def run():
        async with sessions.begin() as session:
            workspace, actor, command, activation = await prepare(session)
            campaign_artist = Artist(
                name="Campaign artist", organization_id=workspace.id
            )
            content_artist = Artist(name="Content artist", organization_id=workspace.id)
            session.add_all([campaign_artist, content_artist])
            await session.flush()
            item = await session.get(MarketingContentItem, command.content_item_id)
            campaign = await session.get(Campaign, item.campaign_id)
            campaign.primary_artist_id = campaign_artist.id
            expected_artist = campaign_artist.id
            if context == "content_override":
                item.artist_id = content_artist.id
                expected_artist = content_artist.id
            profile = ArtistProfile(
                artist_id=(
                    content_artist.id if context == "wrong_artist" else expected_artist
                ),
                universal_profile=UniversalProfile(
                    slug=f"artist-{uuid4()}", user=User(email=f"{uuid4()}@test.com")
                ),
            )
            session.add(profile)
            await session.flush()
            await session.execute(
                update(SocialAccountConnection)
                .where(SocialAccountConnection.id == activation.destination_id)
                .values(artist_profile_id=profile.id)
            )
        async with sessions.begin() as session:
            if context == "wrong_artist":
                with pytest.raises(
                    SchedulingActivationRejected, match="destination_mismatch"
                ):
                    await service(session, workspace, actor).activate(command)
            else:
                job = await service(session, workspace, actor).activate(command)
                assert job.effective_artist_id == expected_artist

    asyncio.run(run())


@pytest.mark.parametrize(
    "control,reason",
    [
        ("authoring_enabled", "authoring_disabled"),
        ("execution_enabled", "execution_disabled"),
        ("delivery_receiver_configured", "missing_durable_delivery_receiver"),
    ],
)
def test_controls_fail_closed(sessions, control, reason):
    async def run():
        async with sessions.begin() as session:
            workspace, actor, command, _ = await prepare(session)
        async with sessions.begin() as session:
            with pytest.raises(SchedulingActivationRejected, match=reason):
                await service(
                    session,
                    workspace,
                    actor,
                    controls=replace(ENABLED, **{control: False}),
                ).activate(command)
            assert await counts(session) == (0, 0, 0)

    asyncio.run(run())


def test_rejects_mismatched_job_time_snapshot(sessions, monkeypatch):
    original = scheduling_activation.evaluate_channel_eligibility

    def wrong_snapshot(**kwargs):
        result = original(**kwargs)
        return replace(
            result, scheduled_for=result.scheduled_for + timedelta(minutes=1)
        )

    monkeypatch.setattr(
        scheduling_activation, "evaluate_channel_eligibility", wrong_snapshot
    )

    async def run():
        async with sessions.begin() as session:
            workspace, actor, command, _ = await prepare(session)
        async with sessions.begin() as session:
            with pytest.raises(
                SchedulingActivationRejected, match="changed_schedule_generation"
            ):
                await service(session, workspace, actor).activate(command)
            assert await counts(session) == (0, 0, 0)

    asyncio.run(run())


@pytest.mark.parametrize("edit", ["time", "destination"])
def test_material_edit_requires_reapproval_and_wins_activation_race(sessions, edit):
    async def run():
        async with sessions.begin() as session:
            workspace, actor, command, _ = await prepare(session)
            editor, _ = await _seed_actor(
                session,
                workspace=workspace,
                email=f"{uuid4()}@test.com",
                capabilities=(Capability.marketing_content_edit.value,),
            )
            destination = SocialAccountConnection(
                organization_id=workspace.id,
                provider="instagram",
                status="connected",
                connection_method="direct_api",
                capabilities=["content_publish"],
            )
            session.add(destination)
        async with (
            sessions() as writer,
            sessions() as activator,
            sessions() as observer,
        ):
            # Prime a stale identity map before the editor acquires the parent lock.
            await activator.get(MarketingContentItem, command.content_item_id)
            await activator.get(MarketingContentItemChannel, command.channel_id)
            pid = await activator.scalar(text("select pg_backend_pid()"))
            if edit == "time":
                payload = content.MarketingContentChannelUpdate(
                    schedule_timezone="UTC", schedule_local_time="2030-01-15T12:00:00"
                )
            else:
                payload = content.MarketingContentChannelUpdate(
                    social_account_connection_id=destination.id
                )
            await content._update_channel(
                writer,
                workspace.id,
                command.content_item_id,
                command.channel_id,
                payload,
                actor=editor,
            )
            task = asyncio.create_task(
                service(activator, workspace, actor).activate(command)
            )
            await wait_until_blocked(observer, pid, task)
            await writer.commit()
            with pytest.raises(SchedulingActivationRejected):
                await task
            await activator.rollback()
        async with sessions() as session:
            item = await session.get(MarketingContentItem, command.content_item_id)
            channel = await session.get(MarketingContentItemChannel, command.channel_id)
            assert item.content_revision == 2 and item.approved_revision == 1
            assert item.status == "draft"
            # Even acknowledging the new generation/revision cannot bypass approval.
            with pytest.raises(SchedulingActivationRejected, match="stale_approval"):
                await service(session, workspace, actor).activate(
                    replace(
                        command,
                        expected_content_revision=item.content_revision,
                        expected_schedule_generation=channel.schedule_generation,
                    )
                )
            assert (await counts(session))[:2] == (0, 0)

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure,reason",
    [
        ("stale_approval", "stale_approval"),
        ("revoked_approval", "stale_approval"),
        ("contradictory_approval", "stale_approval"),
        ("missing_authority", "stale_approval"),
        ("missing_timezone", "timezone_required"),
        ("stale_revision", "stale_content_revision"),
        ("stale_generation", "changed_schedule_generation"),
        ("destination_mismatch", "destination_mismatch"),
        ("manual_only", "manual_delivery_required"),
        ("parent_only", "missing_schedule_intent"),
        ("missed_window", "missed_schedule_window"),
        ("wrong_channel", "channel_mismatch"),
    ],
)
def test_rejects_ineligible_intent_without_writes(sessions, failure, reason):
    async def run():
        async with sessions.begin() as session:
            workspace, actor, command, activation = await prepare(
                session, seconds_ago=3600 if failure == "missed_window" else -3600
            )
            item = await session.get(MarketingContentItem, command.content_item_id)
            channel = await session.get(MarketingContentItemChannel, command.channel_id)
            destination = await session.get(
                SocialAccountConnection, activation.destination_id
            )
            if failure == "stale_approval":
                item.approved_revision = None
            elif failure == "revoked_approval":
                session.add(
                    ApprovalDecision(
                        organization_id=workspace.id,
                        approval_request_id=activation.snapshot.approval_request_id,
                        actor_kind="user",
                        decision="invalidated",
                    )
                )
            elif failure == "contradictory_approval":
                other = ApprovalRequest(
                    organization_id=workspace.id,
                    resource_type="marketing_content_item",
                    resource_id=uuid4(),
                    resource_revision=1,
                    title="Other",
                    status="approved",
                )
                session.add(other)
                await session.flush()
                item.approval_request_id = other.id
            elif failure == "missing_authority":
                approval = await session.get(
                    ApprovalRequest, activation.snapshot.approval_request_id
                )
                approval.status = "cancelled"
            elif failure == "missing_timezone":
                channel.schedule_timezone = None
            elif failure == "stale_revision":
                command = replace(command, expected_content_revision=2)
            elif failure == "stale_generation":
                command = replace(command, expected_schedule_generation=2)
            elif failure == "destination_mismatch":
                destination.provider = "tiktok"
            elif failure == "manual_only":
                destination.capabilities = ["manual_publish"]
            elif failure == "parent_only":
                item.status = "scheduled"
                item.scheduled_at = channel.scheduled_at
                channel.scheduled_at = None
            elif failure == "wrong_channel":
                command = replace(command, channel_id=uuid4())
        async with sessions() as session:
            with pytest.raises(SchedulingActivationRejected) as caught:
                await service(session, workspace, actor).activate(command)
            assert reason in caught.value.reason_codes
            await session.rollback()
        async with sessions() as session:
            assert await counts(session) == (0, 0, 0)

    asyncio.run(run())


def test_duplicate_active_job_and_changed_replay_inputs(sessions):
    async def run():
        async with sessions.begin() as session:
            workspace, actor, command, _ = await prepare(session)
            await service(session, workspace, actor).activate(command)
        for retry in (
            replace(command, operation_id=uuid4()),
            replace(command, expected_schedule_generation=2),
        ):
            async with sessions() as session:
                with pytest.raises(SchedulingConflict):
                    await service(session, workspace, actor).activate(retry)
                await session.rollback()
        async with sessions() as session:
            assert await counts(session) == (1, 1, 1)

    asyncio.run(run())


@pytest.mark.parametrize(
    "kind", ["anonymous", "agent", "edit_only", "foreign_workspace"]
)
def test_requires_human_schedule_capability_and_workspace_scope(sessions, kind):
    async def run():
        async with sessions.begin() as session:
            workspace, actor, command, _ = await prepare(session)
            if kind == "anonymous":
                actor = None
            elif kind == "agent":
                actor = _agent_actor(actor)
            elif kind == "edit_only":
                actor, _ = await _seed_actor(
                    session,
                    workspace=workspace,
                    email=f"{uuid4()}@test.com",
                    capabilities=(Capability.marketing_content_edit.value,),
                )
            else:
                _, actor, _, _ = await prepare(session)
        async with sessions() as session:
            with pytest.raises(MarketingContentAuthorizationError):
                await service(session, workspace, actor).activate(command)
            assert await counts(session) == (0, 0, 0)

    asyncio.run(run())


def test_workspace_resource_and_destination_isolation(sessions):
    async def run():
        async with sessions.begin() as session:
            workspace, actor, command, _ = await prepare(session)
            other_workspace, other_actor, other_command, other_activation = (
                await prepare(session)
            )
            await session.execute(
                update(MarketingContentItemChannel)
                .where(MarketingContentItemChannel.id == command.channel_id)
                .values(social_account_connection_id=other_activation.destination_id)
            )
        async with sessions() as session:
            with pytest.raises(
                SchedulingActivationRejected, match="destination_mismatch"
            ):
                await service(session, workspace, actor).activate(command)
            await session.rollback()
            with pytest.raises(SchedulingConflict, match="Content not found"):
                await service(session, other_workspace, other_actor).activate(command)
            await session.rollback()
            await service(session, other_workspace, other_actor).activate(
                replace(other_command, operation_id=command.operation_id)
            )
            await session.commit()

    asyncio.run(run())


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
def test_public_boundary_rolls_back_after_outbox_failure(
    sessions, monkeypatch, failure
):
    original = RealtimePublisher.publish

    async def fail_after_write(self, **kwargs):
        await original(self, **kwargs)
        raise failure("injected outbox failure")

    monkeypatch.setattr(RealtimePublisher, "publish", fail_after_write)

    async def run():
        async with sessions.begin() as session:
            workspace, actor, command, _ = await prepare(session)
        async with sessions() as session:
            before = await intent(session, command)
            with pytest.raises(failure, match="injected"):
                await activate_channel_schedule(
                    session,
                    workspace.id,
                    command,
                    actor=actor,
                    controls=ENABLED,
                    lateness_window_seconds=300,
                )
            assert await counts(session) == (0, 0, 0)
            assert await intent(session, command) == before

    asyncio.run(run())


@pytest.mark.parametrize("same_operation", [True, False])
def test_concurrent_activation_serializes_and_emits_once(sessions, same_operation):
    async def run():
        async with sessions.begin() as session:
            workspace, actor, command, _ = await prepare(session)
        async with sessions() as first, sessions() as second, sessions() as observer:
            pid = await second.scalar(text("select pg_backend_pid()"))
            winner = await service(first, workspace, actor).activate(command)
            retry = (
                command if same_operation else replace(command, operation_id=uuid4())
            )
            task = asyncio.create_task(
                service(second, workspace, actor).activate(retry)
            )
            await wait_until_blocked(observer, pid, task)
            assert await counts(observer) == (0, 0, 0)
            await first.commit()
            if same_operation:
                assert (await task).id == winner.id
                await second.commit()
            else:
                with pytest.raises(SchedulingConflict):
                    await task
                await second.rollback()
        async with sessions() as session:
            assert await counts(session) == (1, 1, 1)

    asyncio.run(run())
