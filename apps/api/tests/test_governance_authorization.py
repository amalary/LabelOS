"""Exercise the shared governance boundary with real persisted authorization."""

import asyncio
from uuid import UUID, uuid4

import pytest
from labelos_database.models import (
    AnalyticsProvider,
    Artist,
    Capability,
    Dataset,
    DatasetDocumentation,
    GovernanceActivity,
    Organization,
    OrganizationMembership,
    ProvenanceRecord,
    RealtimeEvent,
    Role,
    RoleCapability,
    WorkspaceMembership,
    WorkspaceMembershipRole,
    WorkspacePermission,
)
from sqlalchemy import func, select, update

from labelos_api.governance import SourceRegistration
from labelos_api.services.governance_service import (
    GovernanceError,
    GovernanceForbidden,
    GovernanceNotFound,
    GovernanceService,
)
from test_analytics_api import _set_analyst_capabilities, _set_context
from test_governance_api import governance_client as governance_client
from test_transformation_lineage import setup


def read_requests(identifier):
    return [
        ("/sources", 200),
        ("/datasets", 200),
        (f"/datasets/{identifier}", 404),
        (f"/datasets/{identifier}/versions", 404),
        (f"/versions/{identifier}", 404),
        (f"/versions/{identifier}/documentation", 404),
        (f"/versions/{identifier}/eligibility", 404),
        (f"/documentation/{identifier}", 404),
        ("/collection-runs", 200),
        (f"/collection-runs/{identifier}", 404),
        ("/transformations", 200),
        ("/lineage", 200),
        ("/activity", 200),
        ("/provenance/records", 200),
        (f"/provenance/records/{identifier}/lineage", 404),
    ]


def mutation_requests(identifier):
    return [
        ("/sources", {"key": "matrix", "display_name": "Matrix"}, 201),
        (
            "/datasets",
            {
                "key": "test",
                "display_name": "Test",
                "provider_id": identifier,
                "owner_department": "a&r",
            },
            404,
        ),
        (f"/datasets/{identifier}/versions", {"version_key": "v1"}, 404),
        (
            f"/versions/{identifier}/transitions",
            {"expected_state": "draft", "state": "finalized"},
            404,
        ),
        (
            f"/versions/{identifier}/transitions",
            {"expected_state": "finalized", "state": "archived"},
            404,
        ),
        (
            f"/versions/{identifier}/documentation",
            {"document": {}, "expected_revision": 0, "change_reason": "Draft"},
            404,
        ),
        *[
            (
                f"/versions/{identifier}/documentation/transitions",
                {"state": state, "expected_revision": 1, "change_reason": "Review"},
                404,
            )
            for state in ("validated", "published")
        ],
        ("/collection-runs", {"documentation_id": identifier, "run_key": "run"}, 404),
        (f"/collection-runs/{identifier}/transitions", {"status": "running"}, 404),
        (
            f"/collection-runs/{identifier}/checkpoints",
            {
                "expected_revision": 0,
                "records_seen": 0,
                "records_written": 0,
                "records_rejected": 0,
                "checkpoint": {},
            },
            404,
        ),
        (
            "/transformations",
            {
                "output_version_id": identifier,
                "input_version_ids": [str(uuid4())],
                "name": "derive",
                "code_reference": "git:123",
                "description": "Derived",
            },
            404,
        ),
        (
            "/provenance/records",
            {
                "version_id": identifier,
                "collection_run_id": identifier,
                "source_reference": str(uuid4()),
            },
            404,
        ),
        (
            "/provenance/transformations",
            {
                "version_id": identifier,
                "input_ids": [str(uuid4())],
                "transformation_type": "derive",
                "transformation_version": "git:123",
                "outputs": [{"kind": "derived_output"}],
            },
            404,
        ),
    ]


@pytest.mark.parametrize(
    "capabilities,read,write",
    [
        ((), False, False),
        (
            (
                "ar.scouting.view",
                "ar.scouting.create",
                "ar.evaluation.view",
                "ar.evaluation.create",
                "ar.signing.approve",
            ),
            False,
            False,
        ),
        (("analytics.view", "analytics.create"), False, False),
        (("governance.admin",), False, False),
        (("governance.view",), True, False),
        (("governance.manage",), False, True),
        (("governance.view", "governance.manage"), True, True),
    ],
)
def test_every_route_uses_persisted_capabilities(
    governance_client, capabilities, read, write
):
    client, maker, seeded = governance_client
    asyncio.run(_set_analyst_capabilities(maker, seeded, capabilities))
    # Forged owner role and capability claims must not broaden the persisted guest.
    _set_context(
        client,
        seeded,
        user_id=seeded.analyst_user_id,
        workspace_permission=WorkspacePermission.owner,
        capability_permissions=("governance.view", "governance.manage"),
    )
    base = f"/api/v1/workspaces/{seeded.workspace_id}/governance"
    identifier = str(uuid4())
    for path, allowed in read_requests(identifier):
        response = client.get(base + path)
        assert response.status_code == (allowed if read else 403), (path, response.text)
    for path, payload, allowed in mutation_requests(identifier):
        response = client.post(base + path, json=payload)
        assert response.status_code == (allowed if write else 403), (
            path,
            response.text,
        )
    details = client.get(
        base + f"/provenance/records/{identifier}/lineage",
        params={"include_source_details": True},
    )
    assert details.status_code == (404 if read and write else 403)


async def seed_graphs(maker, seeded):
    async with maker() as session:
        local = await setup(session, seeded.workspace_id, seeded.owner_user_id)
        outside = await session.get(Organization, seeded.outside_workspace_id)
        foreign = await setup(session, outside.id, outside.owner_user_id)
        await session.commit()
        # service, dataset, version, run, raw record, artist, second artist
        return [str(row.id) for row in local[1:]], [str(row.id) for row in foreign[1:]]


def test_public_service_reads_deny_ungranted_and_unrelated_models(governance_client):
    _, maker, seeded = governance_client
    local, foreign = asyncio.run(seed_graphs(maker, seeded))

    async def run():
        async with maker() as session:
            denied = GovernanceService(
                session, seeded.workspace_id, actor=seeded.analyst_user_id
            )
            with pytest.raises(GovernanceForbidden):
                await denied.latest_documentation(UUID(local[1]))
            await _set_analyst_capabilities(maker, seeded, ("governance.view",))
        async with maker() as session:
            viewer = GovernanceService(
                session, seeded.workspace_id, actor=seeded.analyst_user_id
            )
            assert (
                await viewer.latest_documentation(UUID(local[1]))
            ).version_id == UUID(local[1])
            with pytest.raises(GovernanceNotFound):
                await viewer.latest_documentation(UUID(foreign[1]))
            for model, identifier in ((ProvenanceRecord, local[3]), (Artist, local[4])):
                with pytest.raises(
                    GovernanceError, match="Unsupported governance resource"
                ):
                    await viewer.get_record(model, UUID(identifier))
                with pytest.raises(
                    GovernanceError, match="Unsupported governance resource"
                ):
                    await viewer.list_records(model)
            denied = GovernanceService(
                session, seeded.outside_workspace_id, actor=seeded.analyst_user_id
            )
            with pytest.raises(GovernanceForbidden):
                await denied.latest_documentation(UUID(foreign[1]))

    asyncio.run(run())


@pytest.mark.parametrize("model", [OrganizationMembership, WorkspaceMembership])
def test_removed_memberships_override_claims_and_explicit_grants(
    governance_client, model
):
    client, maker, seeded = governance_client
    asyncio.run(
        _set_analyst_capabilities(
            maker, seeded, ("governance.view", "governance.manage")
        )
    )
    _set_context(client, seeded, user_id=seeded.analyst_user_id)

    async def deactivate():
        async with maker() as session:
            membership = await session.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == seeded.analyst_user_id
                )
            )
            clause = (
                model.id == membership.id
                if model is OrganizationMembership
                else model.organization_membership_id == membership.id
            )
            await session.execute(update(model).where(clause).values(status="removed"))
            await session.commit()

    asyncio.run(deactivate())
    base = f"/api/v1/workspaces/{seeded.workspace_id}/governance"
    assert client.get(base + "/datasets").status_code == 403
    assert (
        client.post(
            base + "/sources", json={"key": "denied", "display_name": "Denied"}
        ).status_code
        == 403
    )


def test_role_names_do_not_grant_governance_and_foreign_roles_fail_closed(
    governance_client,
):
    client, maker, seeded = governance_client
    _set_context(client, seeded, user_id=seeded.analyst_user_id)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/governance"

    async def assign_role():
        async with maker() as session:
            membership = await session.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == seeded.analyst_user_id
                )
            )
            workspace_member = await session.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.organization_membership_id == membership.id
                )
            )
            role = Role(
                workspace_id=seeded.workspace_id,
                key="owner",
                display_name="Owner",
                description="A name is not a capability grant",
            )
            session.add(role)
            await session.flush()
            session.add(
                WorkspaceMembershipRole(
                    membership_id=workspace_member.id, role_id=role.id
                )
            )
            await session.commit()
            return role.id

    role_id = asyncio.run(assign_role())
    assert client.get(base + "/datasets").status_code == 403

    async def grant():
        async with maker() as session:
            capability = Capability(
                key="governance.view",
                display_name="View governance",
                description="Read governance metadata",
            )
            session.add(capability)
            await session.flush()
            session.add(RoleCapability(role_id=role_id, capability_id=capability.id))
            await session.commit()

    asyncio.run(grant())
    assert client.get(base + "/datasets").status_code == 200
    assert (
        client.post(
            base + "/sources", json={"key": "denied", "display_name": "Denied"}
        ).status_code
        == 403
    )

    async def change_scope():
        async with maker() as session:
            await session.execute(
                update(Role)
                .where(Role.id == role_id)
                .values(workspace_id=seeded.outside_workspace_id)
            )
            await session.commit()

    asyncio.run(change_scope())
    assert client.get(base + "/datasets").status_code == 403


def test_source_projection_never_returns_provider_metadata(governance_client, caplog):
    client, maker, seeded = governance_client

    async def seed():
        async with maker() as session:
            provider = AnalyticsProvider(
                organization_id=seeded.workspace_id,
                key="private",
                display_name="Private",
                external_account_id="restricted-account",
                metadata_json={
                    "access_token": "fixture-credential-never-expose",
                    "nested": {"password": "fixture-password"},
                },
            )
            session.add(provider)
            await session.commit()
            return provider.id

    provider_id = asyncio.run(seed())
    base = f"/api/v1/workspaces/{seeded.workspace_id}/governance"
    for capabilities, expected_account in [
        (("governance.view",), None),
        (("governance.view", "governance.manage"), "restricted-account"),
    ]:
        asyncio.run(_set_analyst_capabilities(maker, seeded, capabilities))
        _set_context(client, seeded, user_id=seeded.analyst_user_id)
        result = client.get(base + "/sources")
        assert result.status_code == 200
        assert result.json()[0]["external_account_id"] == expected_account
        assert "fixture-credential" not in result.text and "metadata" not in result.text

        async def check_service(
            capabilities=capabilities, expected_account=expected_account
        ):
            async with maker() as session:
                service = GovernanceService(
                    session, seeded.workspace_id, actor=seeded.analyst_user_id
                )
                rows = await service.list_records(AnalyticsProvider)
                rows.append(await service.get_record(AnalyticsProvider, provider_id))
                for filters in (
                    {"external_account_id": "restricted-account"},
                    {
                        "metadata_json": {
                            "access_token": "fixture-credential-never-expose"
                        }
                    },
                ):
                    with pytest.raises(
                        GovernanceError, match="Unsupported governance filter"
                    ):
                        await service.list_records(AnalyticsProvider, **filters)
                if "governance.manage" in capabilities:
                    rows.append(
                        await service.register_source(
                            SourceRegistration(
                                key="private",
                                display_name="Private",
                                external_account_id="restricted-account",
                            )
                        )
                    )
                for row in rows:
                    assert not hasattr(row, "metadata_json")
                    assert row.external_account_id == expected_account
                # Projection must never mutate the canonical provider.
                assert (
                    await session.get(AnalyticsProvider, provider_id)
                ).external_account_id == "restricted-account"

        asyncio.run(check_service())
    response = client.post(
        base + "/sources",
        json={
            "key": "injected",
            "display_name": "Injected",
            "metadata_json": {"access_token": "fixture-credential-never-expose"},
        },
    )
    assert response.status_code == 422 and "fixture-credential" not in response.text
    assert "fixture-credential" not in caplog.text


def test_nested_foreign_resources_and_writes_are_atomic(governance_client):
    client, maker, seeded = governance_client
    local, foreign = asyncio.run(seed_graphs(maker, seeded))
    dataset, version, run, raw, artist, _ = local
    other_dataset, other_version, other_run, other_raw, other_artist, _ = foreign
    _set_context(client, seeded)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/governance"

    async def facts():
        async with maker() as session:
            counts = [
                await session.scalar(select(func.count()).select_from(model))
                for model in (
                    Dataset,
                    DatasetDocumentation,
                    GovernanceActivity,
                    RealtimeEvent,
                    ProvenanceRecord,
                )
            ]
            source_id = (await session.get(Dataset, UUID(other_dataset))).provider_id
            document_id = (
                await session.scalar(
                    select(DatasetDocumentation).where(
                        DatasetDocumentation.version_id == UUID(other_version)
                    )
                )
            ).id
            return counts, str(source_id), str(document_id)

    before, other_source, other_document = asyncio.run(facts())
    for path in (
        f"/datasets/{other_dataset}",
        f"/datasets/{other_dataset}/versions",
        f"/versions/{other_version}",
        f"/versions/{other_version}/documentation",
        f"/documentation/{other_document}",
        f"/collection-runs/{other_run}",
        f"/provenance/records/{other_raw}/lineage",
    ):
        assert client.get(base + path).status_code == 404
    requests = [
        (
            "/datasets",
            {
                "provider_id": other_source,
                "key": "foreign",
                "display_name": "Foreign",
                "owner_department": "a&r",
            },
        ),
        (
            f"/datasets/{dataset}/versions",
            {"version_key": "child", "parent_version_id": other_version},
        ),
        (
            f"/versions/{other_version}/documentation",
            {"document": {}, "expected_revision": 1, "change_reason": "Foreign"},
        ),
        (
            "/collection-runs",
            {"documentation_id": other_document, "run_key": "foreign"},
        ),
        (
            "/transformations",
            {
                "output_version_id": version,
                "input_version_ids": [other_version],
                "name": "derive",
                "code_reference": "git:123",
                "description": "Foreign",
            },
        ),
        (
            "/provenance/records",
            {
                "version_id": version,
                "collection_run_id": other_run,
                "source_reference": str(uuid4()),
            },
        ),
    ]
    for inputs, outputs in [
        ([other_raw], [{"kind": "derived_output"}]),
        ([raw], [{"kind": "normalized_artist", "artist_id": other_artist}]),
    ]:
        requests.append(
            (
                "/provenance/transformations",
                {
                    "version_id": version,
                    "input_ids": inputs,
                    "transformation_type": (
                        "derive" if inputs == [other_raw] else "normalize"
                    ),
                    "transformation_version": "git:123",
                    "outputs": outputs,
                },
            )
        )
    for path, body in requests:
        response = client.post(base + path, json=body)
        assert response.status_code == 404, (path, response.text)
    assert asyncio.run(facts())[0] == before
    # A valid nested write still succeeds and audits the authenticated actor.
    result = client.post(
        base + "/provenance/transformations",
        json={
            "version_id": version,
            "input_ids": [raw],
            "transformation_type": "normalize",
            "transformation_version": "git:123",
            "outputs": [{"kind": "normalized_artist", "artist_id": artist}],
        },
    )
    assert result.status_code == 201, result.text
    activity = client.get(base + "/activity").json()[-1]
    assert activity["action"] == "provenance.transformed"
    assert activity["actor_key"] == f"user_{seeded.owner_user_id}"
    assert activity["entity_id"] == result.json()["transformation"]["id"]
