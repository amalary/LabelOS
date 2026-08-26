import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from labelos_database.base import Base
from labelos_database.models import (
    Capability,
    Department,
    MembershipDepartmentAccess,
    MembershipProfessionalRole,
    MembershipRole,
    Organization,
    OrganizationMembership,
    ProfessionalRole,
    RealtimeEvent,
    Role,
    RoleCapability,
    UniversalProfile,
    User,
    WorkspaceInvite,
    WorkspaceMembership,
    WorkspaceMembershipRole,
)
from sqlalchemy import func, select
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
    member_membership_id: UUID
    joiner_id: UUID
    artist_role_id: UUID
    manager_role_id: UUID
    producer_role_id: UUID
    ar_role_id: UUID
    legal_role_id: UUID


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
            joiner = User(email="joiner@example.com", display_name="Joiner")
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
            legal_role = ProfessionalRole(
                slug="legal",
                display_name="Legal",
                description="Legal counsel.",
            )
            management_role = ProfessionalRole(
                slug="management",
                display_name="Management",
                description="Artist or business management.",
            )
            artist_role = ProfessionalRole(
                slug="artist",
                display_name="Artist",
                description="Recording artist.",
            )
            producer_role = ProfessionalRole(
                slug="producer",
                display_name="Producer",
                description="Music producer.",
            )
            songwriter_role = ProfessionalRole(
                slug="songwriter",
                display_name="Songwriter",
                description="Composer or lyricist.",
            )
            workspace_artist_role = Role(
                key="artist",
                display_name="Artist",
                description="Artist role.",
                system_role=True,
            )
            workspace_producer_role = Role(
                key="producer",
                display_name="Producer",
                description="Producer role.",
                system_role=True,
            )
            workspace_manager_role = Role(
                key="manager",
                display_name="Manager",
                description="Manager role.",
                system_role=True,
            )
            workspace_ar_role = Role(
                key="a_and_r",
                display_name="A&R",
                description="A&R role.",
                system_role=True,
            )
            workspace_legal_role = Role(
                key="legal",
                display_name="Legal",
                description="Legal role.",
                system_role=True,
            )
            owner_membership = OrganizationMembership(
                organization=org_a,
                user=user,
                role=MembershipRole.owner,
                workos_membership_id="om_OWNER",
            )
            management_department = Department(
                slug="management",
                display_name="Management",
                description="Management department.",
            )
            legal_department = Department(
                slug="legal",
                display_name="Legal",
                description="Legal department.",
            )
            finance_department = Department(
                slug="finance",
                display_name="Finance",
                description="Finance department.",
            )
            member_membership = OrganizationMembership(
                organization=org_a,
                user=member,
                role=MembershipRole.member,
                workos_membership_id="om_MEMBER",
            )
            session.add_all(
                [
                    org_a,
                    org_b,
                    org_c,
                    inactive_org,
                    joiner,
                    legal_role,
                    management_role,
                    artist_role,
                    producer_role,
                    songwriter_role,
                    workspace_artist_role,
                    workspace_producer_role,
                    workspace_manager_role,
                    workspace_ar_role,
                    workspace_legal_role,
                    owner_membership,
                    member_membership,
                    MembershipProfessionalRole(
                        membership=owner_membership,
                        professional_role=legal_role,
                        is_primary=True,
                    ),
                    MembershipProfessionalRole(
                        membership=owner_membership,
                        professional_role=management_role,
                    ),
                    MembershipProfessionalRole(
                        membership=member_membership,
                        professional_role=artist_role,
                        is_primary=True,
                    ),
                    MembershipProfessionalRole(
                        membership=member_membership,
                        professional_role=producer_role,
                    ),
                    MembershipProfessionalRole(
                        membership=member_membership,
                        professional_role=songwriter_role,
                    ),
                    management_department,
                    legal_department,
                    finance_department,
                    MembershipDepartmentAccess(
                        membership=owner_membership,
                        department=management_department,
                        access_level="member",
                        source="admin_grant",
                    ),
                    MembershipDepartmentAccess(
                        membership=owner_membership,
                        department=legal_department,
                        access_level="member",
                        source="manual_request",
                    ),
                    MembershipDepartmentAccess(
                        membership=owner_membership,
                        department=finance_department,
                        access_level="member",
                        source="manual_request",
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
                member_membership_id=member_membership.id,
                joiner_id=joiner.id,
                artist_role_id=workspace_artist_role.id,
                manager_role_id=workspace_manager_role.id,
                producer_role_id=workspace_producer_role.id,
                ar_role_id=workspace_ar_role.id,
                legal_role_id=workspace_legal_role.id,
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
    role_for_org_b: MembershipRole = MembershipRole.member,
    permissions: tuple[str, ...] = ("organization:manage", "members:manage"),
    capability_permissions: tuple[str, ...] = (),
    role_capabilities: tuple[str, ...] = (),
) -> None:
    memberships = [
        MembershipContext(
            organization_id=seeded.org_a_id,
            organization_name="Alpha Label",
            organization_slug="alpha-label",
            workos_organization_id="org_ALPHA",
            role=role_for_org_a,
            capability_permissions=capability_permissions,
            role_capabilities=role_capabilities,
        ),
        MembershipContext(
            organization_id=seeded.org_b_id,
            organization_name="Beta Label",
            organization_slug="beta-label",
            workos_organization_id="org_BETA",
            role=role_for_org_b,
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


def _set_joiner_context(client: TestClient, seeded: SeededOrganizations) -> None:
    async def override_context() -> CurrentUserContext:
        return CurrentUserContext(
            user=User(id=seeded.joiner_id, email="joiner@example.com"),
            principal=AuthenticatedPrincipal(
                provider="workos",
                subject="user_01JOINER",
                session_id="session_JOINER_SECRET",
                organization_id=None,
                role=None,
                roles=(),
                permissions=(),
            ),
            memberships=(),
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


async def _membership_status(
    sessionmaker: async_sessionmaker[AsyncSession],
    membership_id: UUID,
) -> str | None:
    async with sessionmaker() as session:
        membership = await session.get(OrganizationMembership, membership_id)
        return membership.status if membership is not None else None


async def _workspace_membership_status(
    sessionmaker: async_sessionmaker[AsyncSession],
    membership_id: UUID,
) -> str | None:
    async with sessionmaker() as session:
        workspace_membership = await session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.organization_membership_id == membership_id
            )
        )
        return (
            workspace_membership.status
            if workspace_membership is not None
            else None
        )


async def _organization_slug(
    sessionmaker: async_sessionmaker[AsyncSession],
    organization_id: UUID,
) -> str | None:
    async with sessionmaker() as session:
        organization = await session.get(Organization, organization_id)
        return organization.slug if organization is not None else None


async def _membership_professional_role_count(
    sessionmaker: async_sessionmaker[AsyncSession],
    membership_id: UUID,
) -> int:
    async with sessionmaker() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(MembershipProfessionalRole)
            .where(MembershipProfessionalRole.membership_id == membership_id)
        )
        return count or 0


async def _membership_professional_roles(
    sessionmaker: async_sessionmaker[AsyncSession],
    membership_id: UUID,
) -> list[str]:
    async with sessionmaker() as session:
        rows = await session.execute(
            select(ProfessionalRole.display_name)
            .join(MembershipProfessionalRole)
            .where(MembershipProfessionalRole.membership_id == membership_id)
            .order_by(
                MembershipProfessionalRole.is_primary.desc(),
                MembershipProfessionalRole.created_at.asc(),
                ProfessionalRole.display_name.asc(),
            )
        )
        return list(rows.scalars())


async def _membership_department_access(
    sessionmaker: async_sessionmaker[AsyncSession],
    membership_id: UUID,
) -> list[tuple[str, str]]:
    async with sessionmaker() as session:
        rows = await session.execute(
            select(Department.slug, MembershipDepartmentAccess.source)
            .join(MembershipDepartmentAccess)
            .where(MembershipDepartmentAccess.membership_id == membership_id)
            .order_by(
                MembershipDepartmentAccess.created_at.asc(), Department.slug.asc()
            )
        )
        return [(slug, source) for slug, source in rows.all()]


async def _workspace_role_keys(
    sessionmaker: async_sessionmaker[AsyncSession],
    membership_id: UUID,
) -> list[str]:
    async with sessionmaker() as session:
        rows = await session.execute(
            select(Role.key)
            .join(WorkspaceMembershipRole, WorkspaceMembershipRole.role_id == Role.id)
            .join(
                WorkspaceMembership,
                WorkspaceMembership.id == WorkspaceMembershipRole.membership_id,
            )
            .where(WorkspaceMembership.organization_membership_id == membership_id)
            .order_by(
                WorkspaceMembershipRole.assigned_at.asc(),
                Role.key.asc(),
            )
        )
        return list(rows.scalars())


async def _realtime_events(
    sessionmaker: async_sessionmaker[AsyncSession],
    organization_id: UUID,
) -> list[RealtimeEvent]:
    async with sessionmaker() as session:
        rows = await session.scalars(
            select(RealtimeEvent)
            .where(RealtimeEvent.organization_id == organization_id)
            .order_by(RealtimeEvent.created_at.asc(), RealtimeEvent.id.asc())
        )
        return list(rows.all())


async def _universal_profile_count(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> int:
    async with sessionmaker() as session:
        count = await session.scalar(select(func.count()).select_from(UniversalProfile))
        return count or 0


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
            "workspace_permission": "member",
            "role": "member",
            "department_access": [],
            "capability_permissions": [],
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
        "workspace_permission": "owner",
        "role": "owner",
        "department_access": [],
        "capability_permissions": [],
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
            "workspace_permission": "member",
            "role": "member",
            "department_access": [],
            "capability_permissions": [],
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
        "workspace_permission": "owner",
        "role": "owner",
        "department_access": [],
        "capability_permissions": [],
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
        "workspace_permission": "owner",
        "role": "owner",
        "department_access": [],
        "capability_permissions": [],
        "can_switch": True,
    }
    assert asyncio.run(_organization_slug(sessionmaker, seeded.org_a_id)) == (
        "renamed-label"
    )


def test_list_members_requires_view_capability(
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
    assert response.json() == {"detail": "Insufficient capability permission"}


def test_list_members_allows_member_with_view_capability(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(
        client,
        seeded,
        role_for_org_a=MembershipRole.member,
        capability_permissions=("workspace.member.view",),
    )

    response = client.get(f"/api/v1/organizations/{seeded.org_a_id}/members")

    assert response.status_code == 200
    assert response.json()["total"] == 2


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
    owner = next(
        member for member in body["members"] if member["email"] == "owner@example.com"
    )
    member = next(
        member for member in body["members"] if member["email"] == "member@example.com"
    )
    assert owner["workspace_permission"] == "owner"
    assert owner["professional_roles"] == ["Legal", "Management"]
    assert member["professional_roles"] == ["Artist", "Producer", "Songwriter"]
    assert owner["department_access"] == ["management", "legal", "finance"]
    assert owner["pending_department_access"] == []
    assert owner["denied_department_access"] == []
    assert owner["capability_permissions"] == []
    assert "om_OWNER" not in response.text
    assert "om_MEMBER" not in response.text
    assert "session_SECRET" not in response.text


def test_get_current_authorization_context_returns_roles_and_deduped_capabilities(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(
        client,
        seeded,
        role_for_org_a=MembershipRole.member,
        capability_permissions=("analytics.view", "workspace.member.view"),
        role_capabilities=("analytics.view", "artist.profile.edit"),
    )

    response = client.get(
        f"/api/v1/organizations/{seeded.org_a_id}/authorization/context"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["workspace_id"] == str(seeded.org_a_id)
    assert body["roles"] == [{"key": "member", "name": "Member"}]
    assert body["capabilities"] == sorted(set(body["capabilities"]))
    assert "analytics.view" in body["capabilities"]
    assert "artist.profile.edit" in body["capabilities"]
    assert "workspace.member.view" in body["capabilities"]
    assert body["capabilities"].count("analytics.view") == 1
    assert "session_SECRET" not in response.text
    assert "owner@example.com" not in response.text


def test_current_authorization_context_requires_workspace_membership(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(client, seeded)

    response = client.get(
        f"/api/v1/organizations/{seeded.org_c_id}/authorization/context"
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_list_workspace_roles_returns_safe_deterministic_role_definitions(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client

    async def attach_role_capability() -> None:
        async with sessionmaker() as session:
            capability = Capability(
                key="analytics.view",
                display_name="View analytics",
                description="View analytics.",
                system_capability=True,
            )
            session.add(capability)
            await session.flush()
            session.add(
                RoleCapability(
                    role_id=seeded.manager_role_id,
                    capability_id=capability.id,
                )
            )
            await session.commit()

    asyncio.run(attach_role_capability())
    _set_context(client, seeded)

    response = client.get(f"/api/v1/organizations/{seeded.org_a_id}/roles")

    assert response.status_code == 200
    body = response.json()
    role_keys = [role["key"] for role in body["roles"]]
    assert role_keys == sorted(role_keys)
    manager = next(role for role in body["roles"] if role["key"] == "manager")
    assert manager["name"] == "Manager"
    assert manager["capabilities"] == ["analytics.view"]
    assert "metadata" not in response.text
    assert "session_SECRET" not in response.text


def test_list_workspace_roles_requires_role_view_capability(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(client, seeded, role_for_org_a=MembershipRole.member)

    response = client.get(f"/api/v1/organizations/{seeded.org_a_id}/roles")

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient capability permission"}


def test_list_member_role_assignments_returns_only_member_ids_and_roles(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(client, seeded)
    client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}/roles",
        json={"role_id": str(seeded.producer_role_id), "metadata": {"source": "test"}},
    )
    client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}/roles",
        json={"role_id": str(seeded.artist_role_id)},
    )

    response = client.get(
        f"/api/v1/organizations/{seeded.org_a_id}/member-role-assignments"
    )

    assert response.status_code == 200
    assignments = response.json()["assignments"]
    member_assignment = next(
        assignment
        for assignment in assignments
        if assignment["member_id"] == str(seeded.member_membership_id)
    )
    assert member_assignment == {
        "member_id": str(seeded.member_membership_id),
        "roles": [
            {"key": "artist", "name": "Artist"},
            {"key": "producer", "name": "Producer"},
        ],
    }
    assert "member@example.com" not in response.text
    assert "source" not in response.text
    assert "metadata" not in response.text


def test_list_member_role_assignments_requires_member_view_capability(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(client, seeded, role_for_org_a=MembershipRole.member)

    response = client.get(
        f"/api/v1/organizations/{seeded.org_a_id}/member-role-assignments"
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient capability permission"}


def test_assign_and_list_multiple_workspace_roles(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    _set_context(client, seeded)

    artist_response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}/roles",
        json={"role_id": str(seeded.artist_role_id), "metadata": {"source": "test"}},
    )
    producer_response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}/roles",
        json={"role_id": str(seeded.producer_role_id)},
    )
    list_response = client.get(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}/roles",
    )

    assert artist_response.status_code == 201
    assert producer_response.status_code == 201
    assert artist_response.json()["role"]["key"] == "artist"
    assert artist_response.json()["metadata"] == {"source": "test"}
    assert [item["role"]["key"] for item in list_response.json()["roles"]] == [
        "artist",
        "producer",
    ]
    assert asyncio.run(
        _workspace_role_keys(sessionmaker, seeded.member_membership_id)
    ) == ["artist", "producer"]
    events = asyncio.run(_realtime_events(sessionmaker, seeded.org_a_id))
    assert [event.event_type for event in events] == [
        "member.role_changed",
        "profile.role_added",
        "profile.roles_updated",
        "member.role_changed",
        "profile.role_added",
        "profile.roles_updated",
    ]
    assert events[0].payload["action"] == "assigned"
    assert events[0].payload["roleKey"] == "artist"
    assert events[1].entity_type == "profile"
    assert events[1].payload["workspaceId"] == str(seeded.org_a_id)
    assert events[1].payload["roleKey"] == "artist"
    assert events[2].entity_type == "profile"
    assert events[2].payload["workspaceId"] == str(seeded.org_a_id)
    assert events[2].payload["roleKey"] == "artist"
    assert events[2].payload["action"] == "assigned"
    assert "member@example.com" not in str(events[1].payload)
    assert "member@example.com" not in str(events[2].payload)


def test_duplicate_workspace_role_assignment_is_rejected(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    _set_context(client, seeded)
    payload = {"role_id": str(seeded.artist_role_id)}

    first_response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}/roles",
        json=payload,
    )
    duplicate_response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}/roles",
        json=payload,
    )

    assert first_response.status_code == 201
    assert duplicate_response.status_code == 409
    assert duplicate_response.json() == {
        "detail": "Workspace role is already assigned to this member"
    }
    assert asyncio.run(
        _workspace_role_keys(sessionmaker, seeded.member_membership_id)
    ) == ["artist"]


def test_assign_workspace_role_requires_labelos_role_assign_capability(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(
        client,
        seeded,
        role_for_org_a=MembershipRole.member,
        permissions=("members:manage",),
    )

    denied_response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}/roles",
        json={"role_id": str(seeded.artist_role_id)},
    )

    _set_context(
        client,
        seeded,
        role_for_org_a=MembershipRole.member,
        permissions=(),
        capability_permissions=(
            "workspace.member.roles.manage",
            "role.assign",
        ),
    )
    allowed_response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}/roles",
        json={"role_id": str(seeded.artist_role_id)},
    )

    assert denied_response.status_code == 403
    assert denied_response.json() == {"detail": "Insufficient capability permission"}
    assert allowed_response.status_code == 201


def test_assign_workspace_role_requires_member_roles_manage_capability(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(
        client,
        seeded,
        role_for_org_a=MembershipRole.member,
        capability_permissions=("role.assign",),
    )

    response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}/roles",
        json={"role_id": str(seeded.artist_role_id)},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient capability permission"}


def test_assign_workspace_role_rejects_role_with_forbidden_capabilities(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client

    async def attach_role_capability() -> None:
        async with sessionmaker() as session:
            capability = Capability(
                key="contract.execute",
                display_name="Execute contracts",
                description="Execute contract records.",
                system_capability=True,
            )
            session.add(capability)
            await session.flush()
            session.add(
                RoleCapability(
                    role_id=seeded.legal_role_id,
                    capability_id=capability.id,
                )
            )
            await session.commit()

    asyncio.run(attach_role_capability())
    _set_context(
        client,
        seeded,
        role_for_org_a=MembershipRole.member,
        capability_permissions=(
            "workspace.member.roles.manage",
            "role.assign",
        ),
    )

    response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}/roles",
        json={"role_id": str(seeded.legal_role_id)},
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Cannot administer a role with forbidden capabilities"
    }


def test_assign_workspace_role_rejects_self_escalation(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    _set_context(client, seeded)

    async def owner_membership_id() -> UUID:
        async with sessionmaker() as session:
            membership_id = await session.scalar(
                select(OrganizationMembership.id)
                .where(OrganizationMembership.organization_id == seeded.org_a_id)
                .where(OrganizationMembership.user_id == seeded.user_id)
            )
            assert membership_id is not None
            return membership_id

    response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{asyncio.run(owner_membership_id())}/roles",
        json={"role_id": str(seeded.legal_role_id)},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Cannot assign workspace roles to yourself"}


def test_assign_workspace_role_rejects_removed_target_membership(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    _set_context(client, seeded)

    async def remove_member() -> None:
        async with sessionmaker() as session:
            membership = await session.get(
                OrganizationMembership,
                seeded.member_membership_id,
            )
            assert membership is not None
            membership.status = "removed"
            await session.commit()

    asyncio.run(remove_member())

    response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}/roles",
        json={"role_id": str(seeded.artist_role_id)},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_assign_workspace_role_rechecks_removed_actor_membership(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    _set_context(client, seeded)

    async def remove_actor() -> None:
        async with sessionmaker() as session:
            membership = await session.scalar(
                select(OrganizationMembership)
                .where(OrganizationMembership.organization_id == seeded.org_a_id)
                .where(OrganizationMembership.user_id == seeded.user_id)
            )
            assert membership is not None
            membership.status = "removed"
            await session.commit()

    asyncio.run(remove_actor())

    response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}/roles",
        json={"role_id": str(seeded.artist_role_id)},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_workspace_role_assignments_can_differ_between_workspaces(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    _set_context(client, seeded, role_for_org_b=MembershipRole.admin)

    async def beta_membership_id() -> UUID:
        async with sessionmaker() as session:
            organization = await session.get(Organization, seeded.org_b_id)
            assert organization is not None
            beta_member = User(
                email="beta-member@example.com",
                display_name="Beta Member",
            )
            membership = OrganizationMembership(
                organization=organization,
                user=beta_member,
                role=MembershipRole.member,
            )
            session.add(membership)
            await session.commit()
            return membership.id

    beta_member_id = asyncio.run(beta_membership_id())
    client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}/roles",
        json={"role_id": str(seeded.artist_role_id)},
    )
    client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}/roles",
        json={"role_id": str(seeded.producer_role_id)},
    )
    client.post(
        f"/api/v1/organizations/{seeded.org_b_id}/members/{beta_member_id}/roles",
        json={"role_id": str(seeded.ar_role_id)},
    )

    assert asyncio.run(
        _workspace_role_keys(sessionmaker, seeded.member_membership_id)
    ) == ["artist", "producer"]
    assert asyncio.run(_workspace_role_keys(sessionmaker, beta_member_id)) == [
        "a_and_r"
    ]


def test_remove_workspace_role_keeps_universal_profile_and_publishes_activity(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    _set_context(client, seeded)
    assign_response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}/roles",
        json={"role_id": str(seeded.artist_role_id)},
    )
    profile_count = asyncio.run(_universal_profile_count(sessionmaker))

    remove_response = client.delete(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}/roles/{seeded.artist_role_id}",
    )

    assert assign_response.status_code == 201
    assert remove_response.status_code == 204
    assert (
        asyncio.run(_workspace_role_keys(sessionmaker, seeded.member_membership_id))
        == []
    )
    assert asyncio.run(_universal_profile_count(sessionmaker)) == profile_count
    events = asyncio.run(_realtime_events(sessionmaker, seeded.org_a_id))
    member_role_events = [
        event for event in events if event.event_type == "member.role_changed"
    ]
    profile_role_events = [
        event
        for event in events
        if event.event_type in {"profile.role_added", "profile.role_removed"}
    ]
    assert [event.payload["action"] for event in member_role_events] == [
        "assigned",
        "removed",
    ]
    assert [event.event_type for event in profile_role_events] == [
        "profile.role_added",
        "profile.role_removed",
    ]
    assert profile_role_events[-1].payload["roleKey"] == "artist"


def test_remove_member_requires_remove_capability(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(
        client,
        seeded,
        role_for_org_a=MembershipRole.member,
        capability_permissions=("workspace.member.view",),
    )

    response = client.delete(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}",
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient capability permission"}


def test_remove_member_marks_memberships_removed_and_publishes_activity(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    _set_context(client, seeded)

    response = client.delete(
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}",
    )

    assert response.status_code == 204
    assert (
        asyncio.run(_membership_status(sessionmaker, seeded.member_membership_id))
        == "removed"
    )
    assert (
        asyncio.run(
            _workspace_membership_status(sessionmaker, seeded.member_membership_id)
        )
        == "removed"
    )
    events = asyncio.run(_realtime_events(sessionmaker, seeded.org_a_id))
    assert [event.event_type for event in events] == [
        "member.removed",
        "profile.membership_updated",
    ]
    assert events[0].payload["membershipId"] == str(seeded.member_membership_id)
    assert events[0].payload["workspaceId"] == str(seeded.org_a_id)


def test_remove_last_workspace_owner_is_rejected(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    _set_context(client, seeded)

    async def owner_membership_id() -> UUID:
        async with sessionmaker() as session:
            membership_id = await session.scalar(
                select(OrganizationMembership.id)
                .where(OrganizationMembership.organization_id == seeded.org_a_id)
                .where(OrganizationMembership.user_id == seeded.user_id)
            )
            assert membership_id is not None
            return membership_id

    membership_id = asyncio.run(owner_membership_id())
    response = client.delete(
        f"/api/v1/organizations/{seeded.org_a_id}/members/{membership_id}",
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Cannot remove the last workspace owner"}


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


def test_create_workspace_invite_returns_general_join_link(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    _set_context(client, seeded)

    response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/invites",
        json={
            "email": "Sarah@Example.com",
            "professional_roles": ["Legal", "Management"],
            "expires_in_days": 14,
            "maximum_uses": 5,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["workspace"] == {
        "id": str(seeded.org_a_id),
        "name": "Alpha Label",
        "slug": "alpha-label",
    }
    assert body["inviter"] == {
        "id": str(seeded.user_id),
        "email": "owner@example.com",
        "display_name": "Owner",
    }
    assert body["maximum_uses"] == 5
    assert body["use_count"] == 0
    assert body["status"] == "active"
    assert body["join_path"] == f"/join/{body['token']}"
    assert body["email"] == "sarah@example.com"
    assert body["professional_roles"] == ["Legal", "Management"]
    assert body["workspace_roles"] == ["legal", "manager"]
    assert body["proposed_department_access"] == [
        "legal",
        "contracts",
        "agreements",
        "management",
        "artist",
        "releases",
        "marketing",
        "analytics",
    ]
    events = asyncio.run(_realtime_events(sessionmaker, seeded.org_a_id))
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "invitation.sent"
    assert event.actor_user_id == seeded.user_id
    assert event.entity_type == "invitation"
    assert event.entity_id == body["id"]
    assert event.created_at is not None
    assert event.payload["inviteId"] == body["id"]
    assert event.payload["workspaceId"] == str(seeded.org_a_id)
    assert event.payload["professionalRoles"] == ["Legal", "Management"]
    assert "sarah@example.com" not in str(event.payload)
    assert body["token"] not in str(event.payload)


def test_create_workspace_invite_accepts_explicit_department_access(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(client, seeded)

    response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/invites",
        json={
            "email": "Sarah@Example.com",
            "professional_roles": ["Legal", "Management"],
            "department_access": [
                "contracts",
                "agreements",
                "artist",
                "releases",
                "marketing",
                "contracts",
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["professional_roles"] == ["Legal", "Management"]
    assert body["proposed_department_access"] == [
        "contracts",
        "agreements",
        "artist",
        "releases",
        "marketing",
    ]


def test_create_workspace_invite_requires_member_management(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(client, seeded, role_for_org_a=MembershipRole.member)

    response = client.post(f"/api/v1/organizations/{seeded.org_a_id}/invites", json={})

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient capability permission"}


def test_create_workspace_invite_allows_member_with_invite_capability(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(
        client,
        seeded,
        role_for_org_a=MembershipRole.member,
        capability_permissions=("workspace.member.invite",),
    )

    response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/invites",
        json={"email": "capability-inviter@example.com"},
    )

    assert response.status_code == 201
    assert response.json()["email"] == "capability-inviter@example.com"


def test_create_workspace_invite_requires_role_assign_for_selected_roles(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(
        client,
        seeded,
        role_for_org_a=MembershipRole.member,
        capability_permissions=("workspace.member.invite",),
    )

    response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/invites",
        json={"email": "artist@example.com", "professional_roles": ["Artist"]},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient capability permission"}


def test_duplicate_active_workspace_invite_for_email_is_rejected(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, _sessionmaker, seeded = organizations_client
    _set_context(client, seeded)
    payload = {"email": "duplicate@example.com", "professional_roles": ["Artist"]}

    first_response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/invites",
        json=payload,
    )
    duplicate_response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/invites",
        json={"email": "DUPLICATE@example.com", "professional_roles": ["Legal"]},
    )

    assert first_response.status_code == 201
    assert duplicate_response.status_code == 409
    assert duplicate_response.json() == {
        "detail": "An active invite already exists for this email"
    }


def test_get_workspace_invite_returns_public_invite_fields(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    token = "public-token"

    async def seed_invite() -> None:
        async with sessionmaker() as session:
            session.add(
                WorkspaceInvite(
                    token=token,
                    organization_id=seeded.org_a_id,
                    inviter_user_id=seeded.user_id,
                    expires_at=datetime.now(UTC) + timedelta(days=3),
                    maximum_uses=None,
                    status="active",
                )
            )
            await session.commit()

    asyncio.run(seed_invite())

    response = client.get(f"/api/v1/organizations/invites/{token}")

    assert response.status_code == 200
    body = response.json()
    assert body["token"] == token
    assert body["workspace"]["name"] == "Alpha Label"
    assert body["inviter"]["email"] == "owner@example.com"
    assert body["maximum_uses"] is None
    assert body["status"] == "active"
    assert body["email"] is None
    assert body["professional_roles"] == []
    assert body["workspace_roles"] == []
    assert body["proposed_department_access"] == []


def test_accept_workspace_invite_creates_member_without_professional_role(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    _set_context(client, seeded)
    invite_response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/invites",
        json={"maximum_uses": 1},
    )
    token = invite_response.json()["token"]
    _set_joiner_context(client, seeded)

    response = client.post(f"/api/v1/organizations/invites/{token}/accept")

    assert response.status_code == 200
    body = response.json()
    membership_id = UUID(body["membership_id"])
    assert body["workspace"]["id"] == str(seeded.org_a_id)
    assert body["status"] == "active"
    assert (
        asyncio.run(_membership_role(sessionmaker, seeded.org_a_id, seeded.joiner_id))
        == MembershipRole.member
    )
    assert (
        asyncio.run(_membership_professional_role_count(sessionmaker, membership_id))
        == 0
    )


def test_accept_workspace_invite_assigns_selected_professional_roles(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    _set_context(client, seeded)
    invite_response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/invites",
        json={"maximum_uses": 1},
    )
    token = invite_response.json()["token"]
    _set_joiner_context(client, seeded)

    response = client.post(
        f"/api/v1/organizations/invites/{token}/accept",
        json={"professional_roles": ["Artist", "Producer", "A&R", "Artist"]},
    )

    assert response.status_code == 200
    membership_id = UUID(response.json()["membership_id"])
    professional_roles = asyncio.run(
        _membership_professional_roles(sessionmaker, membership_id)
    )
    assert professional_roles[0] == "Artist"
    assert set(professional_roles) == {"Artist", "Producer", "A&R"}


def test_accept_workspace_invite_assigns_invitation_professional_roles(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    _set_context(client, seeded)
    invite_response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/invites",
        json={
            "email": "sarah@example.com",
            "professional_roles": ["Legal", "Management"],
            "maximum_uses": 1,
        },
    )
    token = invite_response.json()["token"]
    _set_joiner_context(client, seeded)

    response = client.post(f"/api/v1/organizations/invites/{token}/accept")

    assert response.status_code == 200
    membership_id = UUID(response.json()["membership_id"])
    professional_roles = asyncio.run(
        _membership_professional_roles(sessionmaker, membership_id)
    )
    assert professional_roles == ["Legal", "Management"]
    assert asyncio.run(_workspace_role_keys(sessionmaker, membership_id)) == [
        "legal",
        "manager",
    ]
    events = asyncio.run(_realtime_events(sessionmaker, seeded.org_a_id))
    assert [event.event_type for event in events] == [
        "invitation.sent",
        "profile.created",
        "profile.workspace_joined",
        "profile.membership_updated",
        "invitation.accepted",
        "member.joined",
        "profile.roles_updated",
    ]
    assert events[1].entity_type == "profile"
    assert events[1].payload["workspaceId"] == str(seeded.org_a_id)
    assert events[2].payload["profileId"] == events[1].payload["profileId"]
    assert events[3].payload["profileId"] == events[1].payload["profileId"]
    assert events[3].payload["status"] == "active"
    assert events[4].payload["profileId"] == events[1].payload["profileId"]
    assert "sarah@example.com" not in str(events[3].payload)
    assert "sarah@example.com" not in str(events[4].payload)
    assert events[-2].event_type == "member.joined"
    assert events[-2].payload["professionalRoles"] == ["Legal", "Management"]
    assert [role["key"] for role in events[-2].payload["workspaceRoles"]] == [
        "legal",
        "manager",
    ]
    assert events[-1].payload["professionalRoles"] == ["Legal", "Management"]


def test_accept_workspace_invite_for_existing_user_adds_second_workspace_roles(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    _set_context(
        client,
        seeded,
        active_organization_id=seeded.org_b_id,
        role_for_org_b=MembershipRole.admin,
    )
    invite_response = client.post(
        f"/api/v1/organizations/{seeded.org_b_id}/invites",
        json={
            "email": "joiner@example.com",
            "professional_roles": ["Artist", "Producer"],
            "maximum_uses": 1,
        },
    )
    token = invite_response.json()["token"]
    _set_joiner_context(client, seeded)

    response = client.post(f"/api/v1/organizations/invites/{token}/accept")

    assert response.status_code == 200
    membership_id = UUID(response.json()["membership_id"])
    assert response.json()["workspace"]["id"] == str(seeded.org_b_id)
    assert asyncio.run(_workspace_role_keys(sessionmaker, membership_id)) == [
        "artist",
        "producer",
    ]


def test_accept_workspace_invite_is_idempotent_for_existing_active_member(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    _set_context(client, seeded)
    invite_response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/invites",
        json={
            "email": "joiner@example.com",
            "professional_roles": ["Artist"],
            "maximum_uses": 2,
        },
    )
    token = invite_response.json()["token"]
    _set_joiner_context(client, seeded)

    first_response = client.post(f"/api/v1/organizations/invites/{token}/accept")
    second_response = client.post(f"/api/v1/organizations/invites/{token}/accept")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    membership_id = UUID(second_response.json()["membership_id"])
    assert asyncio.run(_workspace_role_keys(sessionmaker, membership_id)) == ["artist"]


def test_accept_workspace_invite_grants_invitation_department_access(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    _set_context(client, seeded)
    invite_response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/invites",
        json={
            "email": "sarah@example.com",
            "professional_roles": ["Legal", "Management"],
            "department_access": ["contracts", "agreements", "artist", "releases"],
            "maximum_uses": 1,
        },
    )
    token = invite_response.json()["token"]
    _set_joiner_context(client, seeded)

    response = client.post(f"/api/v1/organizations/invites/{token}/accept")

    assert response.status_code == 200
    membership_id = UUID(response.json()["membership_id"])
    department_access = asyncio.run(
        _membership_department_access(sessionmaker, membership_id)
    )
    assert set(department_access) == {
        ("contracts", "invitation"),
        ("agreements", "invitation"),
        ("artist", "invitation"),
        ("releases", "invitation"),
    }


def test_accept_workspace_invite_rejects_expired_invite(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
    ],
) -> None:
    client, sessionmaker, seeded = organizations_client
    token = "expired-token"

    async def seed_invite() -> None:
        async with sessionmaker() as session:
            session.add(
                WorkspaceInvite(
                    token=token,
                    organization_id=seeded.org_a_id,
                    inviter_user_id=seeded.user_id,
                    expires_at=datetime.now(UTC) - timedelta(days=1),
                    maximum_uses=1,
                    status="active",
                )
            )
            await session.commit()

    asyncio.run(seed_invite())
    _set_joiner_context(client, seeded)

    response = client.post(f"/api/v1/organizations/invites/{token}/accept")

    assert response.status_code == 410
    assert response.json() == {"detail": "Invite is no longer available"}


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
