import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from uuid import UUID

import anyio
import pytest
from fastapi.testclient import TestClient
from labelos_database.base import Base
from labelos_database.models import (
    Artist,
    MembershipRole,
    Organization,
    OrganizationMembership,
    RealtimeEvent,
    UniversalProfile,
    User,
    WorkspaceMembership,
)
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool
from starlette.requests import ClientDisconnect

from labelos_api.api.v1 import realtime
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
    profile_id: UUID


@pytest.fixture(
    params=["sqlite"] + (["postgresql"] if os.environ.get("TEST_POSTGRES_URL") else [])
)
def realtime_engine(request, tmp_path):
    if request.param == "postgresql":
        yield request.getfixturevalue("postgres_test_engine")
        return
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'realtime.db'}",
        connect_args={"check_same_thread": False},
        poolclass=AsyncAdaptedQueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.1,
    )
    try:
        yield engine
    finally:
        asyncio.run(engine.dispose())


@pytest.fixture
def realtime_client(
    monkeypatch: pytest.MonkeyPatch, realtime_engine
) -> Iterator[tuple[TestClient, async_sessionmaker[AsyncSession], RealtimeSeed]]:
    monkeypatch.setenv("APP_ENV", "test")
    engine = realtime_engine
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
            profile = UniversalProfile(
                user=user,
                display_name="Owner Profile",
                primary_email="owner@example.com",
            )
            membership = OrganizationMembership(
                organization=organization,
                user=user,
                role=MembershipRole.owner,
                status="active",
            )
            session.add_all(
                [
                    user,
                    other_user,
                    organization,
                    outside_organization,
                    artist,
                    profile,
                    membership,
                    WorkspaceMembership(
                        workspace=organization,
                        profile=profile,
                        organization_membership=membership,
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
                profile_id=profile.id,
            )

    seeded = asyncio.run(prepare_database())
    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session

    with TestClient(app) as client:
        yield client, sessionmaker, seeded


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


def test_artist_profile_module_mutations_publish_profile_activity(
    realtime_client: tuple[TestClient, async_sessionmaker[AsyncSession], RealtimeSeed],
) -> None:
    client, sessionmaker, seeded = realtime_client
    _set_context(client, seeded)

    create_response = client.post(
        "/api/v1/artists",
        json={
            "name": "Profile Artist",
            "universal_profile_id": str(seeded.profile_id),
            "stage_name": "Profile Artist",
            "genres": ["pop"],
            "dsp_links": {"spotify": "https://open.spotify.com/artist/example"},
        },
    )
    artist_id = create_response.json()["id"]
    update_response = client.patch(
        f"/api/v1/artists/{artist_id}",
        json={
            "name": "Profile Artist",
            "universal_profile_id": str(seeded.profile_id),
            "stage_name": "Profile Artist Updated",
            "career_stage": "emerging",
        },
    )

    assert create_response.status_code == 201
    assert update_response.status_code == 200
    events = asyncio.run(_realtime_events(sessionmaker, seeded.organization_id))
    profile_events = [
        event
        for event in events
        if event.event_type.startswith("profile.artist_profile_")
    ]
    assert [event.event_type for event in profile_events] == [
        "profile.artist_profile_created",
        "profile.artist_profile_updated",
    ]
    assert profile_events[0].entity_type == "profile"
    assert profile_events[0].entity_id == str(seeded.profile_id)
    assert profile_events[0].payload["profileId"] == str(seeded.profile_id)
    assert profile_events[0].payload["workspaceId"] == str(seeded.organization_id)
    assert profile_events[1].payload["changedFields"] == [
        "career_stage",
        "stage_name",
        "universal_profile_id",
    ]
    assert "https://open.spotify.com/artist/example" not in str(
        profile_events[0].payload
    )


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


@pytest.mark.parametrize("revoke_membership", [False, True])
def test_stream_releases_connection_before_yielding_and_sleeping(
    realtime_client,
    monkeypatch: pytest.MonkeyPatch,
    revoke_membership: bool,
) -> None:
    client, sessions, seeded = realtime_client
    _set_context(client, seeded)
    if revoke_membership:
        monkeypatch.setattr(realtime, "MEMBERSHIP_RECHECK_SECONDS", 0)

    async def verify():
        context = await client.app.dependency_overrides[get_current_user_context]()
        async with sessions() as session:
            # Match production, where auth loads the actor in the request session.
            context = CurrentUserContext(
                user=await session.get(User, seeded.user_id),
                principal=context.principal,
                memberships=context.memberships,
            )
            response = await realtime.organization_events(
                seeded.organization_id, session, context
            )
            stream = response.body_iterator
            assert "event: connected" in await anext(stream)

            async def assert_connection_available():
                assert not session.in_transaction()
                # The one-slot pool must be usable by an ordinary request.
                async with sessions() as other:
                    assert await other.scalar(text("SELECT 1")) == 1

            await assert_connection_available()
            async with sessions() as other:
                if revoke_membership:
                    await other.execute(
                        update(OrganizationMembership)
                        .where(OrganizationMembership.user_id == seeded.user_id)
                        .values(status="inactive")
                    )
                await RealtimePublisher(other).publish(
                    organization_id=seeded.organization_id,
                    event_type=RealtimeEventType.artist_updated,
                    actor=None,
                )
                await other.commit()

            event = await anext(stream)
            await assert_connection_available()
            if revoke_membership:
                assert "event: membership_revoked" in event
                with pytest.raises(StopAsyncIteration):
                    await anext(stream)
            else:
                assert "artist.updated" in event

                async def stop_at_idle(_seconds):
                    await assert_connection_available()
                    raise asyncio.CancelledError

                monkeypatch.setattr(realtime.asyncio, "sleep", stop_at_idle)
                with pytest.raises(asyncio.CancelledError):
                    await anext(stream)
            await assert_connection_available()

    asyncio.run(verify())
    events = asyncio.run(_realtime_events(sessions, seeded.organization_id))
    assert events[-1].event_type == RealtimeEventType.presence_left.value


@pytest.mark.parametrize(
    "disconnect", ["send_error", "cancel_scope", "receive_disconnect", "poll_cancel"]
)
def test_disconnect_finishes_stream_before_request_session_closes(
    realtime_client, disconnect, monkeypatch, caplog
):
    client, sessions, seeded = realtime_client
    _set_context(client, seeded)

    async def verify():
        context = await client.app.dependency_overrides[get_current_user_context]()
        async with sessions() as session:
            context = CurrentUserContext(
                user=await session.get(User, seeded.user_id),
                principal=context.principal,
                memberships=context.memberships,
            )
            response = await realtime.organization_events(
                seeded.organization_id, session, context
            )

            sent = anyio.Event()

            async def receive():
                await sent.wait()
                return {"type": "http.disconnect"}

            with anyio.CancelScope() as cancellation:

                async def send(message):
                    if message["type"] == "http.response.body":
                        if disconnect == "send_error":
                            raise OSError("client disconnected")
                        if disconnect == "cancel_scope":
                            cancellation.cancel()
                            await anyio.sleep(0)
                        sent.set()

                if disconnect == "poll_cancel":
                    original_poll = realtime.list_events_after

                    async def cancel_poll(*args, **kwargs):
                        cancellation.cancel()
                        return await original_poll(*args, **kwargs)

                    monkeypatch.setattr(realtime, "list_events_after", cancel_poll)

                try:
                    await response(
                        {
                            "type": "http",
                            "asgi": {
                                "spec_version": (
                                    "2.3"
                                    if disconnect == "receive_disconnect"
                                    else "2.4"
                                )
                            },
                        },
                        receive,
                        send,
                    )
                except ClientDisconnect:
                    assert disconnect == "send_error"
            # Presence cleanup must finish before FastAPI closes its dependency.
            # Otherwise a later generator finalizer can reopen a closed session.
            events = await _realtime_events(sessions, seeded.organization_id)
            assert events[-1].event_type == RealtimeEventType.presence_left.value, [
                getattr(record, "error_type", None) for record in caplog.records
            ]
            assert not session.in_transaction()
            with pytest.raises(StopAsyncIteration):
                await anext(response.body_iterator)

    anyio.run(verify)
