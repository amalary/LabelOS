"""Real PostgreSQL worker transactions, races and durable acceptance recovery."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from labelos_database.models import (
    ApprovalRequest,
    Artist,
    ArtistProfile,
    Campaign,
    MarketingContentItem,
    MarketingContentItemChannel,
    RealtimeEvent,
    SchedulingExecutionControl,
    SchedulingJob,
    SchedulingJobTransition,
    SocialAccountConnection,
    UniversalProfile,
    User,
)
from sqlalchemy import event, func, select, update

from labelos_api.repositories.scheduling import SchedulingConflict, SchedulingRepository
from labelos_api.scheduling.contracts import (
    RetryableUnavailable,
    SchedulingFeatureControls,
    TerminalRejected,
)
from labelos_api.scheduling.receivers import UnavailableDeliveryReceiver
from labelos_api.services.scheduling_handoff import accept_scheduling_handoff
from labelos_api.services.scheduling_processor import (
    ClaimedJob,
    SchedulingDueJobProcessor,
    SchedulingExecutionRefused,
    SchedulingWorker,
)
from test_scheduling_handoff_postgres import FakeDurableReceiver, inbox
from test_scheduling_handoff_postgres import sessions as handoff_sessions
from test_scheduling_repository import expire, repo, seed
from test_scheduling_repository import sessions as repository_sessions  # noqa: F401

ENABLED = SchedulingFeatureControls(
    execution_enabled=True, delivery_receiver_configured=True
)

sessions = handoff_sessions


class RecordingReceiver(FakeDurableReceiver):
    def __init__(self):
        self.requests = []
        self.receipts = []

    async def accept(self, session, request):
        self.requests.append(request)
        result = await super().accept(session, request)
        self.receipts.append(result.receipt)
        return result


def processor(sessions, workspace_id, **kwargs):
    options = dict(
        worker=SchedulingWorker(
            principal_id=uuid4(),
            instance_id=uuid4(),
            workspace_ids=frozenset({workspace_id}),
        ),
        controls=ENABLED,
        receiver=RecordingReceiver(),
        lateness_window_seconds=300,
        batch_size=10,
        lease_duration=timedelta(minutes=1),
    )
    options.update(kwargs)
    return SchedulingDueJobProcessor(sessions, **options)


async def ready(sessions, **kwargs):
    async with sessions.begin() as session:
        workspace, _, jobs = await seed(session, **kwargs)
        session.add(
            SchedulingExecutionControl(
                workspace_id=workspace.id, execution_enabled=True
            )
        )
        await session.execute(
            update(SocialAccountConnection).values(
                status="connected", capabilities=["content_publish"]
            )
        )
        for job in jobs:
            channel = await session.get(
                MarketingContentItemChannel, job.marketing_content_item_channel_id
            )
            channel.schedule_local_time = job.scheduled_for.replace(
                tzinfo=None
            ).isoformat()
            channel.schedule_offset_seconds = 0
        return workspace.id, jobs


async def reserve(runner, workspace_id):
    async with runner.sessions.begin() as session:
        await runner._lock_control(session, workspace_id)
        jobs = await repo(session, workspace_id).claim_batch(
            worker_id=runner.worker.worker_id,
            limit=runner.batch_size,
            lease_duration=runner.lease_duration,
        )
        return [ClaimedJob(job.id, job.fencing_token) for job in jobs]


@pytest.mark.parametrize(
    "gate", ["flag", "receiver", "unavailable", "database", "missing", "scope"]
)
def test_refuses_before_claiming(sessions, gate):
    async def run():
        workspace, jobs = await ready(sessions)
        runner = processor(sessions, workspace)
        if gate == "flag":
            runner.controls = SchedulingFeatureControls(
                delivery_receiver_configured=True
            )
        elif gate == "receiver":
            runner.receiver = None
        elif gate == "unavailable":
            runner.receiver = UnavailableDeliveryReceiver()
        elif gate == "scope":
            runner.worker = SchedulingWorker(
                principal_id=uuid4(), instance_id=uuid4(), workspace_ids=frozenset()
            )
        else:
            async with sessions.begin() as session:
                control = await session.get(SchedulingExecutionControl, workspace)
                if gate == "missing":
                    await session.delete(control)
                else:
                    control.execution_enabled = False
        with pytest.raises(SchedulingExecutionRefused):
            await runner.run(workspace)
        async with sessions() as session:
            job = await session.get(SchedulingJob, jobs[0].id)
            assert job.status == "pending" and job.fencing_token == 0

    asyncio.run(run())


def test_concurrent_bounded_processors_no_duplicate_acceptance(sessions):
    async def run():
        workspace, jobs = await ready(sessions, count=8)
        receiver = RecordingReceiver()
        runners = [
            processor(sessions, workspace, batch_size=3, receiver=receiver)
            for _ in range(2)
        ]
        results = await asyncio.gather(*(runner.run(workspace) for runner in runners))
        assert all(result.claimed == 3 for result in results)
        assert all(result.outcomes == {"handed_off": 3} for result in results)
        assert (await runners[0].run(workspace)).claimed == 2
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(inbox)) == 8
            saved = (await session.scalars(select(SchedulingJob))).all()
            assert all(job.status == "handed_off" for job in saved)
            assert len({job.handoff_receipt_id for job in saved}) == len(jobs)
            assert all(job.claimed_by is None for job in saved)
            items = (await session.scalars(select(MarketingContentItem))).all()
            assert all(item.status == "approved" for item in items)
            events = (await session.scalars(select(RealtimeEvent))).all()
            assert len(events) == 24
            assert {e.event_type for e in events} == {
                "marketing.scheduling_job.activated",
                "marketing.scheduling_job.claimed",
                "marketing.scheduling_job.handed_off",
            }
            history = (
                await session.scalars(
                    select(SchedulingJobTransition).where(
                        SchedulingJobTransition.operation == "accept_delivery"
                    )
                )
            ).all()
            assert len(history) == 8
            assert all(row.actor_kind == "worker" for row in history)

    asyncio.run(run())


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("revision", "stale_content_revision"),
        ("approval", "stale_approval"),
        ("approval_id", "stale_approval"),
        ("schedule", "changed_schedule_generation"),
        ("generation", "changed_schedule_generation"),
        ("timezone", "changed_schedule_generation"),
        ("missing_schedule", "missing_schedule_intent"),
        ("destination", "connection_unavailable"),
        ("provider", "destination_mismatch"),
        ("manual", "manual_delivery_required"),
        ("late", "missed_schedule_window"),
    ],
)
def test_revalidate_after_claim(sessions, mutation, reason):
    async def run():
        workspace, jobs = await ready(sessions)
        runner = processor(sessions, workspace)
        claim = (await reserve(runner, workspace))[0]
        async with sessions.begin() as session:
            if mutation == "revision":
                await session.execute(
                    update(MarketingContentItem).values(content_revision=2)
                )
            elif mutation == "approval":
                await session.execute(update(ApprovalRequest).values(status="rejected"))
            elif mutation == "approval_id":
                approval = ApprovalRequest(
                    organization_id=workspace,
                    resource_type="marketing_content_item",
                    resource_id=jobs[0].marketing_content_item_id,
                    resource_revision=1,
                    title="Replacement",
                    status="approved",
                )
                session.add(approval)
                await session.flush()
                await session.execute(
                    update(MarketingContentItem).values(approval_request_id=approval.id)
                )
            elif mutation == "destination":
                await session.execute(
                    update(SocialAccountConnection).values(status="disconnected")
                )
            elif mutation == "provider":
                await session.execute(
                    update(SocialAccountConnection).values(provider="tiktok")
                )
            elif mutation == "manual":
                await session.execute(
                    update(SocialAccountConnection).values(
                        capabilities=["manual_publish"]
                    )
                )
            elif mutation == "late":
                runner.window = 0
            else:
                values = {
                    "schedule": {
                        "scheduled_at": jobs[0].scheduled_for + timedelta(minutes=1)
                    },
                    "generation": {"schedule_generation": 2},
                    "timezone": {"schedule_timezone": "Etc/UTC"},
                    "missing_schedule": {"scheduled_at": None},
                }[mutation]
                await session.execute(
                    update(MarketingContentItemChannel).values(**values)
                )
        assert await runner.process_claim(workspace, claim) == reason
        assert not runner.receiver.requests
        async with sessions() as session:
            job = await session.get(SchedulingJob, claim.id)
            assert job.status == "blocked" and job.blocked_reason_code == reason
            assert await session.scalar(select(func.count()).select_from(inbox)) == 0

    asyncio.run(run())


def test_late_and_future_jobs_are_never_submitted(sessions):
    async def run():
        workspace, _ = await ready(sessions, seconds_ago=600)
        runner = processor(sessions, workspace)
        result = await runner.run(workspace)
        assert result.claimed == 0
        assert result.outcomes == {"missed_schedule_window": 1}
        future_workspace, _ = await ready(sessions, seconds_ago=-600)
        future = processor(sessions, future_workspace)
        assert (await future.run(future_workspace)).claimed == 0
        assert not runner.receiver.requests and not future.receiver.requests

    asyncio.run(run())


def test_expired_leases_and_stale_workers(sessions):
    async def run():
        workspace, _ = await ready(sessions)
        old = processor(sessions, workspace)
        claim = (await reserve(old, workspace))[0]
        async with sessions.begin() as session:
            await expire(session, claim.id)
        new = processor(sessions, workspace)
        new_claims = []
        original = new.process_claim

        async def capture(workspace, new_claim):
            new_claims.append(new_claim)
            with pytest.raises(SchedulingConflict):
                await old.process_claim(workspace, claim)
            return await original(workspace, new_claim)

        new.process_claim = capture
        result = await new.run(workspace)
        assert result.recovered == 1 and result.outcomes == {"handed_off": 1}
        assert new_claims[0].fencing_token > claim.fencing_token
        assert not old.receiver.requests
        async with sessions() as session:
            from labelos_api.scheduling.metrics import scheduling_metrics

            metrics = await scheduling_metrics(session, workspace)
            assert metrics["expired"] == metrics["requeued"] == 1
            assert metrics["handed_off"] == 1
            events = list(
                await session.scalars(
                    select(RealtimeEvent).where(
                        RealtimeEvent.event_type
                        == "marketing.scheduling_job.lease_expired"
                    )
                )
            )
            assert len(events) == 1

    asyncio.run(run())


def test_partial_failures_continue_and_known_nonacceptance_requeues(sessions, caplog):
    class Mixed(RecordingReceiver):
        async def accept(self, session, request):
            result = await super().accept(session, request)
            index = len(self.requests)
            if index == 1:
                raise RuntimeError("PRIVATE_COPY SECRET_TOKEN")
            if index == 2:
                return RetryableUnavailable()
            if index == 3:
                return TerminalRejected()
            return result

    async def run():
        workspace, _ = await ready(sessions, count=4)
        receiver = Mixed()
        runner = processor(sessions, workspace, receiver=receiver)
        result = await runner.run(workspace)
        assert result.outcomes == {
            "job_failed": 1,
            "delivery_unavailable": 1,
            "handoff_contract_violation": 1,
            "handed_off": 1,
        }
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(inbox)) == 1
            jobs = (await session.scalars(select(SchedulingJob))).all()
            assert sorted(job.status.value for job in jobs) == [
                "blocked",
                "claimed",
                "handed_off",
                "pending",
            ]
        first_retry = receiver.requests[1]
        assert (await runner.run(workspace)).outcomes == {"handed_off": 1}
        assert receiver.requests[-1] == first_retry

    with caplog.at_level("INFO"):
        asyncio.run(run())
    assert "PRIVATE_COPY" not in caplog.text and "SECRET_TOKEN" not in caplog.text
    metrics = [
        record for record in caplog.records if record.msg == "scheduling_batch_metrics"
    ]
    assert metrics[0].failed_count == 1
    assert metrics[0].job_gauges == dict(
        pending=1, due=1, claimed=1, blocked=1, handed_off=1, cancelled=0, superseded=0
    )
    assert metrics[0].retained_transition_totals == dict(requeued=1, expired=0)
    assert metrics[1].failed_count == 0
    processed = [
        record for record in caplog.records if record.msg == "scheduling_job_processed"
    ]
    assert all(record.correlation_id for record in processed)


def test_crash_between_receiver_and_job_write_rolls_back_then_reuses_envelope(
    sessions, monkeypatch
):
    async def run():
        workspace, _ = await ready(sessions)
        runner = processor(sessions, workspace)
        claim = (await reserve(runner, workspace))[0]
        original = SchedulingRepository.record_handoff_acceptance

        async def crash(*args, **kwargs):
            raise RuntimeError("simulated crash before local update")

        monkeypatch.setattr(SchedulingRepository, "record_handoff_acceptance", crash)
        with pytest.raises(RuntimeError):
            await runner.process_claim(workspace, claim)
        async with sessions.begin() as session:
            assert await session.scalar(select(func.count()).select_from(inbox)) == 0
            assert (await session.get(SchedulingJob, claim.id)).status == "claimed"
            assert (
                await session.scalar(select(func.count()).select_from(RealtimeEvent))
                == 2
            )
            await expire(session, claim.id)
        monkeypatch.setattr(SchedulingRepository, "record_handoff_acceptance", original)
        assert (await runner.run(workspace)).outcomes == {"handed_off": 1}
        assert runner.receiver.requests[0] == runner.receiver.requests[1]

    asyncio.run(run())


def test_lost_commit_acknowledgement_recovers_same_receipt(sessions):
    async def run():
        workspace, _ = await ready(sessions)
        runner = processor(sessions, workspace)
        claim = (await reserve(runner, workspace))[0]
        # Simulate loss of the response after PostgreSQL has committed.
        assert await runner.process_claim(workspace, claim) == "handed_off"
        original = runner.receiver.receipts[0]
        request = runner.receiver.requests[0]
        async with sessions.begin() as session:
            await session.execute(
                update(MarketingContentItem).values(content_revision=2)
            )
        assert await runner.process_claim(workspace, claim) == "handed_off"
        async with sessions.begin() as session:
            result = await accept_scheduling_handoff(
                repo(session, workspace),
                receiver=runner.receiver,
                request=request,
                expected_worker=runner.worker.worker_id,
                expected_fencing_token=claim.fencing_token,
                controls=ENABLED,
            )
            assert result.receipt == original
            job = await session.get(SchedulingJob, claim.id)
            assert job.handoff_receipt_id == original.delivery_request_id
            assert await session.scalar(select(func.count()).select_from(inbox)) == 1
        assert (await runner.run(workspace)).claimed == 0

    asyncio.run(run())


@pytest.mark.parametrize("change", ["approval", "schedule", "control"])
def test_invalidation_winning_lock_race_prevents_acceptance(sessions, change):
    async def run():
        workspace, _ = await ready(sessions)
        runner = processor(sessions, workspace)
        claim = (await reserve(runner, workspace))[0]
        async with sessions() as editor:
            if change == "control":
                await editor.execute(
                    update(SchedulingExecutionControl).values(execution_enabled=False)
                )
            else:
                # Same parent-first coordination order as application writers.
                await editor.execute(select(MarketingContentItem).with_for_update())
                if change == "approval":
                    await editor.execute(
                        update(ApprovalRequest).values(status="rejected")
                    )
                else:
                    await editor.execute(
                        update(MarketingContentItemChannel).values(
                            schedule_generation=2
                        )
                    )
            task = asyncio.create_task(runner.process_claim(workspace, claim))
            await asyncio.sleep(0.1)
            assert not task.done()
            await editor.commit()
            if change == "control":
                with pytest.raises(SchedulingExecutionRefused):
                    await task
            else:
                expected = (
                    "stale_approval"
                    if change == "approval"
                    else "changed_schedule_generation"
                )
                assert await task == expected
        assert not runner.receiver.requests

    asyncio.run(run())


def test_acceptance_wins_control_race_and_excludes_credential_columns(sessions):
    async def run():
        workspace, _ = await ready(sessions)
        entered, release = asyncio.Event(), asyncio.Event()

        class Pausing(RecordingReceiver):
            async def accept(self, session, request):
                entered.set()
                await release.wait()
                return await super().accept(session, request)

        runner = processor(sessions, workspace, receiver=Pausing())
        claim = (await reserve(runner, workspace))[0]
        statements = []
        engine = sessions.kw["bind"].sync_engine

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            task = asyncio.create_task(runner.process_claim(workspace, claim))
            await asyncio.wait_for(entered.wait(), 5)

            async def disable():
                async with sessions.begin() as session:
                    await session.execute(
                        update(SchedulingExecutionControl).values(
                            execution_enabled=False
                        )
                    )

            change = asyncio.create_task(disable())
            await asyncio.sleep(0.1)
            assert not change.done()
            release.set()
            assert await task == "handed_off"
            await change
        finally:
            event.remove(engine, "before_cursor_execute", record)
        account_queries = [
            sql
            for sql in statements
            if sql.startswith("SELECT") and "FROM social_account_connections" in sql
        ]
        assert account_queries
        assert all(
            "credential" not in sql and "metadata" not in sql for sql in account_queries
        )
        # Locked context reuse keeps approval evidence loading constant per job.
        approval_queries = [
            sql for sql in statements if "FROM approval_requests" in sql
        ]
        assert len(approval_queries) <= 3

    asyncio.run(run())


@pytest.mark.parametrize("expires", ["lease", "lateness"])
def test_expiration_during_receiver_rolls_back_acceptance(sessions, expires):
    class Slow(RecordingReceiver):
        async def accept(self, session, request):
            result = await super().accept(session, request)
            await session.execute(select(func.pg_sleep(1.1)))
            return result

    async def run():
        workspace, _ = await ready(sessions, seconds_ago=0)
        runner = processor(
            sessions,
            workspace,
            receiver=Slow(),
            lease_duration=timedelta(seconds=1 if expires == "lease" else 60),
            lateness_window_seconds=1 if expires == "lateness" else 300,
        )
        claim = (await reserve(runner, workspace))[0]
        if expires == "lease":
            with pytest.raises(SchedulingConflict):
                await runner.process_claim(workspace, claim)
        else:
            assert (
                await runner.process_claim(workspace, claim) == "missed_schedule_window"
            )
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(inbox)) == 0
            job = await session.get(SchedulingJob, claim.id)
            assert job.handoff_receipt_id is None
            assert job.status == ("claimed" if expires == "lease" else "blocked")

    asyncio.run(run())


def test_destination_artist_mapping_is_reloaded(sessions):
    async def run():
        async with sessions.begin() as session:
            workspace, activations, _ = await seed(session, activate=False)
            artist = Artist(organization_id=workspace.id, name="Authorized artist")
            other = Artist(organization_id=workspace.id, name="Other artist")
            session.add_all([artist, other])
            await session.flush()
            await session.execute(update(Campaign).values(primary_artist_id=artist.id))
            profile = ArtistProfile(
                artist_id=artist.id,
                universal_profile=UniversalProfile(
                    slug=f"artist-{uuid4()}", user=User(email=f"{uuid4()}@test.com")
                ),
            )
            session.add(profile)
            await session.flush()
            await session.execute(
                update(SocialAccountConnection).values(
                    artist_profile_id=profile.id,
                    status="connected",
                    capabilities=["content_publish"],
                )
            )
            activation = replace(activations[0], effective_artist_id=artist.id)
            job = await repo(session, workspace.id).create_pending_job(activation)
            channel = await session.get(
                MarketingContentItemChannel, job.marketing_content_item_channel_id
            )
            channel.schedule_local_time = job.scheduled_for.replace(
                tzinfo=None
            ).isoformat()
            channel.schedule_offset_seconds = 0
            session.add(
                SchedulingExecutionControl(
                    workspace_id=workspace.id, execution_enabled=True
                )
            )
        runner = processor(sessions, workspace.id)
        claim = (await reserve(runner, workspace.id))[0]
        async with sessions.begin() as session:
            await session.execute(
                update(ArtistProfile)
                .where(ArtistProfile.id == profile.id)
                .values(artist_id=other.id)
            )
        assert await runner.process_claim(workspace.id, claim) == "destination_mismatch"
        assert not runner.receiver.requests

    asyncio.run(run())


def test_unknown_commit_outcome_never_requeues_accepted_job(sessions):
    async def run():
        workspace, _ = await ready(sessions)
        runner = processor(sessions, workspace)
        original = runner.process_claim
        claims = []

        async def lose_ack(workspace_id, claim):
            claims.append(claim)
            await original(workspace_id, claim)
            raise RuntimeError("commit acknowledgement lost")

        runner.process_claim = lose_ack
        assert (await runner.run(workspace)).outcomes == {"job_failed": 1}
        assert (await runner.run(workspace)).claimed == 0
        receipt = runner.receiver.receipts[0]
        assert await original(workspace, claims[0]) == "handed_off"
        async with sessions() as session:
            job = await session.get(SchedulingJob, claims[0].id)
            assert job.handoff_receipt_id == receipt.delivery_request_id
            assert job.status == "handed_off"
            assert await session.scalar(select(func.count()).select_from(inbox)) == 1
        assert len(runner.receiver.requests) == 1

    asyncio.run(run())


@pytest.mark.parametrize("invalid", ["stale", "late"])
def test_expired_invalid_claims_are_blocked_during_recovery(sessions, invalid):
    async def run():
        workspace, _ = await ready(sessions)
        runner = processor(sessions, workspace)
        claim = (await reserve(runner, workspace))[0]
        async with sessions.begin() as session:
            await expire(session, claim.id)
            if invalid == "stale":
                await session.execute(
                    update(MarketingContentItem).values(content_revision=2)
                )
        if invalid == "late":
            runner.window = 0
        reason = (
            "stale_content_revision" if invalid == "stale" else "missed_schedule_window"
        )
        result = await runner.run(workspace)
        assert result.recovered == 1 and result.claimed == 0
        assert result.outcomes == {reason: 1}
        assert not runner.receiver.requests
        async with sessions() as session:
            job = await session.get(SchedulingJob, claim.id)
            assert job.status == "blocked" and job.blocked_reason_code == reason
            assert job.fencing_token > claim.fencing_token

    asyncio.run(run())
