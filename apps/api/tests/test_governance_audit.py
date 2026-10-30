"""Regression evidence for the pre-provider governance audit."""

import asyncio
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from labelos_database.models import (
    AnalyticsProvider,
    CollectionRun,
    DatasetDocumentation,
    DatasetVersion,
    GovernanceActivity,
    RealtimeEvent,
)
from sqlalchemy import func, inspect, select, update
from sqlalchemy.exc import DBAPIError

from labelos_api.governance import (
    CollectionCheckpoint,
    CollectionRunCreate,
    CollectionRunProgress,
    CollectionRunTransition,
    DocumentationCreate,
    DocumentationTransition,
    SourceRegistration,
)
from labelos_api.repositories import analytics
from labelos_api.services.governance_service import (
    GovernanceConflict,
    GovernanceService,
)
from test_dataset_documentation import reviewable_datasheet
from test_dataset_versioning import metadata, transition
from test_governance import governance_db as governance_db
from test_governance import governed_version, prepare_governance_db
from test_governance import (
    test_version_history_runs_provenance_and_outbox as exercise_governance_history,
)


def migration_scripts():
    return ScriptDirectory.from_config(
        Config(
            str(Path(__file__).resolve().parents[3] / "packages/database/alembic.ini")
        )
    )


@pytest.mark.parametrize("conflicting", [False, True])
def test_concurrent_source_registration_reuses_canonical_registry(
    postgres_test_engine, monkeypatch, conflicting
):
    async def run():
        maker, workspace, user = await prepare_governance_db(postgres_test_engine)
        original = analytics.get_provider_by_key
        readers = 0
        ready = asyncio.Event()

        async def simultaneous_read(*args):
            nonlocal readers
            row = await original(*args)
            if row is None:
                readers += 1
                if readers == 2:
                    ready.set()
                await asyncio.wait_for(ready.wait(), 5)
            return row

        monkeypatch.setattr(analytics, "get_provider_by_key", simultaneous_read)

        async def register(name):
            async with maker() as session:
                service = GovernanceService(session, workspace, actor=user)
                try:
                    result = await service.register_source(
                        SourceRegistration(key="concurrent", display_name=name)
                    )
                    await session.commit()
                    return result.id
                except GovernanceConflict:
                    # Conflict-safe insertion keeps the caller transaction usable.
                    assert (
                        await session.scalar(
                            select(func.count()).select_from(AnalyticsProvider)
                        )
                        == 1
                    )
                    await session.commit()
                    return "conflict"

        results = await asyncio.gather(
            register("Source"), register("Other" if conflicting else "Source")
        )
        if conflicting:
            assert results.count("conflict") == 1
        else:
            assert results[0] == results[1]
        async with maker() as session:
            for model in (AnalyticsProvider, GovernanceActivity, RealtimeEvent):
                assert (
                    await session.scalar(select(func.count()).select_from(model)) == 1
                )

    asyncio.run(run())


@pytest.mark.parametrize("revision", ["202610120100", "202610120200", "202610120300"])
def test_downgrade_refuses_to_discard_history_before_mutating_schema(
    governance_db, revision
):
    maker, workspace, user = governance_db
    migration = migration_scripts().get_revision(revision).module

    async def run():
        async with maker() as session:
            service, _, dataset, _, _ = await governed_version(session, workspace, user)
            version = await service.create_version(dataset.id, metadata("reviewed"))
            await service.document_version(
                version.id,
                DocumentationCreate(
                    document=reviewable_datasheet(),
                    expected_revision=0,
                    change_reason="Review",
                ),
            )
            published = await service.transition_documentation(
                version.id,
                DocumentationTransition(
                    state="validated", expected_revision=1, change_reason="Validated"
                ),
            )
            await service.transition_version(version.id, transition())
            await session.commit()
            conn = await session.connection()

            def reject(sync):
                before = {
                    table: inspect(sync).get_columns(table)
                    for table in (
                        "dataset_versions",
                        "dataset_documentation",
                        "governance_activity",
                    )
                }
                with (
                    Operations.context(MigrationContext.configure(sync)),
                    pytest.raises(RuntimeError, match="history prevents downgrade"),
                ):
                    migration.downgrade()
                assert {
                    table: [c["name"] for c in inspect(sync).get_columns(table)]
                    for table in before
                } == {
                    table: [c["name"] for c in columns]
                    for table, columns in before.items()
                }

            await conn.run_sync(reject)
            assert await session.get(DatasetDocumentation, published.id) is published
            # Rejection also leaves immutability triggers installed.
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.execute(
                        update(DatasetVersion)
                        .where(DatasetVersion.id == version.id)
                        .values(version_key="tampered")
                    )

    asyncio.run(run())


def test_audit_indexes_roundtrip_preserves_populated_history(governance_db):
    maker, workspace, user = governance_db
    migration = migration_scripts().get_revision("202610130100").module

    async def run():
        async with maker() as session:
            _, _, _, version, doc = await governed_version(session, workspace, user)
            await session.commit()
            conn = await session.connection()

            def roundtrip(sync):
                with Operations.context(MigrationContext.configure(sync)):
                    migration.downgrade()
                    migration.upgrade()
                for name, table, columns in migration.INDEXES:
                    assert any(
                        i["name"] == name and i["column_names"] == columns
                        for i in inspect(sync).get_indexes(table)
                    )

            await conn.run_sync(roundtrip)
            await session.refresh(version)
            await session.refresh(doc)
            assert doc.version_id == version.id
            assert doc.document_sha256

    asyncio.run(run())


def test_postgres_checkpoint_compare_and_swap(postgres_test_engine):
    async def run():
        maker, workspace, user = await prepare_governance_db(postgres_test_engine)
        async with maker() as session:
            service, _, _, _, doc = await governed_version(session, workspace, user)
            collection = await service.create_run(
                CollectionRunCreate(documentation_id=doc.id, run_key="checkpoint-race")
            )
            await service.transition_run(
                collection.id, CollectionRunTransition(status="running")
            )
            await session.commit()
            identifier = collection.id

        async def checkpoint(count):
            async with maker() as session:
                service = GovernanceService(session, workspace, actor=user)
                try:
                    await service.checkpoint_run(
                        identifier,
                        CollectionRunProgress(
                            expected_revision=0,
                            records_seen=count,
                            records_written=count,
                            records_rejected=0,
                            checkpoint=CollectionCheckpoint(offset=count),
                        ),
                    )
                    await session.commit()
                    return "committed"
                except GovernanceConflict:
                    await session.rollback()
                    return "conflict"

        assert sorted(await asyncio.gather(checkpoint(10), checkpoint(20))) == [
            "committed",
            "conflict",
        ]
        async with maker() as session:
            saved = await session.get(CollectionRun, identifier)
            assert saved.progress_revision == 1
            assert saved.records_written in (10, 20)
            assert saved.checkpoint["offset"] == saved.records_written
            for model in (GovernanceActivity, RealtimeEvent):
                assert (
                    await session.scalar(select(func.count()).select_from(model)) == 7
                )

    asyncio.run(run())


def test_postgres_governance_behavior_on_full_migration_chain(postgres_test_engine):
    scripts = migration_scripts()

    def migrate(connection):
        with Operations.context(MigrationContext.configure(connection)):
            for revision in reversed(list(scripts.walk_revisions())):
                revision.module.upgrade()

    async def prepare():
        async with postgres_test_engine.begin() as connection:
            await connection.run_sync(migrate)
        # create_all only checks existing tables here; all governance DDL and
        # triggers came from migrations, not metadata-created test fixtures.
        return await prepare_governance_db(postgres_test_engine)

    exercise_governance_history(asyncio.run(prepare()))
