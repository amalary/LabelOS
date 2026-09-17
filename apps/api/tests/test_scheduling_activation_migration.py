import asyncio
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from labelos_database.base import Base
from labelos_database.bootstrap import seed_system_roles_and_capabilities
from sqlalchemy import text


def test_schedule_permission_migration_round_trip(database_test_engine):
    root = Path(__file__).resolve().parents[3]
    scripts = ScriptDirectory.from_config(
        Config(str(root / "packages/database/alembic.ini"))
    )
    revision = scripts.get_revision("202609152000")
    assert scripts.get_revision("202609152100").down_revision == revision.revision
    assert revision.down_revision == "202609151800"

    def check(connection):
        Base.metadata.create_all(connection)
        seed_system_roles_and_capabilities(connection)
        with Operations.context(MigrationContext.configure(connection)):
            # Simulate the existing role catalog before this permission existed.
            revision.module.downgrade()
            for _ in range(2):
                revision.module.upgrade()
            rows = connection.execute(text("""
                SELECT r.key FROM roles r
                JOIN role_capabilities rc ON rc.role_id = r.id
                JOIN capabilities c ON c.id = rc.capability_id
                WHERE c.key = 'marketing.content.schedule'
            """)).scalars().all()
            assert sorted(rows) == ["admin", "manager", "marketing", "owner"]
            assert connection.scalar(text("SELECT count(*) FROM scheduling_jobs")) == 0
            revision.module.downgrade()
            assert connection.scalar(text("""
                SELECT count(*) FROM capabilities
                WHERE key = 'marketing.content.schedule'
            """)) == 0
            revision.module.upgrade()

    async def run():
        async with database_test_engine.begin() as connection:
            await connection.run_sync(check)

    asyncio.run(run())
