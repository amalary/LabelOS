import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from labelos_database.models import (
    DatasetDocumentation,
    GovernanceActivity,
    RealtimeEvent,
)
from pydantic import ValidationError
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError

from labelos_api.api.v1.governance import DocumentationResponse
from labelos_api.governance import (
    Datasheet,
    DocumentationCreate,
    DocumentationTransition,
    documentation_issues,
)
from labelos_api.services.governance_service import GovernanceConflict, GovernanceError
from test_analytics_api import _set_analyst_capabilities, _set_context
from test_governance import complete_datasheet, governed_version
from test_governance import governance_db as governance_db
from test_governance_api import governance_client as governance_client


def reviewable_datasheet():
    return Datasheet.model_validate(
        {
            **complete_datasheet().model_dump(mode="json"),
            "provenance": "Provider exports collected by the registered source",
            "origin": "Provider aggregate artist statistics",
            "source_version": "provider-release-2026-10",
            "ownership": "A&R data steward; provider owns upstream data",
            "coverage": "US public artist accounts, September 2026",
            "update_frequency": "Weekly",
            "biases": "Popular artists and English-language releases overrepresented",
            "dataset_schema": {
                "description": "One row per artist and observation date",
                "fields": [
                    {
                        "name": "artist_id",
                        "data_type": "string",
                        "description": "Provider artist identifier",
                        "nullable": False,
                        "privacy_classification": "non_personal",
                    }
                ],
            },
        }
    )


def test_legacy_document_response_preserves_digest_inputs():
    content = {"schema_version": 1, "motivation": "Original archived purpose"}
    digest = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    response = DocumentationResponse.model_validate(
        {
            "id": uuid4(),
            "organization_id": uuid4(),
            "version_id": uuid4(),
            "created_at": datetime.now(UTC),
            "revision": 1,
            "state": "draft",
            "authored_revision": None,
            "document": content,
            "document_sha256": digest,
            "production_eligible": False,
            "change_reason": "Original draft",
            "actor_kind": "user",
            "actor_key": "author",
        }
    ).model_dump(mode="json")
    assert response["document"] == content
    assert (
        hashlib.sha256(
            json.dumps(
                response["document"], sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        == response["document_sha256"]
    )


@pytest.mark.parametrize(
    "field",
    [
        "motivation",
        "composition",
        "collection",
        "preprocessing",
        "intended_uses",
        "limitations",
        "distribution",
        "licensing",
        "privacy",
        "retention",
        "maintenance",
        "maintainer",
        "provenance",
        "origin",
        "source_version",
        "ownership",
        "coverage",
        "update_frequency",
        "biases",
        "dataset_schema",
    ],
)
def test_review_requires_each_section(field):
    payload = reviewable_datasheet().model_dump()
    assert not documentation_issues(Datasheet.model_validate(payload))
    del payload[field]
    assert f"missing_{field}" in documentation_issues(Datasheet.model_validate(payload))


@pytest.mark.parametrize("mutation", ["blank", "missing_type", "duplicate", "empty"])
def test_schema_field_contracts(mutation):
    payload = reviewable_datasheet().model_dump()
    fields = payload["dataset_schema"]["fields"]
    if mutation == "blank":
        fields[0]["description"] = "  "
    elif mutation == "missing_type":
        del fields[0]["data_type"]
    elif mutation == "duplicate":
        fields.append(dict(fields[0]))
    else:
        fields.clear()
    with pytest.raises(ValidationError):
        Datasheet.model_validate(payload)


def transition(state, revision):
    return DocumentationTransition(
        state=state, expected_revision=revision, change_reason=f"{state} review"
    )


def test_lifecycle_authorship_history_and_atomicity(governance_db):
    maker, workspace_id, user_id = governance_db

    async def run():
        async with maker() as session:
            service, source, dataset, version, initial = await governed_version(
                session, workspace_id, user_id
            )
            assert dataset.provider_id == source.id and initial.state == "draft"
            with pytest.raises(GovernanceError, match="Incomplete documentation"):
                await service.transition_documentation(
                    version.id, transition("validated", 1)
                )
            draft = await service.document_version(
                version.id,
                DocumentationCreate(
                    document=reviewable_datasheet(),
                    change_reason="Complete datasheet",
                    expected_revision=1,
                ),
            )
            with pytest.raises(GovernanceConflict):
                await service.transition_documentation(
                    version.id, transition("published", 2)
                )
            validated = await service.transition_documentation(
                version.id, transition("validated", 2)
            )
            with pytest.raises(GovernanceConflict):
                await service.transition_documentation(
                    version.id, transition("published", 2)
                )
            published = await service.transition_documentation(
                version.id, transition("published", 3)
            )
            with pytest.raises(GovernanceConflict):
                await service.transition_documentation(
                    version.id, transition("published", 4)
                )
            assert (
                draft.authored_revision
                == validated.authored_revision
                == published.authored_revision
                == 2
            )
            assert (
                draft.document_sha256
                == validated.document_sha256
                == published.document_sha256
            )
            assert draft.document == published.document
            assert draft.actor_key == published.actor_key == str(user_id)
            assert draft.created_at <= validated.created_at <= published.created_at
            published_id = published.id
            original = (
                published.document.copy(),
                published.document_sha256,
                published.created_at,
            )
            await session.commit()
            for statement in (
                update(DatasetDocumentation)
                .where(DatasetDocumentation.id == published_id)
                .values(state="draft"),
                update(DatasetDocumentation)
                .where(DatasetDocumentation.id == published_id)
                .values(document={}),
                update(DatasetDocumentation)
                .where(DatasetDocumentation.id == published_id)
                .values(actor_key="forged-author", authored_revision=1),
                update(DatasetDocumentation)
                .where(DatasetDocumentation.id == published_id)
                .values(created_at=datetime.now(UTC)),
                delete(DatasetDocumentation).where(
                    DatasetDocumentation.id == published_id
                ),
            ):
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.execute(statement)
            replacement = await service.document_version(
                version.id,
                DocumentationCreate(
                    document=Datasheet(motivation="Correction in progress"),
                    expected_revision=4,
                    change_reason="New draft",
                ),
            )
            assert replacement.state == "draft" and replacement.authored_revision == 5
            history = await service.list_records(
                DatasetDocumentation, version_id=version.id
            )
            assert [row.state for row in history] == [
                "draft",
                "draft",
                "validated",
                "published",
                "draft",
            ]
            assert (
                published.document,
                published.document_sha256,
                published.created_at,
            ) == original
            # Rolling back a draft also rolls back its audit event and outbox message.
            await session.rollback()
        async with maker() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(DatasetDocumentation)
                )
                == 4
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


def setup_api_document(client, seeded):
    _set_context(client, seeded)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/governance"
    source = client.post(
        base + "/sources", json={"key": "ar", "display_name": "A&R"}
    ).json()
    dataset = client.post(
        base + "/datasets",
        json={
            "key": "ar",
            "display_name": "A&R",
            "provider_id": source["id"],
            "owner_department": "a&r",
        },
    ).json()
    version = client.post(
        base + f"/datasets/{dataset['id']}/versions", json={"version_key": "v1"}
    ).json()
    path = base + f"/versions/{version['id']}/documentation"
    payload = {
        "document": reviewable_datasheet().model_dump(mode="json"),
        "expected_revision": 0,
        "change_reason": "Authored datasheet",
    }
    response = client.post(path, json=payload)
    assert response.status_code == 201, response.text
    return base, path, payload, response.json()


def test_documentation_api_review_and_historical_reads(governance_client):
    client, maker, seeded = governance_client
    base, path, payload, draft = setup_api_document(client, seeded)
    assert draft["state"] == "draft"
    forged = {**payload, "expected_revision": 1, "state": "published"}
    assert client.post(path, json=forged).status_code == 422
    assert (
        client.post(
            path + "/transitions", json=transition("published", 1).model_dump()
        ).status_code
        == 409
    )
    # A delegated reviewer is distinct from the content author.
    asyncio.run(
        _set_analyst_capabilities(
            maker, seeded, ("governance.manage", "governance.view")
        )
    )
    _set_context(client, seeded, user_id=seeded.analyst_user_id)
    for state, revision in (("validated", 1), ("published", 2)):
        response = client.post(
            path + "/transitions", json=transition(state, revision).model_dump()
        )
        assert response.status_code == 201, response.text
        assert response.json()["actor_key"] == f"user_{seeded.analyst_user_id}"
        assert response.json()["authored_revision"] == 1
    published = response.json()
    assert published["document_sha256"] == draft["document_sha256"]
    assert (
        client.post(path, json={**payload, "expected_revision": 3}).status_code == 201
    )
    assert client.get(path, params={"state": "published"}).json() == [published]
    assert client.get(base + f"/documentation/{published['id']}").json() == published
    assert (
        client.get(base + f"/documentation/{draft['id']}").json()["actor_key"]
        == draft["actor_key"]
    )
    assert (
        client.get(path, params={"offset": 1, "limit": 2}).json()[0]["state"]
        == "validated"
    )
    assert client.get(path, params={"state": "invalid"}).status_code == 422
    assert client.get(base + f"/documentation/{uuid4()}").status_code == 404


def test_documentation_api_denies_unauthorized_modification(governance_client):
    client, maker, seeded = governance_client
    base, path, payload, draft = setup_api_document(client, seeded)
    asyncio.run(_set_analyst_capabilities(maker, seeded, ("governance.view",)))
    _set_context(client, seeded, user_id=seeded.analyst_user_id)
    assert client.get(path).status_code == 200
    assert (
        client.post(path, json={**payload, "expected_revision": 1}).status_code == 403
    )
    assert (
        client.post(
            path + "/transitions", json=transition("validated", 1).model_dump()
        ).status_code
        == 403
    )
    assert (
        client.patch(
            base + f"/documentation/{draft['id']}", json={"state": "published"}
        ).status_code
        == 405
    )
    assert client.delete(base + f"/documentation/{draft['id']}").status_code == 405
    assert client.get(path).json() == [draft]
    _set_context(client, seeded)
    outside = f"/api/v1/workspaces/{seeded.outside_workspace_id}/governance"
    assert client.get(outside + f"/documentation/{draft['id']}").status_code == 403
    assert (
        client.post(
            path.replace(base, outside) + "/transitions",
            json=transition("validated", 1).model_dump(),
        ).status_code
        == 403
    )


def test_corrections_require_fresh_review_and_preserve_publications(governance_client):
    client, _, seeded = governance_client
    base, path, payload, draft = setup_api_document(client, seeded)

    def advance(state, revision):
        response = client.post(
            path + "/transitions", json=transition(state, revision).model_dump()
        )
        assert response.status_code == 201, response.text
        return response.json()

    advance("validated", 1)
    first_publication = advance("published", 2)
    correction = {
        **payload,
        "expected_revision": 3,
        "document": {**payload["document"], "coverage": "US and Canadian artists"},
    }
    response = client.post(path, json=correction)
    assert response.status_code == 201, response.text
    assert response.json()["state"] == "draft"
    assert response.json()["document_sha256"] != draft["document_sha256"]
    advance("validated", 4)

    # Editing validated content starts a fresh draft; its earlier review cannot
    # authorize publication, even when the caller supplies the latest revision.
    response = client.post(path, json={**correction, "expected_revision": 5})
    assert response.status_code == 201, response.text
    assert response.json()["authored_revision"] == 6
    for state, revision in (("published", 5), ("published", 6)):
        assert (
            client.post(
                path + "/transitions", json=transition(state, revision).model_dump()
            ).status_code
            == 409
        )
    advance("validated", 6)
    second_publication = advance("published", 7)
    assert second_publication["authored_revision"] == 6
    assert second_publication["document"]["coverage"] == "US and Canadian artists"
    assert client.get(path, params={"state": "published"}).json() == [
        first_publication,
        second_publication,
    ]
    assert (
        client.get(base + f"/documentation/{first_publication['id']}").json()
        == first_publication
    )
    assert client.get(path).json()[0] == draft


def test_rejected_documentation_requests_have_no_side_effects(governance_client):
    client, maker, seeded = governance_client
    base, path, payload, draft = setup_api_document(client, seeded)

    async def counts():
        async with maker() as session:
            return tuple(
                [
                    await session.scalar(select(func.count()).select_from(model))
                    for model in (
                        DatasetDocumentation,
                        GovernanceActivity,
                        RealtimeEvent,
                    )
                ]
            )

    for field, value in (
        ("actor_key", "forged-author"),
        ("actor_kind", "system"),
        ("created_at", "2000-01-01T00:00:00Z"),
        ("authored_revision", 1),
        ("document_sha256", "0" * 64),
    ):
        before = asyncio.run(counts())
        assert (
            client.post(
                path, json={**payload, "expected_revision": 1, field: value}
            ).status_code
            == 422
        )
        assert (
            client.post(
                path + "/transitions",
                json={**transition("validated", 1).model_dump(), field: value},
            ).status_code
            == 422
        )
        assert asyncio.run(counts()) == before

    response = client.post(
        path,
        json={**payload, "expected_revision": 1, "document": {"motivation": "Draft"}},
    )
    assert response.status_code == 201, response.text
    before = asyncio.run(counts())
    response = client.post(
        path + "/transitions", json=transition("validated", 2).model_dump()
    )
    assert response.status_code == 400
    assert "missing_dataset_schema" in response.json()["detail"]
    assert "missing_provenance" in response.json()["detail"]
    assert asyncio.run(counts()) == before
    assert client.get(path, params={"state": "published"}).json() == []
    assert client.get(base + f"/documentation/{draft['id']}").json() == draft


@pytest.mark.parametrize("capabilities", [(), ("governance.manage",)])
def test_documentation_reads_require_view_capability(governance_client, capabilities):
    client, maker, seeded = governance_client
    base, path, payload, draft = setup_api_document(client, seeded)
    asyncio.run(_set_analyst_capabilities(maker, seeded, capabilities))
    # Claimed capabilities in the authentication context cannot override the DB.
    _set_context(
        client,
        seeded,
        user_id=seeded.analyst_user_id,
        capability_permissions=("governance.view", "governance.manage"),
    )
    assert client.get(path).status_code == 403
    assert client.get(path, params={"state": "published"}).status_code == 403
    assert client.get(base + f"/documentation/{draft['id']}").status_code == 403
    if not capabilities:
        assert (
            client.post(path, json={**payload, "expected_revision": 1}).status_code
            == 403
        )
        assert (
            client.post(
                path + "/transitions", json=transition("validated", 1).model_dump()
            ).status_code
            == 403
        )
    _set_context(client, seeded)
    assert client.get(path).json() == [draft]


def test_documentation_endpoints_require_authentication(client):
    base = f"/api/v1/workspaces/{uuid4()}/governance"
    path = base + f"/versions/{uuid4()}/documentation"
    assert client.get(path).status_code == 401
    assert client.get(base + f"/documentation/{uuid4()}").status_code == 401
    assert (
        client.post(
            path,
            json={
                "document": {},
                "expected_revision": 0,
                "change_reason": "Unauthorized draft",
            },
        ).status_code
        == 401
    )
    assert (
        client.post(
            path + "/transitions", json=transition("validated", 1).model_dump()
        ).status_code
        == 401
    )


def test_documentation_migration_preserves_existing_history(governance_db):
    maker, workspace_id, user_id = governance_db
    scripts = ScriptDirectory.from_config(
        Config(
            str(Path(__file__).resolve().parents[3] / "packages/database/alembic.ini")
        )
    )
    migration = scripts.get_revision("202610120200").module

    async def run():
        async with maker() as session:
            _, _, _, _, doc = await governed_version(session, workspace_id, user_id)
            identifier, digest, content = (
                doc.id,
                doc.document_sha256,
                doc.document.copy(),
            )
            await session.commit()
            connection = await session.connection()

            def migrate(conn):
                with Operations.context(MigrationContext.configure(conn)):
                    migration.downgrade()
                    migration.upgrade()

            await connection.run_sync(migrate)
            session.expire_all()
            restored = await session.get(DatasetDocumentation, identifier)
            assert restored.document == content and restored.document_sha256 == digest
            assert restored.state == "draft" and restored.authored_revision is None
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.execute(
                        delete(DatasetDocumentation).where(
                            DatasetDocumentation.id == identifier
                        )
                    )

    asyncio.run(run())
