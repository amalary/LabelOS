"""Collection attempt lifecycle shared by authenticated APIs and future workers."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from labelos_database.models import CollectionRun, GovernanceActivity, RealtimeEvent
from pydantic import ValidationError
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError

from labelos_api.governance import (
    CollectionCheckpoint,
    CollectionRunCreate,
    CollectionRunProgress,
    CollectionRunTransition,
)
from labelos_api.services.governance_service import (
    GovernanceConflict,
    GovernanceService,
)
from test_governance import governance_db as _governance_db
from test_governance import governed_version

governance_db = _governance_db


@pytest.mark.parametrize(
    "status", ["completed", "succeeded", "partially_completed", "failed", "cancelled"]
)
def test_completion_is_immutable_and_idempotent(governance_db, status):
    maker, workspace_id, user_id = governance_db

    async def exercise():
        async with maker() as session:
            service, source, _, version, doc = await governed_version(
                session, workspace_id, user_id
            )
            run = await service.create_run(
                CollectionRunCreate(
                    documentation_id=doc.id, run_key="attempt", job_id=uuid4()
                )
            )
            assert run.source_id == source.id and run.version_id == version.id
            with pytest.raises(GovernanceConflict):
                await service.transition_run(
                    run.id, CollectionRunTransition(status="completed")
                )
            await service.transition_run(
                run.id, CollectionRunTransition(status="running")
            )
            progress = CollectionRunProgress(
                expected_revision=0,
                records_seen=4,
                records_written=2,
                records_rejected=1,
                checkpoint=CollectionCheckpoint(offset=4, page=1),
            )
            await service.checkpoint_run(run.id, progress)
            with pytest.raises(GovernanceConflict):
                await service.checkpoint_run(run.id, progress)
            with pytest.raises(GovernanceConflict):
                await service.transition_run(
                    run.id, CollectionRunTransition(status="completed")
                )
            outcome = CollectionRunTransition(
                status=status,
                records_seen=5,
                records_written=3,
                records_rejected=1,
                error_code=(
                    "invalid_data"
                    if status in {"failed", "partially_completed"}
                    else None
                ),
            )
            await service.transition_run(run.id, outcome)
            end = run.completed_at
            await session.commit()
            before = await session.scalar(
                select(func.count()).select_from(GovernanceActivity)
            )
            assert (await service.transition_run(run.id, outcome)).completed_at.replace(
                tzinfo=UTC
            ) == end.replace(tzinfo=UTC)
            assert (
                await session.scalar(
                    select(func.count()).select_from(GovernanceActivity)
                )
                == before
            )
            assert (
                await session.scalar(select(func.count()).select_from(RealtimeEvent))
                == before
            )
            with pytest.raises(GovernanceConflict):
                await service.transition_run(
                    run.id, outcome.model_copy(update={"records_seen": 6})
                )
            with pytest.raises(GovernanceConflict):
                await service.checkpoint_run(
                    run.id, progress.model_copy(update={"expected_revision": 1})
                )
            with pytest.raises(GovernanceConflict):
                await service.transition_run(
                    run.id, CollectionRunTransition(status="running")
                )
            for statement in (
                delete(CollectionRun).where(CollectionRun.id == run.id),
                update(CollectionRun)
                .where(CollectionRun.id == run.id)
                .values(records_seen=99),
                update(CollectionRun)
                .where(CollectionRun.id == run.id)
                .values(job_id=uuid4()),
            ):
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.execute(statement)

    asyncio.run(exercise())


def test_retry_attempts_preserve_history_checkpoint_and_budget(governance_db):
    maker, workspace_id, user_id = governance_db

    async def exercise():
        async with maker() as session:
            service, _, _, _, doc = await governed_version(
                session, workspace_id, user_id
            )
            first = await service.create_run(
                CollectionRunCreate(
                    documentation_id=doc.id, run_key="first", max_attempts=2
                )
            )
            retry_payload = CollectionRunCreate(
                documentation_id=doc.id,
                run_key="second",
                retry_of_id=first.id,
                max_attempts=2,
            )
            with pytest.raises(GovernanceConflict):
                await service.create_run(retry_payload)
            await service.transition_run(
                first.id, CollectionRunTransition(status="running")
            )
            await service.checkpoint_run(
                first.id,
                CollectionRunProgress(
                    expected_revision=0,
                    records_seen=3,
                    records_written=2,
                    records_rejected=1,
                    checkpoint=CollectionCheckpoint(offset=3),
                ),
            )
            await service.transition_run(
                first.id,
                CollectionRunTransition(
                    status="partially_completed",
                    records_seen=3,
                    records_written=2,
                    records_rejected=1,
                    error_code="rate_limited",
                ),
            )
            second = await service.create_run(retry_payload)
            assert (await service.create_run(retry_payload)).id == second.id
            assert second.attempt == 2 and second.records_seen == 0
            assert second.checkpoint == first.checkpoint
            assert first.status == "partially_completed" and first.records_seen == 3
            with pytest.raises(GovernanceConflict):
                await service.create_run(
                    retry_payload.model_copy(update={"run_key": "fork"})
                )
            await service.transition_run(
                second.id, CollectionRunTransition(status="running")
            )
            await service.transition_run(
                second.id,
                CollectionRunTransition(
                    status="failed", error_code="provider_unavailable"
                ),
            )
            with pytest.raises(GovernanceConflict):
                await service.create_run(
                    retry_payload.model_copy(
                        update={"run_key": "third", "retry_of_id": second.id}
                    )
                )
            assert len(await service.list_records(CollectionRun)) == 2
            await session.commit()

    asyncio.run(exercise())


def test_delayed_start_cancellation_and_transaction_rollback(governance_db):
    maker, workspace_id, user_id = governance_db

    async def exercise():
        async with maker() as session:
            service, _, _, _, doc = await governed_version(
                session, workspace_id, user_id
            )
            run = await service.create_run(
                CollectionRunCreate(
                    documentation_id=doc.id,
                    run_key="delayed",
                    not_before=datetime.now(UTC) + timedelta(hours=1),
                )
            )
            with pytest.raises(GovernanceConflict):
                await service.transition_run(
                    run.id, CollectionRunTransition(status="running")
                )
            await service.transition_run(
                run.id, CollectionRunTransition(status="cancelled")
            )
            assert run.started_at is None and run.completed_at is not None
            active = await service.create_run(
                CollectionRunCreate(documentation_id=doc.id, run_key="active")
            )
            await service.transition_run(
                active.id, CollectionRunTransition(status="running")
            )
            identifier = active.id
            await session.commit()
            count = await session.scalar(
                select(func.count()).select_from(GovernanceActivity)
            )
            await service.checkpoint_run(
                identifier,
                CollectionRunProgress(
                    expected_revision=0,
                    records_seen=10,
                    records_written=9,
                    records_rejected=1,
                    checkpoint=CollectionCheckpoint(offset=10),
                ),
            )
            await session.rollback()
        async with maker() as session:
            service = GovernanceService(session, workspace_id, actor=user_id)
            persisted = await service.get_record(CollectionRun, identifier)
            assert (
                persisted.records_seen == 0
                and persisted.progress_revision == 0
                and persisted.checkpoint is None
            )
            assert (
                await session.scalar(
                    select(func.count()).select_from(GovernanceActivity)
                )
                == count
            )
            assert (
                await session.scalar(select(func.count()).select_from(RealtimeEvent))
                == count
            )

    asyncio.run(exercise())


def test_sensitive_payloads_are_not_accepted_as_checkpoints_or_errors():
    for payload in (
        {"access_token": "secret"},
        {"offset": "secret"},
        {"cursor_reference": "https://user:password@example.com"},
    ):
        with pytest.raises(ValidationError):
            CollectionCheckpoint.model_validate(payload)
    with pytest.raises(ValidationError):
        CollectionRunTransition(status="failed", error_code="Bearer secret")
    with pytest.raises(ValidationError):
        CollectionRunTransition(status="partially_completed", error_code="invalid_data")


def test_tracking_migration_preserves_populated_history(governance_db):
    from pathlib import Path

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    from labelos_database.models import DatasetTransformation

    from labelos_api.governance import TransformationCreate, VersionCreate

    maker, workspace_id, user_id = governance_db
    scripts = ScriptDirectory.from_config(
        Config(
            str(Path(__file__).resolve().parents[3] / "packages/database/alembic.ini")
        )
    )
    migration = scripts.get_revision("202610120400").module

    def roundtrip(connection):
        with Operations.context(MigrationContext.configure(connection)):
            provenance = scripts.get_revision("202610120500").module
            provenance.downgrade()
            migration.downgrade()
            migration.upgrade()
            provenance.upgrade()

    async def exercise():
        async with maker() as session:
            service, _, dataset, version, doc = await governed_version(
                session, workspace_id, user_id
            )
            run = await service.create_run(
                CollectionRunCreate(documentation_id=doc.id, run_key="historical")
            )
            await service.transition_run(
                run.id, CollectionRunTransition(status="running")
            )
            await service.transition_run(
                run.id,
                CollectionRunTransition(
                    status="succeeded", records_seen=4, records_written=4
                ),
            )
            output = await service.create_version(
                dataset.id, VersionCreate(version_key="derived")
            )
            transformation = await service.record_transformation(
                TransformationCreate(
                    output_version_id=output.id,
                    input_version_ids=[version.id],
                    collection_run_id=run.id,
                    name="normalize",
                    code_reference="git:test",
                    description="Aggregate",
                )
            )
            identifier, transform_id = run.id, transformation.id
            await session.commit()
        async with maker.kw["bind"].begin() as connection:
            await connection.run_sync(roundtrip)
        async with maker() as session:
            saved = await session.get(CollectionRun, identifier)
            assert saved.status == "succeeded" and saved.records_written == 4
            assert saved.attempt == 1 and saved.progress_revision == 0
            assert (
                await session.get(DatasetTransformation, transform_id)
            ).collection_run_id == identifier
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.execute(
                        delete(CollectionRun).where(CollectionRun.id == identifier)
                    )

    asyncio.run(exercise())


def test_postgres_concurrent_completions_and_retries(postgres_test_engine):
    from test_governance import prepare_governance_db

    async def exercise():
        maker, workspace_id, user_id = await prepare_governance_db(postgres_test_engine)
        async with maker() as session:
            service, _, _, _, doc = await governed_version(
                session, workspace_id, user_id
            )
            run = await service.create_run(
                CollectionRunCreate(
                    documentation_id=doc.id, run_key="concurrent-finish"
                )
            )
            await service.transition_run(
                run.id, CollectionRunTransition(status="running")
            )
            identifier, documentation_id = run.id, doc.id
            await session.commit()

        async def complete():
            async with maker() as session:
                service = GovernanceService(session, workspace_id, actor=user_id)
                result = await service.transition_run(
                    identifier,
                    CollectionRunTransition(status="failed", error_code="rate_limited"),
                )
                await session.commit()
                return result.completed_at

        ends = await asyncio.gather(complete(), complete())
        assert ends[0] == ends[1]

        async def retry():
            async with maker() as session:
                service = GovernanceService(session, workspace_id, actor=user_id)
                result = await service.create_run(
                    CollectionRunCreate(
                        documentation_id=documentation_id,
                        run_key="same-retry",
                        retry_of_id=identifier,
                    )
                )
                await session.commit()
                return result.id

        identifiers = await asyncio.gather(retry(), retry())
        assert identifiers[0] == identifiers[1]
        async with maker() as session:
            assert (
                await session.scalar(select(func.count()).select_from(CollectionRun))
                == 2
            )
            assert (
                await session.scalar(
                    select(func.count()).select_from(GovernanceActivity)
                )
                == 8
            )
            assert (
                await session.scalar(select(func.count()).select_from(RealtimeEvent))
                == 8
            )

    asyncio.run(exercise())
