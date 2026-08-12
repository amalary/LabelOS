import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from labelos_database.base import Base
from labelos_database.models import (
    Artist,
    MembershipRole,
    Organization,
    OrganizationMembership,
    Release,
    User,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from labelos_api.auth import (
    AuthenticatedPrincipal,
    CurrentUserContext,
    MembershipContext,
    get_current_principal,
    get_current_user_context,
    get_session,
)
from labelos_api.main import create_app
from labelos_api.realtime import RealtimeEventType, RealtimePublisher
from labelos_api.realtime.events import list_events_after
from labelos_api.workos_client import get_workos_client


@dataclass(frozen=True)
class OrganizationSecuritySeed:
    org_a_id: UUID
    org_b_id: UUID
    owner_a_id: UUID
    member_a_id: UUID
    owner_b_id: UUID
    member_b_id: UUID
    owner_a_membership_id: UUID
    member_a_membership_id: UUID
    owner_b_membership_id: UUID
    member_b_membership_id: UUID
    artist_a_id: UUID
    artist_b_id: UUID
    release_a_id: UUID
    release_b_id: UUID


class FakeWorkOSClient:
    def __init__(self) -> None:
        self.deleted_membership_ids: list[str] = []
        self.memberships: dict[str, dict] = {
            "om_MEMBER_A": {
                "id": "om_MEMBER_A",
                "user_id": "user_MEMBER_A",
                "organization_id": "org_ALPHA",
                "status": "active",
                "role": {"slug": "admin"},
                "user": {"email": "member-a@example.com", "name": "Member A"},
            },
            "om_MEMBER_B": {
                "id": "om_MEMBER_B",
                "user_id": "user_MEMBER_B",
                "organization_id": "org_BETA",
                "status": "active",
                "role": {"slug": "admin"},
                "user": {"email": "member-b@example.com", "name": "Member B"},
            },
        }

    async def list_invitations(
        self,
        *,
        organization_id: str,
        email: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return []

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
def organization_security_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[
    tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        OrganizationSecuritySeed,
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

    async def prepare_database() -> OrganizationSecuritySeed:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with sessionmaker() as session:
            owner_a = User(
                workos_user_id="user_OWNER_A",
                email="owner-a@example.com",
                display_name="Owner A",
            )
            member_a = User(
                workos_user_id="user_MEMBER_A",
                email="member-a@example.com",
                display_name="Member A",
            )
            owner_b = User(
                workos_user_id="user_OWNER_B",
                email="owner-b@example.com",
                display_name="Owner B",
            )
            member_b = User(
                workos_user_id="user_MEMBER_B",
                email="member-b@example.com",
                display_name="Member B",
            )
            org_a = Organization(
                name="Organization A",
                slug="organization-a",
                workos_organization_id="org_ALPHA",
                owner=owner_a,
            )
            org_b = Organization(
                name="Organization B",
                slug="organization-b",
                workos_organization_id="org_BETA",
                owner=owner_b,
            )
            artist_a = Artist(name="Artist A", organization=org_a)
            artist_b = Artist(name="Artist B", organization=org_b)
            release_a = Release(title="Release A", artist=artist_a, organization=org_a)
            release_b = Release(title="Release B", artist=artist_b, organization=org_b)
            owner_a_membership = OrganizationMembership(
                organization=org_a,
                user=owner_a,
                role=MembershipRole.owner,
                workos_membership_id="om_OWNER_A",
            )
            member_a_membership = OrganizationMembership(
                organization=org_a,
                user=member_a,
                role=MembershipRole.member,
                workos_membership_id="om_MEMBER_A",
            )
            owner_b_membership = OrganizationMembership(
                organization=org_b,
                user=owner_b,
                role=MembershipRole.owner,
                workos_membership_id="om_OWNER_B",
            )
            member_b_membership = OrganizationMembership(
                organization=org_b,
                user=member_b,
                role=MembershipRole.member,
                workos_membership_id="om_MEMBER_B",
            )
            session.add_all(
                [
                    owner_a,
                    member_a,
                    owner_b,
                    member_b,
                    org_a,
                    org_b,
                    artist_a,
                    artist_b,
                    release_a,
                    release_b,
                    owner_a_membership,
                    member_a_membership,
                    owner_b_membership,
                    member_b_membership,
                ]
            )
            await session.commit()
            return OrganizationSecuritySeed(
                org_a_id=org_a.id,
                org_b_id=org_b.id,
                owner_a_id=owner_a.id,
                member_a_id=member_a.id,
                owner_b_id=owner_b.id,
                member_b_id=member_b.id,
                owner_a_membership_id=owner_a_membership.id,
                member_a_membership_id=member_a_membership.id,
                owner_b_membership_id=owner_b_membership.id,
                member_b_membership_id=member_b_membership.id,
                artist_a_id=artist_a.id,
                artist_b_id=artist_b.id,
                release_a_id=release_a.id,
                release_b_id=release_b.id,
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


def _authenticate(
    client: TestClient,
    *,
    subject: str,
    email: str,
    organization_id: str | None,
    role: str,
    permissions: tuple[str, ...],
) -> None:
    async def override_principal() -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            provider="workos",
            subject=subject,
            session_id=f"session_{subject}",
            email=email,
            display_name=email.split("@", maxsplit=1)[0],
            organization_id=organization_id,
            role=role,
            roles=(role,),
            permissions=permissions,
        )

    client.app.dependency_overrides[get_current_principal] = override_principal


def _authenticate_owner_a(client: TestClient) -> None:
    _authenticate(
        client,
        subject="user_OWNER_A",
        email="owner-a@example.com",
        organization_id="org_ALPHA",
        role="owner",
        permissions=(
            "organization:manage",
            "members:manage",
            "artists:view",
            "artists:manage",
            "releases:view",
        ),
    )


def _authenticate_stale_owner_a_context(
    client: TestClient,
    seeded: OrganizationSecuritySeed,
) -> None:
    async def override_context() -> CurrentUserContext:
        return CurrentUserContext(
            user=User(
                id=seeded.owner_a_id,
                email="owner-a@example.com",
                display_name="Owner A",
            ),
            principal=AuthenticatedPrincipal(
                provider="workos",
                subject="user_OWNER_A",
                session_id="session_user_OWNER_A",
                email="owner-a@example.com",
                display_name="Owner A",
                organization_id="org_ALPHA",
                role="owner",
                roles=("owner",),
                permissions=("members:manage",),
            ),
            memberships=(
                MembershipContext(
                    organization_id=seeded.org_a_id,
                    organization_name="Organization A",
                    organization_slug="organization-a",
                    workos_organization_id="org_ALPHA",
                    role=MembershipRole.owner,
                ),
            ),
        )

    client.app.dependency_overrides[get_current_user_context] = override_context


def _authenticate_owner_b(client: TestClient) -> None:
    _authenticate(
        client,
        subject="user_OWNER_B",
        email="owner-b@example.com",
        organization_id="org_BETA",
        role="owner",
        permissions=(
            "organization:manage",
            "members:manage",
            "artists:view",
            "artists:manage",
            "releases:view",
        ),
    )


def _authenticate_member_a(client: TestClient) -> None:
    _authenticate(
        client,
        subject="user_MEMBER_A",
        email="member-a@example.com",
        organization_id="org_ALPHA",
        role="member",
        permissions=("artists:view", "releases:view"),
    )


async def _artist_name(
    sessionmaker: async_sessionmaker[AsyncSession],
    artist_id: UUID,
) -> str | None:
    async with sessionmaker() as session:
        artist = await session.get(Artist, artist_id)
        return artist.name if artist is not None else None


async def _membership_exists(
    sessionmaker: async_sessionmaker[AsyncSession],
    membership_id: UUID,
) -> bool:
    async with sessionmaker() as session:
        return await session.get(OrganizationMembership, membership_id) is not None


async def _delete_membership(
    sessionmaker: async_sessionmaker[AsyncSession],
    membership_id: UUID,
) -> None:
    async with sessionmaker() as session:
        membership = await session.get(OrganizationMembership, membership_id)
        assert membership is not None
        await session.delete(membership)
        await session.commit()


async def _make_member_a_only_active_owner(
    sessionmaker: async_sessionmaker[AsyncSession],
    seeded: OrganizationSecuritySeed,
) -> None:
    async with sessionmaker() as session:
        owner_a = await session.get(
            OrganizationMembership, seeded.owner_a_membership_id
        )
        member_a = await session.get(
            OrganizationMembership, seeded.member_a_membership_id
        )
        assert owner_a is not None
        assert member_a is not None
        owner_a.role = MembershipRole.member
        member_a.role = MembershipRole.owner
        await session.commit()


def test_organization_a_users_can_access_organization_a(
    organization_security_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        OrganizationSecuritySeed,
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organization_security_client
    _authenticate_owner_a(client)

    organization_response = client.get("/api/v1/organizations/current")
    artist_response = client.get(f"/api/v1/artists/{seeded.artist_a_id}")

    assert organization_response.status_code == 200
    assert organization_response.json()["id"] == str(seeded.org_a_id)
    assert artist_response.status_code == 200
    assert artist_response.json()["id"] == str(seeded.artist_a_id)


def test_cross_organization_access_is_denied_both_directions(
    organization_security_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        OrganizationSecuritySeed,
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organization_security_client
    _authenticate_owner_a(client)

    a_to_b = client.get(f"/api/v1/artists/{seeded.artist_b_id}")

    _authenticate_owner_b(client)
    b_to_a = client.get(f"/api/v1/artists/{seeded.artist_a_id}")

    assert a_to_b.status_code == 404
    assert b_to_a.status_code == 404


def test_url_resource_id_manipulation_cannot_bypass_authorization(
    organization_security_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        OrganizationSecuritySeed,
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organization_security_client
    _authenticate_owner_a(client)

    member_response = client.patch(
        f"/api/v1/organizations/{seeded.org_a_id}/members/{seeded.member_b_membership_id}",
        json={"role": "admin"},
    )
    nested_response = client.get(f"/api/v1/artists/{seeded.artist_b_id}/releases")

    assert member_response.status_code == 404
    assert nested_response.status_code == 404


def test_cross_org_updates_and_deletes_fail_without_mutation(
    organization_security_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        OrganizationSecuritySeed,
        FakeWorkOSClient,
    ],
) -> None:
    client, sessionmaker, seeded, _workos = organization_security_client
    _authenticate_owner_a(client)

    update_response = client.patch(
        f"/api/v1/artists/{seeded.artist_b_id}",
        json={"name": "Cross Org Rename"},
    )
    delete_response = client.delete(f"/api/v1/artists/{seeded.artist_b_id}")

    assert update_response.status_code == 404
    assert delete_response.status_code == 404
    assert asyncio.run(_artist_name(sessionmaker, seeded.artist_b_id)) == "Artist B"


def test_lists_and_searches_never_leak_records(
    organization_security_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        OrganizationSecuritySeed,
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organization_security_client
    _authenticate_owner_a(client)

    organizations_response = client.get("/api/v1/organizations")
    artists_response = client.get("/api/v1/artists", params={"search": "Artist"})

    assert organizations_response.status_code == 200
    assert {org["id"] for org in organizations_response.json()["organizations"]} == {
        str(seeded.org_a_id)
    }
    assert str(seeded.org_b_id) not in organizations_response.text
    assert artists_response.status_code == 200
    assert {artist["id"] for artist in artists_response.json()["artists"]} == {
        str(seeded.artist_a_id)
    }
    assert str(seeded.artist_b_id) not in artists_response.text


def test_removed_members_lose_access_immediately(
    organization_security_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        OrganizationSecuritySeed,
        FakeWorkOSClient,
    ],
) -> None:
    client, sessionmaker, seeded, _workos = organization_security_client
    _authenticate_member_a(client)

    before_removal = client.get(f"/api/v1/artists/{seeded.artist_a_id}")
    asyncio.run(_delete_membership(sessionmaker, seeded.member_a_membership_id))
    after_removal = client.get(f"/api/v1/artists/{seeded.artist_a_id}")

    assert before_removal.status_code == 200
    assert after_removal.status_code == 403
    assert after_removal.json() == {"detail": "Organization context required"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/realtime/organizations/not-a-uuid/events"),
        ("post", "/api/v1/organizations/not-a-uuid/activate"),
        ("patch", "/api/v1/organizations/not-a-uuid"),
    ],
)
def test_invalid_organization_ids_fail_safely(
    method: str,
    path: str,
    organization_security_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        OrganizationSecuritySeed,
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, _seeded, _workos = organization_security_client
    _authenticate_owner_a(client)

    if method == "get":
        response = client.get(path)
    else:
        response = getattr(client, method)(path, json={"name": "Ignored"})

    assert response.status_code == 422
    assert response.json() == {"detail": "Request validation failed"}


def test_organization_switching_cannot_bypass_authorization(
    organization_security_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        OrganizationSecuritySeed,
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organization_security_client
    _authenticate(
        client,
        subject="user_OWNER_A",
        email="owner-a@example.com",
        organization_id="org_BETA",
        role="owner",
        permissions=("artists:view", "artists:manage"),
    )

    current_response = client.get("/api/v1/organizations/current")
    artist_response = client.get(f"/api/v1/artists/{seeded.artist_b_id}")

    assert current_response.status_code == 403
    assert current_response.json() == {"detail": "Organization context required"}
    assert artist_response.status_code == 403
    assert artist_response.json() == {"detail": "Organization context required"}


def test_roles_are_enforced(
    organization_security_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        OrganizationSecuritySeed,
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organization_security_client
    _authenticate_member_a(client)

    organization_update = client.patch(
        f"/api/v1/organizations/{seeded.org_a_id}",
        json={"name": "Member Rename"},
    )
    members_list = client.get(f"/api/v1/organizations/{seeded.org_a_id}/members")
    artist_create = client.post("/api/v1/artists", json={"name": "Unauthorized"})

    assert organization_update.status_code == 403
    assert organization_update.json() == {"detail": "Insufficient organization role"}
    assert members_list.status_code == 403
    assert members_list.json() == {"detail": "Insufficient organization role"}
    assert artist_create.status_code == 403
    assert artist_create.json() == {"detail": "Insufficient permission"}


def test_last_owner_protections_work(
    organization_security_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        OrganizationSecuritySeed,
        FakeWorkOSClient,
    ],
) -> None:
    client, sessionmaker, seeded, _workos = organization_security_client
    asyncio.run(_make_member_a_only_active_owner(sessionmaker, seeded))
    _authenticate_stale_owner_a_context(client, seeded)

    response = client.delete(
        f"/api/v1/organizations/{seeded.org_a_id}/members/{seeded.member_a_membership_id}"
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Cannot remove the final owner"}
    assert asyncio.run(_membership_exists(sessionmaker, seeded.member_a_membership_id))


def test_realtime_events_are_organization_scoped(
    organization_security_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        OrganizationSecuritySeed,
        FakeWorkOSClient,
    ],
) -> None:
    _client, sessionmaker, seeded, _workos = organization_security_client

    async def publish_and_read() -> list[tuple[str, UUID]]:
        async with sessionmaker() as session:
            owner_a = await session.get(User, seeded.owner_a_id)
            owner_b = await session.get(User, seeded.owner_b_id)
            assert owner_a is not None
            assert owner_b is not None
            await RealtimePublisher(session).publish(
                organization_id=seeded.org_a_id,
                event_type=RealtimeEventType.artist_updated,
                actor=owner_a,
                entity_type="artist",
                entity_id=seeded.artist_a_id,
            )
            event_b = await RealtimePublisher(session).publish(
                organization_id=seeded.org_b_id,
                event_type=RealtimeEventType.artist_updated,
                actor=owner_b,
                entity_type="artist",
                entity_id=seeded.artist_b_id,
            )
            await RealtimePublisher(session).publish(
                organization_id=seeded.org_a_id,
                event_type=RealtimeEventType.release_updated,
                actor=owner_a,
                entity_type="release",
                entity_id=seeded.release_a_id,
            )
            await session.commit()
            events = await list_events_after(
                session,
                organization_id=seeded.org_a_id,
                after_event_id=event_b.id,
            )
            return [(event.type.value, event.organization_id) for event in events]

    assert asyncio.run(publish_and_read()) == [
        (RealtimeEventType.artist_updated.value, seeded.org_a_id),
        (RealtimeEventType.release_updated.value, seeded.org_a_id),
    ]


def test_unauthorized_users_cannot_establish_organization_realtime_subscriptions(
    organization_security_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        OrganizationSecuritySeed,
        FakeWorkOSClient,
    ],
) -> None:
    client, _sessionmaker, seeded, _workos = organization_security_client
    _authenticate_owner_a(client)

    response = client.get(f"/api/v1/realtime/organizations/{seeded.org_b_id}/events")

    assert response.status_code == 403
    assert response.json() == {"detail": "Organization membership required"}
