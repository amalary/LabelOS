import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from labelos_database.base import Base
from labelos_database.models import (
    Artist,
    ArtistProfile,
    MembershipRole,
    Organization,
    OrganizationMembership,
    Release,
    UniversalProfile,
    User,
    WorkspaceMembership,
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
class SeededTenants:
    user_id: UUID
    org_a_id: UUID
    org_b_id: UUID
    artist_a_id: UUID
    artist_b_id: UUID
    release_a_id: UUID
    release_b_id: UUID
    profile_id: UUID
    outside_profile_id: UUID


@pytest.fixture
def isolated_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants]]:
    monkeypatch.setenv("APP_ENV", "test")
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def prepare_database() -> SeededTenants:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with sessionmaker() as session:
            owner = User(email="owner@example.com", display_name="Owner")
            owner_profile = UniversalProfile(
                user=owner,
                display_name="Owner Profile",
                slug="owner-profile",
            )
            outside_profile = UniversalProfile(
                user=User(email="outside@example.com", display_name="Outside User"),
                display_name="Outside Profile",
                slug="outside-profile",
            )
            org_a = Organization(
                name="Label A",
                slug="label-a",
                workos_organization_id="org_A",
                owner=owner,
            )
            org_b = Organization(
                name="Label B",
                slug="label-b",
                workos_organization_id="org_B",
                owner=owner,
            )
            org_a_membership = OrganizationMembership(
                organization=org_a,
                user=owner,
                role=MembershipRole.admin,
            )
            org_a_workspace_membership = WorkspaceMembership(
                workspace=org_a,
                profile=owner_profile,
                organization_membership=org_a_membership,
                status="active",
            )
            org_b_membership = OrganizationMembership(
                organization=org_b,
                user=outside_profile.user,
                role=MembershipRole.member,
            )
            org_b_workspace_membership = WorkspaceMembership(
                workspace=org_b,
                profile=outside_profile,
                organization_membership=org_b_membership,
                status="active",
            )
            artist_a = Artist(name="Artist A", organization=org_a)
            artist_b = Artist(name="Artist B", organization=org_b)
            release_a = Release(
                title="Release A",
                artist=artist_a,
                organization=org_a,
            )
            release_b = Release(
                title="Release B",
                artist=artist_b,
                organization=org_b,
            )
            session.add_all(
                [
                    owner,
                    owner_profile,
                    outside_profile,
                    org_a,
                    org_b,
                    org_a_membership,
                    org_a_workspace_membership,
                    org_b_membership,
                    org_b_workspace_membership,
                    artist_a,
                    artist_b,
                    release_a,
                    release_b,
                ]
            )
            await session.commit()
            return SeededTenants(
                user_id=owner.id,
                org_a_id=org_a.id,
                org_b_id=org_b.id,
                artist_a_id=artist_a.id,
                artist_b_id=artist_b.id,
                release_a_id=release_a.id,
                release_b_id=release_b.id,
                profile_id=owner_profile.id,
                outside_profile_id=outside_profile.id,
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


def _set_active_organization(
    client: TestClient,
    *,
    local_organization_id: UUID,
    workos_organization_id: str,
    permissions: tuple[str, ...] = ("artists:view", "artists:manage"),
    user_id: UUID | None = None,
    role: MembershipRole = MembershipRole.admin,
) -> None:
    async def override_context() -> CurrentUserContext:
        return CurrentUserContext(
            user=User(id=user_id, email="person@example.com"),
            principal=AuthenticatedPrincipal(
                provider="workos",
                subject="user_01TEST",
                session_id="session_01TEST",
                organization_id=workos_organization_id,
                role=role.value,
                roles=(role.value,),
                permissions=permissions,
            ),
            memberships=(
                MembershipContext(
                    organization_id=local_organization_id,
                    organization_name="Active Label",
                    organization_slug="active-label",
                    workos_organization_id=workos_organization_id,
                    role=role,
                ),
            ),
        )

    client.app.dependency_overrides[get_current_user_context] = override_context


async def _artist_name(
    sessionmaker: async_sessionmaker[AsyncSession],
    artist_id: UUID,
) -> str | None:
    async with sessionmaker() as session:
        artist = await session.get(Artist, artist_id)
        return artist.name if artist is not None else None


async def _artist_organization_id(
    sessionmaker: async_sessionmaker[AsyncSession],
    artist_id: UUID,
) -> UUID | None:
    async with sessionmaker() as session:
        artist = await session.get(Artist, artist_id)
        return artist.organization_id if artist is not None else None


async def _artist_profile(
    sessionmaker: async_sessionmaker[AsyncSession],
    artist_id: UUID,
) -> ArtistProfile | None:
    async with sessionmaker() as session:
        return await session.scalar(
            select(ArtistProfile).where(ArtistProfile.artist_id == artist_id)
        )


async def _artist_profile_by_id(
    sessionmaker: async_sessionmaker[AsyncSession],
    artist_profile_id: UUID,
) -> ArtistProfile | None:
    async with sessionmaker() as session:
        return await session.get(ArtistProfile, artist_profile_id)


async def _artist_ids_for_organization(
    sessionmaker: async_sessionmaker[AsyncSession],
    organization_id: UUID,
) -> set[UUID]:
    async with sessionmaker() as session:
        rows = await session.scalars(
            select(Artist.id).where(Artist.organization_id == organization_id)
        )
        return set(rows.all())


def test_artist_list_is_scoped_to_active_organization(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, _sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
    )

    response = client.get("/api/v1/artists")

    assert response.status_code == 200
    artist_ids = {artist["id"] for artist in response.json()["artists"]}
    assert str(seeded.artist_a_id) in artist_ids
    assert str(seeded.artist_b_id) not in artist_ids


def test_artist_search_is_scoped_to_active_organization(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, _sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
    )

    response = client.get("/api/v1/artists", params={"search": "Artist"})

    assert response.status_code == 200
    artist_ids = {artist["id"] for artist in response.json()["artists"]}
    assert artist_ids == {str(seeded.artist_a_id)}


def test_existing_artist_without_profile_still_reads(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, _sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
        user_id=seeded.user_id,
        role=MembershipRole.owner,
    )

    response = client.get(f"/api/v1/artists/{seeded.artist_a_id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(seeded.artist_a_id)
    assert response.json()["name"] == "Artist A"
    assert response.json()["profile"] is None


def test_artist_create_ignores_client_supplied_organization_id(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
    )

    response = client.post(
        "/api/v1/artists",
        json={
            "name": "Spoofed Tenant Artist",
            "organization_id": str(seeded.org_b_id),
        },
    )

    assert response.status_code == 201
    created_id = UUID(response.json()["id"])
    assert response.json()["profile"] is None
    assert (
        asyncio.run(_artist_organization_id(sessionmaker, created_id))
        == seeded.org_a_id
    )
    persisted_profile = asyncio.run(_artist_profile(sessionmaker, created_id))
    assert persisted_profile is None
    assert created_id in asyncio.run(
        _artist_ids_for_organization(sessionmaker, seeded.org_a_id)
    )
    assert created_id not in asyncio.run(
        _artist_ids_for_organization(sessionmaker, seeded.org_b_id)
    )


def test_artist_create_can_attach_artist_profile_module(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
        user_id=seeded.user_id,
        role=MembershipRole.owner,
    )

    response = client.post(
        "/api/v1/artists",
        json={
            "name": "Profiled Artist",
            "universal_profile_id": str(seeded.profile_id),
            "genres": ["pop"],
            "dsp_links": {"spotify": "https://open.spotify.com/artist/test"},
            "career_stage": "emerging",
        },
    )

    assert response.status_code == 201
    created_id = UUID(response.json()["id"])
    assert response.json()["profile"]["universal_profile_id"] == str(seeded.profile_id)
    assert response.json()["profile"]["stage_name"] == "Profiled Artist"
    assert response.json()["profile"]["genres"] == ["pop"]
    assert response.json()["profile"]["dsp_links"] == {
        "spotify": "https://open.spotify.com/artist/test"
    }
    persisted_profile = asyncio.run(_artist_profile(sessionmaker, created_id))
    assert persisted_profile is not None
    assert persisted_profile.universal_profile_id == seeded.profile_id
    assert persisted_profile.career_stage == "emerging"


def test_workspace_artist_profile_create_links_catalog_artist(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
        user_id=seeded.user_id,
        role=MembershipRole.owner,
    )

    response = client.post(
        f"/api/v1/workspaces/{seeded.org_a_id}/artist-profiles",
        json={
            "artist_id": str(seeded.artist_a_id),
            "universal_profile_id": str(seeded.profile_id),
            "genres": ["pop"],
            "career_stage": "developing",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["artist_id"] == str(seeded.artist_a_id)
    assert body["workspace_id"] == str(seeded.org_a_id)
    assert body["artist_name"] == "Artist A"
    assert body["universal_profile_id"] == str(seeded.profile_id)
    assert body["stage_name"] == "Artist A"
    assert body["genres"] == ["pop"]

    persisted_profile = asyncio.run(_artist_profile(sessionmaker, seeded.artist_a_id))
    assert persisted_profile is not None
    assert persisted_profile.universal_profile_id == seeded.profile_id
    assert persisted_profile.career_stage == "developing"


def test_workspace_artist_profile_create_rejects_duplicate_artist_module(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, _sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
        user_id=seeded.user_id,
        role=MembershipRole.owner,
    )
    payload = {
        "artist_id": str(seeded.artist_a_id),
        "universal_profile_id": str(seeded.profile_id),
    }

    first_response = client.post(
        f"/api/v1/workspaces/{seeded.org_a_id}/artist-profiles",
        json=payload,
    )
    duplicate_response = client.post(
        f"/api/v1/workspaces/{seeded.org_a_id}/artist-profiles",
        json=payload,
    )

    assert first_response.status_code == 201
    assert duplicate_response.status_code == 409


def test_workspace_artist_profile_create_rejects_cross_workspace_inputs(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, _sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
        user_id=seeded.user_id,
        role=MembershipRole.owner,
    )

    outside_artist_response = client.post(
        f"/api/v1/workspaces/{seeded.org_a_id}/artist-profiles",
        json={
            "artist_id": str(seeded.artist_b_id),
            "universal_profile_id": str(seeded.profile_id),
        },
    )
    outside_profile_response = client.post(
        f"/api/v1/workspaces/{seeded.org_a_id}/artist-profiles",
        json={
            "artist_id": str(seeded.artist_a_id),
            "universal_profile_id": str(seeded.outside_profile_id),
        },
    )

    assert outside_artist_response.status_code == 404
    assert outside_profile_response.status_code == 404


def test_workspace_artist_profile_detail_reads_profile_module(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, _sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
        user_id=seeded.user_id,
        role=MembershipRole.owner,
    )
    create_response = client.post(
        "/api/v1/artists",
        json={
            "name": "Detailed Artist",
            "universal_profile_id": str(seeded.profile_id),
            "genres": ["pop"],
        },
    )
    artist_profile_id = create_response.json()["profile"]["id"]

    response = client.get(
        f"/api/v1/workspaces/{seeded.org_a_id}/artist-profiles/{artist_profile_id}"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == artist_profile_id
    assert body["workspace_id"] == str(seeded.org_a_id)
    assert body["artist_name"] == "Detailed Artist"
    assert body["universal_profile_id"] == str(seeded.profile_id)


def test_workspace_artist_profile_update_changes_module_fields(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
        user_id=seeded.user_id,
        role=MembershipRole.owner,
    )
    create_response = client.post(
        "/api/v1/artists",
        json={
            "name": "Editable Artist",
            "universal_profile_id": str(seeded.profile_id),
            "genres": ["pop"],
        },
    )
    artist_profile_id = UUID(create_response.json()["profile"]["id"])

    response = client.patch(
        f"/api/v1/workspaces/{seeded.org_a_id}/artist-profiles/{artist_profile_id}",
        json={
            "stage_name": "Edited Stage",
            "genres": ["pop", "dance"],
            "career_stage": "developing",
        },
    )

    assert response.status_code == 200
    assert response.json()["stage_name"] == "Edited Stage"
    assert response.json()["genres"] == ["pop", "dance"]
    persisted = asyncio.run(_artist_profile_by_id(sessionmaker, artist_profile_id))
    assert persisted is not None
    assert persisted.stage_name == "Edited Stage"
    assert persisted.career_stage == "developing"


def test_workspace_artist_profile_update_requires_artist_edit_capability(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, _sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
        user_id=seeded.user_id,
        role=MembershipRole.owner,
    )
    create_response = client.post(
        "/api/v1/artists",
        json={
            "name": "Capability Artist",
            "universal_profile_id": str(seeded.profile_id),
            "genres": ["pop"],
        },
    )
    artist_profile_id = create_response.json()["profile"]["id"]
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
        permissions=("artists:view", "artists:manage"),
        user_id=seeded.user_id,
    )
    client.app.dependency_overrides[get_current_user_context] = (
        lambda: CurrentUserContext(
            user=User(id=seeded.user_id, email="person@example.com"),
            principal=AuthenticatedPrincipal(
                provider="workos",
                subject="user_01TEST",
                session_id="session_01TEST",
                organization_id="org_A",
                role="member",
                roles=("member",),
                permissions=("artists:view", "artists:manage"),
            ),
            memberships=(
                MembershipContext(
                    organization_id=seeded.org_a_id,
                    organization_name="Active Label",
                    organization_slug="active-label",
                    workos_organization_id="org_A",
                    role=MembershipRole.member,
                ),
            ),
        )
    )

    response = client.patch(
        f"/api/v1/workspaces/{seeded.org_a_id}/artist-profiles/{artist_profile_id}",
        json={"stage_name": "Blocked Edit"},
    )

    assert response.status_code == 403


def test_workspace_artist_profile_update_rejects_profile_outside_workspace(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, _sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
        user_id=seeded.user_id,
        role=MembershipRole.owner,
    )
    create_response = client.post(
        "/api/v1/artists",
        json={
            "name": "Reassignment Artist",
            "universal_profile_id": str(seeded.profile_id),
            "genres": ["pop"],
        },
    )
    artist_profile_id = create_response.json()["profile"]["id"]

    response = client.patch(
        f"/api/v1/workspaces/{seeded.org_a_id}/artist-profiles/{artist_profile_id}",
        json={"universal_profile_id": str(seeded.outside_profile_id)},
    )

    assert response.status_code == 404


def test_artist_create_rejects_module_fields_without_universal_profile(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, _sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
    )

    response = client.post(
        "/api/v1/artists",
        json={"name": "Unanchored Artist", "genres": ["pop"]},
    )

    assert response.status_code == 422


def test_artist_create_rejects_profile_outside_active_workspace(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, _sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
    )

    response = client.post(
        "/api/v1/artists",
        json={
            "name": "Cross Workspace Artist Profile",
            "universal_profile_id": str(seeded.outside_profile_id),
            "genres": ["pop"],
        },
    )

    assert response.status_code == 404


def test_cross_organization_read_returns_404(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, _sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
    )

    response = client.get(f"/api/v1/artists/{seeded.artist_b_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_existing_artist_without_profile_can_update_and_get_profile(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
    )

    response = client.patch(
        f"/api/v1/artists/{seeded.artist_a_id}",
        json={"name": "Artist A Updated"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Artist A Updated"
    assert response.json()["profile"] is None
    persisted_profile = asyncio.run(_artist_profile(sessionmaker, seeded.artist_a_id))
    assert persisted_profile is None


def test_artist_update_rejects_profile_outside_active_workspace(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
    )

    response = client.patch(
        f"/api/v1/artists/{seeded.artist_a_id}",
        json={
            "name": "Artist A",
            "universal_profile_id": str(seeded.outside_profile_id),
            "genres": ["pop"],
        },
    )

    assert response.status_code == 404
    persisted_profile = asyncio.run(_artist_profile(sessionmaker, seeded.artist_a_id))
    assert persisted_profile is None


@pytest.mark.parametrize("method", ["put", "patch"])
def test_cross_organization_update_returns_404_and_does_not_mutate(
    method: str,
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
    )

    response = getattr(client, method)(
        f"/api/v1/artists/{seeded.artist_b_id}",
        json={"name": "Leaked Update"},
    )

    assert response.status_code == 404
    assert asyncio.run(_artist_name(sessionmaker, seeded.artist_b_id)) == "Artist B"


def test_nested_artist_releases_are_scoped_to_active_organization(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, _sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
        permissions=("artists:view", "artists:manage", "releases:view"),
    )

    response = client.get(f"/api/v1/artists/{seeded.artist_a_id}/releases")

    assert response.status_code == 200
    release_ids = {release["id"] for release in response.json()["releases"]}
    assert release_ids == {str(seeded.release_a_id)}
    assert str(seeded.release_b_id) not in release_ids


def test_cross_organization_nested_artist_releases_return_404(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, _sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
        permissions=("artists:view", "artists:manage", "releases:view"),
    )

    response = client.get(f"/api/v1/artists/{seeded.artist_b_id}/releases")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_cross_organization_delete_returns_404_and_does_not_delete(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
    )

    response = client.delete(f"/api/v1/artists/{seeded.artist_b_id}")

    assert response.status_code == 404
    assert asyncio.run(_artist_name(sessionmaker, seeded.artist_b_id)) == "Artist B"
