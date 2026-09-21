import asyncio
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from labelos_database.base import Base
from labelos_database.models import SchedulingExecutionControl
from sqlalchemy import inspect


def test_execution_control_migration_round_trip(database_test_engine):
    root = Path(__file__).resolve().parents[3]
    scripts = ScriptDirectory.from_config(
        Config(str(root / "packages/database/alembic.ini"))
    )
    revision = scripts.get_revision("202609152100")
    assert scripts.get_heads() == ["202609210100"]
    assert scripts.get_revision("202609162200").down_revision == revision.revision
    assert revision.down_revision == "202609152000"

    def check(connection):
        Base.metadata.create_all(connection)
        with Operations.context(MigrationContext.configure(connection)):
            revision.module.downgrade()
            assert not inspect(connection).has_table("scheduling_execution_controls")
            revision.module.upgrade()
            columns = inspect(connection).get_columns("scheduling_execution_controls")
            enabled = next(c for c in columns if c["name"] == "execution_enabled")
            assert not enabled["nullable"]
            assert enabled["default"] in ("false", "0")
            assert (
                connection.execute(SchedulingExecutionControl.__table__.select()).all()
                == []
            )
            revision.module.downgrade()
            revision.module.upgrade()

    async def run():
        async with database_test_engine.begin() as connection:
            await connection.run_sync(check)

    asyncio.run(run())
