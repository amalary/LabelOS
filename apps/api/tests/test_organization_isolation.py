import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from labelos_database.base import Base
from labelos_database.models import Artist, MembershipRole, Organization, User
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
    org_a_id: UUID
    org_b_id: UUID
    artist_a_id: UUID
    artist_b_id: UUID


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
            artist_a = Artist(name="Artist A", organization=org_a)
            artist_b = Artist(name="Artist B", organization=org_b)
            session.add_all([owner, org_a, org_b, artist_a, artist_b])
            await session.commit()
            return SeededTenants(
                org_a_id=org_a.id,
                org_b_id=org_b.id,
                artist_a_id=artist_a.id,
                artist_b_id=artist_b.id,
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
) -> None:
    async def override_context() -> CurrentUserContext:
        return CurrentUserContext(
            user=User(email="person@example.com"),
            principal=AuthenticatedPrincipal(
                provider="workos",
                subject="user_01TEST",
                session_id="session_01TEST",
                organization_id=workos_organization_id,
                role="admin",
                roles=("admin",),
                permissions=permissions,
            ),
            memberships=(
                MembershipContext(
                    organization_id=local_organization_id,
                    organization_name="Active Label",
                    organization_slug="active-label",
                    workos_organization_id=workos_organization_id,
                    role=MembershipRole.admin,
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
        json={"name": "Spoofed Tenant Artist", "organization_id": str(seeded.org_b_id)},
    )

    assert response.status_code == 201
    created_id = UUID(response.json()["id"])
    assert (
        asyncio.run(_artist_organization_id(sessionmaker, created_id))
        == seeded.org_a_id
    )
    assert created_id in asyncio.run(
        _artist_ids_for_organization(sessionmaker, seeded.org_a_id)
    )
    assert created_id not in asyncio.run(
        _artist_ids_for_organization(sessionmaker, seeded.org_b_id)
    )


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


def test_cross_organization_update_returns_404_and_does_not_mutate(
    isolated_client: tuple[TestClient, async_sessionmaker[AsyncSession], SeededTenants],
) -> None:
    client, sessionmaker, seeded = isolated_client
    _set_active_organization(
        client,
        local_organization_id=seeded.org_a_id,
        workos_organization_id="org_A",
    )

    response = client.put(
        f"/api/v1/artists/{seeded.artist_b_id}",
        json={"name": "Leaked Update"},
    )

    assert response.status_code == 404
    assert asyncio.run(_artist_name(sessionmaker, seeded.artist_b_id)) == "Artist B"


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
