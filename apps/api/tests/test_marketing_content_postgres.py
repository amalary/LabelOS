"""Real PostgreSQL transactions: row locks, stale ORM state, and rollback.

These tests are required in CI. Locally set TEST_POSTGRES_URL to an isolated test
server; each test creates and drops only its own randomly named schema.
"""

import asyncio
from uuid import uuid4

import pytest
from labelos_database.base import Base
from labelos_database.models import (
    Campaign,
    MarketingContentItemChannel,
    MarketingContentItemStatus,
    Organization,
    User,
)
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from labelos_api.repositories import marketing_content
from labelos_api.repositories.approval_resources import (
    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
)
from labelos_api.services import approval_service
from labelos_api.services import marketing_content_service as service


@pytest.fixture
def pg_sessionmaker(postgres_test_engine):
    async def prepare():
        async with postgres_test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())
    return async_sessionmaker(postgres_test_engine, expire_on_commit=False)


async def seed(session):
    workspace = Organization(
        name="Concurrent", slug="concurrent", owner=User(email="concurrent@test.com")
    )
    campaign = Campaign(name="Launch", organization=workspace)
    session.add(campaign)
    await session.flush()
    item = await service.create_content_item(
        session,
        workspace.id,
        service.MarketingContentItemCreate(
            campaign_id=campaign.id,
            title="Post",
            content_type="image",
            channels=[
                service.MarketingContentChannelCreate(
                    channel="instagram", placement="feed"
                )
            ],
        ),
    )
    return workspace.id, item.id, item.channels[0].id


def channels(copy, *, add=False):
    values = [
        service.MarketingContentChannelCreate(
            channel="instagram",
            placement="feed",
            copy_text_override=copy,
        )
    ]
    if add:
        values.append(service.MarketingContentChannelCreate(channel="tiktok"))
    return values


async def wait_until_blocked(observer, pid, task):
    # Observe an actual server lock wait rather than assuming a sleep created a race.
    async with asyncio.timeout(5):
        while True:
            if task.done():
                task.result()
                pytest.fail("Writer completed without waiting for the parent lock")
            blockers = await observer.scalar(
                text("SELECT cardinality(pg_blocking_pids(:pid))"),
                {"pid": pid},
            )
            if blockers:
                return
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("entrypoint", ["replacement", "single", "parent"])
def test_concurrent_edits_refresh_stale_state_and_increment_each_revision(
    pg_sessionmaker, entrypoint
):
    async def run():
        async with pg_sessionmaker() as session:
            workspace_id, item_id, channel_id = await seed(session)
        async with (
            pg_sessionmaker() as holder,
            pg_sessionmaker() as waiter,
            pg_sessionmaker() as observer,
        ):
            # Keep stale parent and channel objects in the waiting session.
            stale = await marketing_content.get_item(waiter, workspace_id, item_id)
            assert stale.content_revision == 1
            assert len(stale.channels) == 1
            pid = await waiter.scalar(text("SELECT pg_backend_pid()"))
            await marketing_content.get_item_for_update(
                holder, item_id, workspace_id=workspace_id
            )

            async def second_write():
                if entrypoint == "replacement":
                    return await service.replace_channels(
                        waiter, workspace_id, item_id, channels("Second", add=True)
                    )
                if entrypoint == "single":
                    return await service.update_channel(
                        waiter,
                        workspace_id,
                        item_id,
                        channel_id,
                        service.MarketingContentChannelUpdate(
                            copy_text_override="Second"
                        ),
                    )
                return await service.update_content_item(
                    waiter,
                    workspace_id,
                    item_id,
                    service.MarketingContentItemUpdate(
                        title="Second", material_change=True
                    ),
                )

            task = asyncio.create_task(second_write())
            try:
                await wait_until_blocked(observer, pid, task)
                first = await service.replace_channels(
                    holder, workspace_id, item_id, channels("First", add=True)
                )
                created_id = next(
                    row.id for row in first.channels if row.channel == "tiktok"
                )
                await asyncio.wait_for(task, timeout=10)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            final = await service.get_content_item(observer, workspace_id, item_id)
            assert final.content_revision == 3
            assert [(row.channel, row.id) for row in final.channels] == [
                ("instagram", channel_id),
                ("tiktok", created_id),
            ]
            assert final.channels[0].copy_text_override == (
                "First" if entrypoint == "parent" else "Second"
            )
            if entrypoint == "parent":
                assert final.title == "Second"

    asyncio.run(run())


@pytest.mark.parametrize("first_writer", ["edit", "approval"])
def test_channel_edit_and_approval_use_same_lock_order(pg_sessionmaker, first_writer):
    async def run():
        async with pg_sessionmaker() as session:
            workspace_id, item_id, channel_id = await seed(session)
            request = await approval_service.submit_resource_for_approval(
                session,
                workspace_id,
                MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                item_id,
            )
            request_id = request.id
        async with (
            pg_sessionmaker() as holder,
            pg_sessionmaker() as waiter,
            pg_sessionmaker() as observer,
        ):
            await marketing_content.get_item(waiter, workspace_id, item_id)
            pid = await waiter.scalar(text("SELECT pg_backend_pid()"))
            await marketing_content.get_item_for_update(
                holder, item_id, workspace_id=workspace_id
            )
            if first_writer == "edit":
                task = asyncio.create_task(
                    approval_service.approve_request(waiter, workspace_id, request_id)
                )
            else:
                task = asyncio.create_task(
                    service.replace_channels(
                        waiter, workspace_id, item_id, channels("Edited")
                    )
                )
            try:
                await wait_until_blocked(observer, pid, task)
                if first_writer == "edit":
                    await service.replace_channels(
                        holder, workspace_id, item_id, channels("Edited")
                    )
                    with pytest.raises(
                        approval_service.ApprovalStaleResourceRevisionError
                    ):
                        await asyncio.wait_for(task, timeout=10)
                    await waiter.rollback()
                else:
                    await approval_service.approve_request(
                        holder, workspace_id, request_id
                    )
                    await asyncio.wait_for(task, timeout=10)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            final = await service.get_content_item(observer, workspace_id, item_id)
            assert final.content_revision == 2
            assert final.channels[0].id == channel_id
            assert final.status == MarketingContentItemStatus.draft
            assert final.approval_request_id is None
            assert final.approved_at is None
            history = await approval_service.get_approval_history(
                observer, workspace_id, request_id
            )
            assert [entry.decision.value for entry in history] == (
                ["submitted"]
                if first_writer == "edit"
                else ["submitted", "approved", "invalidated"]
            )

    asyncio.run(run())


def test_repository_reconciliation_serializes_concurrent_additions(pg_sessionmaker):
    async def run():
        async with pg_sessionmaker() as session:
            workspace_id, item_id, channel_id = await seed(session)
        async with (
            pg_sessionmaker() as holder,
            pg_sessionmaker() as waiter,
            pg_sessionmaker() as observer,
        ):
            await marketing_content.get_item(waiter, workspace_id, item_id)
            pid = await waiter.scalar(text("SELECT pg_backend_pid()"))
            first = await marketing_content.reconcile_channels(
                holder,
                item_id,
                [
                    {"channel": "instagram", "placement": "feed"},
                    {"channel": "tiktok"},
                ],
            )
            task = asyncio.create_task(
                marketing_content.reconcile_channels(
                    waiter,
                    item_id,
                    [
                        {"channel": "instagram", "placement": "feed"},
                        {"channel": "tiktok"},
                    ],
                )
            )
            try:
                await wait_until_blocked(observer, pid, task)
                await holder.commit()
                second = await asyncio.wait_for(task, timeout=10)
                await waiter.commit()
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            assert first.retained_channel_ids == (channel_id,)
            assert len(first.created_channel_ids) == 1
            assert (
                second.created_channel_ids
                == second.updated_channel_ids
                == second.removed_channel_ids
                == ()
            )
            assert second.retained_channel_ids == (
                channel_id,
                first.created_channel_ids[0],
            )
            assert second.material_change is False

    asyncio.run(run())


def test_postgres_foreign_key_failure_rolls_back_reconciliation(pg_sessionmaker):
    async def run():
        async with pg_sessionmaker() as session:
            workspace_id, item_id, channel_id = await seed(session)
            # Trigger a real FK violation while replacing an existing channel.
            with pytest.raises(IntegrityError):
                await marketing_content.reconcile_channels(
                    session,
                    item_id,
                    [
                        {"channel": "tiktok", "social_account_connection_id": uuid4()},
                    ],
                )
            await session.rollback()
        async with pg_sessionmaker() as session:
            item = await service.get_content_item(session, workspace_id, item_id)
            assert [(row.channel, row.id) for row in item.channels] == [
                ("instagram", channel_id)
            ]
            assert list(
                (await session.scalars(select(MarketingContentItemChannel.id))).all()
            ) == [channel_id]

    asyncio.run(run())


def test_parent_lock_is_workspace_scoped_and_noop_releases_it(pg_sessionmaker):
    async def run():
        async with pg_sessionmaker() as session:
            workspace_id, item_id, _channel_id = await seed(session)
        async with pg_sessionmaker() as holder, pg_sessionmaker() as waiter:
            await marketing_content.get_item_for_update(
                holder, item_id, workspace_id=workspace_id
            )
            outside = await asyncio.wait_for(
                marketing_content.get_item_for_update(
                    waiter, item_id, workspace_id=uuid4()
                ),
                timeout=2,
            )
            assert outside is None
            await holder.commit()
            await service.replace_channels(
                waiter, workspace_id, item_id, channels(None)
            )
            assert not waiter.in_transaction()
            locked = await asyncio.wait_for(
                marketing_content.get_item_for_update(
                    holder, item_id, workspace_id=workspace_id
                ),
                timeout=2,
            )
            assert locked is not None
            assert locked.content_revision == 1

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_repository_channel_mutation_waits_for_parent_removal(
    pg_sessionmaker, operation
):
    async def run():
        async with pg_sessionmaker() as session:
            workspace_id, item_id, channel_id = await seed(session)
        async with (
            pg_sessionmaker() as holder,
            pg_sessionmaker() as waiter,
            pg_sessionmaker() as observer,
        ):
            await marketing_content.get_item(waiter, workspace_id, item_id)
            pid = await waiter.scalar(text("SELECT pg_backend_pid()"))
            await marketing_content.get_item_for_update(holder, item_id)
            if operation == "update":
                mutation = marketing_content.update_channel(
                    waiter, channel_id, {"copy_text_override": "Too late"}
                )
            else:
                mutation = marketing_content.delete_channel(waiter, channel_id)
            task = asyncio.create_task(mutation)
            try:
                await wait_until_blocked(observer, pid, task)
                removed = await marketing_content.reconcile_channels(
                    holder, item_id, []
                )
                assert removed.removed_channel_ids == (channel_id,)
                await holder.commit()
                result = await asyncio.wait_for(task, timeout=10)
                assert result is (None if operation == "update" else False)
                await waiter.commit()
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            assert await observer.get(MarketingContentItemChannel, channel_id) is None

    asyncio.run(run())
