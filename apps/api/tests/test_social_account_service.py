import asyncio
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from labelos_database.base import Base
from labelos_database.capabilities import Capability
from labelos_database.models import (
    Artist,
    ArtistProfile,
    MembershipRole,
    Organization,
    OrganizationMembership,
    RealtimeEvent,
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

from labelos_api.repositories import social_accounts
from labelos_api.services.social_account_service import (
    SocialAccountAuthorizationError,
    SocialAccountConnectionCreate,
    SocialAccountConnectionQuery,
    SocialAccountConnectionUpdate,
    SocialAccountDuplicateError,
    SocialAccountLifecycleError,
    SocialAccountNotFoundError,
    SocialAccountRelationshipError,
    associate_artist_profile,
    can_auto_publish,
    can_read_account_analytics,
    can_read_post_analytics,
    check_connection_health,
    create_connection,
    disconnect_connection,
    get_connection,
    list_connections,
    register_assisted_connection,
    requires_manual_publish,
    resolve_capabilities,
    supports_capability,
    supports_manual_metrics,
    transition_status,
    update_connection,
)
from labelos_api.social_accounts.providers import (
    AssistedSocialAccountConnectionProvider,
    FakeOAuthSocialAccountConnectionProvider,
    FakeThirdPartySocialAccountConnectionProvider,
    SocialAccountProviderError,
    SocialAccountProviderKey,
    SocialAccountProviderRegistry,
)


@pytest.fixture
def sessionmaker() -> Iterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare_database())
    yield async_sessionmaker(bind=engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


async def _seed_workspace_graph(session: AsyncSession) -> dict[str, object]:
    workspace = Organization(
        name="Alpha Social",
        slug=f"alpha-social-{uuid4()}",
        owner=User(email=f"owner-alpha-social-{uuid4()}@example.com"),
    )
    other_workspace = Organization(
        name="Beta Social",
        slug=f"beta-social-{uuid4()}",
        owner=User(email=f"owner-beta-social-{uuid4()}@example.com"),
    )
    profile = UniversalProfile(
        user=User(email=f"profile-alpha-social-{uuid4()}@example.com"),
        slug=f"profile-alpha-social-{uuid4()}",
    )
    artist_profile_user = User(email=f"artist-alpha-social-{uuid4()}@example.com")
    artist_universal_profile = UniversalProfile(
        user=artist_profile_user,
        slug=f"artist-alpha-social-{uuid4()}",
    )
    other_universal_profile = UniversalProfile(
        user=User(email=f"artist-beta-social-{uuid4()}@example.com"),
        slug=f"artist-beta-social-{uuid4()}",
    )
    workspace_membership = WorkspaceMembership(workspace=workspace, profile=profile)
    artist_workspace_membership = WorkspaceMembership(
        workspace=workspace,
        profile=artist_universal_profile,
    )
    other_workspace_membership = WorkspaceMembership(
        workspace=other_workspace,
        profile=other_universal_profile,
    )
    artist = Artist(name="Alpha Artist", organization=workspace)
    artist_profile = ArtistProfile(
        artist=artist,
        universal_profile=artist_universal_profile,
        stage_name="Alpha Artist",
    )
    other_artist = Artist(name="Beta Artist", organization=other_workspace)
    other_artist_profile = ArtistProfile(
        artist=other_artist,
        universal_profile=other_universal_profile,
        stage_name="Beta Artist",
    )
    session.add_all(
        [
            workspace_membership,
            artist_workspace_membership,
            other_workspace_membership,
            artist_profile,
            other_artist_profile,
        ]
    )
    await session.flush()
    return {
        "workspace": workspace,
        "other_workspace": other_workspace,
        "profile": profile,
        "artist_profile": artist_profile,
        "other_artist_profile": other_artist_profile,
    }


async def _seed_actor(
    session: AsyncSession,
    *,
    workspace: Organization,
    email: str,
    capability_keys: list[str],
    permission: WorkspacePermission = WorkspacePermission.guest,
) -> User:
    user = User(email=email)
    profile = UniversalProfile(user=user, slug=email.split("@", maxsplit=1)[0])
    membership = OrganizationMembership(
        organization=workspace,
        user=user,
        role=MembershipRole.guest,
        workspace_permission=permission,
        department_access=["marketing"],
        capability_permissions=capability_keys,
    )
    workspace_membership = WorkspaceMembership(
        workspace=workspace,
        profile=profile,
        organization_membership=membership,
        status="active",
    )
    session.add_all([user, profile, membership, workspace_membership])
    await session.flush()
    return user


async def _realtime_events(
    session: AsyncSession,
    organization_id: UUID,
) -> list[RealtimeEvent]:
    rows = await session.scalars(
        select(RealtimeEvent)
        .where(RealtimeEvent.organization_id == organization_id)
        .order_by(RealtimeEvent.created_at.asc(), RealtimeEvent.id.asc())
    )
    return list(rows.all())


def test_social_account_repository_create_get_list_update_and_scope(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, object]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            other_workspace = data["other_workspace"]
            artist_profile = data["artist_profile"]
            assert isinstance(workspace, Organization)
            assert isinstance(other_workspace, Organization)
            assert isinstance(artist_profile, ArtistProfile)

            created = await social_accounts.create_connection(
                session,
                workspace.id,
                {
                    "provider": "instagram",
                    "artist_profile_id": artist_profile.id,
                    "username": "alpha",
                    "capabilities": ["content_publish"],
                    "provider_metadata": {"avatar": "set"},
                },
            )
            missing = await social_accounts.get_connection(
                session,
                other_workspace.id,
                created.id,
            )
            updated = await social_accounts.update_connection(
                session,
                workspace.id,
                created.id,
                {"display_name": "Alpha Social"},
            )
            page = await social_accounts.list_connections(
                session,
                workspace.id,
                provider="instagram",
                status=None,
                artist_profile_id=None,
                include_disconnected=True,
                limit=10,
                offset=0,
            )
            await session.commit()
            assert updated is not None
            return {
                "missing": missing,
                "display_name": updated.display_name,
                "total": page.total,
                "ids": [item.id for item in page.items],
            }

    result = asyncio.run(run())
    assert result["missing"] is None
    assert result["display_name"] == "Alpha Social"
    assert result["total"] == 1
    assert len(result["ids"]) == 1


def test_social_account_service_lifecycle_disconnect_and_capability_helpers(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, object]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            artist_profile = data["artist_profile"]
            assert isinstance(workspace, Organization)
            assert isinstance(artist_profile, ArtistProfile)

            connection = await create_connection(
                session,
                workspace.id,
                SocialAccountConnectionCreate(
                    provider="TikTok",
                    artist_profile_id=artist_profile.id,
                    username="alpha",
                    capabilities=["manual_publish"],
                ),
            )
            limited = await transition_status(
                session,
                workspace.id,
                connection.id,
                SocialAccountConnectionStatus.limited,
            )
            limited_status = limited.status
            connected = await transition_status(
                session,
                workspace.id,
                connection.id,
                SocialAccountConnectionStatus.connected,
            )
            connected_status = connected.status
            disconnected = await disconnect_connection(
                session,
                workspace.id,
                connection.id,
            )
            listed_without_disconnected = await list_connections(
                session,
                workspace.id,
                query=SocialAccountConnectionQuery(include_disconnected=False),
            )
            read_back = await get_connection(session, workspace.id, connection.id)
            return {
                "provider": connection.provider,
                "limited": limited_status,
                "connected": connected_status,
                "disconnected": disconnected.status,
                "credential_ref": disconnected.credential_ref,
                "filtered_total": listed_without_disconnected.total,
                "read_back": read_back.status,
                "supports_manual": supports_capability(connection, "manual_publish"),
                "auto": can_auto_publish(connection),
                "manual": requires_manual_publish(connection),
                "account_analytics": can_read_account_analytics(connection),
                "post_analytics": can_read_post_analytics(connection),
                "manual_metrics": supports_manual_metrics(connection),
                "resolved": resolve_capabilities(connection),
            }

    result = asyncio.run(run())
    assert result["provider"] == "tiktok"
    assert result["limited"] == SocialAccountConnectionStatus.limited
    assert result["connected"] == SocialAccountConnectionStatus.connected
    assert result["disconnected"] == SocialAccountConnectionStatus.disconnected
    assert result["credential_ref"] is None
    assert result["filtered_total"] == 0
    assert result["read_back"] == SocialAccountConnectionStatus.disconnected
    assert result["supports_manual"] is True
    assert result["auto"] is False
    assert result["manual"] is True
    assert result["account_analytics"] is False
    assert result["post_analytics"] is False
    assert result["manual_metrics"] is False
    assert result["resolved"]["requires_manual_publish"] is True
    assert result["resolved"]["supports_manual_metrics"] is False


def test_social_account_service_update_and_optional_artist_association(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[str | None, object, object]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            artist_profile = data["artist_profile"]
            assert isinstance(workspace, Organization)
            assert isinstance(artist_profile, ArtistProfile)

            connection = await create_connection(
                session,
                workspace.id,
                SocialAccountConnectionCreate(provider="youtube"),
            )
            associated = await associate_artist_profile(
                session,
                workspace.id,
                connection.id,
                artist_profile.id,
            )
            associated_artist_profile_id = associated.artist_profile_id
            updated = await update_connection(
                session,
                workspace.id,
                connection.id,
                SocialAccountConnectionUpdate(
                    display_name="Alpha Channel",
                    provider_metadata={"banner": "blue"},
                    capabilities=["manual_publish", "manual_publish"],
                ),
            )
            cleared = await associate_artist_profile(
                session,
                workspace.id,
                connection.id,
                None,
            )
            return (
                updated.display_name,
                associated_artist_profile_id,
                cleared.artist_profile_id,
                updated.capabilities,
            )

    display_name, associated_artist, cleared_artist, capabilities = asyncio.run(run())
    assert display_name == "Alpha Channel"
    assert associated_artist is not None
    assert cleared_artist is None
    assert capabilities == ["manual_publish"]


def test_register_assisted_connection_normalizes_and_assigns_safe_defaults(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, object]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            artist_profile = data["artist_profile"]
            assert isinstance(workspace, Organization)
            assert isinstance(artist_profile, ArtistProfile)

            artist_connection = await register_assisted_connection(
                session,
                workspace.id,
                SocialAccountConnectionCreate(
                    provider="Twitter",
                    artist_profile_id=artist_profile.id,
                    username=" @LabelOS ",
                    display_name=" Label OS ",
                    profile_url=" https://x.com/LabelOS ",
                    provider_metadata={"source": "artist-submitted"},
                ),
            )
            label_connection = await register_assisted_connection(
                session,
                workspace.id,
                SocialAccountConnectionCreate(
                    provider="YouTube",
                    username=" label-channel ",
                    display_name="Label Channel",
                ),
            )
            return {
                "artist_provider": artist_connection.provider,
                "artist_username": artist_connection.username,
                "artist_status": artist_connection.status,
                "artist_profile_id": artist_connection.artist_profile_id,
                "artist_url": artist_connection.profile_url,
                "artist_capabilities": artist_connection.capabilities,
                "artist_metadata": artist_connection.provider_metadata,
                "label_provider": label_connection.provider,
                "label_artist_profile_id": label_connection.artist_profile_id,
                "label_capabilities": label_connection.capabilities,
                "label_status": label_connection.status,
            }

    result = asyncio.run(run())
    assert result["artist_provider"] == "x"
    assert result["artist_username"] == "labelos"
    assert result["artist_status"] == SocialAccountConnectionStatus.connected
    assert result["artist_profile_id"] is not None
    assert result["artist_url"] == "https://x.com/LabelOS"
    assert result["artist_capabilities"] == ["manual_publish"]
    assert result["artist_metadata"] == {"source": "artist-submitted"}
    assert result["label_provider"] == "youtube"
    assert result["label_artist_profile_id"] is None
    assert result["label_capabilities"] == ["manual_publish"]
    assert result["label_status"] == SocialAccountConnectionStatus.connected


def test_register_assisted_connection_rejects_invalid_provider_url_and_capabilities(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            assert isinstance(workspace, Organization)
            result: dict[str, bool] = {}

            try:
                await register_assisted_connection(
                    session,
                    workspace.id,
                    SocialAccountConnectionCreate(provider="threads", username="alpha"),
                )
            except SocialAccountProviderError:
                result["invalid_provider"] = True
                await session.rollback()

            try:
                await register_assisted_connection(
                    session,
                    workspace.id,
                    SocialAccountConnectionCreate(
                        provider="instagram",
                        username="alpha",
                        profile_url="javascript:alert(1)",
                    ),
                )
            except SocialAccountProviderError:
                result["invalid_url"] = True
                await session.rollback()

            try:
                await register_assisted_connection(
                    session,
                    workspace.id,
                    SocialAccountConnectionCreate(
                        provider="instagram",
                        username="alpha",
                        capabilities=["content_publish"],
                    ),
                )
            except SocialAccountProviderError:
                result["disallowed_capability"] = True
                await session.rollback()

            return result

    assert asyncio.run(run()) == {
        "invalid_provider": True,
        "invalid_url": True,
        "disallowed_capability": True,
    }


def test_register_assisted_connection_detects_duplicates_by_workspace_provider_handle(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, object]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            other_workspace = data["other_workspace"]
            assert isinstance(workspace, Organization)
            assert isinstance(other_workspace, Organization)
            workspace_id = workspace.id
            other_workspace_id = other_workspace.id

            first = await register_assisted_connection(
                session,
                workspace_id,
                SocialAccountConnectionCreate(provider="instagram", username="@Alpha"),
            )
            first_id = first.id
            result: dict[str, object] = {
                "first_username": first.username,
            }
            try:
                await register_assisted_connection(
                    session,
                    workspace_id,
                    SocialAccountConnectionCreate(
                        provider="Instagram",
                        username=" alpha ",
                    ),
                )
            except SocialAccountDuplicateError:
                result["duplicate_blocked"] = True
                await session.rollback()

            other = await register_assisted_connection(
                session,
                other_workspace_id,
                SocialAccountConnectionCreate(provider="instagram", username="ALPHA"),
            )
            result["other_workspace_username"] = other.username

            await disconnect_connection(session, workspace_id, first_id)
            replacement = await register_assisted_connection(
                session,
                workspace_id,
                SocialAccountConnectionCreate(provider="instagram", username="alpha"),
            )
            result["replacement_id"] = replacement.id
            return result

    result = asyncio.run(run())
    assert result["first_username"] == "alpha"
    assert result["duplicate_blocked"] is True
    assert result["other_workspace_username"] == "alpha"
    assert result["replacement_id"] is not None


def test_register_assisted_connection_blocks_external_duplicates(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, object]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            other_workspace = data["other_workspace"]
            assert isinstance(workspace, Organization)
            assert isinstance(other_workspace, Organization)
            workspace_id = workspace.id
            other_workspace_id = other_workspace.id

            first = await register_assisted_connection(
                session,
                workspace_id,
                SocialAccountConnectionCreate(
                    provider="instagram",
                    external_account_id="ig_alpha",
                    username="alpha",
                ),
            )
            first_id = first.id
            result: dict[str, object] = {"first_id": first_id}
            try:
                await register_assisted_connection(
                    session,
                    workspace_id,
                    SocialAccountConnectionCreate(
                        provider="Instagram",
                        external_account_id="ig_alpha",
                        username="alpha-alt",
                    ),
                )
            except SocialAccountDuplicateError:
                result["duplicate_blocked"] = True
                await session.rollback()

            other = await register_assisted_connection(
                session,
                other_workspace_id,
                SocialAccountConnectionCreate(
                    provider="instagram",
                    external_account_id="ig_alpha",
                    username="alpha",
                ),
            )
            await disconnect_connection(session, workspace_id, first_id)
            replacement = await register_assisted_connection(
                session,
                workspace_id,
                SocialAccountConnectionCreate(
                    provider="instagram",
                    external_account_id="ig_alpha",
                    username="alpha-replacement",
                ),
            )
            result["other_workspace_id"] = other.id
            result["replacement_id"] = replacement.id
            return result

    result = asyncio.run(run())
    assert result["first_id"] is not None
    assert result["duplicate_blocked"] is True
    assert result["other_workspace_id"] is not None
    assert result["replacement_id"] is not None


def test_register_assisted_connection_enforces_manage_authorization(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            assert isinstance(workspace, Organization)

            manage_actor = await _seed_actor(
                session,
                workspace=workspace,
                email="assisted-manage@example.com",
                capability_keys=[Capability.marketing_account_manage.value],
            )
            view_actor = await _seed_actor(
                session,
                workspace=workspace,
                email="assisted-view@example.com",
                capability_keys=[Capability.marketing_account_view.value],
            )
            created = await register_assisted_connection(
                session,
                workspace.id,
                SocialAccountConnectionCreate(provider="spotify", username="artist"),
                actor=manage_actor.id,
            )
            result = {"manage_created": created.provider == "spotify"}
            try:
                await register_assisted_connection(
                    session,
                    workspace.id,
                    SocialAccountConnectionCreate(provider="spotify", username="other"),
                    actor=view_actor.id,
                )
            except SocialAccountAuthorizationError:
                result["view_denied"] = True
            return result

    assert asyncio.run(run()) == {
        "manage_created": True,
        "view_denied": True,
    }


def test_assisted_connection_disconnect_and_health_semantics(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, object]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            assert isinstance(workspace, Organization)

            connection = await register_assisted_connection(
                session,
                workspace.id,
                SocialAccountConnectionCreate(provider="tiktok", username="alpha"),
            )
            registered_status = connection.status
            health = await check_connection_health(session, workspace.id, connection.id)
            disconnected = await disconnect_connection(
                session,
                workspace.id,
                connection.id,
            )
            disconnected_health = await check_connection_health(
                session,
                workspace.id,
                connection.id,
            )
            return {
                "status": registered_status,
                "credential_ref": connection.credential_ref,
                "health_healthy": health.healthy,
                "health_status": health.status,
                "disconnected": disconnected.status,
                "disconnected_health_healthy": disconnected_health.healthy,
                "disconnected_health_status": disconnected_health.status,
            }

    result = asyncio.run(run())
    assert result["status"] == SocialAccountConnectionStatus.connected
    assert result["credential_ref"] is None
    assert result["health_healthy"] is True
    assert result["health_status"] == "assisted_action_required"
    assert result["disconnected"] == SocialAccountConnectionStatus.disconnected
    assert result["disconnected_health_healthy"] is False
    assert result["disconnected_health_status"] == "disconnected"


def test_instagram_connections_are_distinct_by_connection_method(
    sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = SocialAccountProviderRegistry(
        [
            AssistedSocialAccountConnectionProvider(SocialAccountProviderKey.instagram),
            FakeOAuthSocialAccountConnectionProvider(),
            FakeThirdPartySocialAccountConnectionProvider(),
        ]
    )
    monkeypatch.setattr(
        "labelos_api.social_accounts.providers.provider_registry",
        registry,
    )

    async def run() -> dict[str, object]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            assert isinstance(workspace, Organization)

            assisted = await register_assisted_connection(
                session,
                workspace.id,
                SocialAccountConnectionCreate(
                    provider="instagram",
                    external_account_id="ig_same_account",
                    username="@artist",
                ),
            )
            direct_api = await create_connection(
                session,
                workspace.id,
                SocialAccountConnectionCreate(
                    provider="instagram",
                    external_account_id="ig_same_account",
                    username="@artist",
                    connection_method=SocialAccountConnectionMethod.direct_api,
                    status=SocialAccountConnectionStatus.connected,
                ),
            )
            third_party = await create_connection(
                session,
                workspace.id,
                SocialAccountConnectionCreate(
                    provider="instagram",
                    external_account_id="ig_same_account",
                    username="@artist",
                    connection_method=SocialAccountConnectionMethod.third_party,
                    status=SocialAccountConnectionStatus.connected,
                    provider_metadata={
                        "third_party": {
                            "external_integration_account_id": "vendor-account-1",
                            "external_connection_id": "vendor-connection-1",
                        }
                    },
                ),
            )
            page = await list_connections(
                session,
                workspace.id,
                query=SocialAccountConnectionQuery(provider="instagram"),
            )
            return {
                "total": page.total,
                "methods": sorted(
                    connection.connection_method.value for connection in page.items
                ),
                "providers": {connection.provider for connection in page.items},
                "external_ids": {
                    connection.external_account_id for connection in page.items
                },
                "third_party_metadata": third_party.provider_metadata,
                "assisted_capabilities": assisted.capabilities,
                "direct_capabilities": direct_api.capabilities,
                "third_party_capabilities": third_party.capabilities,
            }

    result = asyncio.run(run())
    assert result["total"] == 3
    assert result["methods"] == ["assisted", "direct_api", "third_party"]
    assert result["providers"] == {"instagram"}
    assert result["external_ids"] == {"ig_same_account"}
    assert result["assisted_capabilities"] == ["manual_publish"]
    assert result["direct_capabilities"] == [
        "content_publish",
        "account_analytics_read",
        "post_analytics_read",
    ]
    assert result["third_party_capabilities"] == [
        "content_publish",
        "account_analytics_read",
        "post_analytics_read",
    ]
    assert result["third_party_metadata"]["third_party"] == {
        "adapter_key": "fake_test",
        "external_integration_account_id": "vendor-account-1",
        "external_connection_id": "vendor-connection-1",
    }


def test_social_account_status_transition_publishes_health_changed_event(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, object]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            assert isinstance(workspace, Organization)

            connection = await register_assisted_connection(
                session,
                workspace.id,
                SocialAccountConnectionCreate(provider="tiktok", username="alpha"),
            )
            limited = await transition_status(
                session,
                workspace.id,
                connection.id,
                SocialAccountConnectionStatus.limited,
            )
            records = await _realtime_events(session, workspace.id)
            return {
                "status": limited.status,
                "types": [record.event_type for record in records],
                "entity_types": [record.entity_type for record in records],
                "health_payload": records[-1].payload,
            }

    result = asyncio.run(run())
    assert result["status"] == SocialAccountConnectionStatus.limited
    assert result["types"] == [
        "marketing.social_account.connected",
        "marketing.social_account.health_changed",
    ]
    assert result["entity_types"] == [
        "social_account_connection",
        "social_account_connection",
    ]
    assert result["health_payload"]["previousStatus"] == "connected"
    assert result["health_payload"]["status"] == "limited"


def test_social_account_service_rejects_invalid_and_cross_workspace_artists(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            other_artist_profile = data["other_artist_profile"]
            assert isinstance(workspace, Organization)
            assert isinstance(other_artist_profile, ArtistProfile)

            result: dict[str, bool] = {}
            try:
                await create_connection(
                    session,
                    workspace.id,
                    SocialAccountConnectionCreate(
                        provider="instagram",
                        artist_profile_id=uuid4(),
                    ),
                )
            except SocialAccountRelationshipError:
                result["invalid_artist"] = True
                await session.rollback()

            connection = await create_connection(
                session,
                workspace.id,
                SocialAccountConnectionCreate(provider="instagram"),
            )
            try:
                await associate_artist_profile(
                    session,
                    workspace.id,
                    connection.id,
                    other_artist_profile.id,
                )
            except SocialAccountRelationshipError:
                result["cross_workspace_artist"] = True
            return result

    assert asyncio.run(run()) == {
        "invalid_artist": True,
        "cross_workspace_artist": True,
    }


def test_social_account_service_enforces_workspace_connection_scope(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> bool:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            other_workspace = data["other_workspace"]
            assert isinstance(workspace, Organization)
            assert isinstance(other_workspace, Organization)

            connection = await create_connection(
                session,
                workspace.id,
                SocialAccountConnectionCreate(provider="instagram"),
            )
            try:
                await get_connection(session, other_workspace.id, connection.id)
            except SocialAccountNotFoundError:
                return True
            return False

    assert asyncio.run(run()) is True


def test_social_account_service_rejects_invalid_lifecycle_transitions(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            assert isinstance(workspace, Organization)

            connection = await create_connection(
                session,
                workspace.id,
                SocialAccountConnectionCreate(provider="instagram"),
            )
            result: dict[str, bool] = {}
            try:
                await transition_status(
                    session,
                    workspace.id,
                    connection.id,
                    SocialAccountConnectionStatus.reconnect_required,
                )
            except SocialAccountLifecycleError:
                result["pending_to_reconnect"] = True

            errored = await transition_status(
                session,
                workspace.id,
                connection.id,
                SocialAccountConnectionStatus.error,
                error_code="oauth_failed",
            )
            try:
                await transition_status(
                    session,
                    workspace.id,
                    errored.id,
                    SocialAccountConnectionStatus.connected,
                )
            except SocialAccountLifecycleError:
                result["error_recovery_requires_flag"] = True
            recovered = await transition_status(
                session,
                workspace.id,
                errored.id,
                SocialAccountConnectionStatus.connected,
                recovery_succeeded=True,
            )
            disconnected = await disconnect_connection(
                session, workspace.id, recovered.id
            )
            try:
                await transition_status(
                    session,
                    workspace.id,
                    disconnected.id,
                    SocialAccountConnectionStatus.connected,
                    recovery_succeeded=True,
                )
            except SocialAccountLifecycleError:
                result["disconnected_to_connected"] = True
            return result

    assert asyncio.run(run()) == {
        "pending_to_reconnect": True,
        "error_recovery_requires_flag": True,
        "disconnected_to_connected": True,
    }


def test_social_account_service_enforces_view_and_manage_permissions(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            assert isinstance(workspace, Organization)

            view_actor = await _seed_actor(
                session,
                workspace=workspace,
                email="social-view@example.com",
                capability_keys=[Capability.marketing_account_view.value],
            )
            manage_actor = await _seed_actor(
                session,
                workspace=workspace,
                email="social-manage@example.com",
                capability_keys=[Capability.marketing_account_manage.value],
            )
            none_actor = await _seed_actor(
                session,
                workspace=workspace,
                email="social-none@example.com",
                capability_keys=[],
            )
            connection = await create_connection(
                session,
                workspace.id,
                SocialAccountConnectionCreate(provider="instagram"),
                actor=manage_actor.id,
            )
            result = {
                "manage_created": connection.provider == "instagram",
                "view_read": (
                    await get_connection(
                        session,
                        workspace.id,
                        connection.id,
                        actor=view_actor.id,
                    )
                ).id
                == connection.id,
            }
            try:
                await update_connection(
                    session,
                    workspace.id,
                    connection.id,
                    SocialAccountConnectionUpdate(display_name="Denied"),
                    actor=view_actor.id,
                )
            except SocialAccountAuthorizationError:
                result["view_cannot_manage"] = True
            try:
                await list_connections(session, workspace.id, actor=none_actor.id)
            except SocialAccountAuthorizationError:
                result["none_cannot_view"] = True
            return result

    assert asyncio.run(run()) == {
        "manage_created": True,
        "view_read": True,
        "view_cannot_manage": True,
        "none_cannot_view": True,
    }


def test_social_account_service_blocks_updates_to_disconnected_accounts(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, object]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            assert isinstance(workspace, Organization)

            connection = await create_connection(
                session,
                workspace.id,
                SocialAccountConnectionCreate(
                    provider="instagram",
                    credential_ref="vault://token",
                ),
            )
            disconnected = await disconnect_connection(
                session,
                workspace.id,
                connection.id,
            )
            result: dict[str, object] = {
                "status": disconnected.status,
                "credential_ref": disconnected.credential_ref,
            }
            try:
                await update_connection(
                    session,
                    workspace.id,
                    connection.id,
                    SocialAccountConnectionUpdate(display_name="Should Fail"),
                )
            except SocialAccountLifecycleError:
                result["update_blocked"] = True
            return result

    assert asyncio.run(run()) == {
        "status": SocialAccountConnectionStatus.disconnected,
        "credential_ref": None,
        "update_blocked": True,
    }
