import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from labelos_database.base import Base
from labelos_database.bootstrap import seed_system_roles_and_capabilities
from labelos_database.governance_guards import guard_statements
from labelos_database.models import (
    AnalyticsProvider,
    CollectionRun,
    Dataset,
    DatasetDocumentation,
    DatasetLineage,
    DatasetVersion,
    GovernanceActivity,
    MembershipRole,
    Organization,
    OrganizationMembership,
    RealtimeEvent,
    UniversalProfile,
    User,
    WorkspaceMembership,
    WorkspacePermission,
)
from pydantic import ValidationError
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from labelos_api.governance import (
    CollectionRunCreate,
    CollectionRunTransition,
    DatasetCreate,
    Datasheet,
    DocumentationCreate,
    RetentionPolicy,
    SourceRegistration,
    TransformationCreate,
    VersionCreate,
    validate_production,
)
from labelos_api.services.governance_service import (
    GovernanceConflict,
    GovernanceError,
    GovernanceForbidden,
    GovernanceNotFound,
    GovernanceService,
)


def complete_datasheet():
    today = datetime.now(UTC).date()
    return Datasheet(
        motivation="A&R discovery and aggregate analytics",
        composition="Public artist aggregate counts; sampling is incomplete",
        collection="Authorized provider API collection",
        preprocessing="Normalize identifiers and deduplicate counts",
        intended_uses=["Talent research", "Aggregate reporting"],
        prohibited_uses=["Individual profiling"],
        limitations="Not representative",
        distribution="Internal workspace only",
        licensing="Approved limited use",
        terms_reference="Reviewed policy revision 1",
        terms_reviewed_on=today,
        terms_valid_until=today + timedelta(days=30),
        license_approved=True,
        privacy="No personal records stored",
        privacy_reviewed=True,
        retention=RetentionPolicy(
            derived_data_days=90,
            deletion_process="Adapter deletes at expiry",
            lineage_policy="Retain non-sensitive version IDs and code references",
        ),
        maintenance="Monthly review; revoke on terms change",
        maintainer="Data steward",
    )


async def prepare_governance_db(database_test_engine):
    async with database_test_engine.begin() as conn:
        if conn.dialect.name == "sqlite":
            await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(database_test_engine, expire_on_commit=False)
    async with maker() as session:
        owner = User(email="governance@example.com")
        workspace = Organization(name="Governed", slug="governed", owner=owner)
        membership = OrganizationMembership(
            organization=workspace,
            user=owner,
            role=MembershipRole.owner,
            workspace_permission=WorkspacePermission.owner,
        )
        WorkspaceMembership(
            workspace=workspace,
            profile=UniversalProfile(user=owner, slug="steward"),
            organization_membership=membership,
            status="active",
        )
        session.add(workspace)
        await session.commit()
        return maker, workspace.id, owner.id


@pytest.fixture
def governance_db(database_test_engine):
    return asyncio.run(prepare_governance_db(database_test_engine))


async def governed_version(session, workspace_id, user_id):
    service = GovernanceService(
        session, workspace_id, actor=await session.get(User, user_id)
    )
    source = await service.register_source(
        SourceRegistration(key="shared", display_name="Shared")
    )
    dataset = await service.create_dataset(
        DatasetCreate(
            key="discovery",
            display_name="Discovery",
            provider_id=source.id,
            owner_department="a&r",
        )
    )
    version = await service.create_version(dataset.id, VersionCreate(version_key="v1"))
    doc = await service.document_version(
        version.id,
        DocumentationCreate(
            document=complete_datasheet(),
            change_reason="Initial review",
            expected_revision=0,
            production_eligible=True,
        ),
    )
    return service, source, dataset, version, doc


def test_contracts_and_production_rules():
    today = datetime.now(UTC).date()
    assert validate_production(complete_datasheet(), today=today).eligible
    assert not validate_production(Datasheet(), today=today).eligible
    expired = complete_datasheet().model_copy(
        update={"terms_valid_until": today - timedelta(days=1)}
    )
    assert (
        "terms_expired_or_unbounded" in validate_production(expired, today=today).issues
    )
    with pytest.raises(ValidationError):
        RetentionPolicy(
            raw_payload_policy="time_limited",
            raw_payload_days=0,
            derived_data_days=30,
            deletion_process="delete",
            lineage_policy="ids",
        )
    with pytest.raises(ValidationError):
        Datasheet(motivation="   ")
    with pytest.raises(ValidationError):
        CollectionRunTransition(status="succeeded", records_seen=1, records_written=2)
    with pytest.raises(ValidationError):
        CollectionRunTransition(status="failed")
    with pytest.raises(ValidationError):
        CollectionRunTransition(status="failed", error_code="raw token SECRET")
    with pytest.raises(ValidationError):
        SourceRegistration(
            key="source", display_name="Source", raw_payload={"secret": 1}
        )


def test_version_history_runs_provenance_and_outbox(governance_db):
    maker, workspace_id, user_id = governance_db

    async def run():
        async with maker() as session:
            service, source, dataset, version, doc = await governed_version(
                session, workspace_id, user_id
            )
            assert (
                await service.register_source(
                    SourceRegistration(key="shared", display_name="Shared")
                )
            ).id == source.id
            assert (
                await session.scalar(
                    select(func.count()).select_from(AnalyticsProvider)
                )
                == 1
            )
            collection = await service.create_run(
                CollectionRunCreate(
                    documentation_id=doc.id, run_key="run-1", production=True
                )
            )
            assert (
                await service.create_run(
                    CollectionRunCreate(
                        documentation_id=doc.id, run_key="run-1", production=True
                    )
                )
            ).id == collection.id
            await service.transition_run(
                collection.id, CollectionRunTransition(status="running")
            )
            await service.transition_run(
                collection.id,
                CollectionRunTransition(
                    status="succeeded",
                    records_seen=10,
                    records_written=8,
                    records_rejected=2,
                ),
            )
            assert collection.completed_at.replace(
                tzinfo=UTC
            ) >= collection.started_at.replace(tzinfo=UTC)
            with pytest.raises(GovernanceConflict):
                await service.transition_run(
                    collection.id, CollectionRunTransition(status="running")
                )
            output = await service.create_version(
                dataset.id, VersionCreate(version_key="normalized-v1")
            )
            transformation = await service.record_transformation(
                TransformationCreate(
                    output_version_id=output.id,
                    input_version_ids=[version.id],
                    collection_run_id=collection.id,
                    name="normalize",
                    code_reference="git:abc123",
                    description="Normalize public counts",
                )
            )
            assert (await service.list_records(DatasetLineage))[
                0
            ].transformation_id == transformation.id
            replacement = await service.document_version(
                version.id,
                DocumentationCreate(
                    document=Datasheet(motivation="Terms withdrawn"),
                    expected_revision=1,
                    change_reason="Provider revoked use",
                ),
            )
            assert replacement.revision == 2 and doc.revision == 1
            assert collection.documentation_id == doc.id
            assert not (await service.eligibility(version.id)).eligible
            with pytest.raises(GovernanceConflict):
                await service.create_run(
                    CollectionRunCreate(
                        documentation_id=doc.id, run_key="stale", production=True
                    )
                )
            with pytest.raises(GovernanceConflict):
                await service.document_version(
                    version.id,
                    DocumentationCreate(
                        document=Datasheet(), expected_revision=1, change_reason="stale"
                    ),
                )
            with pytest.raises(GovernanceError):
                await service.record_transformation(
                    TransformationCreate(
                        output_version_id=version.id,
                        input_version_ids=[output.id],
                        name="cycle",
                        code_reference="git:x",
                        description="cycle",
                    )
                )
            await session.commit()
        async with maker() as session:
            audit = list(await session.scalars(select(GovernanceActivity)))
            events = list(
                await session.scalars(
                    select(RealtimeEvent).where(
                        RealtimeEvent.event_type == "governance.changed"
                    )
                )
            )
            assert len(audit) == len(events) == 10
            assert {event.operation_id for event in events} == {
                str(row.id) for row in audit
            }
            assert all(
                set(event.payload) == {"action", "activityId"} for event in events
            )
            assert all(row.actor_key == str(user_id) for row in audit)

    asyncio.run(run())


def test_rollback_removes_state_audit_and_outbox(governance_db):
    maker, workspace_id, user_id = governance_db

    async def run():
        async with maker() as session:
            await governed_version(session, workspace_id, user_id)
            await session.rollback()
        async with maker() as session:
            for model in (
                Dataset,
                DatasetVersion,
                DatasetDocumentation,
                GovernanceActivity,
                RealtimeEvent,
                AnalyticsProvider,
            ):
                assert (
                    await session.scalar(select(func.count()).select_from(model)) == 0
                )

    asyncio.run(run())


def test_production_rechecks_at_start_and_source_ownership(governance_db):
    maker, workspace_id, user_id = governance_db

    async def run():
        async with maker() as session:
            service, _, dataset, version, doc = await governed_version(
                session, workspace_id, user_id
            )
            queued = await service.create_run(
                CollectionRunCreate(
                    documentation_id=doc.id, run_key="queue", production=True
                )
            )
            await service.document_version(
                version.id,
                DocumentationCreate(
                    document=Datasheet(), expected_revision=1, change_reason="Revoked"
                ),
            )
            with pytest.raises(GovernanceConflict):
                await service.transition_run(
                    queued.id, CollectionRunTransition(status="running")
                )
            assert queued.status == "queued"
            await service.transition_run(
                queued.id, CollectionRunTransition(status="cancelled")
            )
            other = Organization(
                name="Other", slug="other", owner=User(email="other@example.com")
            )
            provider = AnalyticsProvider(
                organization=other, key="outside", display_name="Outside"
            )
            session.add(provider)
            await session.flush()
            with pytest.raises(GovernanceNotFound):
                await service.create_dataset(
                    DatasetCreate(
                        key="outside",
                        display_name="Outside",
                        provider_id=provider.id,
                        owner_department="analytics",
                    )
                )
            denied = GovernanceService(
                session, other.id, actor=await session.get(User, user_id)
            )
            with pytest.raises(GovernanceForbidden):
                await denied.list_records(Dataset)
            with pytest.raises(GovernanceForbidden):
                GovernanceService(session, workspace_id, actor=None)
            with pytest.raises(GovernanceError):
                await service.document_version(
                    version.id,
                    DocumentationCreate(
                        document=Datasheet(),
                        expected_revision=2,
                        change_reason="Incomplete",
                        production_eligible=True,
                    ),
                )
            failed = await service.create_run(
                CollectionRunCreate(documentation_id=doc.id, run_key="development")
            )
            await service.transition_run(
                failed.id, CollectionRunTransition(status="running")
            )
            await service.transition_run(
                failed.id,
                CollectionRunTransition(
                    status="failed", error_code="rate_limited", records_seen=2
                ),
            )
            assert failed.error_code == "rate_limited"

    asyncio.run(run())


def test_database_guards_and_workspace_foreign_keys(governance_db):
    maker, workspace_id, user_id = governance_db

    async def run():
        async with maker() as session:
            service, _, dataset, version, doc = await governed_version(
                session, workspace_id, user_id
            )
            collection = await service.create_run(
                CollectionRunCreate(documentation_id=doc.id, run_key="guard")
            )
            await session.commit()
            for statement in (
                update(DatasetDocumentation)
                .where(DatasetDocumentation.id == doc.id)
                .values(change_reason="tampered"),
                delete(DatasetDocumentation).where(DatasetDocumentation.id == doc.id),
                update(CollectionRun)
                .where(CollectionRun.id == collection.id)
                .values(status="succeeded", completed_at=datetime.now(UTC)),
                delete(Dataset).where(Dataset.id == dataset.id),
            ):
                with pytest.raises(DBAPIError), session.no_autoflush:
                    async with session.begin_nested():
                        await session.execute(statement)
            other = Organization(
                name="Other", slug="other-fk", owner=User(email="other-fk@example.com")
            )
            session.add(other)
            await session.flush()
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    session.add(
                        DatasetVersion(
                            organization_id=other.id,
                            dataset_id=dataset.id,
                            version_key="foreign",
                        )
                    )
                    await session.flush()

    asyncio.run(run())


def test_migration_roundtrip_and_schema_parity(database_test_engine):
    scripts = ScriptDirectory.from_config(
        Config(
            str(Path(__file__).resolve().parents[3] / "packages/database/alembic.ini")
        )
    )
    revision = scripts.get_revision("202610120100")
    lifecycle = scripts.get_revision("202610120200")
    assert revision.down_revision == "202609210100"
    assert lifecycle.down_revision == revision.revision
    versioning = scripts.get_revision("202610120300")
    assert versioning.down_revision == lifecycle.revision
    tracking = scripts.get_revision("202610120400")
    assert tracking.down_revision == versioning.revision
    provenance = scripts.get_revision("202610120500")
    assert provenance.down_revision == tracking.revision
    audit = scripts.get_revision("202610130100")
    assert audit.down_revision == provenance.revision
    quota = scripts.get_revision("202610270100")
    assert quota.down_revision == audit.revision
    shortlist = scripts.get_revision("202610270200")
    assert shortlist.down_revision == quota.revision
    assert scripts.get_current_head() == shortlist.revision
    assert revision.module.guard_statements("postgresql") == guard_statements(
        "postgresql", versioning=False, collection_tracking=False
    )
    assert revision.module.guard_statements("sqlite") == guard_statements(
        "sqlite", versioning=False, collection_tracking=False
    )
    for dialect in ("postgresql", "sqlite"):
        assert all(
            statement in guard_statements(dialect)
            for statement in versioning.module.NEW_GUARDS[dialect]
        )

    def check(conn):
        Base.metadata.create_all(conn)
        seed_system_roles_and_capabilities(conn)
        with Operations.context(MigrationContext.configure(conn)):
            audit.module.downgrade()
            provenance.module.downgrade()
            tracking.module.downgrade()
            versioning.module.downgrade()
            lifecycle.module.downgrade()
            revision.module.downgrade()
            revision.module.upgrade()
            lifecycle.module.upgrade()
            versioning.module.upgrade()
            tracking.module.upgrade()
            provenance.module.upgrade()
            audit.module.upgrade()
            names = {
                "datasets",
                "dataset_versions",
                "dataset_documentation",
                "collection_runs",
                "dataset_transformations",
                "dataset_lineage",
                "governance_activity",
                "provenance_records",
                "provenance_transformations",
                "provenance_edges",
            }
            context = MigrationContext.configure(
                conn,
                opts={
                    "include_object": lambda obj, name, type_, reflected, compare_to: (
                        name in names if type_ == "table" else True
                    )
                },
            )
            assert compare_metadata(context, Base.metadata) == []
            grants = (
                conn.execute(
                    text(
                        "SELECT r.key FROM roles r "
                        "JOIN role_capabilities rc ON r.id=rc.role_id "
                        "JOIN capabilities c ON c.id=rc.capability_id "
                        "WHERE c.key='governance.manage' ORDER BY r.key"
                    )
                )
                .scalars()
                .all()
            )
            assert grants == ["admin", "owner"]
            audit.module.downgrade()
            provenance.module.downgrade()
            tracking.module.downgrade()
            versioning.module.downgrade()
            lifecycle.module.downgrade()
            revision.module.downgrade()
            revision.module.upgrade()
            lifecycle.module.upgrade()
            versioning.module.upgrade()
            tracking.module.upgrade()
            provenance.module.upgrade()
            audit.module.upgrade()

    async def run():
        async with database_test_engine.begin() as conn:
            await conn.run_sync(check)

    asyncio.run(run())


def test_postgres_governance_migration(postgres_test_engine):
    # Explicit test remains skipped/blocked locally when no URL is configured.
    test_migration_roundtrip_and_schema_parity(postgres_test_engine)


def test_postgres_concurrent_revision_and_run_transition(postgres_test_engine):
    async def run():
        maker, workspace_id, user_id = await prepare_governance_db(postgres_test_engine)
        async with maker() as session:
            service, _, _, version, doc = await governed_version(
                session, workspace_id, user_id
            )
            collection = await service.create_run(
                CollectionRunCreate(documentation_id=doc.id, run_key="concurrent")
            )
            await session.commit()
            version_id, run_id = version.id, collection.id

        async def compete(operation):
            async with maker() as session:
                service = GovernanceService(session, workspace_id, actor=user_id)
                try:
                    if operation == "document":
                        await service.document_version(
                            version_id,
                            DocumentationCreate(
                                document=complete_datasheet(),
                                expected_revision=1,
                                change_reason="Concurrent review",
                            ),
                        )
                    else:
                        await service.transition_run(
                            run_id, CollectionRunTransition(status="running")
                        )
                    await session.commit()
                    return "committed"
                except GovernanceConflict:
                    await session.rollback()
                    return "conflict"

        for operation in ("document", "start"):
            outcomes = await asyncio.gather(compete(operation), compete(operation))
            assert sorted(outcomes) == ["committed", "conflict"]
        async with maker() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(DatasetDocumentation)
                )
                == 2
            )
            assert (
                await session.scalar(
                    select(func.count()).select_from(GovernanceActivity)
                )
                == 7
            )
            assert (
                await session.scalar(select(func.count()).select_from(RealtimeEvent))
                == 7
            )

    asyncio.run(run())
