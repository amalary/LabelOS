import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from labelos_database.base import Base
from labelos_database.capabilities import Capability
from labelos_database.models import (
    Artist,
    ArtistProfile,
    MembershipRole,
    OAuthAuthorizationState,
    OAuthAuthorizationStateStatus,
    Organization,
    OrganizationMembership,
    RealtimeEvent,
    SocialAccountConnection,
    SocialAccountConnectionMethod,
    SocialAccountConnectionStatus,
    UniversalProfile,
    User,
    WorkspaceMembership,
    WorkspacePermission,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from labelos_api.api.v1.social_account_connections import (
    get_credential_store_dependency,
    get_social_account_provider_registry,
)
from labelos_api.auth import (
    AuthenticatedPrincipal,
    CurrentUserContext,
    MembershipContext,
    get_current_user_context,
    get_session,
)
from labelos_api.main import create_app
from labelos_api.services.credential_store import InMemoryCredentialStore
from labelos_api.social_accounts.providers import (
    FakeOAuthSocialAccountConnectionProvider,
    SocialAccountProviderRegistry,
)


@dataclass(frozen=True)
class SeededSocialAccountConnectionsApi:
    owner_user_id: UUID
    viewer_user_id: UUID
    blocked_user_id: UUID
    outside_user_id: UUID
    workspace_id: UUID
    outside_workspace_id: UUID
    owner_profile_id: UUID
    artist_profile_id: UUID
    outside_artist_profile_id: UUID


@pytest.fixture
def social_account_connections_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[
    tuple[
        TestClient, async_sessionmaker[AsyncSession], SeededSocialAccountConnectionsApi
    ]
]:
    monkeypatch.setenv("APP_ENV", "test")
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def prepare_database() -> SeededSocialAccountConnectionsApi:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with sessionmaker() as session:
            owner = User(email="social-owner@example.com", display_name="Owner")
            viewer = User(email="social-viewer@example.com", display_name="Viewer")
            blocked = User(email="social-blocked@example.com", display_name="Blocked")
            outside_owner = User(email="social-outside@example.com")
            workspace = Organization(
                name="Alpha Social API",
                slug="alpha-social-connections-api",
                owner=owner,
                workos_organization_id="org_ALPHA_SOCIAL_API",
            )
            outside_workspace = Organization(
                name="Beta Social API",
                slug="beta-social-connections-api",
                owner=outside_owner,
                workos_organization_id="org_BETA_SOCIAL_API",
            )
            owner_membership = OrganizationMembership(
                organization=workspace,
                user=owner,
                role=MembershipRole.owner,
                workspace_permission=WorkspacePermission.owner,
                department_access=["marketing", "management"],
            )
            viewer_membership = OrganizationMembership(
                organization=workspace,
                user=viewer,
                role=MembershipRole.guest,
                workspace_permission=WorkspacePermission.guest,
                department_access=["marketing"],
                capability_permissions=[Capability.marketing_account_view.value],
            )
            blocked_membership = OrganizationMembership(
                organization=workspace,
                user=blocked,
                role=MembershipRole.guest,
                workspace_permission=WorkspacePermission.guest,
                department_access=["marketing"],
                capability_permissions=[],
            )
            outside_membership = OrganizationMembership(
                organization=outside_workspace,
                user=outside_owner,
                role=MembershipRole.owner,
                workspace_permission=WorkspacePermission.owner,
                department_access=["marketing", "management"],
            )
            owner_profile = UniversalProfile(
                user=owner,
                slug="social-owner",
                display_name="Social Owner",
            )
            viewer_profile = UniversalProfile(
                user=viewer,
                slug="social-viewer",
                display_name="Social Viewer",
            )
            blocked_profile = UniversalProfile(
                user=blocked,
                slug="social-blocked",
                display_name="Social Blocked",
            )
            outside_profile = UniversalProfile(
                user=outside_owner,
                slug="social-outside",
                display_name="Social Outside",
            )
            artist_profile_user = User(email="artist-social@example.com")
            artist_universal_profile = UniversalProfile(
                user=artist_profile_user,
                slug="artist-social",
                display_name="Alpha Artist Profile",
            )
            outside_artist_universal_profile = UniversalProfile(
                user=User(email="outside-artist-social@example.com"),
                slug="outside-artist-social",
                display_name="Beta Artist Profile",
            )
            WorkspaceMembership(
                workspace=workspace,
                profile=owner_profile,
                organization_membership=owner_membership,
                status="active",
            )
            WorkspaceMembership(
                workspace=workspace,
                profile=viewer_profile,
                organization_membership=viewer_membership,
                status="active",
            )
            WorkspaceMembership(
                workspace=workspace,
                profile=blocked_profile,
                organization_membership=blocked_membership,
                status="active",
            )
            WorkspaceMembership(
                workspace=outside_workspace,
                profile=outside_profile,
                organization_membership=outside_membership,
                status="active",
            )
            artist = Artist(name="Alpha Artist", organization=workspace)
            artist_profile = ArtistProfile(
                artist=artist,
                universal_profile=artist_universal_profile,
                stage_name="Alpha",
            )
            outside_artist = Artist(name="Beta Artist", organization=outside_workspace)
            outside_artist_profile = ArtistProfile(
                artist=outside_artist,
                universal_profile=outside_artist_universal_profile,
                stage_name="Beta",
            )
            session.add_all(
                [
                    viewer_membership,
                    blocked_membership,
                    outside_membership,
                    artist_profile,
                    outside_artist_profile,
                ]
            )
            await session.commit()
            return SeededSocialAccountConnectionsApi(
                owner_user_id=owner.id,
                viewer_user_id=viewer.id,
                blocked_user_id=blocked.id,
                outside_user_id=outside_owner.id,
                workspace_id=workspace.id,
                outside_workspace_id=outside_workspace.id,
                owner_profile_id=owner_profile.id,
                artist_profile_id=artist_profile.id,
                outside_artist_profile_id=outside_artist_profile.id,
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
    seeded: SeededSocialAccountConnectionsApi,
    *,
    user_id: UUID | None = None,
    email: str = "social-owner@example.com",
    workspace_id: UUID | None = None,
    workos_organization_id: str = "org_ALPHA_SOCIAL_API",
    workspace_permission: WorkspacePermission = WorkspacePermission.owner,
    capability_permissions: tuple[str, ...] = (),
    department_access: tuple[str, ...] = ("marketing", "management"),
) -> None:
    resolved_user_id = user_id or seeded.owner_user_id
    resolved_workspace_id = workspace_id or seeded.workspace_id

    async def override_context() -> CurrentUserContext:
        return CurrentUserContext(
            user=User(id=resolved_user_id, email=email),
            principal=AuthenticatedPrincipal(
                provider="workos",
                subject=f"user_{resolved_user_id}",
                session_id="session_SECRET",
                email=email,
                organization_id=workos_organization_id,
                role=workspace_permission.value,
                roles=(workspace_permission.value,),
            ),
            memberships=(
                MembershipContext(
                    organization_id=resolved_workspace_id,
                    organization_name="Alpha Social API",
                    organization_slug="alpha-social-connections-api",
                    workos_organization_id=workos_organization_id,
                    workspace_permission=workspace_permission,
                    department_access=department_access,
                    capability_permissions=capability_permissions,
                ),
            ),
        )

    client.app.dependency_overrides[get_current_user_context] = override_context


def _base(seeded: SeededSocialAccountConnectionsApi) -> str:
    return f"/api/v1/workspaces/{seeded.workspace_id}/social-account-connections"


def _outside_base(seeded: SeededSocialAccountConnectionsApi) -> str:
    return (
        f"/api/v1/workspaces/{seeded.outside_workspace_id}"
        "/social-account-connections"
    )


def _oauth_start_base(seeded: SeededSocialAccountConnectionsApi) -> str:
    return f"{_base(seeded)}/oauth/start"


def _oauth_callback_base(seeded: SeededSocialAccountConnectionsApi) -> str:
    return f"{_base(seeded)}/oauth/instagram/callback"


def _install_fake_oauth(
    client: TestClient,
    store: InMemoryCredentialStore | None = None,
) -> InMemoryCredentialStore:
    credential_store = store or InMemoryCredentialStore()
    registry = SocialAccountProviderRegistry(
        [FakeOAuthSocialAccountConnectionProvider()]
    )
    client.app.dependency_overrides[get_credential_store_dependency] = (
        lambda: credential_store
    )
    client.app.dependency_overrides[get_social_account_provider_registry] = (
        lambda: registry
    )
    return credential_store


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


async def _state_statuses(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> list[OAuthAuthorizationStateStatus]:
    async with sessionmaker() as session:
        rows = await session.scalars(
            select(OAuthAuthorizationState).order_by(
                OAuthAuthorizationState.created_at.asc(),
                OAuthAuthorizationState.id.asc(),
            )
        )
        return [row.status for row in rows.all()]


async def _social_connections(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> list[SocialAccountConnection]:
    async with sessionmaker() as session:
        rows = await session.scalars(select(SocialAccountConnection))
        return list(rows.all())


def _payload(
    seeded: SeededSocialAccountConnectionsApi,
    *,
    provider: str = "Instagram",
    handle: str = " @AlphaArtist ",
) -> dict[str, object]:
    return {
        "provider": provider,
        "artist_profile_id": str(seeded.artist_profile_id),
        "external_account_id": "ig-alpha-1",
        "handle": handle,
        "display_name": "Alpha Artist",
        "profile_url": "https://instagram.com/AlphaArtist",
        "provider_metadata": {"source": "artist-submitted"},
    }


def test_social_account_connection_routes_require_authentication(
    client: TestClient,
) -> None:
    response = client.get(f"/api/v1/workspaces/{uuid4()}/social-account-connections")
    assert response.status_code == 401


def test_social_account_connection_list_get_create_update_and_disconnect(
    social_account_connections_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededSocialAccountConnectionsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = social_account_connections_client
    _set_context(client, seeded)
    base = _base(seeded)

    created_response = client.post(base, json=_payload(seeded))
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["provider"] == "instagram"
    assert created["handle"] == "alphaartist"
    assert created["connection_method"] == "assisted"
    assert created["status"] == "connected"
    assert created["capabilities"] == ["manual_publish"]
    assert created["resolved_capabilities"]["requires_manual_publish"] is True
    assert created["artist_association"]["artist_profile_id"] == str(
        seeded.artist_profile_id
    )

    got = client.get(f"{base}/{created['id']}")
    assert got.status_code == 200
    assert got.json()["display_name"] == "Alpha Artist"

    updated = client.patch(
        f"{base}/{created['id']}",
        json={
            "artist_profile_id": None,
            "handle": "alphafinal",
            "display_name": "Alpha Final",
            "profile_url": "https://instagram.com/AlphaFinal",
            "provider_metadata": {"reviewed": True},
        },
    )
    assert updated.status_code == 200
    updated_body = updated.json()
    assert updated_body["handle"] == "alphafinal"
    assert updated_body["display_name"] == "Alpha Final"
    assert updated_body["artist_association"] is None

    listed = client.get(base)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["social_account_connections"][0]["id"] == created["id"]

    disconnected = client.post(f"{base}/{created['id']}/disconnect")
    assert disconnected.status_code == 200
    assert disconnected.json()["status"] == "disconnected"
    assert disconnected.json()["token_expires_at"] is None

    active_only = client.get(base, params={"include_disconnected": False})
    assert active_only.status_code == 200
    assert active_only.json()["total"] == 0


def test_social_account_connection_health_and_sync_routes_update_timestamps(
    social_account_connections_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededSocialAccountConnectionsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = social_account_connections_client
    _set_context(client, seeded)
    base = _base(seeded)

    created_response = client.post(base, json=_payload(seeded))
    assert created_response.status_code == 201
    connection_id = created_response.json()["id"]

    health = client.post(f"{base}/{connection_id}/health")
    assert health.status_code == 200
    health_body = health.json()
    assert health_body["status"] == "connected"
    assert health_body["last_health_checked_at"] is not None

    synced = client.post(f"{base}/{connection_id}/sync")
    assert synced.status_code == 200
    synced_body = synced.json()
    assert synced_body["status"] == "connected"
    assert synced_body["last_synced_at"] is not None


def test_social_account_connection_mutations_publish_workspace_scoped_activity_events(
    social_account_connections_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededSocialAccountConnectionsApi,
    ],
) -> None:
    client, sessionmaker, seeded = social_account_connections_client
    _set_context(client, seeded)
    base = _base(seeded)

    created_response = client.post(
        base,
        json={
            **_payload(seeded),
            "provider_metadata": {
                "source": "artist-submitted",
                "access_token": "SECRET",
                "nested": {"refresh_token": "SECRET"},
            },
        },
    )
    assert created_response.status_code == 201
    created_body = created_response.json()
    connection_id = created_body["id"]
    assert created_body["provider_metadata"] == {
        "source": "artist-submitted",
        "nested": {},
    }

    updated = client.patch(
        f"{base}/{connection_id}",
        json={
            "display_name": "Alpha Evented",
        },
    )
    disconnected = client.post(f"{base}/{connection_id}/disconnect")

    assert updated.status_code == 200
    assert disconnected.status_code == 200

    records = asyncio.run(_realtime_events(sessionmaker, seeded.workspace_id))
    stored_connections = asyncio.run(_social_connections(sessionmaker))
    persisted = json.dumps(
        [connection.provider_metadata for connection in stored_connections],
        default=str,
    ).lower()
    assert "access_token" not in persisted
    assert "refresh_token" not in persisted
    assert "secret" not in persisted
    assert [record.event_type for record in records] == [
        "marketing.social_account.connected",
        "marketing.social_account.updated",
        "marketing.social_account.disconnected",
    ]
    assert all(record.entity_type == "social_account_connection" for record in records)
    assert all(record.entity_id == connection_id for record in records)
    assert all(record.organization_id == seeded.workspace_id for record in records)
    assert all(
        record.channel == f"organization:{seeded.workspace_id}" for record in records
    )
    assert all(record.actor_user_id == seeded.owner_user_id for record in records)

    created_payload = records[0].payload
    assert created_payload["connectionId"] == connection_id
    assert created_payload["provider"] == "instagram"
    assert created_payload["artistProfileId"] == str(seeded.artist_profile_id)
    assert created_payload["connectionMethod"] == "assisted"
    assert created_payload["status"] == "connected"
    assert created_payload["handle"] == "alphaartist"
    assert created_payload["displayName"] == "Alpha Artist"
    assert created_payload["externalAccountId"] == "ig-alpha-1"

    updated_payload = records[1].payload
    assert updated_payload["changedFields"] == "display_name"

    disconnected_payload = records[2].payload
    assert disconnected_payload["previousStatus"] == "connected"
    assert disconnected_payload["status"] == "disconnected"
    assert (
        "credential_ref"
        not in json.dumps(
            [record.payload for record in records],
            default=str,
        ).lower()
    )
    assert (
        "access_token"
        not in json.dumps(
            [record.payload for record in records],
            default=str,
        ).lower()
    )
    assert (
        "refresh_token"
        not in json.dumps(
            [record.payload for record in records],
            default=str,
        ).lower()
    )
    assert (
        "secret"
        not in json.dumps(
            [record.payload for record in records],
            default=str,
        ).lower()
    )


def test_social_account_connection_failed_mutations_do_not_publish_events(
    social_account_connections_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededSocialAccountConnectionsApi,
    ],
) -> None:
    client, sessionmaker, seeded = social_account_connections_client
    _set_context(client, seeded)
    base = _base(seeded)
    created = client.post(base, json=_payload(seeded))
    assert created.status_code == 201
    connection_id = created.json()["id"]

    _set_context(
        client,
        seeded,
        user_id=seeded.viewer_user_id,
        email="social-viewer@example.com",
        workspace_permission=WorkspacePermission.guest,
        capability_permissions=(Capability.marketing_account_view.value,),
        department_access=("marketing",),
    )
    unauthorized_update = client.patch(
        f"{base}/{connection_id}",
        json={"display_name": "Denied"},
    )
    unauthorized_create = client.post(base, json=_payload(seeded, handle="denied"))

    _set_context(client, seeded)
    duplicate = client.post(base, json=_payload(seeded))
    invalid_artist = client.patch(
        f"{base}/{connection_id}",
        json={"artist_profile_id": str(seeded.outside_artist_profile_id)},
    )

    assert unauthorized_update.status_code == 403
    assert unauthorized_create.status_code == 403
    assert duplicate.status_code == 409
    assert invalid_artist.status_code == 400

    records = asyncio.run(_realtime_events(sessionmaker, seeded.workspace_id))
    assert [record.event_type for record in records] == [
        "marketing.social_account.connected",
    ]


def test_social_account_connection_activity_events_preserve_workspace_isolation(
    social_account_connections_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededSocialAccountConnectionsApi,
    ],
) -> None:
    client, sessionmaker, seeded = social_account_connections_client
    _set_context(client, seeded)
    alpha = client.post(_base(seeded), json=_payload(seeded))
    assert alpha.status_code == 201

    _set_context(
        client,
        seeded,
        user_id=seeded.outside_user_id,
        email="social-outside@example.com",
        workspace_id=seeded.outside_workspace_id,
        workos_organization_id="org_BETA_SOCIAL_API",
        workspace_permission=WorkspacePermission.owner,
    )
    beta = client.post(
        _outside_base(seeded),
        json={
            "provider": "TikTok",
            "handle": "betaartist",
            "display_name": "Beta Artist",
            "profile_url": "https://tiktok.com/@betaartist",
        },
    )
    assert beta.status_code == 201

    alpha_records = asyncio.run(_realtime_events(sessionmaker, seeded.workspace_id))
    beta_records = asyncio.run(
        _realtime_events(sessionmaker, seeded.outside_workspace_id)
    )
    assert [record.entity_id for record in alpha_records] == [alpha.json()["id"]]
    assert [record.entity_id for record in beta_records] == [beta.json()["id"]]
    assert alpha_records[0].channel == f"organization:{seeded.workspace_id}"
    assert beta_records[0].channel == f"organization:{seeded.outside_workspace_id}"


def test_social_account_connection_view_only_user_cannot_mutate(
    social_account_connections_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededSocialAccountConnectionsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = social_account_connections_client
    _set_context(client, seeded)
    created = client.post(_base(seeded), json=_payload(seeded)).json()

    _set_context(
        client,
        seeded,
        user_id=seeded.viewer_user_id,
        email="social-viewer@example.com",
        workspace_permission=WorkspacePermission.guest,
        capability_permissions=(Capability.marketing_account_view.value,),
        department_access=("marketing",),
    )
    assert client.get(_base(seeded)).status_code == 200
    assert (
        client.patch(
            f"{_base(seeded)}/{created['id']}",
            json={"display_name": "Denied"},
        ).status_code
        == 403
    )
    assert client.post(f"{_base(seeded)}/{created['id']}/disconnect").status_code == 403
    assert (
        client.post(_base(seeded), json=_payload(seeded, handle="other")).status_code
        == 403
    )


def test_social_account_connection_user_without_view_is_denied(
    social_account_connections_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededSocialAccountConnectionsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = social_account_connections_client
    _set_context(
        client,
        seeded,
        user_id=seeded.blocked_user_id,
        email="social-blocked@example.com",
        workspace_permission=WorkspacePermission.guest,
        capability_permissions=(),
        department_access=("marketing",),
    )

    response = client.get(_base(seeded))
    assert response.status_code == 403


def test_social_account_connection_cross_workspace_access_is_hidden(
    social_account_connections_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededSocialAccountConnectionsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = social_account_connections_client
    _set_context(client, seeded)
    created = client.post(_base(seeded), json=_payload(seeded)).json()

    _set_context(
        client,
        seeded,
        user_id=seeded.outside_user_id,
        email="social-outside@example.com",
        workspace_id=seeded.outside_workspace_id,
        workos_organization_id="org_BETA_SOCIAL_API",
        workspace_permission=WorkspacePermission.owner,
    )
    assert client.get(f"{_outside_base(seeded)}/{created['id']}").status_code == 404
    assert (
        client.patch(
            f"{_outside_base(seeded)}/{created['id']}",
            json={"display_name": "Cross Workspace"},
        ).status_code
        == 404
    )


def test_social_account_connection_rejects_invalid_artist_duplicate_and_provider(
    social_account_connections_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededSocialAccountConnectionsApi,
    ],
) -> None:
    client, _sessionmaker, seeded = social_account_connections_client
    _set_context(client, seeded)
    base = _base(seeded)

    invalid_artist = client.post(
        base,
        json={**_payload(seeded), "artist_profile_id": str(uuid4())},
    )
    assert invalid_artist.status_code == 400

    outside_artist = client.post(
        base,
        json={
            **_payload(seeded, handle="outside-artist"),
            "artist_profile_id": str(seeded.outside_artist_profile_id),
        },
    )
    assert outside_artist.status_code == 400

    invalid_provider = client.post(
        base,
        json=_payload(seeded, provider="threads", handle="threads-alpha"),
    )
    assert invalid_provider.status_code == 400

    assert (
        client.post(base, json=_payload(seeded, handle="@duplicate")).status_code == 201
    )
    duplicate = client.post(base, json=_payload(seeded, handle=" duplicate "))
    assert duplicate.status_code == 409

    external_duplicate = client.post(
        base,
        json={
            **_payload(seeded, handle="unique-handle"),
            "external_account_id": "ig-alpha-1",
        },
    )
    assert external_duplicate.status_code == 409


def test_social_account_connection_safe_serialization(
    social_account_connections_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededSocialAccountConnectionsApi,
    ],
) -> None:
    client, sessionmaker, seeded = social_account_connections_client
    expires_at = datetime.now(UTC) + timedelta(days=1)

    async def seed_sensitive_connection() -> UUID:
        async with sessionmaker() as session:
            connection = SocialAccountConnection(
                organization_id=seeded.workspace_id,
                provider="spotify",
                external_account_id="spotify-alpha",
                username="alpha",
                display_name="Alpha Spotify",
                profile_url="https://open.spotify.com/artist/alpha",
                connection_method=SocialAccountConnectionMethod.assisted,
                status=SocialAccountConnectionStatus.connected,
                capabilities=["manual_publish"],
                credential_ref="vault://secret/spotify",
                token_expires_at=expires_at,
                last_synced_at=datetime.now(UTC),
                last_health_checked_at=datetime.now(UTC),
                provider_metadata={
                    "avatar_url": "https://cdn.example/avatar.png",
                    "access_token": "SECRET",
                    "nested": {
                        "refresh-token": "SECRET",
                        "safe": "kept",
                    },
                },
            )
            session.add(connection)
            await session.commit()
            return connection.id

    connection_id = asyncio.run(seed_sensitive_connection())
    _set_context(client, seeded)
    response = client.get(f"{_base(seeded)}/{connection_id}")

    assert response.status_code == 200
    body = response.json()
    assert "credential_ref" not in body
    assert "access_token" not in body["provider_metadata"]
    assert "refresh-token" not in body["provider_metadata"]["nested"]
    assert body["provider_metadata"]["avatar_url"] == "https://cdn.example/avatar.png"
    assert body["provider_metadata"]["nested"]["safe"] == "kept"
    assert body["token_expires_at"] is not None
    [persisted] = asyncio.run(_social_connections(sessionmaker))
    assert persisted.provider_metadata == {
        "avatar_url": "https://cdn.example/avatar.png",
        "nested": {"safe": "kept"},
    }


def test_social_account_oauth_start_builds_provider_authorization_url(
    social_account_connections_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededSocialAccountConnectionsApi,
    ],
) -> None:
    client, sessionmaker, seeded = social_account_connections_client
    _install_fake_oauth(client)
    _set_context(client, seeded)

    response = client.post(
        _oauth_start_base(seeded),
        json={
            "provider": "instagram",
            "redirect_uri": "https://labelos.test/oauth/callback",
            "safe_redirect_path": "/workspace/settings?tab=connections",
            "scopes": ["publish", "account_metrics"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["authorization_url"].startswith(
        "https://fake-oauth.labelos.test/authorize?"
    )
    assert "state=" in body["authorization_url"]
    assert "fake-access-token" not in body["authorization_url"]
    assert body["scopes"] == ["publish", "account_metrics"]
    assert asyncio.run(_state_statuses(sessionmaker)) == [
        OAuthAuthorizationStateStatus.pending
    ]


def test_social_account_oauth_callback_stores_credentials_and_connects_account(
    social_account_connections_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededSocialAccountConnectionsApi,
    ],
) -> None:
    client, sessionmaker, seeded = social_account_connections_client
    store = _install_fake_oauth(client)
    _set_context(client, seeded)
    started = client.post(
        _oauth_start_base(seeded),
        json={
            "provider": "instagram",
            "redirect_uri": "https://labelos.test/oauth/callback",
            "safe_redirect_path": "/workspace/settings?tab=connections",
        },
    ).json()

    response = client.get(
        _oauth_callback_base(seeded),
        params={
            "state": started["state"],
            "code": "success",
            "redirect_uri": "https://labelos.test/oauth/callback",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("&oauth=connected")
    rows = asyncio.run(_social_connections(sessionmaker))
    assert len(rows) == 1
    connection = rows[0]
    assert connection.status == SocialAccountConnectionStatus.connected
    assert connection.connection_method == SocialAccountConnectionMethod.direct_api
    assert connection.external_account_id == "fake-account-success"
    assert connection.capabilities == [
        "content_publish",
        "account_analytics_read",
        "post_analytics_read",
    ]
    assert connection.credential_ref is not None
    assert (asyncio.run(store.get(connection.credential_ref))).expose()[
        "access_token"
    ] == "fake-access-token:success"
    persisted = json.dumps(
        {
            "provider_metadata": connection.provider_metadata,
            "credential_ref": connection.credential_ref,
            "external_account_id": connection.external_account_id,
        },
        default=str,
    )
    assert "fake-access-token" not in persisted
    assert "fake-refresh-token" not in persisted
    assert asyncio.run(_state_statuses(sessionmaker)) == [
        OAuthAuthorizationStateStatus.consumed
    ]


def test_social_account_oauth_callback_partial_scopes_creates_limited_connection(
    social_account_connections_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededSocialAccountConnectionsApi,
    ],
) -> None:
    client, sessionmaker, seeded = social_account_connections_client
    _install_fake_oauth(client)
    _set_context(client, seeded)
    state = client.post(
        _oauth_start_base(seeded),
        json={
            "provider": "instagram",
            "redirect_uri": "https://labelos.test/oauth/callback",
        },
    ).json()["state"]

    response = client.get(
        _oauth_callback_base(seeded),
        params={"state": state, "code": "partial-scopes"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    connection = asyncio.run(_social_connections(sessionmaker))[0]
    assert connection.status == SocialAccountConnectionStatus.limited
    assert connection.capabilities == ["content_publish"]


@pytest.mark.parametrize(
    ("params", "expected_state"),
    [
        ({"error": "access_denied"}, OAuthAuthorizationStateStatus.consumed),
        ({"code": "exchange-fails"}, OAuthAuthorizationStateStatus.consumed),
        ({"code": "malformed"}, OAuthAuthorizationStateStatus.consumed),
    ],
)
def test_social_account_oauth_callback_failures_do_not_connect_accounts(
    social_account_connections_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededSocialAccountConnectionsApi,
    ],
    params: dict[str, str],
    expected_state: OAuthAuthorizationStateStatus,
) -> None:
    client, sessionmaker, seeded = social_account_connections_client
    _install_fake_oauth(client)
    _set_context(client, seeded)
    state = client.post(
        _oauth_start_base(seeded),
        json={
            "provider": "instagram",
            "redirect_uri": "https://labelos.test/oauth/callback",
        },
    ).json()["state"]

    response = client.get(
        _oauth_callback_base(seeded),
        params={"state": state, **params},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        "/workspace/settings?tab=connections&oauth=failed"
    )
    assert asyncio.run(_social_connections(sessionmaker)) == []
    assert asyncio.run(_state_statuses(sessionmaker)) == [expected_state]
    payload = json.dumps(dict(response.headers))
    assert "fake-access-token" not in payload
    assert "fake-refresh-token" not in payload


def test_social_account_oauth_credential_store_failure_does_not_connect_account(
    social_account_connections_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededSocialAccountConnectionsApi,
    ],
) -> None:
    client, sessionmaker, seeded = social_account_connections_client
    store = _install_fake_oauth(client)
    _set_context(client, seeded)
    state = client.post(
        _oauth_start_base(seeded),
        json={
            "provider": "instagram",
            "redirect_uri": "https://labelos.test/oauth/callback",
        },
    ).json()["state"]
    store.fail_operations.add("put")

    response = client.get(
        _oauth_callback_base(seeded),
        params={"state": state, "code": "success"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert asyncio.run(_social_connections(sessionmaker)) == []
    assert asyncio.run(_state_statuses(sessionmaker)) == [
        OAuthAuthorizationStateStatus.consumed
    ]


def test_social_account_oauth_state_replay_workspace_mismatch_and_actor_denials(
    social_account_connections_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededSocialAccountConnectionsApi,
    ],
) -> None:
    client, sessionmaker, seeded = social_account_connections_client
    _install_fake_oauth(client)
    _set_context(client, seeded)
    state = client.post(
        _oauth_start_base(seeded),
        json={
            "provider": "instagram",
            "redirect_uri": "https://labelos.test/oauth/callback",
        },
    ).json()["state"]
    first = client.get(
        _oauth_callback_base(seeded),
        params={"state": state, "code": "success"},
        follow_redirects=False,
    )
    replay = client.get(
        _oauth_callback_base(seeded),
        params={"state": state, "code": "success"},
        follow_redirects=False,
    )

    _set_context(client, seeded)
    mismatch_state = client.post(
        _oauth_start_base(seeded),
        json={
            "provider": "instagram",
            "redirect_uri": "https://labelos.test/oauth/callback",
        },
    ).json()["state"]
    _set_context(
        client,
        seeded,
        user_id=seeded.outside_user_id,
        email="social-outside@example.com",
        workspace_id=seeded.outside_workspace_id,
        workos_organization_id="org_BETA_SOCIAL_API",
        workspace_permission=WorkspacePermission.owner,
    )
    workspace_mismatch = client.get(
        f"{_outside_base(seeded)}/oauth/instagram/callback",
        params={"state": mismatch_state, "code": "success"},
        follow_redirects=False,
    )

    _set_context(
        client,
        seeded,
        user_id=seeded.viewer_user_id,
        email="social-viewer@example.com",
        workspace_permission=WorkspacePermission.guest,
        capability_permissions=(Capability.marketing_account_view.value,),
        department_access=("marketing",),
    )
    unauthorized_start = client.post(
        _oauth_start_base(seeded),
        json={
            "provider": "instagram",
            "redirect_uri": "https://labelos.test/oauth/callback",
        },
    )
    unauthorized_callback = client.get(
        _oauth_callback_base(seeded),
        params={"state": mismatch_state, "code": "success"},
        follow_redirects=False,
    )

    assert first.status_code == 303
    assert replay.status_code == 303
    assert workspace_mismatch.status_code == 303
    assert unauthorized_start.status_code == 403
    assert unauthorized_callback.status_code == 403
    assert len(asyncio.run(_social_connections(sessionmaker))) == 1
    assert asyncio.run(_state_statuses(sessionmaker)) == [
        OAuthAuthorizationStateStatus.consumed,
        OAuthAuthorizationStateStatus.pending,
    ]


def test_social_account_connection_openapi_contract_exposes_stable_routes(
    social_account_connections_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededSocialAccountConnectionsApi,
    ],
) -> None:
    client, _sessionmaker, _seeded = social_account_connections_client

    schema = client.get("/openapi.json").json()
    paths = schema["paths"]

    assert "/api/v1/workspaces/{workspace_id}/social-account-connections" in paths
    assert (
        "/api/v1/workspaces/{workspace_id}/social-account-connections/oauth/start"
        in paths
    )
    assert (
        "/api/v1/workspaces/{workspace_id}/social-account-connections/oauth/{provider}/callback"
        in paths
    )
    assert (
        "/api/v1/workspaces/{workspace_id}/social-account-connections/{connection_id}"
        in paths
    )
    assert (
        "/api/v1/workspaces/{workspace_id}/social-account-connections/{connection_id}/disconnect"
        in paths
    )
