"""Composition/rollback and PostgreSQL source fencing at application boundaries."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from labelos_database.base import Base
from labelos_database.models import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalRequestStage,
    MarketingContentItem,
    MarketingContentItemChannel,
    MarketingContentItemStatus,
    RealtimeEvent,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from labelos_api.realtime import RealtimeEventType, RealtimePublisher
from labelos_api.repositories import marketing_content
from labelos_api.repositories.approval_resources import (
    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
)
from labelos_api.services import approval_service, content_invalidation
from labelos_api.services import marketing_content_service as content
from labelos_api.services.content_transactions import (
    ApprovalTransaction,
    MarketingContentTransaction,
)
from test_approval_service import _seed
from test_marketing_content_postgres import wait_until_blocked

TABLES = (
    MarketingContentItem,
    MarketingContentItemChannel,
    ApprovalRequest,
    ApprovalRequestStage,
    ApprovalDecision,
    RealtimeEvent,
)


def make_sessions(engine):
    async def prepare_database():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare_database())
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def sessionmaker(database_test_engine):
    return make_sessions(database_test_engine)


@pytest.fixture
def pg_sessionmaker(postgres_test_engine):
    return make_sessions(postgres_test_engine)


async def snapshot(session):
    return {
        model.__tablename__: (
            await session.execute(select(model.__table__).order_by(model.id))
        )
        .mappings()
        .all()
        for model in TABLES
    }


async def prepare(session, *, approved=False):
    seed = await _seed(session)
    item = await content.replace_channels(
        session,
        seed.organization_id,
        seed.content_item_id,
        [
            content.MarketingContentChannelCreate(
                channel="instagram",
                schedule_timezone="UTC",
                schedule_local_time="2027-01-15T12:00:00",
            )
        ],
        actor=seed.submitter,
    )
    channel_id = item.channels[0].id
    request_id = None
    if approved:
        request = await approval_service.submit_resource_for_approval(
            session,
            seed.organization_id,
            MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
            item.id,
            actor=seed.submitter,
        )
        request_id = request.id
        await approval_service.approve_request(
            session,
            seed.organization_id,
            request.id,
            actor=seed.reviewer,
        )
    return seed, channel_id, request_id


@pytest.mark.parametrize(
    "operation",
    [
        "create",
        "parent",
        "combined",
        "replace",
        "channel",
        "submit",
        "approve",
        "schedule",
        "cancel_parent",
        "assign",
        "changes",
        "reject",
        "cancel",
        "invalidate",
        "resubmit",
        "revoke",
    ],
)
def test_composed_operations_rollback_every_write(sessionmaker, operation):
    async def run():
        async with sessionmaker() as session:
            seed, channel_id, request_id = await prepare(
                session,
                approved=operation
                in {
                    "parent",
                    "combined",
                    "replace",
                    "channel",
                    "schedule",
                    "revoke",
                },
            )
            if operation in {
                "approve",
                "assign",
                "changes",
                "reject",
                "cancel",
                "invalidate",
                "resubmit",
            }:
                request = await approval_service.submit_resource_for_approval(
                    session,
                    seed.organization_id,
                    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                    seed.content_item_id,
                    actor=seed.submitter,
                )
                request_id = request.id
            if operation == "resubmit":
                await approval_service.request_changes(
                    session,
                    seed.organization_id,
                    request_id,
                    actor=seed.reviewer,
                )
                await content.update_content_item(
                    session,
                    seed.organization_id,
                    seed.content_item_id,
                    content.MarketingContentItemUpdate(
                        title="Revision two", material_change=True
                    ),
                    actor=seed.submitter,
                )
            baseline = await snapshot(session)
            # A commit from any nested service would fail this test immediately.
            session.commit = AsyncMock(side_effect=AssertionError("Internal commit"))
            edits = MarketingContentTransaction(
                session, seed.organization_id, actor=seed.submitter
            )
            reviews = ApprovalTransaction(
                session, seed.organization_id, actor=seed.reviewer
            )
            submissions = ApprovalTransaction(
                session, seed.organization_id, actor=seed.submitter
            )
            if operation == "create":
                await edits.create_content_item(
                    content.MarketingContentItemCreate(
                        campaign_id=seed.campaign_id,
                        title="Transient",
                        content_type="caption",
                    )
                )
            elif operation == "parent":
                await edits.update_content_item(
                    seed.content_item_id,
                    content.MarketingContentItemUpdate(
                        title="Changed",
                        material_change=True,
                    ),
                )
            elif operation == "combined":
                await edits.update_content_item_with_channels(
                    seed.content_item_id,
                    content.MarketingContentItemUpdate(
                        title="Changed", material_change=True
                    ),
                    [],
                )
            elif operation == "replace":
                await edits.replace_channels(seed.content_item_id, [])
            elif operation == "channel":
                await edits.update_channel(
                    seed.content_item_id,
                    channel_id,
                    content.MarketingContentChannelUpdate(copy_text_override="Changed"),
                )
            elif operation == "submit":
                await edits.transition_status(seed.content_item_id, "in_review")
            elif operation == "approve":
                await MarketingContentTransaction(
                    session, seed.organization_id, actor=seed.reviewer
                ).transition_status(
                    seed.content_item_id,
                    "approved",
                )
            elif operation == "schedule":
                await edits.transition_status(seed.content_item_id, "scheduled")
            elif operation == "cancel_parent":
                await edits.transition_status(seed.content_item_id, "cancelled")
            elif operation == "assign":
                await reviews.assign_stage_reviewer(
                    request_id, seed.reviewer_profile_id
                )
            elif operation == "changes":
                await reviews.request_changes(request_id)
            elif operation == "reject":
                await reviews.reject_request(request_id)
            elif operation == "cancel":
                await submissions.cancel_request(request_id)
            elif operation == "invalidate":
                await submissions.invalidate_request(request_id)
            elif operation == "resubmit":
                await submissions.resubmit_resource(
                    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                    seed.content_item_id,
                    previous_approval_request_id=request_id,
                )
            else:
                await submissions.record_current_approval_invalidated(request_id)
            assert await snapshot(session) != baseline
            await session.rollback()
        async with sessionmaker() as observer:
            assert await snapshot(observer) == baseline

    asyncio.run(run())


def test_removal_hook_and_realtime_are_one_rollback_unit(sessionmaker, monkeypatch):
    async def run():
        async with sessionmaker() as session:
            seed, channel_id, request_id = await prepare(session, approved=True)
            baseline = await snapshot(session)
            item = await marketing_content.get_item(
                session, seed.organization_id, seed.content_item_id
            )
            revision = item.content_revision
            observed = []

            async def future_invalidation(transaction, invalidation, *, actor):
                assert transaction is session
                assert actor == seed.submitter
                assert invalidation.previous_content_revision == revision
                assert invalidation.previous_approval_request_id == request_id
                assert invalidation.removed_channel_ids == (channel_id,)
                assert (
                    await transaction.get(MarketingContentItemChannel, channel_id)
                    is not None
                )
                # Stand-in for future cancellation/history writes, using an existing
                # transactional record. No scheduling table is introduced.
                observed.append(
                    await RealtimePublisher(transaction).publish(
                        organization_id=seed.organization_id,
                        event_type=RealtimeEventType.marketing_content_updated,
                        actor=seed.submitter,
                        payload={"test": "future invalidation"},
                    )
                )

            monkeypatch.setattr(
                content_invalidation, "invalidate_content_channels", future_invalidation
            )
            edits = MarketingContentTransaction(
                session, seed.organization_id, actor=seed.submitter
            )
            await edits.update_content_item_with_channels(
                seed.content_item_id,
                content.MarketingContentItemUpdate(
                    title="Removed", material_change=True
                ),
                [],
            )
            changed = await marketing_content.get_item(
                session, seed.organization_id, seed.content_item_id
            )
            assert changed.content_revision == revision + 1
            assert changed.channels == []
            assert observed
            # A later failure must undo earlier source and outbox writes.
            with pytest.raises(RuntimeError):
                try:
                    raise RuntimeError("Later operation failed")
                except RuntimeError:
                    await session.rollback()
                    raise
        async with sessionmaker() as observer:
            assert await snapshot(observer) == baseline

    asyncio.run(run())


@pytest.mark.parametrize("scope", [MarketingContentTransaction, ApprovalTransaction])
def test_transaction_scope_requires_explicit_actor(scope):
    with pytest.raises(ValueError, match="explicit authoring actor"):
        scope(None, None, actor=None)
    with pytest.raises(TypeError):
        scope(None, None)


@pytest.mark.parametrize(
    "invalid", ["revision", "generation", "approval", "pointer", "intent"]
)
def test_locked_verification_rejects_stale_source(sessionmaker, invalid):
    async def run():
        async with sessionmaker() as session:
            seed, channel_id, request_id = await prepare(session, approved=True)
            edits = MarketingContentTransaction(
                session, seed.organization_id, actor=seed.submitter
            )
            item = await marketing_content.get_item(
                session, seed.organization_id, seed.content_item_id
            )
            revision = item.content_revision
            generation = item.channels[0].schedule_generation
            if invalid == "approval":
                await ApprovalTransaction(
                    session, seed.organization_id, actor=seed.submitter
                ).record_current_approval_invalidated(request_id)
            if invalid == "pointer":
                other = await ApprovalTransaction(
                    session, seed.organization_id, actor=seed.submitter
                ).submit_resource_for_approval(
                    MARKETING_CONTENT_ITEM_RESOURCE_TYPE, seed.other_content_item_id
                )
                item.approval_request_id = other.id
            if invalid == "intent":
                item.channels[0].schedule_timezone = None
            with pytest.raises(
                (
                    content.MarketingContentLifecycleError,
                    approval_service.ApprovalStaleResourceRevisionError,
                )
            ):
                await edits.verify_scheduling_source(
                    seed.content_item_id,
                    channel_id,
                    expected_content_revision=revision + (invalid == "revision"),
                    expected_schedule_generation=generation + (invalid == "generation"),
                )
            await session.rollback()

    asyncio.run(run())


def test_locked_source_keeps_content_approval_and_intent_consistent(pg_sessionmaker):
    async def run():
        async with pg_sessionmaker() as session:
            seed, channel_id, request_id = await prepare(session, approved=True)
            item = await marketing_content.get_item(
                session, seed.organization_id, seed.content_item_id
            )
            revision, generation = (
                item.content_revision,
                item.channels[0].schedule_generation,
            )
        async with (
            pg_sessionmaker() as holder,
            pg_sessionmaker() as waiter,
            pg_sessionmaker() as observer,
        ):
            source = await MarketingContentTransaction(
                holder, seed.organization_id, actor=seed.submitter
            ).verify_scheduling_source(
                seed.content_item_id,
                channel_id,
                expected_content_revision=revision,
                expected_schedule_generation=generation,
            )
            assert source.approval.request_id == request_id
            assert source.channel.scheduled_at == datetime(2027, 1, 15, 12, tzinfo=UTC)
            pid = await waiter.scalar(text("SELECT pg_backend_pid()"))
            task = asyncio.create_task(
                content.update_channel(
                    waiter,
                    seed.organization_id,
                    seed.content_item_id,
                    channel_id,
                    content.MarketingContentChannelUpdate(
                        copy_text_override="Concurrent"
                    ),
                    actor=seed.submitter,
                )
            )
            try:
                await wait_until_blocked(observer, pid, task)
                await holder.commit()
                await asyncio.wait_for(task, 10)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            # The previously loaded source is stale; verification reloads after locking.
            with pytest.raises(approval_service.ApprovalStaleResourceRevisionError):
                await MarketingContentTransaction(
                    holder, seed.organization_id, actor=seed.submitter
                ).verify_scheduling_source(
                    seed.content_item_id,
                    channel_id,
                    expected_content_revision=revision,
                    expected_schedule_generation=generation,
                )
            await holder.rollback()

    asyncio.run(run())


def test_concurrent_material_edit_prevents_stale_approval(pg_sessionmaker):
    async def run():
        async with pg_sessionmaker() as session:
            seed, channel_id, _ = await prepare(session)
            request = await approval_service.submit_resource_for_approval(
                session,
                seed.organization_id,
                MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                seed.content_item_id,
                actor=seed.submitter,
            )
            request_id = request.id
        async with (
            pg_sessionmaker() as holder,
            pg_sessionmaker() as waiter,
            pg_sessionmaker() as observer,
        ):
            # Deliberately cache old content and request before the edit wins the lock.
            stale = await marketing_content.get_item(
                waiter, seed.organization_id, seed.content_item_id
            )
            revision = stale.content_revision
            await approval_service.get_approval_request(
                waiter, seed.organization_id, request_id
            )
            await MarketingContentTransaction(
                holder, seed.organization_id, actor=seed.submitter
            ).update_channel(
                seed.content_item_id,
                channel_id,
                content.MarketingContentChannelUpdate(
                    copy_text_override="New revision"
                ),
            )
            pid = await waiter.scalar(text("SELECT pg_backend_pid()"))
            task = asyncio.create_task(
                approval_service.approve_request(
                    waiter, seed.organization_id, request_id, actor=seed.reviewer
                )
            )
            try:
                await wait_until_blocked(observer, pid, task)
                await holder.commit()
                with pytest.raises(approval_service.ApprovalStaleResourceRevisionError):
                    await asyncio.wait_for(task, 10)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                await waiter.rollback()
            current = await marketing_content.get_item(
                observer, seed.organization_id, seed.content_item_id
            )
            assert current.content_revision == revision + 1
            assert current.status == MarketingContentItemStatus.draft
            assert current.approved_revision is None

    asyncio.run(run())


def test_public_resubmission_failure_cannot_commit_submission(
    sessionmaker, monkeypatch
):
    async def run():
        async with sessionmaker() as session:
            seed, _, _ = await prepare(session)
            request = await approval_service.submit_resource_for_approval(
                session,
                seed.organization_id,
                MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                seed.content_item_id,
                actor=seed.submitter,
            )
            request_id = request.id
            await approval_service.request_changes(
                session,
                seed.organization_id,
                request_id,
                actor=seed.reviewer,
            )
            await content.update_content_item(
                session,
                seed.organization_id,
                seed.content_item_id,
                content.MarketingContentItemUpdate(
                    title="Revised", material_change=True
                ),
                actor=seed.submitter,
            )
            baseline = await snapshot(session)
            publish = approval_service._publish_approval_event

            async def fail_after_resubmission(*args, **kwargs):
                await publish(*args, **kwargs)
                if kwargs["event_action"] == "resubmitted":
                    raise RuntimeError("Outbox insertion failed after submission")

            monkeypatch.setattr(
                approval_service, "_publish_approval_event", fail_after_resubmission
            )
            with pytest.raises(RuntimeError, match="Outbox insertion"):
                await approval_service.resubmit_resource(
                    session,
                    seed.organization_id,
                    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                    seed.content_item_id,
                    previous_approval_request_id=request_id,
                    actor=seed.submitter,
                )
        async with sessionmaker() as observer:
            assert await snapshot(observer) == baseline

    asyncio.run(run())


def test_postgres_outbox_visible_only_with_outer_commit(pg_sessionmaker):
    async def run():
        async with pg_sessionmaker() as session:
            seed, _, _ = await prepare(session)
            baseline = await snapshot(session)
        async with pg_sessionmaker() as writer, pg_sessionmaker() as observer:
            edits = MarketingContentTransaction(
                writer, seed.organization_id, actor=seed.submitter
            )
            await edits.update_content_item(
                seed.content_item_id,
                content.MarketingContentItemUpdate(
                    title="Atomic", material_change=True
                ),
            )
            assert await snapshot(observer) == baseline
            await writer.rollback()
            assert await snapshot(observer) == baseline
            # Reuse a UUID identity after rollback (ORM users are expired by rollback).
            edits = MarketingContentTransaction(
                writer, seed.organization_id, actor=seed.submitter.id
            )
            await edits.update_content_item(
                seed.content_item_id,
                content.MarketingContentItemUpdate(
                    title="Committed", material_change=True
                ),
            )
            pending = await snapshot(writer)
            await writer.commit()
            assert await snapshot(observer) == pending

    asyncio.run(run())


def test_public_guard_conflict_rolls_back_partial_request_update(sessionmaker):
    async def run():
        async with sessionmaker() as session:
            seed, _, _ = await prepare(session)
            request = await approval_service.submit_resource_for_approval(
                session,
                seed.organization_id,
                MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                seed.content_item_id,
                actor=seed.submitter,
            )
            request_id = request.id
            # An inconsistent stage must not leave the preceding guarded request
            # update committed when the second guard rejects the operation.
            request.stages[0].status = "approved"
            await session.commit()
            baseline = await snapshot(session)
            with pytest.raises(approval_service.ApprovalAlreadyResolvedError):
                await approval_service.approve_request(
                    session, seed.organization_id, request_id, actor=seed.reviewer
                )
            assert await snapshot(session) == baseline
            await session.commit()
        async with sessionmaker() as observer:
            assert await snapshot(observer) == baseline

    asyncio.run(run())
