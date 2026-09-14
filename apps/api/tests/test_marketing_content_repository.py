import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone

import pytest
from labelos_database.base import Base
from labelos_database.models import (
    Campaign,
    MarketingContentItem,
    MarketingContentItemChannel,
    Organization,
    User,
)
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labelos_api.repositories import marketing_content


@pytest.fixture
def sessionmaker(database_test_engine) -> Iterator[async_sessionmaker[AsyncSession]]:
    engine = database_test_engine

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record):
        if engine.dialect.name == "sqlite":
            connection.execute("PRAGMA foreign_keys=ON")

    async def prepare():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())
    yield async_sessionmaker(engine, expire_on_commit=False)


async def seed_item(session):
    workspace = Organization(
        name="Label", slug="label", owner=User(email="label@test.com")
    )
    campaign = Campaign(name="Launch", organization=workspace)
    item = MarketingContentItem(
        organization=workspace,
        campaign=campaign,
        title="Post",
        content_type="image",
        channels=[
            MarketingContentItemChannel(channel="instagram", placement="feed"),
            MarketingContentItemChannel(channel="threads", placement="default"),
        ],
    )
    session.add(item)
    await session.commit()
    return item


def test_reconciliation_identifies_removals_before_mutation_and_preserves_ids(
    sessionmaker,
):
    async def run():
        async with sessionmaker() as session:
            item = await seed_item(session)
            original = {row.channel: row.id for row in item.channels}
            plan = marketing_content.plan_channel_reconciliation(
                item,
                [
                    {"channel": "tiktok"},
                    {
                        "channel": "instagram",
                        "placement": "feed",
                        "copy_text_override": "Edit",
                    },
                ],
            )
            assert tuple(row.id for row in plan.removed) == (original["threads"],)
            assert item.channels[0].copy_text_override is None
            assert (
                await session.get(MarketingContentItemChannel, original["threads"])
                is not None
            )
            result = await marketing_content.apply_channel_reconciliation(session, plan)
            assert result.retained_channel_ids == (original["instagram"],)
            assert result.updated_channel_ids == (original["instagram"],)
            assert result.removed_channel_ids == (original["threads"],)
            assert len(result.created_channel_ids) == 1
            assert result.created_channel_ids[0] not in original.values()
            assert result.material_change is True
            await session.commit()
            rows = list(
                (await session.scalars(select(MarketingContentItemChannel))).all()
            )
            assert {row.id for row in rows} == {
                original["instagram"],
                result.created_channel_ids[0],
            }
            # The legacy repository function still returns rows, in logical order.
            rows = await marketing_content.replace_channels(
                session,
                item.id,
                [
                    {"channel": "tiktok"},
                    {
                        "channel": "instagram",
                        "placement": "feed",
                        "copy_text_override": "Edit",
                    },
                ],
            )
            assert [row.channel for row in rows] == ["instagram", "tiktok"]
            assert rows[0].id == original["instagram"]
            assert rows[1].id == result.created_channel_ids[0]

    asyncio.run(run())


@pytest.mark.parametrize(
    ("field", "value", "material"),
    [
        ("copy_text_override", "New copy", True),
        ("scheduled_at", datetime(2026, 10, 1, tzinfo=UTC), True),
        ("asset_refs", [{"id": "asset"}], True),
        ("metadata_json", {"hashtags": ["launch"]}, True),
        ("published_at", datetime(2026, 10, 1, tzinfo=UTC), False),
        ("external_post_id", "post-123", False),
        ("external_url", "https://example.com/post", False),
    ],
)
def test_reconciliation_classifies_updates_and_clears_omitted_values(
    sessionmaker, field, value, material
):
    async def run():
        async with sessionmaker() as session:
            item = await seed_item(session)
            item_id = item.id
            channel_id = item.channels[0].id
            values = [
                {"channel": "instagram", "placement": "feed", field: value},
                {"channel": "threads"},
            ]
            result = await marketing_content.reconcile_channels(
                session, item_id, values
            )
            assert result.retained_channel_ids[0] == channel_id
            assert result.updated_channel_ids == (channel_id,)
            assert result.created_channel_ids == result.removed_channel_ids == ()
            assert result.material_change is material
            await session.commit()
            session.expire_all()
            if isinstance(value, datetime):
                values[0][field] = value.astimezone(tz=timezone(timedelta(hours=2)))
            noop = await marketing_content.reconcile_channels(session, item_id, values)
            assert noop.updated_channel_ids == ()
            assert noop.material_change is False
            cleared = await marketing_content.reconcile_channels(
                session,
                item_id,
                [
                    {"channel": "instagram", "placement": "feed"},
                    {"channel": "threads"},
                ],
            )
            assert cleared.updated_channel_ids == (channel_id,)
            assert cleared.material_change is material

    asyncio.run(run())


def test_reconciliation_noop_order_duplicates_and_ownership(sessionmaker):
    async def run():
        async with sessionmaker() as session:
            item = await seed_item(session)
            item_id = item.id
            ids = tuple(row.id for row in item.channels)
            result = await marketing_content.reconcile_channels(
                session,
                item_id,
                [
                    {"channel": "threads"},
                    {"channel": "instagram", "placement": "feed"},
                ],
            )
            assert result.retained_channel_ids == ids
            assert (
                result.created_channel_ids
                == result.updated_channel_ids
                == result.removed_channel_ids
                == ()
            )
            assert result.material_change is False
            for values in (
                [
                    {"channel": "threads"},
                    {"channel": "threads", "placement": "default"},
                ],
                [{"channel": "threads", "marketing_content_item_id": item_id}],
                [{"channel": "threads", "organization_id": item.organization_id}],
            ):
                with pytest.raises(ValueError):
                    await marketing_content.reconcile_channels(session, item_id, values)
            assert tuple(row.id for row in item.channels) == ids

    asyncio.run(run())


def test_reconciliation_empty_replacement_explicitly_removes_all_channels(sessionmaker):
    async def run():
        async with sessionmaker() as session:
            item = await seed_item(session)
            ids = tuple(row.id for row in item.channels)
            result = await marketing_content.reconcile_channels(session, item.id, [])
            assert result.removed_channel_ids == ids
            assert (
                result.retained_channel_ids
                == result.created_channel_ids
                == result.updated_channel_ids
                == ()
            )
            assert result.material_change is True
            await session.commit()
            assert (
                list((await session.scalars(select(MarketingContentItemChannel))).all())
                == []
            )

    asyncio.run(run())
