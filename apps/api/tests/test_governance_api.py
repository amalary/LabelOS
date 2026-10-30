import asyncio
from uuid import uuid4

from labelos_database.models import WorkspacePermission

from test_analytics_api import (
    _metric_payload,
    _set_analyst_capabilities,
    _set_context,
)
from test_analytics_api import (
    analytics_client as _analytics_client,
)
from test_governance import complete_datasheet

# Reuse the established authenticated workspace graph.
governance_client = _analytics_client


def test_governance_api_shared_source_and_end_to_end(governance_client):
    client, _, seeded = governance_client
    _set_context(client, seeded)
    prefix = f"/api/v1/workspaces/{seeded.workspace_id}"
    base = prefix + "/governance"
    metric = client.post(
        prefix + "/analytics/metric-definitions", json=_metric_payload()
    )
    assert metric.status_code == 201, metric.text
    provider_id = metric.json()["provider"]["id"]
    source = client.post(
        base + "/sources",
        json={"key": "internal", "display_name": "Internal Analytics"},
    )
    assert source.status_code == 201, source.text
    assert source.json()["id"] == provider_id
    assert len(client.get(base + "/sources").json()) == 1
    dataset = client.post(
        base + "/datasets",
        json={
            "key": "discovery",
            "display_name": "Discovery",
            "provider_id": provider_id,
            "owner_department": "a&r",
        },
    )
    assert dataset.status_code == 201, dataset.text
    dataset_id = dataset.json()["id"]
    version = client.post(
        base + f"/datasets/{dataset_id}/versions", json={"version_key": "v1"}
    )
    assert version.status_code == 201, version.text
    version_id = version.json()["id"]
    body = {
        "document": complete_datasheet().model_dump(mode="json"),
        "change_reason": "Initial review",
        "expected_revision": 0,
        "production_eligible": True,
    }
    document = client.post(base + f"/versions/{version_id}/documentation", json=body)
    assert document.status_code == 201, document.text
    assert client.get(base + f"/versions/{version_id}/eligibility").json()["eligible"]
    assert (
        client.post(
            base + f"/versions/{version_id}/documentation", json=body
        ).status_code
        == 409
    )
    assert len(client.get(base + f"/versions/{version_id}/documentation").json()) == 1
    run = client.post(
        base + "/collection-runs",
        json={
            "documentation_id": document.json()["id"],
            "run_key": "run1",
            "production": True,
        },
    )
    assert run.status_code == 201, run.text
    run_id = run.json()["id"]
    for status in ("running", "succeeded"):
        result = client.post(
            base + f"/collection-runs/{run_id}/transitions", json={"status": status}
        )
        assert result.status_code == 200, result.text
    assert (
        client.post(
            base + f"/collection-runs/{run_id}/transitions", json={"status": "running"}
        ).status_code
        == 409
    )
    assert (
        client.get(base + f"/collection-runs/{run_id}").json()["status"] == "succeeded"
    )
    output = client.post(
        base + f"/datasets/{dataset_id}/versions", json={"version_key": "derived-v1"}
    )
    transformation = client.post(
        base + "/transformations",
        json={
            "output_version_id": output.json()["id"],
            "input_version_ids": [version_id],
            "collection_run_id": run_id,
            "name": "normalize",
            "code_reference": "git:abc123",
            "description": "Normalization",
        },
    )
    assert transformation.status_code == 201, transformation.text
    lineage = client.get(
        base + "/lineage", params={"transformation_id": transformation.json()["id"]}
    )
    assert lineage.json()[0]["input_version_id"] == version_id
    assert len(client.get(base + "/activity").json()) == 8  # source already existed
    assert client.get(base + "/datasets", params={"limit": 0}).status_code == 422
    assert client.get(base + f"/datasets/{uuid4()}").status_code == 404
    assert (
        client.post(
            base + "/sources", json={"key": "internal", "display_name": "Different"}
        ).status_code
        == 409
    )


def test_governance_api_authorization_across_departments(governance_client):
    client, maker, seeded = governance_client
    base = f"/api/v1/workspaces/{seeded.workspace_id}/governance"
    _set_context(
        client,
        seeded,
        user_id=seeded.analyst_user_id,
        workspace_permission=WorkspacePermission.guest,
    )
    assert client.get(base + "/datasets").status_code == 403
    asyncio.run(_set_analyst_capabilities(maker, seeded, ("governance.view",)))
    _set_context(
        client,
        seeded,
        user_id=seeded.analyst_user_id,
        workspace_permission=WorkspacePermission.guest,
        department_access=("a&r",),
        capability_permissions=("governance.view",),
    )
    assert client.get(base + "/datasets").status_code == 200
    assert (
        client.post(
            base + "/sources", json={"key": "test", "display_name": "Test"}
        ).status_code
        == 403
    )
    asyncio.run(
        _set_analyst_capabilities(
            maker, seeded, ("governance.view", "governance.manage")
        )
    )
    assert (
        client.post(
            base + "/sources", json={"key": "test", "display_name": "Test"}
        ).status_code
        == 201
    )
    assert (
        client.get(
            f"/api/v1/workspaces/{seeded.outside_workspace_id}/governance/datasets"
        ).status_code
        == 403
    )


def test_governance_api_requires_authentication(client):
    response = client.get(f"/api/v1/workspaces/{uuid4()}/governance/datasets")
    assert response.status_code == 401


def test_collection_api_history_permissions_and_redaction(governance_client, caplog):
    from uuid import UUID

    from labelos_database.models import Organization

    from labelos_api.governance import CollectionRunCreate
    from test_governance import governed_version

    client, maker, seeded = governance_client
    _set_context(client, seeded)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/governance"

    async def seed_runs():
        async with maker() as session:
            service, source, _, version, doc = await governed_version(
                session, seeded.workspace_id, seeded.owner_user_id
            )
            local = await service.create_run(
                CollectionRunCreate(
                    documentation_id=doc.id, run_key="run-key-do-not-log"
                )
            )
            outside = await session.get(Organization, seeded.outside_workspace_id)
            other_service, other_source, _, other_version, other_doc = (
                await governed_version(session, outside.id, outside.owner_user_id)
            )
            other = await other_service.create_run(
                CollectionRunCreate(
                    documentation_id=other_doc.id, run_key="run-key-do-not-log"
                )
            )
            await session.commit()
            return (
                str(local.id),
                str(other.id),
                str(source.id),
                str(version.id),
                str(other_doc.id),
                str(other_source.id),
            )

    run_id, other_id, source_id, version_id, other_doc_id, other_source_id = (
        asyncio.run(seed_runs())
    )
    result = client.get(
        base + "/collection-runs",
        params={"source_id": source_id, "version_id": version_id, "status": "queued"},
    )
    assert result.status_code == 200, result.text
    assert [row["id"] for row in result.json()] == [run_id]
    assert result.json()[0]["source_id"] == source_id
    assert result.json()[0]["version_id"] == version_id
    assert (
        client.post(
            base + "/collection-runs",
            json={
                "documentation_id": result.json()[0]["documentation_id"],
                "run_key": "foreign-retry",
                "retry_of_id": other_id,
            },
        ).status_code
        == 404
    )
    assert (
        client.get(
            base + "/collection-runs", params={"source_id": other_source_id}
        ).json()
        == []
    )
    assert client.get(base + f"/collection-runs/{other_id}").status_code == 404
    assert (
        client.post(
            base + f"/collection-runs/{other_id}/transitions",
            json={"status": "running"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            base + "/collection-runs",
            json={"documentation_id": other_doc_id, "run_key": "foreign"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            base + f"/collection-runs/{run_id}/transitions", json={"status": "running"}
        ).status_code
        == 200
    )
    progress = {
        "expected_revision": 0,
        "records_seen": 2,
        "records_written": 1,
        "records_rejected": 1,
        "checkpoint": {"offset": 2},
    }
    assert (
        client.post(
            base + f"/collection-runs/{other_id}/checkpoints", json=progress
        ).status_code
        == 404
    )
    assert (
        client.post(
            base + f"/collection-runs/{run_id}/checkpoints", json=progress
        ).status_code
        == 200
    )
    progress["checkpoint"] = {"access_token": "never-log-this-token"}
    rejected = client.post(
        base + f"/collection-runs/{run_id}/checkpoints", json=progress
    )
    assert rejected.status_code == 422 and "never-log-this-token" not in rejected.text
    outcome = {
        "status": "partially_completed",
        "records_seen": 2,
        "records_written": 1,
        "records_rejected": 1,
        "error_code": "invalid_data",
    }
    first = client.post(base + f"/collection-runs/{run_id}/transitions", json=outcome)
    second = client.post(base + f"/collection-runs/{run_id}/transitions", json=outcome)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    rejected = client.post(
        base + f"/collection-runs/{run_id}/transitions",
        json={"status": "failed", "error_code": "Bearer never-log-this-token"},
    )
    assert rejected.status_code == 422 and "never-log-this-token" not in rejected.text
    logged = repr([record.__dict__ for record in caplog.records])
    assert "never-log-this-token" not in logged and "do-not-log" not in logged
    assert (
        client.get(base + "/collection-runs", params={"status": "completed"}).json()
        == []
    )
    _set_context(
        client,
        seeded,
        user_id=seeded.analyst_user_id,
        workspace_permission=WorkspacePermission.guest,
    )
    assert client.get(base + "/collection-runs").status_code == 403
    assert (
        client.post(
            base + f"/collection-runs/{run_id}/transitions", json=outcome
        ).status_code
        == 403
    )
    asyncio.run(_set_analyst_capabilities(maker, seeded, ("governance.view",)))
    _set_context(
        client,
        seeded,
        user_id=seeded.analyst_user_id,
        workspace_permission=WorkspacePermission.guest,
        department_access=("a&r",),
        capability_permissions=("governance.view",),
    )
    assert client.get(base + f"/collection-runs/{run_id}").status_code == 200
    assert (
        client.post(
            base + f"/collection-runs/{run_id}/checkpoints",
            json={**progress, "checkpoint": {}},
        ).status_code
        == 403
    )
    assert UUID(run_id) != UUID(other_id)
