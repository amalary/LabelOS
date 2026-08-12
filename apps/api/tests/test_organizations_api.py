import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from labelos_database.base import Base
from labelos_database.models import (
    ActivityEvent,
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
from labelos_api.workos_client import get_workos_client


@dataclass(frozen=True)
class SeededOrganizations:
    user_id: UUID
    org_a_id: UUID
    org_b_id: UUID
    org_c_id: UUID
    inactive_org_id: UUID
    member_id: UUID
    member_membership_id: UUID


class FakeWorkOSClient:
    def __init__(self) -> None:
        self.invitations: list[dict] = []
        self.memberships: dict[str, dict] = {
            "om_MEMBER": {
                "id": "om_MEMBER",
                "user_id": "user_MEMBER",
                "organization_id": "org_ALPHA",
                "status": "active",
                "role": {"slug": "member"},
                "user": {
                    "email": "member@example.com",
                    "name": "Member",
                },
            },
            "om_OWNER": {
                "id": "om_OWNER",
                "user_id": "user_OWNER",
                "organization_id": "org_ALPHA",
                "status": "active",
                "role": {"slug": "owner"},
                "user": {
                    "email": "owner@example.com",
                    "name": "Owner",
                },
            },
            "om_JOIN": {
                "id": "om_JOIN",
                "user_id": "user_01TEST",
                "organization_id": "org_JOIN",
                "status": "active",
                "role": {"slug": "member"},
                "user": {
                    "email": "owner@example.com",
                    "name": "Owner",
                },
            },
        }
        self.deleted_membership_ids: list[str] = []

    async def list_invitations(
        self,
        *,
        organization_id: str,
        email: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return [
            invitation
            for invitation in self.invitations[:limit]
            if invitation["organization_id"] == organization_id
            and (email is None or invitation["email"] == email)
        ]

    async def send_invitation(
        self,
        *,
        email: str,
        organization_id: str,
        role_slug: str,
        inviter_user_id: str | None,
    ) -> dict:
        invitation = {
            "id": f"invitation_{len(self.invitations) + 1:02d}",
            "email": email,
            "state": "pending",
            "organization_id": organization_id,
            "role_slug": role_slug,
            "inviter_user_id": inviter_user_id,
            "token": "SECRET_TOKEN",
            "accept_invitation_url": "https://example.test/invite?token=SECRET_TOKEN",
            "created_at": "2026-08-03T12:00:00.000Z",
            "expires_at": "2026-08-10T12:00:00.000Z",
        }
        self.invitations.append(invitation)
        return invitation

    async def find_invitation_by_token(self, token: str) -> dict:
        if token != "join_TOKEN":
            raise AssertionError("unexpected invitation token")
        return {
            "id": "invitation_JOIN",
            "email": "owner@example.com",
            "state": "pending",
            "organization_id": "org_JOIN",
            "role_slug": "member",
        }

    async def accept_invitation(self, invitation_id: str) -> dict:
        assert invitation_id == "invitation_JOIN"
        return {"id": invitation_id, "state": "accepted"}

    async def list_organization_memberships(
        self,
        *,
        organization_id: str,
        user_id: str | None = None,
        statuses: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return [
            membership
            for membership in self.memberships.values()
            if membership["organization_id"] == organization_id
            and (user_id is None or membership["user_id"] == user_id)
            and (not statuses or membership["status"] in statuses)
        ][:limit]

    async def update_organization_membership(
        self,
        *,
        membership_id: str,
        role_slug: str,
    ) -> dict:
        membership = self.memberships[membership_id]
        membership["role"] = {"slug": role_slug}
        return membership

    async def delete_organization_membership(self, membership_id: str) -> None:
        self.deleted_membership_ids.append(membership_id)
        self.memberships.pop(membership_id, None)


@pytest.fixture
def organizations_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[
    tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
        FakeWorkOSClient,
    ]
]:
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
                    OrganizationMembership(
                        organization=org_a,
                        user=user,
                        role=MembershipRole.owner,
                        workos_membership_id="om_OWNER",
                    ),
                    member_membership,
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
            )

    seeded = asyncio.run(prepare_database())
    app = create_app()
    fake_workos = FakeWorkOSClient()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    async def override_workos():
        yield fake_workos

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_workos_client] = override_workos

    with TestClient(app) as client:
        yield client, sessionmaker, seeded, fake_workos

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


async def _membership_by_id(
    sessionmaker: async_sessionmaker[AsyncSession],
    membership_id: UUID,
) -> OrganizationMembership | None:
    async with sessionmaker() as session:
        return await session.get(OrganizationMembership, membership_id)


async def _activity_events(
    sessionmaker: async_sessionmaker[AsyncSession],
    organization_id: UUID,
) -> list[ActivityEvent]:
    async with sessionmaker() as session:
        events = await session.scalars(
            select(ActivityEvent)
            .where(ActivityEvent.organization_id == organization_id)
            .order_by(ActivityEvent.created_at.asc(), ActivityEvent.id.asc())
        )
        return list(events.all())


async def _set_membership_role(
    sessionmaker: async_sessionmaker[AsyncSession],
    membership_id: UUID,
    role: MembershipRole,
) -> None:
    async with sessionmaker() as session:
        membership = await session.get(OrganizationMembership, membership_id)
        assert membership is not None
        membership.role = role
        await session.commit()


def test_organizations_require_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/organizations")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_list_organizations_for_current_user_with_pagination(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organizations_client
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
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organizations_client
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
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organizations_client
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
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organizations_client
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
        FakeWorkOSClient,
    ],
) -> None:
    client, sessionmaker, seeded, _workos = organizations_client
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
    events = asyncio.run(_activity_events(sessionmaker, organization_id))
    assert [event.event_type for event in events] == [
        "organization.created",
        "member.joined",
    ]
    assert events[0].operation == "create_organization"
    assert events[0].actor_user_id == seeded.user_id
    assert events[0].changes == {
        "name": {"from": None, "to": "New Label"},
        "slug": {"from": None, "to": "new-label"},
    }


def test_create_organization_rejects_duplicate_slug(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organizations_client
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
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organizations_client
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
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organizations_client
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
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organizations_client
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
        FakeWorkOSClient,
    ],
) -> None:
    client, sessionmaker, seeded, _workos = organizations_client
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
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organizations_client
    _set_context(client, seeded, role_for_org_a=MembershipRole.member)

    response = client.get(f"/api/v1/organizations/{seeded.org_a_id}/members")

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient organization role"}


def test_list_members_returns_paginated_safe_member_records(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, workos = organizations_client
    workos.invitations.append(
        {
            "id": "invitation_PENDING",
            "email": "new@example.com",
            "state": "pending",
            "organization_id": "org_ALPHA",
            "role_slug": "viewer",
            "token": "SECRET_TOKEN",
            "accept_invitation_url": "https://example.test/SECRET_TOKEN",
        }
    )
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
    assert body["invitations"] == [
        {
            "id": "invitation_PENDING",
            "email": "new@example.com",
            "role": "viewer",
            "state": "pending",
            "expires_at": None,
            "created_at": None,
        }
    ]
    assert "om_OWNER" not in response.text
    assert "om_MEMBER" not in response.text
    assert "session_SECRET" not in response.text
    assert "SECRET_TOKEN" not in response.text


def test_invite_member_uses_workos_and_returns_pending_invitation_without_token(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
        FakeWorkOSClient,
    ],
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, sessionmaker, seeded, workos = organizations_client
    _set_context(client, seeded, active_organization_id=seeded.org_a_id)

    caplog.set_level("INFO", logger="labelos_api.audit")
    response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/invitations",
        json={"email": " New.Member@Example.COM ", "role": "viewer"},
    )

    assert response.status_code == 201
    assert response.json()["email"] == "new.member@example.com"
    assert response.json()["state"] == "pending"
    assert response.json()["role"] == "viewer"
    assert workos.invitations[0]["inviter_user_id"] == "user_01TEST"
    assert "SECRET_TOKEN" not in response.text
    assert "accept_invitation_url" not in response.text
    events = asyncio.run(_activity_events(sessionmaker, seeded.org_a_id))
    invited = [event for event in events if event.event_type == "member.invited"]
    assert len(invited) == 1
    assert invited[0].operation == "invite_organization_member"
    assert invited[0].actor_user_id == seeded.user_id
    assert invited[0].entity_type == "invitation"
    assert invited[0].changes == {"role": {"from": None, "to": "viewer"}}
    assert invited[0].event_metadata == {
        "invitation_id": response.json()["id"],
        "invitation_state": "pending",
    }
    audit_records = [
        record for record in caplog.records if record.name == "labelos_api.audit"
    ]
    assert len(audit_records) == 1
    assert audit_records[0].event_type == "member.invited"
    assert audit_records[0].operation == "invite_organization_member"
    assert audit_records[0].result == "success"
    log_payload = str(audit_records[0].__dict__)
    assert "SECRET_TOKEN" not in log_payload
    assert "accept_invitation_url" not in log_payload
    assert "new.member@example.com" not in log_payload


def test_invite_member_rejects_already_member_and_already_invited(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, workos = organizations_client
    _set_context(client, seeded, active_organization_id=seeded.org_a_id)

    member_response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/invitations",
        json={"email": "member@example.com", "role": "member"},
    )
    assert member_response.status_code == 409
    assert member_response.json() == {"detail": "User is already an active member"}

    workos.invitations.append(
        {
            "id": "invitation_EXISTING",
            "email": "pending@example.com",
            "state": "pending",
            "organization_id": "org_ALPHA",
            "role_slug": "member",
        }
    )
    invited_response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/invitations",
        json={"email": "pending@example.com", "role": "member"},
    )
    assert invited_response.status_code == 409
    assert invited_response.json() == {
        "detail": "User already has a pending invitation"
    }


def test_join_organization_accepts_verified_invitation_and_syncs_membership(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
        FakeWorkOSClient,
    ],
) -> None:
    client, sessionmaker, seeded, _workos = organizations_client
    _set_context(client, seeded, active_workos_organization_id=None)

    response = client.post(
        "/api/v1/organizations/join",
        json={"invitation_token": "join_TOKEN"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "owner@example.com"
    assert response.json()["role"] == "member"
    assert "join_TOKEN" not in response.text

    async def membership_exists() -> bool:
        async with sessionmaker() as session:
            organization = await session.scalar(
                select(Organization).where(
                    Organization.workos_organization_id == "org_JOIN"
                )
            )
            if organization is None:
                return False
            membership = await session.scalar(
                select(OrganizationMembership)
                .where(OrganizationMembership.organization_id == organization.id)
                .where(OrganizationMembership.user_id == seeded.user_id)
            )
            return (
                membership is not None and membership.workos_membership_id == "om_JOIN"
            )

    assert asyncio.run(membership_exists())


def test_update_member_role_requires_active_organization_context(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organizations_client
    _set_context(client, seeded, active_workos_organization_id=None)

    response = client.patch(
        f"/api/v1/organizations/{seeded.org_a_id}/members/{seeded.member_membership_id}",
        json={"role": "admin"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Active organization mismatch"}


def test_update_member_role_requires_owner_and_members_permission(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organizations_client
    _set_context(
        client,
        seeded,
        active_organization_id=seeded.org_a_id,
        role_for_org_a=MembershipRole.admin,
    )

    role_response = client.patch(
        f"/api/v1/organizations/{seeded.org_a_id}/members/{seeded.member_membership_id}",
        json={"role": "admin"},
    )

    assert role_response.status_code == 403
    assert role_response.json() == {"detail": "Insufficient organization role"}

    _set_context(
        client,
        seeded,
        active_organization_id=seeded.org_a_id,
        permissions=("organization:manage",),
    )

    permission_response = client.patch(
        f"/api/v1/organizations/{seeded.org_a_id}/members/{seeded.member_membership_id}",
        json={"role": "admin"},
    )

    assert permission_response.status_code == 403
    assert permission_response.json() == {"detail": "Insufficient permission"}


def test_update_member_role_changes_non_owner_member(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
        FakeWorkOSClient,
    ],
) -> None:
    client, sessionmaker, seeded, _workos = organizations_client
    _set_context(client, seeded, active_organization_id=seeded.org_a_id)

    response = client.patch(
        f"/api/v1/organizations/{seeded.org_a_id}/members/{seeded.member_membership_id}",
        json={"role": "admin"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "admin"
    assert body["email"] == "member@example.com"
    membership = asyncio.run(
        _membership_by_id(sessionmaker, seeded.member_membership_id)
    )
    assert membership is not None
    assert membership.role == MembershipRole.admin
    assert _workos.memberships["om_MEMBER"]["role"] == {"slug": "admin"}


def test_update_member_role_rejects_owner_role(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organizations_client
    _set_context(client, seeded, active_organization_id=seeded.org_a_id)

    response = client.patch(
        f"/api/v1/organizations/{seeded.org_a_id}/members/{seeded.member_membership_id}",
        json={"role": "owner"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Request validation failed"}


def test_remove_member_deletes_workos_and_local_membership(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
        FakeWorkOSClient,
    ],
) -> None:
    client, sessionmaker, seeded, workos = organizations_client
    _set_context(client, seeded, active_organization_id=seeded.org_a_id)

    response = client.delete(
        f"/api/v1/organizations/{seeded.org_a_id}/members/{seeded.member_membership_id}"
    )

    assert response.status_code == 204
    assert "om_MEMBER" in workos.deleted_membership_ids
    assert (
        asyncio.run(_membership_by_id(sessionmaker, seeded.member_membership_id))
        is None
    )


def test_remove_member_prevents_final_owner(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
        FakeWorkOSClient,
    ],
) -> None:
    client, sessionmaker, seeded, _workos = organizations_client
    _set_context(client, seeded, active_organization_id=seeded.org_a_id)
    asyncio.run(
        _set_membership_role(
            sessionmaker,
            seeded.member_membership_id,
            MembershipRole.owner,
        )
    )

    async def demote_context_user() -> None:
        async with sessionmaker() as session:
            membership = await session.scalar(
                select(OrganizationMembership)
                .where(OrganizationMembership.organization_id == seeded.org_a_id)
                .where(OrganizationMembership.user_id == seeded.user_id)
            )
            assert membership is not None
            membership.role = MembershipRole.member
            await session.commit()

    asyncio.run(demote_context_user())

    response = client.delete(
        f"/api/v1/organizations/{seeded.org_a_id}/members/{seeded.member_membership_id}"
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Cannot remove the final owner"}


def test_cross_organization_members_returns_not_found(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organizations_client
    _set_context(client, seeded)

    response = client.get(f"/api/v1/organizations/{seeded.org_c_id}/members")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_invalid_organization_id_returns_validation_error(
    organizations_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededOrganizations,
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organizations_client
    _set_context(client, seeded)

    response = client.get(f"/api/v1/organizations/{uuid4()}-bad/members")

    assert response.status_code == 422
    assert response.json() == {"detail": "Request validation failed"}
