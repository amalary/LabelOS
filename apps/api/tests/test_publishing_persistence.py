import asyncio
import hashlib
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from labelos_database.base import Base
from labelos_database.models import (
    ApprovalRequest,
    MarketingContentItem,
    MarketingContentItemChannel,
    Organization,
    Publication,
    PublicationAttempt,
    PublicationLease,
    PublicationTransition,
    RealtimeEvent,
    SchedulingJob,
    SocialAccountConnection,
)
from labelos_database.publishing import (
    OPERATIONS,
    OUTCOMES,
    REASONS,
    SOURCES,
    STATES,
    PublicResourceURL,
)
from sqlalchemy import delete, event, func, inspect, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from labelos_api.publishing import contracts as domain
from labelos_api.repositories.publishing import (
    PublicationConflict,
    PublicationRepository,
    aggregate,
)
from labelos_api.repositories.scheduling import snapshot_for
from labelos_api.scheduling.payload import (
    canonical_json,
    envelope,
    fingerprint,
    prepare_request,
)
from test_scheduling_persistence import NOW, job_for, source


@pytest.fixture
def sessions(database_test_engine):
    engine = database_test_engine
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def setup(connection, _):
            connection.isolation_level = None
            connection.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(engine.sync_engine, "begin")
        def begin(connection):
            connection.exec_driver_sql("BEGIN")

    async def prepare():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())
    return async_sessionmaker(engine, expire_on_commit=False)


async def seed(session, *, persist=True):
    item, approval, user = await source(session)
    connection = SocialAccountConnection(
        organization_id=item.organization_id,
        provider="instagram",
        connection_method="assisted",
    )
    session.add(connection)
    await session.flush()
    item.channels[0].social_account_connection_id = connection.id
    job = job_for(item, approval, user, social_account_connection_id=connection.id)
    session.add(job)
    await session.flush()
    request = prepare_request(
        snapshot=snapshot_for(job),
        job_id=job.id,
        destination_id=connection.id,
        artist_profile_id=None,
        authoring_timezone="UTC",
        correlation_id=uuid4(),
        item=item,
        channel=item.channels[0],
        asset_bytes={},
    )
    repository = PublicationRepository(session, job.workspace_id)
    row = await repository.create(request, created_at=NOW) if persist else None
    return repository, row, request


def start_entry(row):
    now = row.next_retry_at or row.updated_at + timedelta(seconds=1)
    return domain.PublicationTransition(
        operation=(
            domain.PublicationOperation.start
            if not row.attempts
            else domain.PublicationOperation.retry
        ),
        occurred_at=now,
        attempt=domain.PublicationAttempt(
            id=uuid4(),
            workspace_id=row.workspace_id,
            publication_id=row.id,
            number=len(row.attempts) + 1,
            started_at=now,
        ),
    )


def result_entry(row, outcome="published", source="provider_response"):
    operations = {
        "published": "confirm_success",
        "unknown": "require_manual_action",
        "retryable_failure": "fail_retryable",
        "permanent_failure": "fail_permanently",
    }
    return domain.PublicationTransition(
        operation=domain.PublicationOperation(operations[outcome]),
        occurred_at=row.updated_at + timedelta(seconds=1),
        evidence=domain.PublicationEvidence(
            workspace_id=row.workspace_id,
            publication_id=row.id,
            attempt_id=row.attempts[-1].id,
            destination_id=row.social_account_connection_id,
            outcome=domain.DeliveryOutcome(outcome),
            source=domain.EvidenceSource(source),
            observed_at=row.updated_at + timedelta(seconds=1),
            external_post_id="post-123" if outcome == "published" else None,
            reason=(
                None
                if outcome == "published"
                else (
                    domain.PublicationFailureReason.outcome_unknown
                    if outcome == "unknown"
                    else domain.PublicationFailureReason.temporary_unavailability
                )
            ),
        ),
    )


async def append(repository, row, entry, **kwargs):
    return await repository.append(
        row.id,
        expected_version=row.transition_version,
        operation_id=uuid4(),
        entry=entry,
        execution_id=uuid4() if entry.attempt else None,
        **kwargs,
    )


def test_storage_contract_parity():
    for stored, enum in (
        (STATES, domain.PublicationState),
        (OPERATIONS, domain.PublicationOperation),
        (OUTCOMES, domain.DeliveryOutcome),
        (REASONS, domain.PublicationFailureReason),
        (SOURCES, domain.EvidenceSource),
    ):
        assert set(stored) == set(enum)


def test_creation_readback_envelope_and_scope(sessions):
    async def run():
        async with sessions() as session:
            repo, row, request = await seed(session)
            identifier, receipt = row.id, row.receipt_id
            await session.commit()
        async with sessions() as session:
            repo = PublicationRepository(session, request.snapshot.workspace_id)
            row = await repo.get(identifier)
            assert row.receipt_id == receipt
            assert aggregate(row).state == domain.PublicationState.pending
            assert row.canonical_envelope == canonical_json(envelope(request))
            assert (
                hashlib.sha256(row.canonical_envelope).hexdigest()
                == row.payload_fingerprint
            )
            assert (await repo.create(request, created_at=NOW)).id == identifier
            assert await PublicationRepository(session, uuid4()).get(identifier) is None
            assert (
                await PublicationRepository(session, uuid4()).get_by_job(request.job_id)
                is None
            )
            with pytest.raises(PublicationConflict):
                await PublicationRepository(session, uuid4()).create(
                    request, created_at=NOW
                )
            changed = replace(request, correlation_id=uuid4())
            changed = replace(changed, payload_fingerprint=fingerprint(changed))
            with pytest.raises(PublicationConflict, match="payload_conflict"):
                await repo.create(changed, created_at=NOW)
            assert (
                await session.scalar(select(func.count()).select_from(Publication)) == 1
            )
            assert (
                await session.scalar(select(func.count()).select_from(RealtimeEvent))
                == 1
            )
            job = await session.get(SchedulingJob, request.job_id)
            assert job.status == "pending" and job.handoff_receipt_id is None

    asyncio.run(run())


def test_retry_and_reconciliation_preserve_attempts_and_outbox(sessions):
    async def run():
        async with sessions() as session:
            repo, row, request = await seed(session)
            row = await append(repo, row, start_entry(row))
            first = row.attempts[0].id
            row = await append(
                repo, row, result_entry(row, "retryable_failure"), http_status=429
            )
            row = await append(repo, row, start_entry(row))
            second = row.attempts[-1].id
            row = await append(
                repo, row, result_entry(row, "unknown", "execution_interrupted")
            )
            assert row.manual_action_reason == "outcome_unknown"
            with pytest.raises(domain.PublicationInvariantError):
                await append(repo, row, start_entry(row))
            row = await repo.get(row.id)
            with pytest.raises(domain.PublicationInvariantError):
                await append(repo, row, result_entry(row))
            row = await repo.get(row.id)
            row = await append(
                repo, row, result_entry(row, source="reconciliation"), http_status=200
            )
            assert aggregate(row).state == domain.PublicationState.published
            assert [a.id for a in row.attempts] == [first, second]
            assert [t.outcome for t in row.transitions] == [
                None,
                "retryable_failure",
                None,
                "unknown",
                "published",
            ]
            assert row.published_at and row.external_post_id == "post-123"
            assert row.attempts[0].retry_eligible
            assert row.attempts[0].failure_reason == "temporary_unavailability"
            assert row.attempts[1].outcome == "published"
            assert not row.attempts[1].retry_eligible
            assert row.attempts[1].completed_at == row.transitions[3].observed_at
            assert row.manual_action_at is None
            assert row.canonical_envelope == canonical_json(envelope(request))
            await session.commit()
        async with sessions() as session:
            row = await PublicationRepository(
                session, request.snapshot.workspace_id
            ).get(row.id)
            assert len(aggregate(row).history) == 5
            events = (await session.scalars(select(RealtimeEvent))).all()
            assert len(events) == 6
            assert all(
                "external_post_id" not in e.payload
                and "canonical_envelope" not in e.payload
                for e in events
            )

    asyncio.run(run())


@pytest.mark.parametrize("terminal", ["cancelled", "permanent_failure", "published"])
def test_terminal_history_and_source_deletion_are_restricted(sessions, terminal):
    async def run():
        async with sessions() as session:
            repo, row, request = await seed(session)
            if terminal == "cancelled":
                entry = domain.PublicationTransition(
                    operation=domain.PublicationOperation.cancel, occurred_at=NOW
                )
            else:
                row = await append(repo, row, start_entry(row))
                entry = result_entry(row, terminal)
            row = await append(repo, row, entry)
            for model in (
                Publication,
                PublicationAttempt,
                PublicationTransition,
                SchedulingJob,
                SocialAccountConnection,
                MarketingContentItem,
                MarketingContentItemChannel,
                ApprovalRequest,
                Organization,
            ):
                if model == PublicationAttempt and terminal == "cancelled":
                    continue
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.execute(delete(model))
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.execute(update(Publication).values(status="pending"))

    asyncio.run(run())


@pytest.mark.parametrize(
    "fields",
    [
        {"workspace_id": uuid4()},
        {"scheduling_job_id": uuid4()},
        {"marketing_content_item_id": uuid4()},
        {"marketing_content_item_channel_id": uuid4()},
        {"social_account_connection_id": uuid4()},
        {"approval_request_id": uuid4()},
        {"authorized_content_revision": 2},
        {"schedule_generation": 2},
        {"provider": "youtube"},
        {"status": "processing"},
        {"status": "invented"},
        {"transition_version": -1},
        {"payload_schema_version": 2},
        {"payload_fingerprint": "bad"},
        {"canonical_envelope": b""},
        {"provider_url": "https://example.com/post"},
        {"external_post_id": "false-success"},
    ],
)
def test_core_insert_constraints(sessions, fields):
    async def run():
        async with sessions() as session:
            _, row, _ = await seed(session)
            values = {
                c.name: getattr(row, c.name) for c in Publication.__table__.columns
            }
            _, _, request = await seed(session, persist=False)
            snapshot = request.snapshot
            values.update(
                id=uuid4(),
                receipt_id=uuid4(),
                idempotency_key=request.idempotency_key,
                workspace_id=snapshot.workspace_id,
                scheduling_job_id=request.job_id,
                marketing_content_item_id=snapshot.content_item_id,
                marketing_content_item_channel_id=snapshot.channel_id,
                social_account_connection_id=request.destination_id,
                approval_request_id=snapshot.approval_request_id,
                canonical_envelope=canonical_json(envelope(request)),
                payload_fingerprint=request.payload_fingerprint,
                correlation_id=request.correlation_id,
            )
            valid = dict(values)
            values.update(fields)
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.execute(
                        Publication.__table__.insert().values(**values)
                    )
            await session.execute(Publication.__table__.insert().values(**valid))

    asyncio.run(run())


def test_immutable_fields_and_attempt_guards(sessions):
    async def run():
        async with sessions() as session:
            repo, row, _ = await seed(session)
            row = await append(repo, row, start_entry(row))
            for statement in (
                update(Publication).values(payload_fingerprint="b" * 64),
                update(Publication).values(provider="youtube"),
                update(PublicationAttempt).values(started_at=NOW),
                update(PublicationTransition).values(http_status=200),
                PublicationAttempt.__table__.insert().values(
                    id=uuid4(),
                    workspace_id=row.workspace_id,
                    publication_id=row.id,
                    number=2,
                    started_at=row.updated_at,
                    execution_id=uuid4(),
                ),
            ):
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.execute(statement)
            with pytest.raises(PublicationConflict):
                await repo.append(
                    row.id,
                    expected_version=0,
                    operation_id=uuid4(),
                    entry=result_entry(row),
                )

    asyncio.run(run())


def test_failed_operation_and_outer_rollback_leave_no_partial_history(sessions):
    async def run():
        async with sessions() as session:
            repo, row, _ = await seed(session)
            await session.commit()
            original, scope = row.id, row.workspace_id
            entry = start_entry(row)
            operation = uuid4()
            row = await repo.append(
                row.id,
                expected_version=0,
                operation_id=operation,
                entry=entry,
                execution_id=uuid4(),
            )
            with pytest.raises(DBAPIError):
                await repo.append(
                    row.id,
                    expected_version=1,
                    operation_id=operation,
                    entry=result_entry(row),
                )
            row = await repo.get(original)
            assert row.status == "processing" and row.transition_version == 1
            assert len(row.transitions) == 1
            await session.rollback()
        async with sessions() as session:
            row = await PublicationRepository(session, scope).get(original)
            assert row.status == "pending" and row.attempts == []
            assert (
                await session.scalar(select(func.count()).select_from(RealtimeEvent))
                == 1
            )

    asyncio.run(run())


@pytest.mark.parametrize(
    "value",
    [
        "https://user:secret@example.com/post",
        "https://example.com/?token=secret",
        "https://example.com/#secret",
        "http://example.com/post",
        "https://@example.com/post",
        "https://example.com:secret/post",
        "https://example.com/post?",
        "https://example.com/\nsecret",
    ],
)
def test_unsafe_resource_urls(value):
    with pytest.raises(ValueError):
        PublicResourceURL().process_bind_param(value, None)


def test_no_secret_response_storage():
    columns = set(PublicationTransition.__table__.columns.keys()) | set(
        PublicationAttempt.__table__.columns.keys()
    )
    assert not columns & {
        "metadata",
        "provider_response",
        "raw_response",
        "access_token",
        "refresh_token",
        "credential_ref",
        "error_message",
    }


def test_migration_round_trip(postgres_test_engine):
    scripts = ScriptDirectory.from_config(
        Config(
            str(Path(__file__).resolve().parents[3] / "packages/database/alembic.ini")
        )
    )
    assert scripts.get_heads() == ["202609170400"]
    invalidation = scripts.get_revision("head")
    assert invalidation.down_revision == "202609170300"
    recovery = scripts.get_revision("202609170300")
    assert recovery.down_revision == "202609170200"
    leases = scripts.get_revision("202609170200")
    assert leases.down_revision == "202609170100"
    revision = scripts.get_revision("202609170100")
    assert revision.down_revision == "202609162300"
    identity = scripts.get_revision("202609162300")
    foundation = scripts.get_revision("202609162200")
    assert foundation.down_revision == "202609152100"

    def check(connection):
        with Operations.context(MigrationContext.configure(connection)):
            for rev in reversed(list(scripts.walk_revisions())):
                rev.module.upgrade()
            invalidation.module.downgrade()
            recovery.module.downgrade()
            leases.module.downgrade()
            for operation in (revision.module.downgrade, revision.module.upgrade):
                operation()
                assert (
                    "next_retry_at"
                    in {
                        c["name"]
                        for c in inspect(connection).get_columns("publications")
                    }
                ) == (operation == revision.module.upgrade)
            leases.module.upgrade()
            recovery.module.upgrade()
            invalidation.module.upgrade()
            for name in (
                "publication_actions",
                "publication_leases",
                "publications",
                "publication_attempts",
                "publication_transitions",
            ):
                table = Base.metadata.tables[name]
                assert {
                    c["name"] for c in inspect(connection).get_columns(name)
                } == set(table.columns.keys())
                assert all(
                    fk["options"]["ondelete"] == "RESTRICT"
                    for fk in inspect(connection).get_foreign_keys(name)
                )
                assert all(
                    c["name"] for c in inspect(connection).get_check_constraints(name)
                )

            def include_object(obj, name, kind, reflected, compare_to):
                return kind != "table" or name in {
                    "publication_actions",
                    "publication_leases",
                    "publications",
                    "publication_attempts",
                    "publication_transitions",
                }

            context = MigrationContext.configure(
                connection, opts={"include_object": include_object}
            )
            assert compare_metadata(context, Base.metadata) == []

    async def run():
        async with postgres_test_engine.begin() as connection:
            await connection.run_sync(check)
        factory = async_sessionmaker(postgres_test_engine, expire_on_commit=False)
        async with factory() as session:
            repo, row, _ = await seed(session)
            row = await append(repo, row, start_entry(row))
            row = await append(repo, row, result_entry(row))
            assert aggregate(row).state == domain.PublicationState.published
            await session.commit()

        # Dropping delivery storage never rewrites canonical content or scheduling.
        def seeded_roundtrip(connection):
            probe = select(
                MarketingContentItemChannel.id,
                MarketingContentItemChannel.external_post_id,
                MarketingContentItemChannel.external_url,
                MarketingContentItemChannel.published_at,
            )
            before = connection.execute(probe).all()
            assert before and before[0].external_post_id == "unchanged"
            with Operations.context(MigrationContext.configure(connection)):
                # Ownership storage can be backfilled without changing the journal.
                publication_before = connection.execute(select(Publication)).all()
                recovery.module.downgrade()
                leases.module.downgrade()
                leases.module.upgrade()
                assert (
                    connection.execute(select(Publication)).all() == publication_before
                )
                backfilled = connection.execute(
                    select(PublicationLease.__table__)
                ).one()
                assert backfilled.publication_id == row.id
                assert backfilled.fencing_token == 0
                assert backfilled.owner_id is None
                leases.module.downgrade()
                revision.module.downgrade()
                identity.module.downgrade()
                foundation.module.downgrade()
                assert connection.execute(probe).all() == before
                assert not inspect(connection).has_table("publications")
                foundation.module.upgrade()
                identity.module.upgrade()
                revision.module.upgrade()
                leases.module.upgrade()
                recovery.module.upgrade()
                assert connection.execute(probe).all() == before
                assert (
                    connection.scalar(select(func.count()).select_from(Publication))
                    == 0
                )

        async with postgres_test_engine.begin() as connection:
            await connection.run_sync(seeded_roundtrip)

    asyncio.run(run())


def test_concurrent_attempt_start(postgres_test_engine):
    async def run():
        async with postgres_test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(postgres_test_engine, expire_on_commit=False)
        async with factory() as session:
            _, row, _ = await seed(session)
            scope, identifier = row.workspace_id, row.id
            entry = start_entry(row)
            await session.commit()

        async def contender():
            async with factory() as session:
                repo = PublicationRepository(session, scope)
                try:
                    await repo.append(
                        identifier,
                        expected_version=0,
                        operation_id=uuid4(),
                        entry=entry,
                        execution_id=uuid4(),
                    )
                    await session.commit()
                    return "started"
                except PublicationConflict:
                    await session.rollback()
                    return "conflict"

        assert sorted(await asyncio.gather(contender(), contender())) == [
            "conflict",
            "started",
        ]
        async with factory() as session:
            row = await PublicationRepository(session, scope).get(identifier)
            assert len(row.attempts) == len(row.transitions) == 1

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["projection", "orphan_attempt"])
def test_postgres_commit_rejects_incomplete_history(postgres_test_engine, kind):
    async def run():
        async with postgres_test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(postgres_test_engine, expire_on_commit=False)
        async with factory() as session:
            _, row, _ = await seed(session)
            identifier, scope = row.id, row.workspace_id
            await session.commit()
            if kind == "projection":
                await session.execute(
                    update(Publication)
                    .where(Publication.id == identifier)
                    .values(status="processing", transition_version=1, updated_at=NOW)
                )
            else:
                session.add(
                    PublicationAttempt(
                        id=uuid4(),
                        workspace_id=scope,
                        publication_id=identifier,
                        number=1,
                        started_at=NOW,
                        execution_id=uuid4(),
                    )
                )
            with pytest.raises(DBAPIError):
                await session.commit()
            await session.rollback()
        async with factory() as session:
            row = await PublicationRepository(session, scope).get(identifier)
            assert row.status == "pending" and row.attempts == []

    asyncio.run(run())


def test_concurrent_duplicate_creation(postgres_test_engine):
    async def run():
        async with postgres_test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(postgres_test_engine, expire_on_commit=False)
        async with factory() as session:
            _, _, request = await seed(session, persist=False)
            await session.commit()

        async def contender():
            async with factory() as session:
                row = await PublicationRepository(
                    session, request.snapshot.workspace_id
                ).create(request, created_at=NOW)
                await session.commit()
                return row.id, row.receipt_id

        results = await asyncio.gather(contender(), contender())
        assert results[0] == results[1]
        async with factory() as session:
            assert (
                await session.scalar(select(func.count()).select_from(Publication)) == 1
            )
            assert (
                await session.scalar(select(func.count()).select_from(RealtimeEvent))
                == 1
            )

    asyncio.run(run())


def test_frozen_migration_guards_match_metadata():
    from labelos_database.publishing_guards import guard_statements

    scripts = ScriptDirectory.from_config(
        Config(
            str(Path(__file__).resolve().parents[3] / "packages/database/alembic.ini")
        )
    )
    retry = scripts.get_revision("202609170100")
    current = guard_statements("postgresql")
    for statement in retry.module.NEW_FUNCTIONS:
        if "publication_attempts_insert_guard" in statement:
            continue
        assert (
            statement.replace("CREATE OR REPLACE FUNCTION", "CREATE FUNCTION", 1)
            in current
        )
    recovery = scripts.get_revision("202609170300")
    for statement in recovery.module.NEW_ATTEMPT_GUARDS["postgresql"]:
        assert statement in current
    from labelos_database.publication_action_guards import action_guard_statements

    for dialect in ("postgresql", "sqlite"):
        assert recovery.module.action_guard_statements(
            dialect
        ) == action_guard_statements(dialect)
    identity = scripts.get_revision("202609162300")
    assert (
        identity.module.NEW_GUARD.replace(
            "CREATE OR REPLACE FUNCTION", "CREATE FUNCTION", 1
        )
        in current
    )


@pytest.mark.parametrize(
    "column",
    [
        "workspace_id",
        "scheduling_job_id",
        "marketing_content_item_id",
        "marketing_content_item_channel_id",
        "social_account_connection_id",
        "approval_request_id",
    ],
)
def test_existing_foreign_records_cannot_be_mixed(sessions, column):
    async def run():
        async with sessions() as session:
            _, first, _ = await seed(session)
            _, _, request = await seed(session, persist=False)
            values = {
                c.name: getattr(first, c.name) for c in Publication.__table__.columns
            }
            snapshot = request.snapshot
            values.update(
                id=uuid4(),
                receipt_id=uuid4(),
                workspace_id=snapshot.workspace_id,
                scheduling_job_id=request.job_id,
                marketing_content_item_id=snapshot.content_item_id,
                marketing_content_item_channel_id=snapshot.channel_id,
                social_account_connection_id=request.destination_id,
                approval_request_id=snapshot.approval_request_id,
                idempotency_key=request.idempotency_key,
                payload_fingerprint=request.payload_fingerprint,
                canonical_envelope=canonical_json(envelope(request)),
            )
            valid = dict(values)
            values[column] = getattr(first, column)
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.execute(
                        Publication.__table__.insert().values(**values)
                    )
            await session.execute(Publication.__table__.insert().values(**valid))

    asyncio.run(run())


def test_safe_url_and_workspace_mutation_scope(sessions):
    async def run():
        async with sessions() as session:
            repo, row, _ = await seed(session)
            with pytest.raises(PublicationConflict):
                await append(
                    PublicationRepository(session, uuid4()), row, start_entry(row)
                )
            row = await repo.get(row.id)
            row = await append(repo, row, start_entry(row))
            with pytest.raises(ValueError):
                await append(
                    repo,
                    row,
                    result_entry(row),
                    provider_url="https://instagram.com/post?token=secret",
                )
            row = await append(
                repo,
                row,
                result_entry(row),
                provider_url="https://www.instagram.com/p/post-123/",
            )
            assert row.provider_url == "https://www.instagram.com/p/post-123/"
            await session.commit()

    asyncio.run(run())


def test_source_edits_do_not_rewrite_accepted_intent(sessions):
    async def run():
        async with sessions() as session:
            repo, row, request = await seed(session)
            snapshot = row.canonical_envelope
            publication_id = row.id
            await session.execute(
                update(MarketingContentItem)
                .where(MarketingContentItem.id == row.marketing_content_item_id)
                .values(content_revision=2, copy_text="A later draft")
            )
            await session.execute(
                update(MarketingContentItemChannel)
                .where(
                    MarketingContentItemChannel.id
                    == row.marketing_content_item_channel_id
                )
                .values(
                    schedule_generation=2,
                    scheduled_at=NOW + timedelta(days=1),
                    social_account_connection_id=None,
                )
            )
            await session.commit()
            row = await repo.get(publication_id)
            assert row.authorized_content_revision == row.schedule_generation == 1
            assert row.social_account_connection_id == request.destination_id
            assert row.canonical_envelope == snapshot
            assert (await repo.create(request, created_at=NOW)).id == publication_id

    asyncio.run(run())
