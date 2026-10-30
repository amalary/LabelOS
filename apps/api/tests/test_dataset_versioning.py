import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from labelos_database.models import (
    AnalyticsProvider,
    Dataset,
    DatasetDocumentation,
    DatasetLineage,
    DatasetTransformation,
    DatasetVersion,
    GovernanceActivity,
    RealtimeEvent,
)
from pydantic import ValidationError
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import DBAPIError

from labelos_api.governance import (
    CollectionRunCreate,
    CollectionRunTransition,
    DatasetCreate,
    Datasheet,
    DocumentationCreate,
    DocumentationTransition,
    TransformationCreate,
    VersionCreate,
    VersionTransition,
)
from labelos_api.services.governance_service import (
    GovernanceConflict,
    GovernanceError,
    GovernanceNotFound,
    GovernanceService,
)
from test_analytics_api import _set_analyst_capabilities, _set_context
from test_governance import complete_datasheet, governed_version, prepare_governance_db
from test_governance import governance_db as governance_db
from test_governance_api import governance_client as governance_client


def metadata(key="snapshot-1", **changes):
    return VersionCreate(
        **{
            "version_key": key,
            "schema_version": "artist-signals/2",
            "data_fingerprint": "a" * 64,
            "collection_start": datetime(2026, 10, 1, tzinfo=UTC),
            "collection_end": datetime(2026, 10, 2, tzinfo=UTC),
            "source_references": ["provider:export/2026-10-02"],
            **changes,
        }
    )


def transition(state="finalized", expected_state="draft"):
    return VersionTransition(state=state, expected_state=expected_state)


@pytest.mark.parametrize(
    "changes",
    [
        {"data_fingerprint": "x" * 64},
        {"schema_version": " "},
        {"collection_start": "2026-10-03T00:00:00Z"},
        {"collection_start": "2026-10-01T00:00:00"},
        {"collection_end": None},
        {"source_references": []},
        {"source_references": ["same", "same"]},
        {"state": "finalized"},
        {"id": str(uuid4())},
        {"created_at": "2000-01-01T00:00:00Z"},
    ],
)
def test_version_contract_rejects_invalid_or_forged_metadata(changes):
    with pytest.raises(ValidationError):
        metadata(**changes)


def test_finalized_content_and_provenance_are_immutable(governance_db):
    maker, workspace_id, user_id = governance_db

    async def run():
        async with maker() as session:
            service, _, dataset, old, _ = await governed_version(
                session, workspace_id, user_id
            )
            extra = await service.create_version(dataset.id, metadata("extra-input"))
            version = await service.create_version(dataset.id, metadata())
            untransformed = await service.create_version(
                dataset.id, metadata("untransformed")
            )
            await service.transition_version(untransformed.id, transition())
            doc = await service.document_version(
                version.id,
                DocumentationCreate(
                    document=complete_datasheet(),
                    production_eligible=True,
                    expected_revision=0,
                    change_reason="Initial",
                ),
            )
            run = await service.create_run(
                CollectionRunCreate(
                    documentation_id=doc.id,
                    run_key="queued-before-archive",
                    production=True,
                )
            )
            transform = await service.record_transformation(
                TransformationCreate(
                    output_version_id=version.id,
                    input_version_ids=[old.id],
                    name="normalize",
                    code_reference="git:123",
                    description="Normalize aggregates",
                )
            )
            await service.transition_version(version.id, transition())
            await session.commit()
            for values in (
                {"id": uuid4()},
                {"organization_id": uuid4()},
                {"dataset_id": uuid4()},
                {"version_key": "rewrite"},
                {"schema_version": "changed"},
                {"data_fingerprint": "b" * 64},
                {"source_references": ["rewritten"]},
                {"collection_start": datetime(2020, 1, 1, tzinfo=UTC)},
                {"collection_end": datetime(2020, 1, 1, tzinfo=UTC)},
                {"created_at": datetime(2020, 1, 1, tzinfo=UTC)},
                {"parent_version_id": old.id},
                {"state": "draft"},
                {"finalized_at": datetime.now(UTC)},
                {"archived_at": datetime.now(UTC)},
            ):
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.execute(
                            update(DatasetVersion)
                            .where(DatasetVersion.id == version.id)
                            .values(**values)
                        )
            for statement in (
                delete(DatasetVersion).where(DatasetVersion.id == version.id),
                insert(DatasetDocumentation).values(
                    organization_id=workspace_id,
                    version_id=version.id,
                    revision=2,
                    document={},
                    document_sha256="0" * 64,
                    production_eligible=False,
                    change_reason="late",
                    actor_kind="user",
                    actor_key=str(user_id),
                ),
                insert(DatasetTransformation).values(
                    organization_id=workspace_id,
                    output_version_id=untransformed.id,
                    name="late",
                    code_reference="git:x",
                    description="late",
                ),
                insert(DatasetLineage).values(
                    organization_id=workspace_id,
                    transformation_id=transform.id,
                    input_version_id=extra.id,
                ),
            ):
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.execute(statement)
            with pytest.raises(GovernanceConflict):
                await service.document_version(
                    version.id,
                    DocumentationCreate(
                        document=Datasheet(),
                        expected_revision=1,
                        change_reason="late",
                    ),
                )
            with pytest.raises(GovernanceConflict):
                await service.record_transformation(
                    TransformationCreate(
                        output_version_id=version.id,
                        input_version_ids=[old.id],
                        name="late",
                        code_reference="git:x",
                        description="late",
                    )
                )
            await service.transition_version(
                version.id, transition("archived", "finalized")
            )
            with pytest.raises(GovernanceConflict):
                await service.transition_documentation(
                    version.id,
                    DocumentationTransition(
                        state="validated",
                        expected_revision=1,
                        change_reason="late review",
                    ),
                )
            with pytest.raises(GovernanceConflict):
                await service.transition_run(
                    run.id, CollectionRunTransition(status="running")
                )
            with pytest.raises(GovernanceConflict):
                await service.create_run(
                    CollectionRunCreate(
                        documentation_id=doc.id,
                        run_key="after-archive",
                        production=True,
                    )
                )
            assert "version_archived" in (await service.eligibility(version.id)).issues
            child = await service.create_version(
                dataset.id, metadata("snapshot-2", parent_version_id=version.id)
            )
            await session.commit()
            with pytest.raises(GovernanceConflict):
                await service.transition_version(version.id, transition())
            assert child.parent_version_id == version.id
            assert (await service.get_record(DatasetDocumentation, doc.id)).document[
                "motivation"
            ] == complete_datasheet().motivation
            assert [
                v.id
                for v in await service.list_records(
                    DatasetVersion, dataset_id=dataset.id
                )
            ] == [old.id, extra.id, version.id, untransformed.id, child.id]
            assert (
                await service.get_record(DatasetVersion, version.id)
            ).data_fingerprint == "a" * 64

    asyncio.run(run())


def test_parent_validation_and_incomplete_finalization(governance_db):
    maker, workspace_id, user_id = governance_db

    async def run():
        async with maker() as session:
            service, source, dataset, draft, _ = await governed_version(
                session, workspace_id, user_id
            )
            with pytest.raises(GovernanceError, match="complete"):
                await service.transition_version(draft.id, transition())
            with pytest.raises(GovernanceError, match="Parent"):
                await service.create_version(
                    dataset.id, metadata(parent_version_id=draft.id)
                )
            with pytest.raises(GovernanceNotFound):
                await service.create_version(
                    dataset.id, metadata(parent_version_id=uuid4())
                )
            parent = await service.create_version(dataset.id, metadata())
            await service.transition_version(parent.id, transition())
            other = await service.create_dataset(
                DatasetCreate(
                    key="other",
                    display_name="Other",
                    provider_id=source.id,
                    owner_department="a&r",
                )
            )
            with pytest.raises(GovernanceError, match="Parent"):
                await service.create_version(
                    other.id, metadata(parent_version_id=parent.id)
                )
            await session.commit()
            for changes in (
                {"parent_version_id": uuid4()},
                {"parent_version_id": draft.id},
                {"parent_version_id": parent.id, "dataset_id": other.id},
                {"parent_version_id": parent.id, "organization_id": uuid4()},
                {
                    "parent_version_id": parent.id,
                    "created_at": parent.created_at - timedelta(seconds=1),
                },
                {"state": "finalized"},
                {"state": "unknown"},
                {"data_fingerprint": "bad"},
                {"source_references": []},
                {"source_references": [None]},
                {"source_references": [" "]},
                {"source_references": ["duplicate", "duplicate"]},
                {"collection_end": datetime(2020, 1, 1, tzinfo=UTC)},
            ):
                values = {
                    **metadata("invalid").model_dump(),
                    "organization_id": workspace_id,
                    "dataset_id": dataset.id,
                    **changes,
                }
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.execute(insert(DatasetVersion).values(**values))
            identifier = uuid4()
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.execute(
                        insert(DatasetVersion).values(
                            **metadata(
                                "self", parent_version_id=identifier
                            ).model_dump(),
                            id=identifier,
                            organization_id=workspace_id,
                            dataset_id=dataset.id,
                        )
                    )
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.execute(
                        update(DatasetVersion)
                        .where(DatasetVersion.id == draft.id)
                        .values(
                            state="finalized",
                            finalized_at=datetime.now(UTC),
                        )
                    )

    asyncio.run(run())


def api_dataset(client, base, key):
    source = client.post(base + "/sources", json={"key": key, "display_name": key})
    assert source.status_code == 201, source.text
    dataset = client.post(
        base + "/datasets",
        json={
            "key": key,
            "display_name": key,
            "provider_id": source.json()["id"],
            "owner_department": "a&r",
        },
    )
    assert dataset.status_code == 201, dataset.text
    return base + f"/datasets/{dataset.json()['id']}/versions"


def test_version_api_history_authorization_and_workspace_isolation(governance_client):
    client, maker, seeded = governance_client
    _set_context(client, seeded)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/governance"
    path = api_dataset(client, base, "signals")
    response = client.post(
        path,
        json=metadata(
            collection_start="2026-09-30T17:00:00-07:00",
            collection_end="2026-10-01T17:00:00-07:00",
        ).model_dump(mode="json"),
    )
    assert response.status_code == 201, response.text
    draft = response.json()
    item = base + f"/versions/{draft['id']}"
    response = client.post(item + "/transitions", json=transition().model_dump())
    assert response.status_code == 200, response.text
    finalized = response.json()
    assert finalized["state"] == "finalized" and finalized["finalized_at"]
    assert finalized["schema_version"] == "artist-signals/2"
    assert finalized["collection_start"] == "2026-10-01T00:00:00Z"
    assert finalized["collection_end"] == "2026-10-02T00:00:00Z"
    assert (
        client.post(item + "/transitions", json=transition().model_dump()).status_code
        == 409
    )
    response = client.post(
        path,
        json=metadata("snapshot-2", parent_version_id=draft["id"]).model_dump(
            mode="json"
        ),
    )
    assert response.status_code == 201, response.text
    child = response.json()
    assert child["id"] != draft["id"] and child["parent_version_id"] == draft["id"]
    assert (
        client.post(
            path, json=metadata("snapshot-2").model_dump(mode="json")
        ).status_code
        == 409
    )
    assert client.get(item).json() == finalized
    assert client.get(path).json() == [finalized, child]
    assert client.get(path, params={"limit": 1, "offset": 1}).json() == [child]
    assert client.get(path, params={"state": "finalized"}).json() == [finalized]
    assert client.patch(item, json={"data_fingerprint": "b" * 64}).status_code == 405
    assert client.delete(item).status_code == 405
    assert client.get(base + f"/versions/{uuid4()}").status_code == 404
    # Foreign versions must not be disclosed or accepted as parents.
    outside = f"/api/v1/workspaces/{seeded.outside_workspace_id}/governance"
    assert client.get(item.replace(base, outside)).status_code == 403

    async def foreign_version():
        async with maker() as session:
            source = AnalyticsProvider(
                organization_id=seeded.outside_workspace_id,
                key="foreign",
                display_name="Foreign",
            )
            session.add(source)
            await session.flush()
            dataset = Dataset(
                organization_id=seeded.outside_workspace_id,
                provider_id=source.id,
                key="foreign",
                display_name="Foreign",
                owner_department="a&r",
            )
            session.add(dataset)
            await session.flush()
            row = DatasetVersion(
                organization_id=seeded.outside_workspace_id,
                dataset_id=dataset.id,
                **metadata("foreign").model_dump(),
            )
            session.add(row)
            await session.flush()
            row.state, row.finalized_at = "finalized", datetime.now(UTC)
            await session.commit()
            return row.id, dataset.id

    foreign_id, foreign_dataset_id = asyncio.run(foreign_version())
    assert client.get(base + f"/versions/{foreign_id}").status_code == 404
    assert (
        client.get(base + f"/datasets/{foreign_dataset_id}/versions").status_code == 404
    )
    assert (
        client.post(
            path,
            json=metadata("foreign-parent", parent_version_id=foreign_id).model_dump(
                mode="json"
            ),
        ).status_code
        == 404
    )
    assert (
        client.post(
            base + f"/versions/{foreign_id}/transitions",
            json=transition("archived", "finalized").model_dump(),
        ).status_code
        == 404
    )
    asyncio.run(_set_analyst_capabilities(maker, seeded, ("governance.view",)))
    _set_context(client, seeded, user_id=seeded.analyst_user_id)
    assert client.get(item).json() == finalized
    assert (
        client.post(path, json=metadata("denied").model_dump(mode="json")).status_code
        == 403
    )
    assert (
        client.post(
            item + "/transitions", json=transition("archived", "finalized").model_dump()
        ).status_code
        == 403
    )
    asyncio.run(_set_analyst_capabilities(maker, seeded, ("governance.manage",)))
    assert client.get(item).status_code == 403
    assert client.get(path).status_code == 403


def test_version_endpoints_require_authentication(client):
    base = f"/api/v1/workspaces/{uuid4()}/governance"
    assert client.get(base + f"/versions/{uuid4()}").status_code == 401
    assert (
        client.post(
            base + f"/versions/{uuid4()}/transitions", json=transition().model_dump()
        ).status_code
        == 401
    )


def test_postgres_concurrent_versions_and_finalization(postgres_test_engine):
    async def run():
        maker, workspace_id, user_id = await prepare_governance_db(postgres_test_engine)
        async with maker() as session:
            service, _, dataset, _, _ = await governed_version(
                session, workspace_id, user_id
            )
            version = await service.create_version(dataset.id, metadata())
            await session.commit()
            dataset_id, version_id = dataset.id, version.id

        async def compete(operation):
            async with maker() as session:
                service = GovernanceService(session, workspace_id, actor=user_id)
                try:
                    if operation == "create":
                        await service.create_version(dataset_id, metadata("race"))
                    else:
                        await service.transition_version(version_id, transition())
                    await session.commit()
                    return "committed"
                except GovernanceConflict:
                    await session.rollback()
                    return "conflict"

        for operation in ("create", "finalize"):
            assert sorted(
                await asyncio.gather(compete(operation), compete(operation))
            ) == ["committed", "conflict"]
        async with maker() as session:
            assert (
                await session.scalar(select(func.count()).select_from(DatasetVersion))
                == 3
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


def test_postgres_direct_provenance_insert_waits_for_finalization(postgres_test_engine):
    async def run():
        maker, workspace_id, user_id = await prepare_governance_db(postgres_test_engine)
        async with maker() as session:
            service, _, dataset, _, _ = await governed_version(
                session, workspace_id, user_id
            )
            version = await service.create_version(dataset.id, metadata())
            await session.commit()
            version_id = version.id
        started = asyncio.Event()

        async def append_document():
            async with maker() as session:
                started.set()
                with pytest.raises(DBAPIError):
                    await session.execute(
                        insert(DatasetDocumentation).values(
                            organization_id=workspace_id,
                            version_id=version_id,
                            revision=1,
                            document={},
                            document_sha256="0" * 64,
                            production_eligible=False,
                            change_reason="racing",
                            actor_kind="user",
                            actor_key=str(user_id),
                        )
                    )
                await session.rollback()

        async with maker() as session:
            service = GovernanceService(session, workspace_id, actor=user_id)
            await service.transition_version(version_id, transition())
            writer = asyncio.create_task(append_document())
            await started.wait()
            await asyncio.sleep(0.1)
            assert not writer.done()
            await session.commit()
            await asyncio.wait_for(writer, timeout=5)
        async with maker() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(DatasetDocumentation)
                    .where(DatasetDocumentation.version_id == version_id)
                )
                == 0
            )

    asyncio.run(run())


def test_version_migration_preserves_legacy_evidence(governance_db):
    maker, workspace_id, user_id = governance_db
    scripts = ScriptDirectory.from_config(
        Config(
            str(Path(__file__).resolve().parents[3] / "packages/database/alembic.ini")
        )
    )
    migration = scripts.get_revision("202610120300").module

    async def run():
        async with maker() as session:
            _, _, _, version, doc = await governed_version(
                session, workspace_id, user_id
            )
            identifier, created, digest, document_id = (
                version.id,
                version.created_at,
                doc.document_sha256,
                doc.id,
            )
            await session.commit()
            connection = await session.connection()

            def migrate(conn):
                with Operations.context(MigrationContext.configure(conn)):
                    provenance = scripts.get_revision("202610120500").module
                    provenance.downgrade()
                    migration.downgrade()
                    migration.upgrade()
                    provenance.upgrade()

            await connection.run_sync(migrate)
            session.expire_all()
            restored = await session.get(DatasetVersion, identifier)
            assert restored.id == identifier and restored.created_at.replace(
                tzinfo=UTC
            ) == created.replace(tzinfo=UTC)
            assert restored.state == "draft" and restored.data_fingerprint is None
            assert (
                await session.get(DatasetDocumentation, document_id)
            ).document_sha256 == digest
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.execute(
                        update(DatasetVersion)
                        .where(DatasetVersion.id == identifier)
                        .values(version_key="rewritten")
                    )

    asyncio.run(run())
