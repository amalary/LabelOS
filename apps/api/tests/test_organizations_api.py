import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from labelos_database.base import Base
from labelos_database.models import (
    MembershipRole,
    Organization,
    OrganizationMembership,
    User,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from labelos_api.auth import (
    AuthenticatedPrincipal,
    CurrentUserContext,
    MembershipContext,
    get_current_user_context,
    get_session,
)
from labelos_api.main import create_app


@dataclass(frozen=True)
class SeededOrganizations:
    user_id: UUID
    org_a_id: UUID
    org_b_id: UUID
    org_c_id: UUID
    inactive_org_id: UUID
    member_id: UUID


@pytest.fixture
def organizations_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, async_sessionmaker[AsyncSession], SeededOrganizations]]:
    monkeypatch.setenv("APP_ENV", "test")
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def prepare_database() -> SeededOrganizations:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with sessionmaker() as session:
            user = User(email="owner@example.com", display_name="Owner")
            member = User(email="member@example.com", display_name="Member")
            outside_owner = User(email="outside@example.com", display_name="Outside")
            org_a = Organization(
                name="Alpha Label",
                slug="alpha-label",
                workos_organization_id="org_ALPHA",
                owner=user,
            )
            org_b = Organization(
                name="Beta Label",
                slug="beta-label",
                workos_organization_id="org_BETA",
                owner=user,
            )
            org_c = Organization(
                name="Outside Label",
                slug="outside-label",
                workos_organization_id="org_OUTSIDE",
                owner=outside_owner,
            )
            inactive_org = Organization(
                name="Former Label",
                slug="former-label",
                workos_organization_id="org_FORMER",
                owner=user,
            )
            session.add_all(
                [
                    org_a,
                    org_b,
                    org_c,
                    inactive_org,
                    OrganizationMembership(
                        organization=org_a,
                        user=user,
                        role=MembershipRole.owner,
                        workos_membership_id="om_OWNER",
                    ),
                    OrganizationMembership(
                        organization=org_a,
                        user=member,
                        role=MembershipRole.member,
                        workos_membership_id="om_MEMBER",
                    ),
                    OrganizationMembership(
                        organization=org_b,
                        user=user,
                        role=MembershipRole.member,
                    ),
                    OrganizationMembership(
                        organization=org_c,
                        user=outside_owner,
                        role=MembershipRole.owner,
                    ),
                    OrganizationMembership(
                        organization=inactive_org,
                        user=user,
                        role=MembershipRole.member,
                        status="inactive",
                    ),
                ]
            )
            await session.commit()
            return SeededOrganizations(
                user_id=user.id,
                org_a_id=org_a.id,
                org_b_id=org_b.id,
                org_c_id=org_c.id,
                inactive_org_id=inactive_org.id,
                member_id=member.id,
            )

    seeded = asyncio.run(prepare_database())
    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session

    with TestClient(app) as client:
        yield client, sessionmaker, seeded

    asyncio.run(engine.dispose())


def _set_context(
    client: TestClient,
    seeded: SeededOrganizations,
    *,
    active_organization_id: UUID | None = None,
    active_workos_organization_id: str | None = "org_ALPHA",
    role_for_org_a: MembershipRole = MembershipRole.owner,
    permissions: tuple[str, ...] = ("organization:manage", "members:manage"),
) -> None:
    memberships = [
        MembershipContext(
            organization_id=seeded.org_a_id,
            organization_name="Alpha Label",
            organization_slug="alpha-label",
            workos_organization_id="org_ALPHA",
            role=role_for_org_a,
        ),
        MembershipContext(
            organization_id=seeded.org_b_id,
            organization_name="Beta Label",
            organization_slug="beta-label",
            workos_organization_id="org_BETA",
            role=MembershipRole.member,
        ),
    ]
    if active_organization_id is not None:
        for membership in memberships:
            if membership.organization_id == active_organization_id:
                active_workos_organization_id = membership.workos_organization_id

    async def override_context() -> CurrentUserContext:
        return CurrentUserContext(
            user=User(id=seeded.user_id, email="owner@example.com"),
            principal=AuthenticatedPrincipal(
                provider="workos",
                subject="user_01TEST",
                session_id="session_SECRET",
                organization_id=active_workos_organization_id,
                role="owner",
                roles=("owner",),
                permissions=permissions,
            ),
            memberships=tuple(memberships),
        )

    client.app.dependency_overrides[get_current_user_context] = override_context


async def _membership_role(
    sessionmaker: async_sessionmaker[AsyncSession],
    organization_id: UUID,
    user_id: UUID,
) -> MembershipRole | None:
    async with sessionmaker() as session:
        membership = await session.scalar(
            select(OrganizationMembership)
            .where(OrganizationMembership.organization_id == organization_id)
            .where(OrganizationMembership.user_id == user_id)
        )
        return membership.role if membership is not None else None


async def _organization_slug(
    sessionmaker: async_sessionmaker[AsyncSession],
    organization_id: UUID,
) -> str | None:
    async with sessionmaker() as session:
        organization = await session.get(Organization, organization_id)
        return organization.slug if organization is not None else None


def test_organizations_require_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/organizations")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_list_organizations_for_current_user_with_pagination(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(client, seeded)

    response = client.get("/api/v1/organizations", params={"limit": 1, "offset": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 1
    assert body["offset"] == 1
    assert body["total"] == 2
    assert body["organizations"] == [
        {
            "id": str(seeded.org_b_id),
            "name": "Beta Label",
            "slug": "beta-label",
            "role": "member",
            "can_switch": True,
        }
    ]
    assert "org_ALPHA" not in response.text
    assert "session_SECRET" not in response.text
    assert "former-label" not in response.text


def test_get_current_organization(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(client, seeded, active_organization_id=seeded.org_a_id)

    response = client.get("/api/v1/organizations/current")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(seeded.org_a_id),
        "name": "Alpha Label",
        "slug": "alpha-label",
        "role": "owner",
        "can_switch": True,
    }


def test_activate_organization_verifies_active_membership_before_returning_workos_id(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(client, seeded)

    response = client.post(f"/api/v1/organizations/{seeded.org_b_id}/activate")

    assert response.status_code == 200
    assert response.json() == {
        "organization": {
            "id": str(seeded.org_b_id),
            "name": "Beta Label",
            "slug": "beta-label",
            "role": "member",
            "can_switch": True,
        },
        "workos_organization_id": "org_BETA",
    }


@pytest.mark.parametrize("target", ["outside", "inactive"])
def test_activate_organization_rejects_inaccessible_organizations(
    target: str,
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(client, seeded)
    organization_id = seeded.org_c_id if target == "outside" else seeded.inactive_org_id

    response = client.post(f"/api/v1/organizations/{organization_id}/activate")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_create_organization_creates_owner_membership(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    _set_context(client, seeded)

    response = client.post("/api/v1/organizations", json={"name": "  New Label  "})

    assert response.status_code == 201
    body = response.json()
    organization_id = UUID(body["id"])
    assert body == {
        "id": str(organization_id),
        "name": "New Label",
        "slug": "new-label",
        "role": "owner",
        "can_switch": False,
    }
    assert (
        asyncio.run(_membership_role(sessionmaker, organization_id, seeded.user_id))
        == MembershipRole.owner
    )


def test_create_organization_rejects_duplicate_slug(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(client, seeded)

    response = client.post(
        "/api/v1/organizations",
        json={"name": "Duplicate", "slug": "alpha-label"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Organization slug already exists"}


def test_create_organization_validates_slug(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(client, seeded)

    response = client.post(
        "/api/v1/organizations",
        json={"name": "Bad Slug", "slug": "Bad Slug"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Request validation failed"}


def test_update_organization_requires_owner_role(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(client, seeded, role_for_org_a=MembershipRole.admin)

    response = client.patch(
        f"/api/v1/organizations/{seeded.org_a_id}",
        json={"name": "Renamed Label"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient organization role"}


def test_update_organization_requires_manage_permission(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(client, seeded, permissions=("members:manage",))

    response = client.patch(
        f"/api/v1/organizations/{seeded.org_a_id}",
        json={"name": "Renamed Label"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient permission"}


def test_update_organization_changes_name_and_slug(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    _set_context(client, seeded)

    response = client.patch(
        f"/api/v1/organizations/{seeded.org_a_id}",
        json={"name": "Renamed Label", "slug": "renamed-label"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(seeded.org_a_id),
        "name": "Renamed Label",
        "slug": "renamed-label",
        "role": "owner",
        "can_switch": True,
    }
    assert asyncio.run(_organization_slug(sessionmaker, seeded.org_a_id)) == (
        "renamed-label"
    )


def test_list_members_requires_admin_role_and_permission(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(client, seeded, role_for_org_a=MembershipRole.member)

    response = client.get(f"/api/v1/organizations/{seeded.org_a_id}/members")

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient organization role"}


def test_list_members_returns_paginated_safe_member_records(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(client, seeded)

    response = client.get(
        f"/api/v1/organizations/{seeded.org_a_id}/members",
        params={"limit": 10, "offset": 0},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 10
    assert body["offset"] == 0
    assert body["total"] == 2
    emails = {member["email"] for member in body["members"]}
    assert emails == {"owner@example.com", "member@example.com"}
    assert "om_OWNER" not in response.text
    assert "om_MEMBER" not in response.text
    assert "session_SECRET" not in response.text


def test_cross_organization_members_returns_not_found(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(client, seeded)

    response = client.get(f"/api/v1/organizations/{seeded.org_c_id}/members")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_invalid_organization_id_returns_validation_error(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(client, seeded)

    response = client.get(f"/api/v1/organizations/{uuid4()}-bad/members")

    assert response.status_code == 422
    assert response.json() == {"detail": "Request validation failed"}
