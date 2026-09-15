import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

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


@pytest.mark.parametrize("identity_field", ["channel", "placement"])
def test_explicit_identity_retains_edits_and_replaces_logical_changes(
    sessionmaker, identity_field
):
    async def run():
        async with sessionmaker() as session:
            item = await seed_item(session)
            item_id = item.id
            instagram, threads = item.channels
            original_ids = (instagram.id, threads.id)
            values = [
                {"id": threads.id, "channel": "threads"},
                {
                    "id": instagram.id,
                    "channel": "instagram",
                    "placement": "feed",
                    "copy_text_override": "Edit",
                },
            ]
            edited = await marketing_content.reconcile_channels(
                session, item_id, values
            )
            assert edited.retained_channel_ids == original_ids
            assert edited.updated_channel_ids == (instagram.id,)
            assert edited.created_channel_ids == edited.removed_channel_ids == ()
            values[1][identity_field] = (
                "tiktok" if identity_field == "channel" else "story"
            )
            replaced = await marketing_content.reconcile_channels(
                session, item_id, values
            )
            assert replaced.retained_channel_ids == (threads.id,)
            assert replaced.removed_channel_ids == (instagram.id,)
            assert len(replaced.created_channel_ids) == 1
            assert replaced.created_channel_ids[0] not in original_ids
            assert replaced.material_change

    asyncio.run(run())


def test_reconciliation_validates_ids_against_parent_and_rejects_double_claims(
    sessionmaker,
):
    async def run():
        async with sessionmaker() as session:
            item = await seed_item(session)
            instagram, threads = item.channels
            other = MarketingContentItem(
                organization_id=item.organization_id,
                campaign_id=item.campaign_id,
                title="Other parent",
                content_type="image",
                channels=[
                    MarketingContentItemChannel(channel="instagram", placement="feed")
                ],
            )
            session.add(other)
            await session.commit()
            for invalid_id in (uuid4(), other.channels[0].id):
                with pytest.raises(ValueError, match="does not belong"):
                    marketing_content.plan_channel_reconciliation(
                        item,
                        [
                            {
                                "id": invalid_id,
                                "channel": "instagram",
                                "placement": "feed",
                            }
                        ],
                    )
            for second in (
                {"id": instagram.id, "channel": "tiktok"},
                {"channel": "instagram", "placement": "feed"},
            ):
                with pytest.raises(ValueError, match="more than once"):
                    marketing_content.plan_channel_reconciliation(
                        item,
                        [
                            {
                                "id": instagram.id,
                                "channel": "instagram",
                                "placement": "story",
                            },
                            second,
                        ],
                    )
            assert [row.id for row in item.channels] == [instagram.id, threads.id]

    asyncio.run(run())


def test_timezone_reconciliation_result_retains_identity_and_advances_generation(
    sessionmaker,
):
    async def run():
        async with sessionmaker() as session:
            item = await seed_item(session)
            item_id = item.id
            rows = list(item.channels)
            values = [
                {
                    "id": row.id,
                    **{
                        field: getattr(row, field)
                        for field in marketing_content.CHANNEL_VALUE_FIELDS
                    },
                }
                for row in rows
            ]
            values[0].update(
                schedule_timezone="UTC",
                schedule_local_time="2027-06-15T09:30:00",
                schedule_offset_seconds=0,
                scheduled_at=datetime(2027, 6, 15, 9, 30, tzinfo=UTC),
            )
            result = await marketing_content.reconcile_channels(
                session, item_id, values
            )
            assert result.updated_channel_ids == (rows[0].id,)
            assert result.retained_channel_ids == tuple(row.id for row in rows)
            assert result.created_channel_ids == result.removed_channel_ids == ()
            assert result.material_change
            assert rows[0].schedule_generation == 2

            assert rows[1].schedule_generation == 1
            result = await marketing_content.reconcile_channels(
                session, item_id, values
            )
            assert result.updated_channel_ids == ()
            assert not result.material_change
            assert rows[0].schedule_generation == 2

            await marketing_content.update_channel(
                session, rows[0].id, {"schedule_timezone": "Etc/UTC"}
            )
            assert rows[0].schedule_generation == 3
            await marketing_content.update_channel(
                session, rows[0].id, {"schedule_timezone": "Etc/UTC"}
            )
            assert rows[0].schedule_generation == 3

    asyncio.run(run())


def test_explicit_id_swap_releases_unique_keys_and_rolls_back_without_commit(
    sessionmaker,
):
    async def run():
        async with sessionmaker() as session:
            item = await seed_item(session)
            item_id, workspace_id = item.id, item.organization_id
            instagram, threads = item.channels
            original_ids = (instagram.id, threads.id)
            result = await marketing_content.reconcile_channels(
                session,
                item_id,
                [
                    {"id": instagram.id, "channel": "threads"},
                    {"id": threads.id, "channel": "instagram", "placement": "feed"},
                ],
            )
            assert result.removed_channel_ids == original_ids
            assert len(result.created_channel_ids) == 2
            assert result.retained_channel_ids == result.updated_channel_ids == ()
            await session.rollback()
            restored = await marketing_content.get_item(session, workspace_id, item_id)
            assert tuple(row.id for row in restored.channels) == original_ids

    asyncio.run(run())
