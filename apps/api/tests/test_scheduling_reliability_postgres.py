"""Rollout regressions using real PostgreSQL transactions and separate workers."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from labelos_database.models import (
    ApprovalRequest,
    MarketingContentItem,
    MarketingContentItemChannel,
    RealtimeEvent,
    SchedulingExecutionControl,
    SchedulingJob,
    SchedulingJobTransition,
)
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from labelos_api.repositories import marketing_content
from labelos_api.repositories.scheduling import SchedulingConflict
from labelos_api.scheduling.contracts import RetryableUnavailable
from labelos_api.services.scheduling_activation import SchedulingActivationRejected
from test_marketing_content_postgres import wait_until_blocked
from test_scheduling_activation import counts, prepare, service
from test_scheduling_processor_postgres import (
    RecordingReceiver,
    processor,
    ready,
    reserve,
)
from test_scheduling_processor_postgres import sessions as sessions
from test_scheduling_repository import claim, expire, repo
from test_scheduling_repository import sessions as repository_sessions  # noqa: F401


class Unavailable(RecordingReceiver):
    async def accept(self, session, request):
        self.requests.append(request)
        return RetryableUnavailable()


def test_availability_budget_survives_distinct_workers_and_duplicate_sweeps(sessions):
    async def run():
        workspace, jobs = await ready(sessions)
        receiver = Unavailable()
        for expected in (
            "delivery_unavailable",
            "delivery_unavailable",
            "missing_durable_delivery_receiver",
        ):
            runner = processor(sessions, workspace, receiver=receiver)
            assert (await runner.run(workspace)).outcomes == {expected: 1}
        results = await asyncio.gather(
            *[
                processor(sessions, workspace, receiver=receiver).run(workspace)
                for _ in range(4)
            ]
        )
        assert all(result.claimed == 0 for result in results)
        assert len(receiver.requests) == 3
        assert all(request == receiver.requests[0] for request in receiver.requests)
        async with sessions() as session:
            job = await session.get(SchedulingJob, jobs[0].id)
            assert job.status == "blocked" and job.handoff_receipt_id is None
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(RealtimeEvent)
                    .where(
                        RealtimeEvent.event_type
                        == "marketing.scheduling_job.handoff_unavailable"
                    )
                )
                == 3
            )
        async with sessions.begin() as session:
            await repo(session, workspace).apply_user_transition(
                jobs[0].id,
                operation="revalidate",
                operation_id=uuid4(),
                actor_key="user",
            )
        assert (await runner.run(workspace)).outcomes == {
            "missing_durable_delivery_receiver": 1
        }
        assert len(receiver.requests) == 4  # One explicit probe, no new retry budget.

    asyncio.run(run())


def test_rolled_back_unavailability_does_not_consume_retry_budget(sessions):
    async def run():
        workspace, jobs = await ready(sessions)
        receiver = Unavailable()
        runner = processor(sessions, workspace, receiver=receiver)
        original = runner.process_claim
        # Outer transaction loss discards both the requeue and its retry evidence.
        from labelos_api.repositories.scheduling import RetryableInternalFailure

        reserved = (await reserve(runner, workspace))[0]
        async with sessions() as session:
            await repo(session, workspace).requeue_retryable_failure(
                reserved.id,
                expected_worker=runner.worker.worker_id,
                expected_fencing_token=reserved.fencing_token,
                failure=RetryableInternalFailure.delivery_unavailable,
            )
            await session.rollback()
        assert await original(workspace, reserved) == "delivery_unavailable"
        assert (await runner.run(workspace)).outcomes == {"delivery_unavailable": 1}
        assert (await runner.run(workspace)).outcomes == {
            "missing_durable_delivery_receiver": 1
        }
        async with sessions() as session:
            assert (await session.get(SchedulingJob, jobs[0].id)).status == "blocked"
        assert len(receiver.requests) == 3

    asyncio.run(run())


@pytest.mark.parametrize("seconds_ago", [0, 1, 299, 301])
def test_legacy_overdue_activation_has_no_lateness_grace(sessions, seconds_ago):
    async def run():
        async with sessions.begin() as session:
            workspace, actor, command, _ = await prepare(
                session, seconds_ago=seconds_ago
            )
        async with sessions() as session:
            with pytest.raises(
                SchedulingActivationRejected, match="missed_schedule_window"
            ):
                await service(session, workspace, actor).activate(command)
            await session.rollback()
        async with sessions() as session:
            assert await counts(session) == (0, 0, 0)

    asyncio.run(run())


@pytest.mark.parametrize(
    "local_time,instant,reason",
    [
        (
            "2099-03-08T02:30:00",
            datetime(2099, 3, 8, 7, 30, tzinfo=UTC),
            "nonexistent_local_time",
        ),
        (
            "2099-11-01T01:30:00",
            datetime(2099, 11, 1, 5, 30, tzinfo=UTC),
            "disambiguation_required",
        ),
    ],
)
def test_legacy_dst_requires_valid_explicit_resolution(
    sessions, local_time, instant, reason
):
    async def run():
        async with sessions.begin() as session:
            workspace, actor, command, _ = await prepare(session)
            await session.execute(
                update(MarketingContentItemChannel).values(
                    scheduled_at=instant,
                    schedule_local_time=local_time,
                    schedule_timezone="America/New_York",
                    schedule_offset_seconds=None,
                )
            )
        async with sessions() as session:
            with pytest.raises(SchedulingActivationRejected, match=reason):
                await service(session, workspace, actor).activate(command)
            await session.rollback()
        async with sessions() as session:
            assert await counts(session) == (0, 0, 0)

    asyncio.run(run())


def test_enabled_sweeps_never_adopt_legacy_planning_rows(sessions):
    async def run():
        async with sessions.begin() as session:
            workspace, actor, command, _ = await prepare(session)
            session.add(
                SchedulingExecutionControl(
                    workspace_id=workspace.id, execution_enabled=True
                )
            )
        runner = processor(sessions, workspace.id)
        assert (await runner.run(workspace.id)).claimed == 0
        async with sessions.begin() as session:
            assert await counts(session) == (0, 0, 0)
            job = await service(session, workspace, actor).activate(command)
            assert job.created_by_user_id == actor.id
        # Authorizing activation still does not make a future job due.
        assert (await runner.run(workspace.id)).claimed == 0
        assert not runner.receiver.requests

    asyncio.run(run())


@pytest.mark.parametrize("invalid", ["unapproved", "destinationless"])
def test_legacy_activation_requires_current_approval_and_destination(sessions, invalid):
    async def run():
        async with sessions.begin() as session:
            workspace, actor, command, _ = await prepare(session)
            if invalid == "unapproved":
                await session.execute(
                    update(ApprovalRequest).values(status="in_review")
                )
            else:
                await session.execute(
                    update(MarketingContentItemChannel).values(
                        social_account_connection_id=None
                    )
                )
        async with sessions() as session:
            with pytest.raises(SchedulingActivationRejected) as caught:
                await service(session, workspace, actor).activate(command)
            assert (
                "stale_approval"
                if invalid == "unapproved"
                else "connection_unavailable"
            ) in caught.value.reason_codes
            await session.rollback()
        async with sessions() as session:
            assert await counts(session) == (0, 0, 0)

    asyncio.run(run())


@pytest.mark.parametrize("change", ["cancel", "edit", "approval"])
@pytest.mark.parametrize("claim_first", [False, True])
def test_mutation_versus_claim_serializes(sessions, change, claim_first):
    async def run():
        workspace, jobs = await ready(sessions)
        job = jobs[0]
        runner = processor(sessions, workspace)

        async def mutate(session):
            if change == "cancel":
                await repo(session, workspace).apply_user_transition(
                    job.id, operation="cancel", operation_id=uuid4(), actor_key="user"
                )
            else:
                await session.execute(
                    select(MarketingContentItem)
                    .where(MarketingContentItem.id == job.marketing_content_item_id)
                    .with_for_update()
                )
                if change == "edit":
                    await session.execute(
                        update(MarketingContentItem)
                        .where(MarketingContentItem.id == job.marketing_content_item_id)
                        .values(content_revision=2)
                    )
                else:
                    await session.execute(
                        update(ApprovalRequest)
                        .where(ApprovalRequest.id == job.approval_request_id)
                        .values(status="cancelled")
                    )

        async with sessions() as editor, sessions() as worker, sessions() as observer:
            if claim_first:
                claims = await repo(worker, workspace).claim_batch(
                    worker_id=runner.worker.worker_id,
                    limit=1,
                    lease_duration=runner.lease_duration,
                )
                assert len(claims) == 1
                pid = await editor.scalar(text("SELECT pg_backend_pid()"))
                task = asyncio.create_task(mutate(editor))
                await wait_until_blocked(observer, pid, task)
                await worker.commit()
                await task
                await editor.commit()
            else:
                await mutate(editor)
                # SKIP LOCKED must finish while the editor still holds its locks.
                assert await asyncio.wait_for(claim(worker, workspace), 3) == ()
                await worker.commit()
                await editor.commit()
        if claim_first and change != "cancel":
            async with sessions.begin() as session:
                await expire(session, job.id)
        await runner.run(workspace)
        assert not runner.receiver.requests
        async with sessions() as session:
            current = await session.get(SchedulingJob, job.id)
            assert current.status == ("cancelled" if change == "cancel" else "blocked")

    asyncio.run(run())


@pytest.mark.parametrize("claim_first", [False, True])
def test_channel_removal_racing_claim_preserves_history_on_rollback(
    sessions, claim_first
):
    async def run():
        workspace, jobs = await ready(sessions)
        job = jobs[0]
        async with sessions() as worker, sessions() as editor, sessions() as observer:
            if claim_first:
                assert len(await claim(worker, workspace)) == 1
                pid = await editor.scalar(text("SELECT pg_backend_pid()"))
                task = asyncio.create_task(
                    marketing_content.delete_channel(
                        editor, job.marketing_content_item_channel_id
                    )
                )
                await wait_until_blocked(observer, pid, task)
                await worker.commit()
            else:
                await editor.execute(
                    select(MarketingContentItem)
                    .where(MarketingContentItem.id == job.marketing_content_item_id)
                    .with_for_update()
                )
                assert await asyncio.wait_for(claim(worker, workspace), 3) == ()
                await worker.commit()
                task = asyncio.create_task(
                    marketing_content.delete_channel(
                        editor, job.marketing_content_item_channel_id
                    )
                )
            # Referenced channels cannot yet be physically removed. The failed
            # command must roll back, preserving the original approved intent.
            with pytest.raises(IntegrityError):
                await task
            await editor.rollback()
            if not claim_first:
                assert len(await claim(worker, workspace)) == 1
                await worker.commit()
        async with sessions.begin() as session:
            assert await session.get(
                MarketingContentItemChannel, job.marketing_content_item_channel_id
            )
            assert (await session.get(SchedulingJob, job.id)).status == "claimed"
            assert (
                await session.scalar(
                    select(func.count()).select_from(SchedulingJobTransition)
                )
                == 2
            )

    asyncio.run(run())


def test_crash_before_handoff_and_wrong_workspace_cannot_accept(sessions):
    async def run():
        workspace, _ = await ready(sessions)
        other, _ = await ready(sessions)
        crashed = processor(sessions, workspace)
        reserved = (await reserve(crashed, workspace))[0]
        # Crash before any receiver call; another authorized workspace cannot
        # process the opaque claim even if it knows the job UUID and fence.
        foreign = processor(sessions, other)
        with pytest.raises(SchedulingConflict):
            await foreign.process_claim(other, reserved)
        async with sessions.begin() as session:
            await expire(session, reserved.id)
        replacement = processor(sessions, workspace)
        assert (await replacement.run(workspace)).outcomes == {"handed_off": 1}
        assert not crashed.receiver.requests and not foreign.receiver.requests

    asyncio.run(run())


def test_large_backlog_is_bounded_and_drained_without_cross_workspace_work(sessions):
    async def run():
        workspace, jobs = await ready(sessions, count=61)
        other, untouched = await ready(sessions, count=3)
        runner = processor(sessions, workspace, batch_size=25)
        results = [await runner.run(workspace) for _ in range(4)]
        assert [result.claimed for result in results] == [25, 25, 11, 0]
        assert len(runner.receiver.requests) == len(jobs)
        assert (
            len({request.idempotency_key for request in runner.receiver.requests}) == 61
        )
        async with sessions() as session:
            remaining = list(
                await session.scalars(
                    select(SchedulingJob).where(SchedulingJob.workspace_id == other)
                )
            )
            assert {job.id for job in remaining} == {job.id for job in untouched}
            assert all(
                job.status == "pending" and job.fencing_token == 0 for job in remaining
            )

    asyncio.run(run())
