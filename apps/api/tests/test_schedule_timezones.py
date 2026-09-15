from datetime import UTC, datetime

import pytest

from labelos_api.scheduling.timezones import (
    ScheduleValidationError,
    authoring_zone,
    instant_to_local,
    resolve_local_time,
    schedule_values,
    utc_instant,
)


@pytest.mark.parametrize(
    "zone,expected",
    [
        ("UTC", "2027-06-15T09:30:00+00:00"),
        ("America/Los_Angeles", "2027-06-15T16:30:00+00:00"),
        ("America/New_York", "2027-06-15T13:30:00+00:00"),
        ("Asia/Kathmandu", "2027-06-15T03:45:00+00:00"),
    ],
)
def test_normal_and_round_trip(zone, expected):
    result = resolve_local_time("2027-06-15T09:30", zone)
    assert result.scheduled_at.isoformat() == expected
    assert instant_to_local(result.scheduled_at, zone) == result
    assert result.schedule_local_time == "2027-06-15T09:30:00"


@pytest.mark.parametrize("zone", ["America/New_York", "America/Los_Angeles"])
def test_gap_and_fold(zone):
    for choice in (None, "earlier", "later"):
        with pytest.raises(ScheduleValidationError) as error:
            resolve_local_time("2026-03-08T02:30", zone, choice)
        assert error.value.code == "nonexistent_local_time"
    with pytest.raises(ScheduleValidationError) as error:
        resolve_local_time("2026-11-01T01:30", zone)
    assert error.value.code == "disambiguation_required"
    earlier = resolve_local_time("2026-11-01T01:30", zone, "earlier")
    later = resolve_local_time("2026-11-01T01:30", zone, "later")
    assert (later.scheduled_at - earlier.scheduled_at).total_seconds() == 3600
    assert earlier.schedule_local_time == later.schedule_local_time
    assert (
        resolve_local_time(
            "2026-11-01T01:30", zone, offset_seconds=later.schedule_offset_seconds
        )
        == later
    )
    assert earlier.scheduled_at.hour == (5 if zone == "America/New_York" else 8)


@pytest.mark.parametrize(
    "zone,code",
    [
        (None, "timezone_required"),
        ("", "timezone_required"),
        ("PST", "invalid_timezone"),
        ("EST", "invalid_timezone"),
        ("America/Invalid", "invalid_timezone"),
        ("+05:30", "invalid_timezone"),
    ],
)
def test_zone_errors(zone, code):
    with pytest.raises(ScheduleValidationError) as error:
        authoring_zone(zone)
    assert error.value.code == code


@pytest.mark.parametrize(
    "value,code",
    [
        ("garbage", "invalid_timestamp"),
        ("2027-06-15T09:30", "timestamp_timezone_required"),
        (datetime(2027, 6, 15), "timestamp_timezone_required"),
    ],
)
def test_timestamp_errors(value, code):
    with pytest.raises(ScheduleValidationError) as error:
        utc_instant(value)
    assert error.value.code == code


@pytest.mark.parametrize(
    "local", ["2027-02-30T09:30", "2027-01-01", "2027-01-01T09:30Z"]
)
def test_malformed_local_time(local):
    with pytest.raises(ScheduleValidationError) as error:
        resolve_local_time(local, "UTC")
    assert error.value.code == "invalid_local_time"


def test_offset_and_instant_mismatches():
    with pytest.raises(ScheduleValidationError) as error:
        resolve_local_time("2026-11-01T01:30", "America/New_York", "earlier", -18000)
    assert error.value.code == "timezone_instant_mismatch"
    with pytest.raises(ScheduleValidationError) as error:
        schedule_values(
            scheduled_at=datetime(2027, 6, 15, tzinfo=UTC),
            schedule_timezone="UTC",
            schedule_local_time="2027-06-15T09:30",
            schedule_disambiguation=None,
            schedule_offset_seconds=None,
        )
    assert error.value.code == "timezone_instant_mismatch"


def test_legacy_timestamp_remains_unconfirmed():
    values = schedule_values(
        scheduled_at=datetime(2026, 1, 1, tzinfo=UTC),
        schedule_timezone=None,
        schedule_local_time=None,
        schedule_disambiguation=None,
        schedule_offset_seconds=None,
    )
    assert values["schedule_timezone"] is None
    assert values["schedule_local_time"] is None
    assert values["schedule_offset_seconds"] is None


def test_postgres_schedule_migration_round_trip(postgres_test_engine):
    import asyncio
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = (
        Path(__file__).resolve().parents[3]
        / "packages/database/alembic/versions/202609151000_channel_schedule_timezone.py"
    )
    spec = importlib.util.spec_from_file_location("schedule_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def check(connection):
        connection.exec_driver_sql(
            "CREATE TABLE marketing_content_item_channels "
            "(id TEXT PRIMARY KEY, scheduled_at TIMESTAMPTZ)"
        )
        connection.exec_driver_sql(
            "INSERT INTO marketing_content_item_channels "
            "VALUES ('legacy', '2026-01-01T12:00:00Z')"
        )
        with Operations.context(MigrationContext.configure(connection)):
            for operation in (
                migration.upgrade,
                migration.downgrade,
                migration.upgrade,
            ):
                operation()
                assert connection.exec_driver_sql(
                    "SELECT scheduled_at FROM marketing_content_item_channels"
                ).scalar_one() == datetime(2026, 1, 1, 12, tzinfo=UTC)
        assert connection.exec_driver_sql(
            "SELECT schedule_timezone, schedule_local_time, schedule_offset_seconds, "
            "schedule_generation FROM marketing_content_item_channels"
        ).one() == (None, None, None, 1)

    async def run():
        async with postgres_test_engine.begin() as connection:
            await connection.run_sync(check)

    asyncio.run(run())


def test_migration_preserves_legacy_data_on_upgrade_downgrade_reupgrade(
    tmp_path, monkeypatch
):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect

    path = tmp_path / "schedule-migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    config = Config(
        str(Path(__file__).resolve().parents[3] / "packages/database/alembic.ini")
    )
    assert ScriptDirectory.from_config(config).get_heads() == ["202609151800"]
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE marketing_content_item_channels "
            "(id TEXT PRIMARY KEY, scheduled_at DATETIME)"
        )
        connection.exec_driver_sql(
            "INSERT INTO marketing_content_item_channels "
            "VALUES ('legacy', '2026-01-01 12:00:00')"
        )
    command.stamp(config, "202609061800")
    for direction, revision in [
        (command.upgrade, "202609151000"),
        (command.downgrade, "202609061800"),
        (command.upgrade, "202609151000"),
    ]:
        direction(config, revision)
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    "SELECT scheduled_at FROM marketing_content_item_channels"
                ).scalar_one()
                == "2026-01-01 12:00:00"
            )
            names = {
                column["name"]
                for column in inspect(connection).get_columns(
                    "marketing_content_item_channels"
                )
            }
            if revision == "202609151000":
                assert connection.exec_driver_sql(
                    "SELECT schedule_timezone, schedule_local_time, "
                    "schedule_offset_seconds FROM marketing_content_item_channels"
                ).one() == (None, None, None)
            else:
                assert "schedule_timezone" not in names
    engine.dispose()
