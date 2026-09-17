"""Real PostgreSQL transactions; each test uses an isolated disposable schema."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from labelos_database.base import Base
from labelos_database.models import (
    ApprovalDecision,
    ApprovalRequest,
    Campaign,
    MarketingContentItem,
    MarketingContentItemChannel,
    Organization,
    SchedulingJob,
    SchedulingJobTransition,
    SocialAccountConnection,
    User,
)
from labelos_database.scheduling import SchedulingBlockedReason as Reason
from labelos_database.scheduling import SchedulingJobStatus as Status
from sqlalchemy import (
    Column,
    MetaData,
    String,
    Table,
    event,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.ext.asyncio import async_sessionmaker

from labelos_api.repositories.scheduling import (
    JobActivation,
    RetryableInternalFailure,
    SchedulingConflict,
    SchedulingRepository,
    snapshot_for,
)
from labelos_api.scheduling.contracts import (
    DeliveryAcceptanceReceipt,
    DeliveryAcceptanceRequest,
    ScheduleSnapshot,
)

# Test-only transactional receiver storage, not a production Delivery inbox.
inbox = Table(
    "test_delivery_inbox",
    MetaData(),
    Column("key", String, primary_key=True),
    Column("fingerprint", String),
)


@pytest.fixture
def sessions(postgres_test_engine):
    async def prepare():
        async with postgres_test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(inbox.metadata.create_all)

    asyncio.run(prepare())
    return async_sessionmaker(postgres_test_engine, expire_on_commit=False)


def repo(session, workspace_id, window=300):
    return SchedulingRepository(session, workspace_id, lateness_window_seconds=window)


async def seed(session, *, count=1, seconds_ago=10, workspace=None, activate=True):
    if workspace is None:
        workspace = Organization(
            name="Scheduling", slug=uuid4().hex, owner=User(email=f"{uuid4()}@test.com")
        )
        session.add(workspace)
        await session.flush()
    owner_id = workspace.owner_user_id
    now = await session.scalar(select(func.clock_timestamp()))
    activations, jobs = [], []
    for _ in range(count):
        destination = SocialAccountConnection(
            organization_id=workspace.id, provider="instagram"
        )
        session.add(destination)
        await session.flush()
        channel = MarketingContentItemChannel(
            channel="instagram",
            scheduled_at=now - timedelta(seconds=seconds_ago),
            schedule_timezone="UTC",
            social_account_connection_id=destination.id,
        )
        item = MarketingContentItem(
            organization_id=workspace.id,
            campaign=Campaign(name="Launch", organization_id=workspace.id),
            title="Post",
            content_type="image",
            status="approved",
            approved_revision=1,
            channels=[channel],
        )
        session.add(item)
        await session.flush()
        approval = ApprovalRequest(
            organization_id=workspace.id,
            resource_type="marketing_content_item",
            resource_id=item.id,
            resource_revision=1,
            title="Approved",
            status="approved",
        )
        session.add(approval)
        await session.flush()
        item.approval_request_id = approval.id
        await session.flush()
        activation = JobActivation(
            snapshot=ScheduleSnapshot(
                workspace_id=workspace.id,
                content_item_id=item.id,
                channel_id=channel.id,
                content_revision=1,
                approval_request_id=approval.id,
                schedule_generation=1,
                scheduled_for=channel.scheduled_at,
            ),
            operation_id=uuid4(),
            created_by_user_id=owner_id,
            schedule_timezone="UTC",
            destination_id=destination.id,
            effective_artist_id=None,
        )
        activations.append(activation)
        if activate:
            jobs.append(
                await repo(session, workspace.id).create_pending_job(activation)
            )
    return workspace, activations, jobs


async def claim(session, workspace_id, worker="worker:a", limit=100):
    return await repo(session, workspace_id).claim_batch(
        worker_id=worker, limit=limit, lease_duration=timedelta(minutes=1)
    )


async def expire(session, job_id):
    now = await session.scalar(select(func.clock_timestamp()))
    await session.execute(
        update(SchedulingJob)
        .where(SchedulingJob.id == job_id)
        .values(
            claimed_at=now - timedelta(minutes=2),
            claim_expires_at=now - timedelta(seconds=1),
        )
    )


def envelope(job):
    request = DeliveryAcceptanceRequest(
        snapshot=snapshot_for(job),
        job_id=job.id,
        destination_id=job.social_account_connection_id,
        artist_profile_id=None,
        authoring_timezone=job.schedule_timezone,
        payload_fingerprint="test-fingerprint",
        payload_schema_version=1,
        canonical_payload=b'{"caption":"approved"}',
    )
    receipt = DeliveryAcceptanceReceipt(
        delivery_request_id=uuid4(),
        idempotency_key=job.idempotency_key,
        payload_fingerprint=request.payload_fingerprint,
    )
    return request, receipt


def test_simultaneous_workers_skip_locks_and_never_duplicate(sessions):
    async def run():
        async with sessions.begin() as session:
            workspace, _, jobs = await seed(session, count=8)
        async with sessions() as first, sessions() as second:
            left = await claim(first, workspace.id, limit=3)
            # First transaction deliberately holds all its locks. Second must
            # finish before first commits, proving SKIP LOCKED actually operates.
            right = await asyncio.wait_for(
                claim(second, workspace.id, "worker:b", 3), 3
            )
            assert len(left) == len(right) == 3
            assert {j.id for j in left}.isdisjoint(j.id for j in right)
            await asyncio.gather(first.commit(), second.commit())

        async def worker(name):
            async with sessions.begin() as session:
                return {j.id for j in await claim(session, workspace.id, name, 3)}

        a, b = await asyncio.gather(worker("worker:c"), worker("worker:d"))
        assert a.isdisjoint(b)
        assert len(a | b) == 2
        assert len({j.id for j in left + right} | a | b) == len(jobs)
        async with sessions() as session:
            assert await claim(session, workspace.id) == ()
            transitions = (
                await session.scalars(
                    select(SchedulingJobTransition).where(
                        SchedulingJobTransition.operation == "claim"
                    )
                )
            ).all()
            assert len(transitions) == 8

    asyncio.run(run())


def test_concurrent_idempotency_and_active_uniqueness(sessions):
    async def run():
        async with sessions.begin() as session:
            workspace, activations, _ = await seed(session, activate=False)
        activation = activations[0]

        async def activate(value):
            async with sessions.begin() as session:
                return (await repo(session, workspace.id).create_pending_job(value)).id

        ids = await asyncio.gather(*(activate(activation) for _ in range(4)))
        assert len(set(ids)) == 1
        async with sessions.begin() as session:
            repository = repo(session, workspace.id)
            with pytest.raises(SchedulingConflict):
                await repository.create_pending_job(
                    replace(activation, operation_id=uuid4())
                )
            with pytest.raises(SchedulingConflict):
                await repository.find_existing_job(
                    replace(activation, schedule_timezone="Etc/UTC")
                )
            await repository.cancel_pending_job(ids[0], actor_key="user:test")
            assert (await repository.create_pending_job(activation)).id == ids[0]
            replacement = replace(activation, operation_id=uuid4())
            successor = await repository.create_pending_job(replacement)
            assert successor.id != ids[0]
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(SchedulingJob))
                == 2
            )

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["block", "supersede", "retry", "handoff"])
@pytest.mark.parametrize("bad_lease", ["expired", "worker", "fence", "reclaimed"])
def test_every_claimed_transition_rejects_stale_workers(sessions, operation, bad_lease):
    async def run():
        async with sessions.begin() as session:
            workspace, _, jobs = await seed(session)
            job = (await claim(session, workspace.id))[0]
            token = job.fencing_token
            request, receipt = envelope(job)
        if bad_lease in ("expired", "reclaimed"):
            async with sessions.begin() as session:
                await expire(session, job.id)
        if bad_lease == "reclaimed":
            async with sessions.begin() as session:
                recovered = await repo(session, workspace.id).recover_expired_leases(
                    worker_id="recovery", limit=1
                )
                assert recovered[0].fencing_token > token
            async with sessions.begin() as session:
                claimed = (await claim(session, workspace.id, "worker:b"))[0]
                assert claimed.fencing_token > recovered[0].fencing_token
        async with sessions.begin() as session:
            repository = repo(session, workspace.id)
            kwargs = dict(
                expected_worker="wrong" if bad_lease == "worker" else "worker:a",
                expected_fencing_token=token + 10 if bad_lease == "fence" else token,
            )
            with pytest.raises(SchedulingConflict):
                if operation == "block":
                    await repository.block_job(
                        job.id,
                        reason=Reason.stale_approval,
                        actor_key="worker:a",
                        **kwargs,
                    )
                elif operation == "supersede":
                    await repository.supersede_active_job(
                        job.id, actor_key="worker:a", **kwargs
                    )
                elif operation == "retry":
                    await repository.requeue_retryable_failure(
                        job.id,
                        failure=RetryableInternalFailure.database_contention,
                        **kwargs,
                    )
                else:
                    await repository.record_handoff_acceptance(
                        job.id, request=request, receipt=receipt, **kwargs
                    )
            current = await repository.get_job(job.id)
            assert current.status == Status.claimed
            assert current.fencing_token == (
                claimed.fencing_token if bad_lease == "reclaimed" else token
            )

    asyncio.run(run())


def test_future_late_terminal_and_blocked_jobs_are_not_claimed(sessions):
    async def run():
        async with sessions.begin() as session:
            workspace, _, current = await seed(session)
            _, _, future = await seed(session, workspace=workspace, seconds_ago=-3600)
            _, _, late = await seed(session, workspace=workspace, seconds_ago=3600)
            _, _, cancelled = await seed(session, workspace=workspace)
            _, _, superseded = await seed(session, workspace=workspace)
            _, _, blocked = await seed(session, workspace=workspace)
            repository = repo(session, workspace.id)
            await repository.cancel_pending_job(cancelled[0].id, actor_key="user")
            await repository.supersede_active_job(superseded[0].id, actor_key="user")
            await repository.block_job(
                blocked[0].id, reason=Reason.stale_approval, actor_key="user"
            )
        async with sessions.begin() as session:
            repository = repo(session, workspace.id)
            assert {j.id for j in await repository.find_due_pending_jobs()} == {
                current[0].id,
                late[0].id,
            }
            assert [j.id for j in await claim(session, workspace.id)] == [current[0].id]
            assert (await repository.get_job(future[0].id)).status == Status.pending
            missed = await repository.get_job(late[0].id)
            assert missed.status == Status.blocked
            assert missed.blocked_reason_code == Reason.missed_schedule_window
            assert missed.blocked_metadata["lateness_window_seconds"] == 300
            assert (
                await repository.find_active_job(
                    blocked[0].marketing_content_item_channel_id
                )
            ).id == blocked[0].id

    asyncio.run(run())


@pytest.mark.parametrize(
    "drift,reason",
    [
        ("revision", Reason.stale_content_revision),
        ("approved_revision", Reason.stale_approval),
        ("approval_pointer", Reason.stale_approval),
        ("approval_status", Reason.stale_approval),
        ("invalidation", Reason.stale_approval),
        ("new_request", Reason.stale_approval),
        ("generation", Reason.changed_schedule_generation),
        ("instant", Reason.changed_schedule_generation),
        ("timezone", Reason.changed_schedule_generation),
        ("missing_intent", Reason.missing_schedule_intent),
        ("destination", Reason.destination_mismatch),
        ("parent_status", Reason.ineligible_parent_state),
    ],
)
def test_drift_is_detected_and_blocked_before_claim(sessions, drift, reason):
    async def run():
        async with sessions.begin() as session:
            workspace, _, jobs = await seed(session)
            job = jobs[0]
        async with sessions.begin() as session:
            item = await session.get(
                MarketingContentItem, job.marketing_content_item_id
            )
            channel = await session.get(
                MarketingContentItemChannel, job.marketing_content_item_channel_id
            )
            approval = await session.get(ApprovalRequest, job.approval_request_id)
            if drift == "revision":
                item.content_revision += 1
            elif drift == "approved_revision":
                item.approved_revision = None
            elif drift == "approval_pointer":
                other = ApprovalRequest(
                    organization_id=workspace.id,
                    resource_type="marketing_content_item",
                    resource_id=item.id,
                    resource_revision=2,
                    title="Other revision",
                    status="approved",
                )
                session.add(other)
                await session.flush()
                item.approval_request_id = other.id
            elif drift == "approval_status":
                approval.status = "rejected"
            elif drift == "invalidation":
                session.add(
                    ApprovalDecision(
                        approval_request_id=approval.id,
                        organization_id=workspace.id,
                        decision="invalidated",
                        actor_kind="system",
                    )
                )
            elif drift == "new_request":
                session.add(
                    ApprovalRequest(
                        organization_id=workspace.id,
                        resource_type="marketing_content_item",
                        resource_id=item.id,
                        resource_revision=1,
                        title="New active authority",
                        status="requested",
                    )
                )
            elif drift == "generation":
                channel.schedule_generation += 1
            elif drift == "instant":
                channel.scheduled_at += timedelta(seconds=1)
            elif drift == "timezone":
                channel.schedule_timezone = "Etc/UTC"
            elif drift == "missing_intent":
                channel.scheduled_at = None
            elif drift == "destination":
                channel.social_account_connection_id = None
            elif drift == "parent_status":
                item.status = "archived"
        async with sessions.begin() as session:
            repository = repo(session, workspace.id)
            assert await repository.detect_stale_job(job.id) == reason
            assert await claim(session, workspace.id) == ()
            assert (await repository.get_job(job.id)).blocked_reason_code == reason

    asyncio.run(run())


def test_recovery_is_bounded_and_retry_invalidates_old_token(sessions):
    async def run():
        async with sessions.begin() as session:
            workspace, _, _ = await seed(session, count=4)
            jobs = await claim(session, workspace.id)
        async with sessions.begin() as session:
            for job in jobs[:3]:
                await expire(session, job.id)
        async with sessions() as first, sessions() as second:
            a = await repo(first, workspace.id).recover_expired_leases(
                worker_id="r1", limit=2
            )
            b = await asyncio.wait_for(
                repo(second, workspace.id).recover_expired_leases(
                    worker_id="r2", limit=2
                ),
                3,
            )
            assert len(a) == 2 and len(b) == 1
            assert {j.id for j in a}.isdisjoint(j.id for j in b)
            await asyncio.gather(first.commit(), second.commit())
        async with sessions.begin() as session:
            repository = repo(session, workspace.id)
            job = await repository.requeue_retryable_failure(
                jobs[3].id,
                expected_worker="worker:a",
                expected_fencing_token=jobs[3].fencing_token,
                failure=RetryableInternalFailure.database_contention,
            )
            assert job.status == Status.pending and job.claimed_by is None
            assert job.fencing_token > jobs[3].fencing_token
            with pytest.raises(ValueError):
                await repository.requeue_retryable_failure(
                    job.id,
                    expected_worker="worker:a",
                    expected_fencing_token=job.fencing_token,
                    failure="unknown_commit_outcome",
                )

    asyncio.run(run())


def test_handoff_and_inbox_are_atomic_and_terminal(sessions):
    async def run():
        async with sessions.begin() as session:
            workspace, activations, _ = await seed(session)
            job = (await claim(session, workspace.id))[0]
        request, receipt = envelope(job)

        async def accept(session):
            await session.execute(
                insert(inbox).values(
                    key=request.idempotency_key, fingerprint=request.payload_fingerprint
                )
            )
            return await repo(session, workspace.id).record_handoff_acceptance(
                job.id,
                expected_worker="worker:a",
                expected_fencing_token=job.fencing_token,
                request=request,
                receipt=receipt,
            )

        async with sessions() as session:
            result = await accept(session)
            assert result.status == Status.handed_off
            await session.rollback()
        async with sessions.begin() as session:
            assert await session.scalar(select(func.count()).select_from(inbox)) == 0
            assert (
                await repo(session, workspace.id).get_job(job.id)
            ).status == Status.claimed
            await accept(session)
        async with sessions.begin() as session:
            repository = repo(session, workspace.id)
            current = await repository.get_job(job.id)
            assert (
                current.status == Status.handed_off
                and current.handoff_receipt_id == receipt.delivery_request_id
            )
            assert await claim(session, workspace.id) == ()
            assert await repository.recover_expired_leases(worker_id="r", limit=1) == ()
            assert (
                await repository.find_active_job(job.marketing_content_item_channel_id)
                is None
            )
            assert (await repository.find_existing_job(activations[0])).id == job.id
            with pytest.raises(SchedulingConflict):
                await repository.create_pending_job(
                    replace(activations[0], operation_id=uuid4())
                )
            assert await session.scalar(select(func.count()).select_from(inbox)) == 1

    asyncio.run(run())


def test_workspace_isolation_filters_and_keyset_pagination(sessions):
    async def run():
        async with sessions.begin() as session:
            workspace, _, jobs = await seed(session, count=5)
            other, activations, foreign = await seed(session)
        async with sessions.begin() as session:
            repository = repo(session, workspace.id)
            assert await repository.get_job(foreign[0].id) is None
            assert (
                await repository.find_active_job(
                    foreign[0].marketing_content_item_channel_id
                )
                is None
            )
            with pytest.raises(SchedulingConflict):
                await repository.find_existing_job(activations[0])
            for operation in (
                repository.cancel_pending_job,
                repository.supersede_active_job,
            ):
                with pytest.raises(SchedulingConflict):
                    await operation(foreign[0].id, actor_key="user")
            with pytest.raises(SchedulingConflict):
                await repository.block_job(
                    foreign[0].id, actor_key="user", reason=Reason.stale_approval
                )
            seen, cursor = [], None
            while True:
                page = await repository.list_jobs(
                    limit=2, cursor=cursor, statuses=[Status.pending]
                )
                seen.extend(j.id for j in page.jobs)
                cursor = page.next_cursor
                if cursor is None:
                    break
            assert len(seen) == len(set(seen)) == 5
            assert set(seen) == {j.id for j in jobs}
            assert (
                len(
                    (
                        await repository.list_jobs(
                            channel_id=jobs[0].marketing_content_item_channel_id
                        )
                    ).jobs
                )
                == 1
            )
            assert (
                len(
                    (
                        await repository.list_jobs(
                            content_item_id=jobs[0].marketing_content_item_id
                        )
                    ).jobs
                )
                == 1
            )
            assert (await repository.list_jobs(statuses=[])).jobs == ()
            assert len(await claim(session, workspace.id)) == 5
            assert (
                await repo(session, other.id).get_job(foreign[0].id)
            ).status == Status.pending

    asyncio.run(run())


def test_batch_reads_do_not_grow_per_job(sessions, postgres_test_engine):
    async def run():
        async with sessions.begin() as session:
            one, _, _ = await seed(session)
            many, _, _ = await seed(session, count=128)
        reads = []

        def record(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                reads.append(statement)

        event.listen(postgres_test_engine.sync_engine, "before_cursor_execute", record)
        try:
            async with sessions.begin() as session:
                await claim(session, one.id)
            baseline = len(reads)
            reads.clear()
            async with sessions.begin() as session:
                assert len(await claim(session, many.id, limit=128)) == 128
            assert len(reads) == baseline
        finally:
            event.remove(
                postgres_test_engine.sync_engine, "before_cursor_execute", record
            )

    asyncio.run(run())


def test_concurrent_distinct_activations_have_one_winner(sessions):
    async def run():
        async with sessions.begin() as session:
            workspace, activations, _ = await seed(session, activate=False)

        async def activate():
            async with sessions.begin() as session:
                try:
                    job = await repo(session, workspace.id).create_pending_job(
                        replace(activations[0], operation_id=uuid4())
                    )
                    return job.id
                except SchedulingConflict:
                    return None

        results = await asyncio.gather(*(activate() for _ in range(4)))
        assert sum(result is not None for result in results) == 1

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["recover", "retry", "handoff"])
@pytest.mark.parametrize("stale", [False, True])
def test_guards_rechecked_after_claim(sessions, operation, stale):
    async def run():
        async with sessions.begin() as session:
            workspace, _, _ = await seed(session)
            job = (await claim(session, workspace.id))[0]
        async with sessions.begin() as session:
            if stale:
                await session.execute(
                    update(MarketingContentItem)
                    .where(MarketingContentItem.id == job.marketing_content_item_id)
                    .values(content_revision=2)
                )
            if operation == "recover":
                await expire(session, job.id)
        async with sessions.begin() as session:
            # A tightened configured window makes already-claimed work late.
            repository = repo(session, workspace.id, window=300 if stale else 0)
            reason = (
                Reason.stale_content_revision
                if stale
                else Reason.missed_schedule_window
            )
            if operation == "recover":
                rows = await repository.recover_expired_leases(
                    worker_id="recovery", limit=1
                )
                assert rows[0].blocked_reason_code == reason
            elif operation == "retry":
                result = await repository.requeue_retryable_failure(
                    job.id,
                    expected_worker="worker:a",
                    expected_fencing_token=job.fencing_token,
                    failure=RetryableInternalFailure.database_contention,
                )
                assert result.blocked_reason_code == reason
            else:
                request, receipt = envelope(job)
                with pytest.raises(SchedulingConflict, match=reason.value):
                    await repository.record_handoff_acceptance(
                        job.id,
                        expected_worker="worker:a",
                        expected_fencing_token=job.fencing_token,
                        request=request,
                        receipt=receipt,
                    )
                assert (await repository.get_job(job.id)).status == Status.claimed

    asyncio.run(run())


def test_missing_tokens_receipt_mismatch_and_successful_fenced_transitions(sessions):
    async def run():
        async with sessions.begin() as session:
            workspace, activations, _ = await seed(session, count=2)
            jobs = await claim(session, workspace.id)
        async with sessions.begin() as session:
            repository = repo(session, workspace.id)
            for method in (repository.block_job, repository.supersede_active_job):
                extra = (
                    {"reason": Reason.stale_approval}
                    if method == repository.block_job
                    else {}
                )
                with pytest.raises(SchedulingConflict, match="required"):
                    await method(jobs[0].id, actor_key="worker:a", **extra)
            request, receipt = envelope(jobs[0])
            with pytest.raises(SchedulingConflict, match="handoff_contract_violation"):
                await repository.record_handoff_acceptance(
                    jobs[0].id,
                    expected_worker="worker:a",
                    expected_fencing_token=jobs[0].fencing_token,
                    request=request,
                    receipt=replace(receipt, payload_fingerprint="different"),
                )
            blocked = await repository.block_job(
                jobs[0].id,
                actor_key="worker:a",
                expected_worker="worker:a",
                expected_fencing_token=jobs[0].fencing_token,
                reason=Reason.missing_durable_delivery_receiver,
            )
            assert blocked.status == Status.blocked
            superseded = await repository.supersede_active_job(
                jobs[1].id,
                actor_key="worker:a",
                expected_worker="worker:a",
                expected_fencing_token=jobs[1].fencing_token,
            )
            assert superseded.status == Status.superseded
            activation = next(
                a
                for a in activations
                if a.snapshot.channel_id == superseded.marketing_content_item_channel_id
            )
            successor = await repository.create_pending_job(
                replace(
                    activation,
                    operation_id=uuid4(),
                    supersedes_job_id=superseded.id,
                    lineage_root_job_id=superseded.id,
                )
            )
            assert successor.supersedes_job_id == superseded.id
            with pytest.raises(SchedulingConflict):
                await repository.create_pending_job(
                    replace(
                        activation,
                        operation_id=uuid4(),
                        supersedes_job_id=blocked.id,
                        lineage_root_job_id=blocked.id,
                    )
                )

    asyncio.run(run())


def test_single_parent_batch_limit_and_rollback(sessions):
    async def run():
        async with sessions.begin() as session:
            workspace, activations, jobs = await seed(session)
            original = activations[0]
            for index in range(5):
                channel = MarketingContentItemChannel(
                    marketing_content_item_id=original.snapshot.content_item_id,
                    channel="instagram",
                    placement=f"placement-{index}",
                    scheduled_at=original.snapshot.scheduled_for,
                    schedule_timezone="UTC",
                    social_account_connection_id=original.destination_id,
                )
                session.add(channel)
                await session.flush()
                jobs.append(
                    await repo(session, workspace.id).create_pending_job(
                        replace(
                            original,
                            operation_id=uuid4(),
                            snapshot=replace(original.snapshot, channel_id=channel.id),
                        )
                    )
                )
        async with sessions() as session:
            assert len(await claim(session, workspace.id, limit=2)) == 2
            await session.rollback()
        async with sessions.begin() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(SchedulingJobTransition)
                    .where(SchedulingJobTransition.operation == "claim")
                )
                == 0
            )
            assert len(await claim(session, workspace.id, limit=2)) == 2
        async with sessions.begin() as session:
            assert len(await claim(session, workspace.id, limit=100)) == 4

    asyncio.run(run())


def test_parent_writer_is_skipped_then_drift_is_refreshed(sessions):
    async def run():
        async with sessions.begin() as session:
            workspace, _, jobs = await seed(session)
        async with sessions() as writer, sessions() as worker:
            repository = repo(worker, workspace.id)
            stale = await worker.get(
                MarketingContentItem, jobs[0].marketing_content_item_id
            )
            await writer.execute(
                select(MarketingContentItem.id)
                .where(MarketingContentItem.id == stale.id)
                .with_for_update()
            )
            assert await asyncio.wait_for(claim(worker, workspace.id), 3) == ()
            await writer.execute(
                update(MarketingContentItem)
                .where(MarketingContentItem.id == stale.id)
                .values(content_revision=2)
            )
            await writer.commit()
            assert await claim(worker, workspace.id) == ()
            assert stale.content_revision == 2
            assert (
                await repository.get_job(jobs[0].id)
            ).blocked_reason_code == Reason.stale_content_revision
            await worker.commit()

    asyncio.run(run())


def test_database_clock_fences_lease_expiring_after_validation(sessions, monkeypatch):
    async def run():
        async with sessions.begin() as session:
            workspace, _, _ = await seed(session)
            job = (await claim(session, workspace.id))[0]
        async with sessions.begin() as session:
            repository = repo(session, workspace.id)
            real_change = repository._change

            async def after_validation(*args, **kwargs):
                # Simulate an expiration between the Python checks and SQL write.
                await expire(session, job.id)
                return await real_change(*args, **kwargs)

            monkeypatch.setattr(repository, "_change", after_validation)
            request, receipt = envelope(job)
            with pytest.raises(SchedulingConflict, match="expired"):
                await repository.record_handoff_acceptance(
                    job.id,
                    expected_worker="worker:a",
                    expected_fencing_token=job.fencing_token,
                    request=request,
                    receipt=receipt,
                )
            assert (await repository.get_job(job.id)).status == Status.claimed

    asyncio.run(run())


def test_invalid_batch_and_policy_inputs(sessions):
    async def run():
        async with sessions() as session:
            workspace_id = uuid4()
            for window in (-1, None, True):
                with pytest.raises(ValueError):
                    repo(session, workspace_id, window)
            with pytest.raises(ValueError):
                repo(session, None)
            repository = repo(session, workspace_id)
            for limit in (0, -1, 1001, True):
                with pytest.raises(ValueError):
                    await repository.claim_batch(
                        worker_id="worker",
                        limit=limit,
                        lease_duration=timedelta(seconds=30),
                    )
            with pytest.raises(ValueError):
                await repository.claim_batch(
                    worker_id="worker", limit=1, lease_duration=timedelta(0)
                )
            with pytest.raises(ValueError):
                await repository.claim_batch(
                    worker_id=" ", limit=1, lease_duration=timedelta(seconds=30)
                )

    asyncio.run(run())


def test_lease_expires_within_an_open_transaction(sessions):
    async def run():
        async with sessions.begin() as session:
            workspace, _, _ = await seed(session)
        async with sessions.begin() as session:
            repository = repo(session, workspace.id)
            transaction_start = await session.scalar(select(func.now()))
            job = (
                await repository.claim_batch(
                    worker_id="worker:a",
                    limit=1,
                    lease_duration=timedelta(milliseconds=100),
                )
            )[0]
            assert transaction_start < job.claim_expires_at
            # Real PostgreSQL time advances while transaction-start now() stays fixed.
            await session.execute(select(func.pg_sleep(0.15)))
            assert await session.scalar(select(func.now())) == transaction_start
            with pytest.raises(SchedulingConflict, match="expired"):
                await repository.requeue_retryable_failure(
                    job.id,
                    expected_worker="worker:a",
                    expected_fencing_token=job.fencing_token,
                    failure=RetryableInternalFailure.database_contention,
                )
            recovered = await repository.recover_expired_leases(worker_id="r", limit=1)
            assert recovered[0].status == Status.pending

    asyncio.run(run())
