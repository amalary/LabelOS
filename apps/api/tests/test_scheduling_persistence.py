import asyncio
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from labelos_database.base import Base
from labelos_database.models import (
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
from labelos_database.scheduling import SchedulingJobStatus
from sqlalchemy import MetaData, delete, event, func, inspect, select, update
from sqlalchemy.exc import DBAPIError, StatementError
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import Session

from labelos_api.repositories import marketing_content
from labelos_api.scheduling.contracts import (
    ScheduleSnapshot,
    SchedulingBlockedReason,
    SchedulingJobState,
    schedule_blocked_reason,
)

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


@pytest.fixture
def sessions(database_test_engine):
    engine = database_test_engine

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _record):
        if engine.dialect.name == "sqlite":
            connection.execute("PRAGMA foreign_keys=ON")

    async def prepare():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())
    return async_sessionmaker(engine, expire_on_commit=False)


async def source(session):
    user = User(email=f"{uuid4()}@test.com")
    workspace = Organization(name="Label", slug=uuid4().hex, owner=user)
    item = MarketingContentItem(
        organization=workspace,
        campaign=Campaign(name="Launch", organization=workspace),
        title="Post",
        content_type="image",
        scheduled_at=NOW - timedelta(days=1),
        channels=[
            MarketingContentItemChannel(
                channel="instagram",
                scheduled_at=NOW,
                schedule_timezone="UTC",
                schedule_local_time="2026-09-15T12:00:00",
                schedule_offset_seconds=0,
                published_at=NOW - timedelta(days=2),
                external_post_id="unchanged",
                external_url="https://example.com/unchanged",
            )
        ],
    )
    session.add(item)
    await session.flush()
    approval = ApprovalRequest(
        organization_id=workspace.id,
        resource_type="marketing_content_item",
        resource_id=item.id,
        resource_revision=1,
        title="Approve",
        status="approved",
    )
    session.add(approval)
    await session.flush()
    return item, approval, user


def job_for(item, approval, user, **overrides):
    identifier = uuid4()
    values = dict(
        id=identifier,
        workspace_id=item.organization_id,
        marketing_content_item_id=item.id,
        marketing_content_item_channel_id=item.channels[0].id,
        approval_request_id=approval.id,
        authorized_content_revision=1,
        schedule_generation=1,
        scheduled_for=NOW,
        schedule_timezone="UTC",
        created_by_user_id=user.id,
        activation_operation_id=uuid4(),
        idempotency_key=f"labelos:scheduling:v1:{item.organization_id}:{identifier}",
    )
    values.update(overrides)
    return SchedulingJob(**values)


def test_storage_enums_match_approved_contract():
    from labelos_database.scheduling import SchedulingBlockedReason as StoredReason

    assert set(SchedulingJobStatus) == set(SchedulingJobState)
    assert set(StoredReason) == set(SchedulingBlockedReason)


@pytest.mark.parametrize("zone", ["PST", "EST", "America/Invalid", "", "../UTC"])
def test_invalid_job_timezone(zone):
    with pytest.raises(ValueError, match="IANA"):
        SchedulingJob(schedule_timezone=zone)


@pytest.mark.parametrize(
    "metadata",
    [
        {"access_token": "secret"},
        {"raw_error": "provider body"},
        {"reason_codes": ["unknown"]},
        {"observed_content_revision": "secret"},
        {"reason_codes": "stale_approval"},
        {"lateness_window_seconds": True},
    ],
)
def test_blocked_metadata_allowlist(metadata):
    with pytest.raises(ValueError):
        SchedulingJob(blocked_metadata=metadata)


def test_snapshot_stales_without_moving_job_or_publication_results(sessions):
    async def run():
        async with sessions() as session:
            item, approval, user = await source(session)
            job = job_for(item, approval, user)
            session.add(job)
            await session.commit()
            channel = item.channels[0]
            snapshot = ScheduleSnapshot(
                workspace_id=job.workspace_id,
                content_item_id=item.id,
                channel_id=channel.id,
                content_revision=1,
                approval_request_id=approval.id,
                schedule_generation=job.schedule_generation,
                scheduled_for=job.scheduled_for,
            )
            await marketing_content.update_channel(
                session, channel.id, {"scheduled_at": NOW + timedelta(hours=1)}
            )
            await session.commit()
            await session.refresh(job)
            assert channel.schedule_generation == 2
            assert job.scheduled_for == NOW and job.schedule_generation == 1
            assert (
                schedule_blocked_reason(
                    snapshot,
                    scheduled_at=channel.scheduled_at,
                    schedule_generation=channel.schedule_generation,
                )
                == SchedulingBlockedReason.changed_schedule_generation
            )
            assert channel.external_post_id == "unchanged"
            assert channel.external_url == "https://example.com/unchanged"
            assert channel.published_at.replace(tzinfo=UTC) == NOW - timedelta(days=2)
            assert item.scheduled_at.replace(tzinfo=UTC) == NOW - timedelta(days=1)

    asyncio.run(run())


@pytest.mark.parametrize("status", ["pending", "claimed", "blocked"])
def test_active_slot_includes_blocked_and_claimed(sessions, status):
    async def run():
        async with sessions() as session:
            item, approval, user = await source(session)
            fields = {"status": status}
            if status == "claimed":
                fields.update(
                    claimed_at=NOW,
                    claim_expires_at=NOW + timedelta(seconds=30),
                    claimed_by="worker:1",
                    fencing_token=1,
                )
            if status == "blocked":
                fields.update(
                    blocked_at=NOW,
                    blocked_reason_code="stale_approval",
                    blocked_metadata={"reason_codes": ["stale_approval"]},
                )
            session.add(job_for(item, approval, user, **fields))
            await session.flush()
            with pytest.raises(DBAPIError), session.no_autoflush:
                async with session.begin_nested():
                    session.add(job_for(item, approval, user))
                    await session.flush()

    asyncio.run(run())


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "blocked"},
        {"status": "claimed"},
        {"status": "handed_off"},
        {"status": "cancelled"},
        {"authorized_content_revision": 0},
        {"schedule_generation": 0},
        {"fencing_token": -1},
        {"transition_version": 0},
        {"claimed_at": NOW},
        {
            "claimed_at": NOW,
            "claim_expires_at": NOW,
            "claimed_by": "worker",
            "fencing_token": 1,
        },
        {"approval_resource_type": "campaign"},
        {"approval_request_id": uuid4()},
        {"workspace_id": uuid4()},
        {"marketing_content_item_channel_id": uuid4()},
        {"social_account_connection_id": uuid4()},
        {"authorized_content_revision": 2},
        {"handoff_receipt_id": uuid4()},
        {"schedule_timezone": " "},
    ],
)
def test_database_rejects_invalid_rows(sessions, fields):
    async def run():
        async with sessions() as session:
            item, approval, user = await source(session)
            job = job_for(item, approval, user)
            # Core INSERT deliberately bypasses ORM validators: test database guards.
            values = {
                column.name: getattr(job, column.key)
                for column in SchedulingJob.__table__.columns
                if getattr(job, column.key) is not None
            }
            values.update(fields)
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.execute(
                        SchedulingJob.__table__.insert().values(**values)
                    )

    asyncio.run(run())


def test_foreign_scope_approval_identity_and_retry_uniqueness(sessions):
    async def run():
        async with sessions() as session:
            item, approval, user = await source(session)
            other, foreign_approval, _ = await source(session)
            foreign_account = SocialAccountConnection(
                organization_id=other.organization_id,
                provider="instagram",
                display_name="Foreign account",
                connection_method="assisted",
            )
            session.add(foreign_account)
            await session.flush()
            original = job_for(item, approval, user)
            session.add(original)
            await session.flush()
            for fields in (
                {"workspace_id": other.organization_id},
                {"marketing_content_item_channel_id": other.channels[0].id},
                {"approval_request_id": foreign_approval.id},
                {"social_account_connection_id": foreign_account.id},
                {"activation_operation_id": original.activation_operation_id},
                {"idempotency_key": original.idempotency_key},
            ):
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        session.add(
                            job_for(item, approval, user, status="superseded", **fields)
                        )
                        await session.flush()

    asyncio.run(run())


@pytest.mark.parametrize("status", ["cancelled", "superseded", "handed_off"])
def test_terminal_history_lineage_and_restricted_deletion(sessions, status):
    async def run():
        async with sessions() as session:
            item, approval, user = await source(session)
            fields = {"status": status}
            if status == "cancelled":
                fields.update(cancelled_at=NOW, cancellation_reason="user_cancelled")
            if status == "handed_off":
                account = SocialAccountConnection(
                    organization_id=item.organization_id,
                    provider="instagram",
                    display_name="Account",
                    connection_method="assisted",
                )
                session.add(account)
                await session.flush()
                fields.update(
                    handed_off_at=NOW,
                    handoff_receipt_id=uuid4(),
                    social_account_connection_id=account.id,
                )
            old = job_for(item, approval, user, **fields)
            session.add(old)
            await session.flush()
            successor_approval = approval
            if status == "handed_off":
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        session.add(job_for(item, approval, user))
                        await session.flush()
                successor_approval = ApprovalRequest(
                    organization_id=item.organization_id,
                    resource_type="marketing_content_item",
                    resource_id=item.id,
                    resource_revision=2,
                    title="Approve new revision",
                    status="approved",
                )
                session.add(successor_approval)
                await session.flush()
            successor = job_for(
                item,
                successor_approval,
                user,
                authorized_content_revision=successor_approval.resource_revision,
                supersedes_job_id=old.id,
                lineage_root_job_id=old.id,
            )
            session.add(successor)
            await session.flush()
            for statement in (
                delete(SchedulingJob).where(SchedulingJob.id == old.id),
                update(SchedulingJob)
                .where(SchedulingJob.id == old.id)
                .values(status="pending"),
                delete(MarketingContentItemChannel).where(
                    MarketingContentItemChannel.id == item.channels[0].id
                ),
                delete(MarketingContentItem).where(MarketingContentItem.id == item.id),
                delete(ApprovalRequest).where(ApprovalRequest.id == approval.id),
                delete(User).where(User.id == user.id),
            ):
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.execute(statement)
            assert (
                await session.scalar(select(func.count()).select_from(SchedulingJob))
                == 2
            )

    asyncio.run(run())


def test_immutable_snapshot_monotonic_fence_and_append_only_transitions(sessions):
    async def run():
        async with sessions() as session:
            item, approval, user = await source(session)
            job = job_for(item, approval, user, fencing_token=3)
            session.add(job)
            await session.flush()
            transition = SchedulingJobTransition(
                job_id=job.id,
                workspace_id=job.workspace_id,
                marketing_content_item_id=item.id,
                transition_version=1,
                operation_id=job.activation_operation_id,
                operation="activate",
                to_status="pending",
                actor_kind="user",
                actor_key=str(user.id),
            )
            session.add(transition)
            await session.flush()
            for statement in (
                update(SchedulingJob).values(scheduled_for=NOW + timedelta(hours=1)),
                update(SchedulingJob).values(schedule_timezone="America/New_York"),
                update(SchedulingJob).values(schedule_generation=2),
                update(SchedulingJob).values(fencing_token=2),
                delete(SchedulingJobTransition),
                update(SchedulingJobTransition).values(reason_code="rewritten"),
            ):
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.execute(statement)

    asyncio.run(run())


def test_utc_roundtrip_and_naive_rejection(sessions):
    async def run():
        async with sessions() as session:
            item, approval, user = await source(session)
            job = job_for(
                item,
                approval,
                user,
                scheduled_for=NOW.astimezone(timezone(timedelta(hours=5, minutes=45))),
            )
            session.add(job)
            await session.flush()
            await session.refresh(job)
            assert job.scheduled_for == NOW and job.scheduled_for.tzinfo is UTC
            with pytest.raises(StatementError, match="timezone-aware"):
                async with session.begin_nested():
                    session.add(
                        job_for(
                            item, approval, user, scheduled_for=NOW.replace(tzinfo=None)
                        )
                    )
                    await session.flush()

    asyncio.run(run())


def test_mutated_metadata_is_revalidated_at_bind(sessions):
    from sqlalchemy.orm.attributes import flag_modified

    async def run():
        async with sessions() as session:
            item, approval, user = await source(session)
            job = job_for(item, approval, user, blocked_metadata={})
            session.add(job)
            await session.commit()
            with pytest.raises(
                StatementError, match="Unsupported scheduling diagnostic"
            ):
                async with session.begin_nested():
                    job.blocked_metadata["provider_payload"] = "not safe diagnostics"
                    flag_modified(job, "blocked_metadata")
                    await session.flush()

    asyncio.run(run())


def test_full_migration_upgrade_downgrade_reupgrade(database_test_engine):
    scripts = ScriptDirectory.from_config(
        Config(str(ROOT / "packages/database/alembic.ini"))
    )
    assert scripts.get_heads() == ["202609152100"]
    head = scripts.get_revision("202609151800")
    assert head.down_revision == "202609151000"

    def check(connection):
        with Operations.context(MigrationContext.configure(connection)):
            if connection.dialect.name == "postgresql":
                for revision in reversed(list(scripts.walk_revisions())):
                    if revision.revision == head.revision:
                        break
                    revision.module.upgrade()
            else:
                # Older migrations contain PostgreSQL-only ALTER TYPE statements.
                # SQLite supports the models and this revision's complete round trip.
                baseline = MetaData(naming_convention=Base.metadata.naming_convention)
                for table in Base.metadata.sorted_tables:
                    if table.name not in {
                        "scheduling_jobs",
                        "scheduling_job_transitions",
                    }:
                        copy = table.to_metadata(baseline)
                        for index in list(copy.indexes):
                            if index.name.endswith("schedule_scope"):
                                copy.indexes.remove(index)
                baseline.create_all(connection)
            # Seed real legacy intent before the new migration, with no jobs.
            session = Session(connection)
            workspace = Organization(
                name="Legacy", slug="legacy", owner=User(email="legacy@test.com")
            )
            item = MarketingContentItem(
                organization=workspace,
                campaign=Campaign(name="Legacy", organization=workspace),
                title="Legacy",
                content_type="image",
                scheduled_at=NOW,
                channels=[
                    MarketingContentItemChannel(
                        channel="instagram",
                        scheduled_at=NOW,
                        published_at=NOW,
                        external_post_id="legacy-post",
                        external_url="https://example.com/post",
                    )
                ],
            )
            session.add(item)
            session.flush()
            probe = (
                "SELECT scheduled_at, published_at, external_post_id, external_url, "
                "schedule_generation, schedule_timezone "
                "FROM marketing_content_item_channels"
            )
            original = connection.exec_driver_sql(probe).all()
            assert len(original) == 1
            for operation in (
                head.module.upgrade,
                head.module.downgrade,
                head.module.upgrade,
            ):
                operation()
                assert connection.exec_driver_sql(probe).all() == original
                if operation == head.module.upgrade:
                    assert (
                        connection.exec_driver_sql(
                            "SELECT count(*) FROM scheduling_jobs"
                        ).scalar_one()
                        == 0
                    )
                if operation == head.module.downgrade:
                    assert (
                        "scheduling_jobs" not in inspect(connection).get_table_names()
                    )
                    assert not any(
                        i["name"].endswith("schedule_scope")
                        for i in inspect(connection).get_indexes("approval_requests")
                    )
                    if connection.dialect.name == "postgresql":
                        assert not any(
                            e["name"].startswith("scheduling_")
                            for e in inspect(connection).get_enums()
                        )
            inspector = inspect(connection)
            indexes = {i["name"]: i for i in inspector.get_indexes("scheduling_jobs")}
            assert indexes["uq_scheduling_jobs_active_channel"]["unique"]
            assert indexes["ix_scheduling_jobs_due"]["column_names"] == [
                "scheduled_for",
                "id",
            ]
            assert indexes["ix_scheduling_jobs_workspace_list"]["column_names"] == [
                "workspace_id",
                "created_at",
                "id",
            ]
            assert len(inspector.get_foreign_keys("scheduling_jobs")) == 9
            for foreign_key in inspector.get_foreign_keys("scheduling_jobs"):
                assert foreign_key["name"]
                assert foreign_key["options"]["ondelete"] == "RESTRICT"
            assert all(
                c["name"] for c in inspector.get_check_constraints("scheduling_jobs")
            )
            assert (
                connection.exec_driver_sql(
                    "SELECT count(*) FROM scheduling_jobs"
                ).scalar_one()
                == 0
            )
            assert "publishing_deliveries" not in inspector.get_table_names()
            if connection.dialect.name == "postgresql":
                enums = {e["name"]: e["labels"] for e in inspector.get_enums()}
                assert set(enums["scheduling_job_status"]) == set(SchedulingJobStatus)
                column = next(
                    c
                    for c in inspector.get_columns("scheduling_jobs")
                    if c["name"] == "scheduled_for"
                )
                assert column["type"].timezone is True
                connection.exec_driver_sql("SET LOCAL enable_seqscan = off")
                plan = connection.exec_driver_sql(
                    "EXPLAIN SELECT id FROM scheduling_jobs WHERE status = 'pending' "
                    "AND scheduled_for <= CURRENT_TIMESTAMP "
                    "ORDER BY scheduled_for, id LIMIT 10"
                ).all()
                assert "ix_scheduling_jobs_due" in str(plan)
            approval = ApprovalRequest(
                organization_id=workspace.id,
                resource_type="marketing_content_item",
                resource_id=item.id,
                resource_revision=1,
                title="Approve",
                status="approved",
            )
            session.add(approval)
            session.flush()
            job = job_for(item, approval, workspace.owner)
            session.add(job)
            session.flush()
            # Exercise the migrated tables, not just metadata-created test tables.
            for statement in (
                update(SchedulingJob).values(scheduled_for=NOW + timedelta(hours=1)),
                delete(SchedulingJob),
                update(SchedulingJob).values(status="claimed"),
            ):
                with pytest.raises(DBAPIError), connection.begin_nested():
                    connection.execute(statement)
            with pytest.raises(DBAPIError), session.begin_nested():
                session.add(job_for(item, approval, workspace.owner))
                session.flush()
            assert connection.exec_driver_sql(probe).all() == original

    async def run():
        async with database_test_engine.begin() as connection:
            await connection.run_sync(check)

    asyncio.run(run())


def test_postgres_concurrent_activation_slot(postgres_test_engine):
    async def run():
        async with postgres_test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(postgres_test_engine, expire_on_commit=False)
        async with factory() as seed:
            item, approval, user = await source(seed)
            await seed.commit()
        async with factory() as first:
            first.add(job_for(item, approval, user))
            await first.flush()
            attempted = asyncio.Event()

            async def contender():
                async with factory() as second:
                    second.add(job_for(item, approval, user))
                    attempted.set()
                    with pytest.raises(
                        DBAPIError,
                        match="uq_scheduling_jobs_(active_channel|handed_off_intent)",
                    ):
                        await second.commit()

            contender_task = asyncio.create_task(contender())
            await asyncio.wait_for(attempted.wait(), 5)
            await first.commit()
            await asyncio.wait_for(contender_task, 5)
        async with factory() as observer:
            assert (
                await observer.scalar(select(func.count()).select_from(SchedulingJob))
                == 1
            )

    asyncio.run(run())
