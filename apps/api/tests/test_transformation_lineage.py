import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from labelos_database.models import (
    Artist,
    GovernanceActivity,
    Organization,
    ProvenanceEdge,
    ProvenanceRecord,
    ProvenanceTransformation,
    RealtimeEvent,
    User,
    WorkspacePermission,
)
from labelos_database.provenance_guards import guard_statements
from pydantic import ValidationError
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError

from labelos_api.governance import (
    CollectionRunCreate,
    CollectionRunTransition,
    DatasetCreate,
    DocumentationCreate,
    SourceRegistration,
    VersionCreate,
)
from labelos_api.provenance import (
    OutputRecord,
    RawRecordCreate,
    RecordTransformationCreate,
)
from labelos_api.services.governance_service import (
    GovernanceConflict,
    GovernanceError,
    GovernanceNotFound,
)
from labelos_api.services.provenance_service import ProvenanceService
from test_analytics_api import _set_analyst_capabilities, _set_context
from test_governance import complete_datasheet, governed_version
from test_governance import governance_db as governance_db
from test_governance_api import governance_client as governance_client


async def setup(session, workspace_id, user_id):
    _, _, dataset, version, doc = await governed_version(session, workspace_id, user_id)
    service = ProvenanceService(
        session, workspace_id, actor=await session.get(User, user_id)
    )
    run = await service.create_run(
        CollectionRunCreate(documentation_id=doc.id, run_key="lineage")
    )
    await service.transition_run(run.id, CollectionRunTransition(status="running"))
    raw = await service.register_raw(
        RawRecordCreate(
            version_id=version.id,
            collection_run_id=run.id,
            source_reference=uuid4(),
            content_sha256="a" * 64,
        )
    )
    artist = Artist(organization_id=workspace_id, name="One")
    other = Artist(organization_id=workspace_id, name="Two")
    session.add_all([artist, other])
    await session.flush()
    return service, dataset, version, run, raw, artist, other


def command(version_id, inputs, kind="derive", **output):
    return RecordTransformationCreate(
        transformation_type=kind,
        transformation_version="git:abc123",
        version_id=version_id,
        input_ids=inputs,
        outputs=[
            OutputRecord(
                kind={
                    "normalize": "normalized_artist",
                    "merge": "normalized_artist",
                    "transform": "observation",
                    "derive": "derived_output",
                }[kind],
                **output,
            )
        ],
    )


def test_multi_source_merge_observation_and_transformation_history(governance_db):
    maker, workspace_id, user_id = governance_db

    async def run():
        async with maker() as session:
            service, _, version, collection, raw, artist, other = await setup(
                session, workspace_id, user_id
            )
            source2 = await service.register_source(
                SourceRegistration(key="second", display_name="Second")
            )
            dataset2 = await service.create_dataset(
                DatasetCreate(
                    key="second",
                    display_name="Second",
                    provider_id=source2.id,
                    owner_department="a&r",
                )
            )
            version2 = await service.create_version(
                dataset2.id, VersionCreate(version_key="v1")
            )
            doc2 = await service.document_version(
                version2.id,
                DocumentationCreate(
                    document=complete_datasheet(),
                    expected_revision=0,
                    change_reason="Initial",
                ),
            )
            run2 = await service.create_run(
                CollectionRunCreate(documentation_id=doc2.id, run_key="second")
            )
            await service.transition_run(
                run2.id, CollectionRunTransition(status="running")
            )
            raw2 = await service.register_raw(
                RawRecordCreate(
                    version_id=version2.id,
                    collection_run_id=run2.id,
                    source_reference=uuid4(),
                )
            )
            normalized = []
            for source, identity in ((raw, artist), (raw2, other)):
                result = await service.transform(
                    command(version.id, [source.id], "normalize", artist_id=identity.id)
                )
                normalized.append(result.outputs[0])
            merge = await service.transform(
                command(
                    version.id, [n.id for n in normalized], "merge", artist_id=artist.id
                )
            )
            observation = await service.transform(
                command(version.id, [merge.outputs[0].id], "transform")
            )
            payload = command(version.id, [observation.outputs[0].id])
            first = await service.transform(payload)
            newer = await service.transform(
                payload.model_copy(update={"transformation_version": "git:new"})
            )
            await session.commit()
            graph = await service.traverse(newer.outputs[0].id)
            assert len(graph.records) == 7 and len(graph.edges) == 6
            assert {
                n.collection_run_id for n in graph.records if n.kind == "raw_source"
            } == {collection.id, run2.id}
            assert all(
                n.source_reference is None and n.content_sha256 is None
                for n in graph.records
            )
            assert {t.transformation_version for t in graph.transformations} == {
                "git:new",
                "git:abc123",
            }
            assert not graph.truncated
            details = await service.traverse(
                newer.outputs[0].id, include_source_details=True
            )
            assert {
                n.source_reference for n in details.records if n.kind == "raw_source"
            } == {raw.source_reference, raw2.source_reference}
            history = await service.traverse(first.outputs[0].id)
            assert {t.transformation_version for t in history.transformations} == {
                "git:abc123"
            }
            descendants = await service.traverse(raw.id, direction="descendants")
            assert {first.outputs[0].id, newer.outputs[0].id} <= {
                n.id for n in descendants.records
            }
            assert (await service.traverse(newer.outputs[0].id, max_depth=1)).truncated
            assert (await service.traverse(newer.outputs[0].id, max_nodes=1)).truncated
            assert len(await service.records(artist_id=artist.id)) == 2
            assert len(await service.records(artist_id=other.id)) == 1
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(GovernanceActivity)
                    .where(GovernanceActivity.action == "provenance.transformed")
                )
                == 6
            )

    asyncio.run(run())


def test_invalid_references_workspace_boundaries_and_atomic_history(governance_db):
    maker, workspace_id, user_id = governance_db

    async def run():
        async with maker() as session:
            service, _, version, collection, raw, artist, _ = await setup(
                session, workspace_id, user_id
            )
            foreign_workspace = Organization(
                name="Foreign", slug="foreign", owner_user_id=user_id
            )
            session.add(foreign_workspace)
            await session.flush()
            foreign_artist = Artist(
                organization_id=foreign_workspace.id, name="Foreign"
            )
            session.add(foreign_artist)
            await session.flush()
            before = await session.scalar(
                select(func.count()).select_from(RealtimeEvent)
            )
            for payload in (
                command(version.id, [raw.id, uuid4()]),
                command(version.id, [raw.id], "normalize", artist_id=foreign_artist.id),
                command(uuid4(), [raw.id]),
            ):
                with pytest.raises(GovernanceNotFound):
                    await service.transform(payload)
            with pytest.raises(GovernanceError):
                await service.transform(
                    command(version.id, [raw.id, uuid4()], "merge", artist_id=artist.id)
                )
            with pytest.raises(GovernanceNotFound):
                await service.traverse(uuid4())
            with pytest.raises(GovernanceError):
                await service.register_raw(
                    RawRecordCreate(
                        version_id=version.id,
                        collection_run_id=uuid4(),
                        source_reference=uuid4(),
                    )
                )
            assert (
                await session.scalar(
                    select(func.count()).select_from(ProvenanceTransformation)
                )
                == 0
            )
            assert (
                await session.scalar(select(func.count()).select_from(RealtimeEvent))
                == before
            )
            await session.commit()
            for statement in (
                insert(ProvenanceEdge).values(
                    organization_id=foreign_workspace.id,
                    input_id=raw.id,
                    output_id=raw.id,
                ),
                insert(ProvenanceRecord).values(
                    organization_id=foreign_workspace.id,
                    kind="raw_source",
                    generation=0,
                    version_id=version.id,
                    collection_run_id=collection.id,
                    source_reference=uuid4(),
                ),
            ):
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.execute(statement)

    asyncio.run(run())


def test_database_cycles_missing_ancestors_and_immutability(governance_db):
    maker, workspace_id, user_id = governance_db

    async def run():
        async with maker() as session:
            service, _, version, collection, raw, _, _ = await setup(
                session, workspace_id, user_id
            )
            a = await service.transform(command(version.id, [raw.id]))
            b = await service.transform(command(version.id, [a.outputs[0].id]))
            await session.commit()
            for source, target in (
                (b.outputs[0].id, a.outputs[0].id),
                (a.outputs[0].id, a.outputs[0].id),
                (uuid4(), b.outputs[0].id),
            ):
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.execute(
                            insert(ProvenanceEdge).values(
                                organization_id=workspace_id,
                                input_id=source,
                                output_id=target,
                            )
                        )
            for model, values in (
                (ProvenanceRecord, {"generation": 99}),
                (ProvenanceTransformation, {"transformation_version": "rewrite"}),
                (ProvenanceEdge, {"input_id": uuid4()}),
            ):
                for statement in (update(model).values(**values), delete(model)):
                    with pytest.raises(DBAPIError):
                        async with session.begin_nested():
                            await session.execute(statement)
            orphan = ProvenanceRecord(
                organization_id=workspace_id,
                kind="derived_output",
                generation=1,
                version_id=version.id,
                transformation_id=a.transformation.id,
            )
            session.add(orphan)
            await session.flush()
            with pytest.raises(GovernanceConflict, match="missing ancestors"):
                await service.traverse(orphan.id)
            # Simulate imported corruption after disabling only the insert guard.
            suffix = (
                " ON provenance_edges"
                if session.bind.dialect.name == "postgresql"
                else ""
            )
            await session.execute(
                text("DROP TRIGGER provenance_edges_insert_provenance_guard" + suffix)
            )
            await session.execute(
                insert(ProvenanceEdge).values(
                    organization_id=workspace_id,
                    input_id=b.outputs[0].id,
                    output_id=a.outputs[0].id,
                )
            )
            with pytest.raises(GovernanceConflict, match="cycle"):
                await service.traverse(b.outputs[0].id)

    asyncio.run(run())


def test_lineage_api_authorization_and_source_details(governance_client):
    client, maker, seeded = governance_client
    _set_context(client, seeded)

    async def seed():
        async with maker() as session:
            # Fixture owner identity is exposed through the authenticated context.
            owner_id = await session.scalar(
                select(Organization.owner_user_id).where(
                    Organization.id == seeded.workspace_id
                )
            )
            service, _, version, collection, raw, _, _ = await setup(
                session, seeded.workspace_id, owner_id
            )
            result = await service.transform(command(version.id, [raw.id]))
            await session.commit()
            return raw.id, result.outputs[0].id, version.id, collection.id

    raw_id, output_id, version_id, run_id = asyncio.run(seed())
    base = f"/api/v1/workspaces/{seeded.workspace_id}/governance/provenance"
    registered = client.post(
        base + "/records",
        json={
            "version_id": str(version_id),
            "collection_run_id": str(run_id),
            "source_reference": str(uuid4()),
        },
    )
    assert registered.status_code == 201, registered.text
    transformed = client.post(
        base + "/transformations",
        json=command(version_id, [registered.json()["id"]]).model_dump(mode="json"),
    )
    assert transformed.status_code == 201, transformed.text
    assert transformed.json()["inputs"] == [registered.json()["id"]]
    assert transformed.json()["transformation"]["created_at"].endswith("Z")
    assert client.get(base + "/records").status_code == 200
    response = client.get(
        base + f"/records/{output_id}/lineage?include_source_details=true"
    )
    assert response.status_code == 200, response.text
    assert any(n["source_reference"] for n in response.json()["records"])
    assert (
        client.get(base + f"/records/{output_id}/lineage?max_depth=0").status_code
        == 422
    )
    _set_context(
        client,
        seeded,
        user_id=seeded.analyst_user_id,
        workspace_permission=WorkspacePermission.member,
    )
    asyncio.run(_set_analyst_capabilities(maker, seeded, ("governance.view",)))
    response = client.get(base + f"/records/{output_id}/lineage")
    assert response.status_code == 200, response.text
    assert all(n["source_reference"] is None for n in response.json()["records"])
    assert (
        client.get(
            base + f"/records/{raw_id}/lineage?include_source_details=true"
        ).status_code
        == 403
    )
    assert (
        client.post(
            base + "/records",
            json={
                "version_id": str(uuid4()),
                "collection_run_id": str(uuid4()),
                "source_reference": str(uuid4()),
            },
        ).status_code
        == 403
    )
    assert (
        client.get(
            base.replace(str(seeded.workspace_id), str(uuid4()))
            + f"/records/{raw_id}/lineage"
        ).status_code
        == 403
    )


def test_contracts_reject_duplicate_inputs_and_invalid_merge():
    with pytest.raises(ValidationError):
        command(uuid4(), [uuid4()], "merge", artist_id=uuid4())
    identifier = uuid4()
    with pytest.raises(ValidationError):
        command(uuid4(), [identifier, identifier])
    with pytest.raises(ValidationError):
        command(uuid4(), [uuid4()], "normalize")


def test_finalized_versions_and_transaction_rollback(governance_db, monkeypatch):
    from labelos_api.governance import VersionTransition
    from test_dataset_versioning import metadata

    maker, workspace_id, user_id = governance_db

    async def run():
        async with maker() as session:
            service, dataset, _, collection, raw, _, _ = await setup(
                session, workspace_id, user_id
            )
            version = await service.create_version(dataset.id, metadata("outputs"))
            payload = command(version.id, [raw.id])
            payload.collection_run_id = collection.id
            result = await service.transform(payload)
            assert result.transformation.collection_run_id == collection.id
            await service.transition_version(
                version.id, VersionTransition(state="finalized", expected_state="draft")
            )
            await session.commit()
            with pytest.raises(GovernanceConflict):
                await service.transform(payload)
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.execute(
                        insert(ProvenanceTransformation).values(
                            organization_id=workspace_id,
                            version_id=version.id,
                            transformation_type="derive",
                            transformation_version="late",
                            actor_kind="user",
                            actor_key=str(user_id),
                        )
                    )
            assert not (await service.traverse(result.outputs[0].id)).truncated
            next_version = await service.create_version(dataset.id, metadata("next"))
            before_events = await session.scalar(
                select(func.count()).select_from(RealtimeEvent)
            )
            original = service._record

            async def fail_after_audit(action, row):
                await original(action, row)
                raise RuntimeError("simulated adapter failure")

            monkeypatch.setattr(service, "_record", fail_after_audit)
            with pytest.raises(RuntimeError, match="simulated"):
                await service.transform(command(next_version.id, [raw.id]))
            assert (
                await session.scalar(
                    select(func.count()).select_from(ProvenanceTransformation)
                )
                == 1
            )
            assert (
                await session.scalar(select(func.count()).select_from(RealtimeEvent))
                == before_events
            )

    asyncio.run(run())


def test_migration_refuses_to_discard_history(governance_db):
    maker, workspace_id, user_id = governance_db
    scripts = ScriptDirectory.from_config(
        Config(
            str(Path(__file__).resolve().parents[3] / "packages/database/alembic.ini")
        )
    )
    migration = scripts.get_revision("202610120500").module
    for dialect in ("sqlite", "postgresql"):
        assert migration.GUARDS[dialect] == list(guard_statements(dialect))

    async def run():
        async with maker() as session:
            await setup(session, workspace_id, user_id)
            await session.commit()
            connection = await session.connection()

            def downgrade(conn):
                with (
                    Operations.context(MigrationContext.configure(conn)),
                    pytest.raises(RuntimeError, match="Cannot discard"),
                ):
                    migration.downgrade()

            await connection.run_sync(downgrade)
            assert (
                await session.scalar(select(func.count()).select_from(ProvenanceRecord))
                == 1
            )

    asyncio.run(run())
