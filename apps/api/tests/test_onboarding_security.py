"""Ownership regressions: mocked principals, disposable in-memory SQLite only."""

import asyncio
from dataclasses import replace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from labelos_database.base import Base
from labelos_database.models import (
    AuthIdentity,
    Department,
    MembershipDepartmentAccess,
    MembershipRole,
    Organization,
    OrganizationMembership,
    User,
    WorkspaceMembership,
    WorkspacePermission,
)
from labelos_database.workspace_memberships import (
    ensure_workspace_membership_for_organization_membership,
)
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from labelos_api.auth import AuthenticatedPrincipal, get_current_principal, get_session
from labelos_api.main import create_app


@pytest.fixture
def onboarding_client(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite://")
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with maker() as session:
            user = User(email="onboarding@example.test")
            owner = User(email="owner@example.test")
            session.add_all([user, owner])
            await session.flush()
            session.add(
                AuthIdentity(user_id=user.id, provider="workos", subject="user_TEST")
            )
            session.add(
                Department(
                    slug="a&r",
                    display_name="A&R",
                    description="Scouting",
                    is_active=True,
                )
            )
            await session.commit()
            return user.id, owner.id

    user_id, owner_id = asyncio.run(prepare())
    app = create_app()

    async def session_override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    principal = AuthenticatedPrincipal(
        provider="workos",
        subject="user_TEST",
        session_id="session_TEST",
        email="onboarding@example.test",
        organization_id="org_TARGET",
        role="owner",
        roles=("owner",),
    )
    app.dependency_overrides[get_current_principal] = lambda: principal
    with TestClient(app) as client:
        yield client, maker, user_id, owner_id, principal
    asyncio.run(engine.dispose())


def seed_workspace(state, role="guest", status="active", workos_id="org_TARGET"):
    _, maker, user_id, owner_id, _ = state

    async def seed():
        async with maker() as session:
            org = Organization(
                name="Original",
                slug="original",
                owner_user_id=owner_id,
                workos_organization_id=workos_id,
            )
            session.add(org)
            await session.flush()
            session.add(
                OrganizationMembership(
                    organization_id=org.id,
                    user_id=user_id,
                    role=MembershipRole(role),
                    workspace_permission=WorkspacePermission(role),
                    status=status,
                    workos_membership_id="om_ORIGINAL",
                )
            )
            await session.commit()
            return org.id

    return asyncio.run(seed())


def snapshot(state):
    async def read():
        async with state[1]() as session:
            orgs = (
                await session.execute(
                    select(
                        Organization.id,
                        Organization.owner_user_id,
                        Organization.name,
                    )
                )
            ).all()
            memberships = (
                await session.execute(
                    select(
                        OrganizationMembership.organization_id,
                        OrganizationMembership.role,
                        OrganizationMembership.workspace_permission,
                        OrganizationMembership.status,
                        OrganizationMembership.workos_membership_id,
                    )
                )
            ).all()
            grants = await session.scalar(
                select(func.count()).select_from(MembershipDepartmentAccess)
            )
            workspaces = await session.scalar(
                select(func.count()).select_from(WorkspaceMembership)
            )
            return orgs, memberships, grants, workspaces

    return asyncio.run(read())


def sync(client, **overrides):
    return client.post(
        "/api/v1/onboarding/workspace",
        json={
            "workos_organization_id": "org_TARGET",
            "organization_name": "New Label",
            **overrides,
        },
    )


@pytest.mark.parametrize("role", ["guest", "member", "admin"])
@pytest.mark.parametrize("scoped", [True, False])
def test_existing_non_owner_cannot_promote_through_onboarding(
    onboarding_client, role, scoped
):
    client, _, _, _, principal = onboarding_client
    seed_workspace(onboarding_client, role)
    principal = replace(
        principal,
        role=role,
        roles=(role,),
        organization_id="org_TARGET" if scoped else None,
    )
    client.app.dependency_overrides[get_current_principal] = lambda: principal
    before = snapshot(onboarding_client)
    response = sync(client)
    after = snapshot(onboarding_client)
    assert response.status_code == 403, (response.text, after)
    assert after == before


@pytest.mark.parametrize(
    "path", ["/api/v1/onboarding/workspace", "/api/v1/organizations"]
)
def test_workspace_creation_requires_authentication(onboarding_client, path):
    client = onboarding_client[0]
    client.app.dependency_overrides.pop(get_current_principal)
    response = client.post(
        path,
        json={
            "name": "New",
            "organization_name": "New",
            "workos_organization_id": "org_TARGET",
        },
    )
    assert response.status_code == 401
    assert snapshot(onboarding_client) == ([], [], 0, 0)


def test_verified_first_time_owner_can_onboard_and_retry(onboarding_client):
    client = onboarding_client[0]
    response = sync(client)
    assert response.status_code == 200, response.text
    assert response.json()["workspace_permission"] == "owner"
    before = snapshot(onboarding_client)
    assert before[0][0][1] == onboarding_client[2]
    assert before[1][0][1:4] == (
        MembershipRole.owner,
        WorkspacePermission.owner,
        "active",
    )
    assert before[2:] == (1, 1)
    assert sync(client).json() == response.json()
    assert snapshot(onboarding_client) == before


@pytest.mark.parametrize("role", ["guest", "member", "admin"])
def test_existing_non_owner_cannot_create_local_workspace(onboarding_client, role):
    client, _, _, _, principal = onboarding_client
    seed_workspace(onboarding_client, role)
    principal = replace(principal, organization_id=None, role=None, roles=())
    client.app.dependency_overrides[get_current_principal] = lambda: principal
    before = snapshot(onboarding_client)
    response = client.post("/api/v1/organizations", json={"name": "Extra workspace"})
    assert response.status_code == 403
    assert snapshot(onboarding_client) == before


def test_first_time_user_can_create_local_workspace(onboarding_client):
    client, _, _, _, principal = onboarding_client
    principal = replace(principal, organization_id=None, role=None, roles=())
    client.app.dependency_overrides[get_current_principal] = lambda: principal
    response = client.post("/api/v1/organizations", json={"name": "First workspace"})
    assert response.status_code == 201, response.text
    assert response.json()["workspace_permission"] == "owner"
    assert snapshot(onboarding_client)[0][0][0] == UUID(response.json()["id"])


@pytest.mark.parametrize("role", ["guest", "member", "admin", None])
def test_first_local_sync_requires_verified_owner_role(onboarding_client, role):
    client, _, _, _, principal = onboarding_client
    principal = replace(principal, role=role, roles=(role,) if role else ())
    client.app.dependency_overrides[get_current_principal] = lambda: principal
    assert sync(client).status_code == 403
    assert snapshot(onboarding_client) == ([], [], 0, 0)


@pytest.mark.parametrize("organization_id", [None, "org_OTHER"])
def test_owner_claim_must_be_bound_to_target_workspace(
    onboarding_client, organization_id
):
    client, _, _, _, principal = onboarding_client
    principal = replace(principal, organization_id=organization_id)
    client.app.dependency_overrides[get_current_principal] = lambda: principal
    assert sync(client).status_code == 403
    assert snapshot(onboarding_client) == ([], [], 0, 0)


@pytest.mark.parametrize(
    "role,status",
    [
        ("guest", "active"),
        ("member", "active"),
        ("owner", "inactive"),
        ("owner", "pending"),
        ("owner", "removed"),
    ],
)
def test_owner_token_cannot_upgrade_or_reactivate_local_membership(
    onboarding_client, role, status
):
    seed_workspace(onboarding_client, role, status)
    before = snapshot(onboarding_client)
    assert sync(onboarding_client[0]).status_code == 403
    assert snapshot(onboarding_client) == before


@pytest.mark.parametrize("role", ["guest", "member"])
def test_existing_non_owner_cannot_bootstrap_another_workos_workspace(
    onboarding_client, role
):
    seed_workspace(onboarding_client, role, workos_id="org_OLD")
    before = snapshot(onboarding_client)
    # Even a new owner token must not bypass the persisted creation eligibility.
    assert sync(onboarding_client[0]).status_code == 403
    assert snapshot(onboarding_client) == before


def test_owner_sync_preserves_existing_owner_pointer_and_membership_id(
    onboarding_client,
):
    seed_workspace(onboarding_client, "owner")
    assert sync(onboarding_client[0]).status_code == 200
    after = snapshot(onboarding_client)
    assert after[0][0][1] == onboarding_client[3]
    assert after[1][0][4] == "om_ORIGINAL"


@pytest.mark.parametrize(
    "field,value",
    [
        ("workspace_permission", "owner"),
        ("role", "owner"),
        ("membership_status", "active"),
        ("workos_membership_id", "om_OTHER"),
        ("organization_id", "org_OTHER"),
        ("owner_user_id", "other-user"),
    ],
)
def test_onboarding_rejects_client_membership_authority(
    onboarding_client, field, value
):
    assert sync(onboarding_client[0], **{field: value}).status_code == 422
    assert snapshot(onboarding_client) == ([], [], 0, 0)


def test_owner_can_create_another_local_workspace(onboarding_client):
    seed_workspace(onboarding_client, "owner")
    response = onboarding_client[0].post(
        "/api/v1/organizations", json={"name": "Another"}
    )
    assert response.status_code == 201
    assert len(snapshot(onboarding_client)[0]) == 2


@pytest.mark.parametrize("role", ["guest", "member", "owner"])
def test_eligibility_checks_persisted_membership_without_sync(onboarding_client, role):
    seed_workspace(onboarding_client, role)
    before = snapshot(onboarding_client)
    response = onboarding_client[0].get("/api/v1/onboarding/workspace/eligibility")
    assert response.status_code == (204 if role == "owner" else 403)
    assert snapshot(onboarding_client) == before


@pytest.mark.parametrize("role", ["guest", "member", "admin"])
def test_normal_auth_cannot_bypass_onboarding_owner_guard(onboarding_client, role):
    seed_workspace(onboarding_client, role)
    before = snapshot(onboarding_client)
    # A still-valid owner token after a local demotion must not promote the user
    # through ordinary authentication before they retry onboarding.
    assert onboarding_client[0].get("/api/v1/organizations").status_code == 200
    assert sync(onboarding_client[0]).status_code == 403
    assert snapshot(onboarding_client) == before


def test_verified_owner_can_finish_webhook_precreated_workspace(onboarding_client):
    org_id = seed_workspace(onboarding_client, "owner")

    async def remove_membership():
        async with onboarding_client[1]() as session:
            # State between organization.created and membership.created events.
            await session.execute(delete(OrganizationMembership))
            await session.commit()

    asyncio.run(remove_membership())
    response = sync(onboarding_client[0])
    assert response.status_code == 200
    assert response.json()["organization_id"] == str(org_id)
    assert snapshot(onboarding_client)[1][0][2] == WorkspacePermission.owner


@pytest.mark.parametrize("path", ["sync", "create", "eligibility"])
@pytest.mark.parametrize("retain_organization_membership", [True, False])
def test_removed_profile_membership_cannot_be_reactivated(
    onboarding_client, path, retain_organization_membership
):
    seed_workspace(onboarding_client, "owner")

    async def remove():
        async with onboarding_client[1]() as session:
            membership = await session.scalar(select(OrganizationMembership))
            workspace_membership = (
                await ensure_workspace_membership_for_organization_membership(
                    session, membership
                )
            )
            workspace_membership.status = "removed"
            if not retain_organization_membership:
                workspace_membership.organization_membership_id = None
                await session.delete(membership)
            await session.commit()

    asyncio.run(remove())
    before = snapshot(onboarding_client)
    client = onboarding_client[0]
    response = (
        sync(client)
        if path == "sync"
        else (
            client.post("/api/v1/organizations", json={"name": "Another"})
            if path == "create"
            else client.get("/api/v1/onboarding/workspace/eligibility")
        )
    )
    assert response.status_code == 403
    assert snapshot(onboarding_client) == before


def test_normal_auth_cannot_bootstrap_owner_for_existing_member(onboarding_client):
    seed_workspace(onboarding_client, "member", workos_id="org_OLD")
    before = snapshot(onboarding_client)
    assert onboarding_client[0].get("/api/v1/organizations").status_code == 403
    assert snapshot(onboarding_client) == before
