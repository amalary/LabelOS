import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from labelos_database.base import Base
from labelos_database.models import (
    ActivityEvent,
    Artist,
    MembershipRole,
    Organization,
    OrganizationMembership,
    RealtimeEvent,
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
from labelos_api.realtime import RealtimeEventType, RealtimePublisher, realtime_channel
from labelos_api.realtime.events import list_events_after


@dataclass(frozen=True)
class RealtimeSeed:
    user_id: UUID
    other_user_id: UUID
    organization_id: UUID
    outside_organization_id: UUID
    artist_id: UUID


@pytest.fixture
def realtime_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, async_sessionmaker[AsyncSession], RealtimeSeed]]:
    monkeypatch.setenv("APP_ENV", "test")
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def prepare_database() -> RealtimeSeed:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with sessionmaker() as session:
            user = User(email="owner@example.com", display_name="Owner")
            other_user = User(email="outside@example.com", display_name="Outside")
            organization = Organization(
                name="Alpha Label",
                slug="alpha-label",
                workos_organization_id="org_ALPHA",
                owner=user,
            )
            outside_organization = Organization(
                name="Outside Label",
                slug="outside-label",
                workos_organization_id="org_OUTSIDE",
                owner=other_user,
            )
            artist = Artist(name="Artist A", organization=organization)
            session.add_all(
                [
                    user,
                    other_user,
                    organization,
                    outside_organization,
                    artist,
                    OrganizationMembership(
                        organization=organization,
                        user=user,
                        role=MembershipRole.owner,
                        status="active",
                    ),
                    OrganizationMembership(
                        organization=outside_organization,
                        user=other_user,
                        role=MembershipRole.owner,
                        status="active",
                    ),
                ]
            )
            await session.commit()
            return RealtimeSeed(
                user_id=user.id,
                other_user_id=other_user.id,
                organization_id=organization.id,
                outside_organization_id=outside_organization.id,
                artist_id=artist.id,
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
    seeded: RealtimeSeed,
    *,
    memberships: tuple[MembershipContext, ...] | None = None,
    permissions: tuple[str, ...] = ("artists:view", "artists:manage"),
) -> None:
    async def override_context() -> CurrentUserContext:
        return CurrentUserContext(
            user=User(
                id=seeded.user_id,
                email="owner@example.com",
                display_name="Owner",
            ),
            principal=AuthenticatedPrincipal(
                provider="workos",
                subject="user_01TEST",
                session_id="session_SECRET",
                organization_id="org_ALPHA",
                role="owner",
                roles=("owner",),
                permissions=permissions,
            ),
            memberships=(
                memberships
                if memberships is not None
                else (
                    MembershipContext(
                        organization_id=seeded.organization_id,
                        organization_name="Alpha Label",
                        organization_slug="alpha-label",
                        workos_organization_id="org_ALPHA",
                        role=MembershipRole.owner,
                    ),
                )
            ),
        )

    client.app.dependency_overrides[get_current_user_context] = override_context


async def _realtime_events(
    sessionmaker: async_sessionmaker[AsyncSession],
    organization_id: UUID,
) -> list[RealtimeEvent]:
    async with sessionmaker() as session:
        rows = await session.scalars(
            select(RealtimeEvent)
            .where(RealtimeEvent.organization_id == organization_id)
            .order_by(RealtimeEvent.created_at.asc())
        )
        return list(rows.all())


async def _activity_events(
    sessionmaker: async_sessionmaker[AsyncSession],
    organization_id: UUID,
) -> list[ActivityEvent]:
    async with sessionmaker() as session:
        rows = await session.scalars(
            select(ActivityEvent)
            .where(ActivityEvent.organization_id == organization_id)
            .order_by(ActivityEvent.created_at.asc())
        )
        return list(rows.all())


def test_artist_mutation_publishes_committed_organization_event(
    realtime_client: tuple[TestClient, async_sessionmaker[AsyncSession], RealtimeSeed],
) -> None:
    client, sessionmaker, seeded = realtime_client
    _set_context(client, seeded)

    response = client.patch(
        f"/api/v1/artists/{seeded.artist_id}",
        json={"name": "Renamed Artist"},
    )

    assert response.status_code == 200
    events = asyncio.run(_realtime_events(sessionmaker, seeded.organization_id))
    assert len(events) == 1
    event = events[0]
    assert event.event_type == RealtimeEventType.artist_updated.value
    assert event.channel == realtime_channel(seeded.organization_id)
    assert event.entity_type == "artist"
    assert event.entity_id == str(seeded.artist_id)
    assert event.actor_user_id == seeded.user_id
    assert event.actor_display_name == "Owner"
    assert event.payload["artist"]["name"] == "Renamed Artist"
    activity_events = asyncio.run(
        _activity_events(sessionmaker, seeded.organization_id)
    )
    assert len(activity_events) == 1
    assert activity_events[0].event_type == "artist.updated"
    assert activity_events[0].operation == "update_artist"
    assert activity_events[0].actor_user_id == seeded.user_id
    assert activity_events[0].changes == {
        "name": {"from": "Artist A", "to": "Renamed Artist"}
    }


def test_realtime_subscription_requires_database_membership(
    realtime_client: tuple[TestClient, async_sessionmaker[AsyncSession], RealtimeSeed],
) -> None:
    client, _sessionmaker, seeded = realtime_client
    _set_context(
        client,
        seeded,
        memberships=(
            MembershipContext(
                organization_id=seeded.outside_organization_id,
                organization_name="Outside Label",
                organization_slug="outside-label",
                workos_organization_id="org_OUTSIDE",
                role=MembershipRole.owner,
            ),
        ),
    )

    response = client.get(
        f"/api/v1/realtime/organizations/{seeded.outside_organization_id}/events"
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Organization membership required"}


def test_realtime_event_cursor_is_organization_scoped(
    realtime_client: tuple[TestClient, async_sessionmaker[AsyncSession], RealtimeSeed],
) -> None:
    _client, sessionmaker, seeded = realtime_client

    async def publish_and_read() -> list[str]:
        async with sessionmaker() as session:
            user = await session.get(User, seeded.user_id)
            outside_user = await session.get(User, seeded.other_user_id)
            first = await RealtimePublisher(session).publish(
                organization_id=seeded.organization_id,
                event_type=RealtimeEventType.artist_updated,
                actor=user,
                entity_type="artist",
                entity_id=seeded.artist_id,
            )
            await RealtimePublisher(session).publish(
                organization_id=seeded.outside_organization_id,
                event_type=RealtimeEventType.organization_updated,
                actor=outside_user,
                entity_type="organization",
                entity_id=seeded.outside_organization_id,
            )
            await RealtimePublisher(session).publish(
                organization_id=seeded.organization_id,
                event_type=RealtimeEventType.release_updated,
                actor=user,
                entity_type="release",
                entity_id=seeded.artist_id,
            )
            await session.commit()
            events = await list_events_after(
                session,
                organization_id=seeded.organization_id,
                after_event_id=first.id,
            )
            return [event.type.value for event in events]

    assert asyncio.run(publish_and_read()) == [RealtimeEventType.release_updated.value]
