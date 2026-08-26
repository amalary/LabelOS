import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from labelos_database.base import Base
from labelos_database.models import (
    Artist,
    ArtistProfile,
    Capability,
    Department,
    MembershipDepartmentAccess,
    MembershipRole,
    Organization,
    OrganizationMembership,
    ProfileAttribute,
    ProfileLink,
    ProfilePreference,
    RealtimeEvent,
    Role,
    RoleCapability,
    UniversalProfile,
    User,
    WorkspaceMembership,
    WorkspaceMembershipRole,
    WorkspacePermission,
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
class SeededProfiles:
    user_id: UUID
    member_user_id: UUID
    outside_user_id: UUID
    workspace_id: UUID
    outside_workspace_id: UUID
    profile_id: UUID
    member_profile_id: UUID
    outside_profile_id: UUID


@pytest.fixture
def profiles_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, async_sessionmaker[AsyncSession], SeededProfiles]]:
    monkeypatch.setenv("APP_ENV", "test")
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def prepare_database() -> SeededProfiles:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with sessionmaker() as session:
            owner = User(
                email="owner@example.com",
                workos_user_id="user_WORKOS_OWNER",
                first_name="Original",
                last_name="Owner",
                display_name="Owner",
            )
            member = User(email="member@example.com", display_name="Member")
            outside = User(email="outside@example.com", display_name="Outside")
            workspace = Organization(
                name="Alpha Label",
                slug="alpha-label",
                owner=owner,
                workos_organization_id="org_ALPHA",
            )
            outside_workspace = Organization(
                name="Outside Label",
                slug="outside-label",
                owner=outside,
                workos_organization_id="org_OUTSIDE",
            )
            owner_membership = OrganizationMembership(
                organization=workspace,
                user=owner,
                role=MembershipRole.owner,
            )
            member_membership = OrganizationMembership(
                organization=workspace,
                user=member,
                role=MembershipRole.member,
            )
            outside_membership = OrganizationMembership(
                organization=outside_workspace,
                user=outside,
                role=MembershipRole.owner,
            )
            owner_profile = UniversalProfile(
                user=owner,
                slug="owner-profile",
                display_name="Owner Profile",
                headline="Label owner",
                biography="Original bio",
                avatar_url="https://example.com/avatar.png",
                location="Los Angeles, CA",
                timezone="America/Los_Angeles",
                primary_email="owner@example.com",
                first_name="Original",
                last_name="Owner",
            )
            member_profile = UniversalProfile(
                user=member,
                slug="member-profile",
                display_name="Member Profile",
                headline="Member headline",
                biography="Member private biography",
                primary_email="member@example.com",
            )
            outside_profile = UniversalProfile(
                user=outside,
                slug="outside-profile",
                display_name="Outside Profile",
                primary_email="outside@example.com",
            )
            session.add_all(
                [
                    WorkspaceMembership(
                        workspace=workspace,
                        profile=owner_profile,
                        organization_membership=owner_membership,
                        status="active",
                    ),
                    WorkspaceMembership(
                        workspace=workspace,
                        profile=member_profile,
                        organization_membership=member_membership,
                        status="active",
                    ),
                    WorkspaceMembership(
                        workspace=outside_workspace,
                        profile=outside_profile,
                        organization_membership=outside_membership,
                        status="active",
                    ),
                    ProfileLink(
                        profile=owner_profile,
                        link_type="website",
                        url="https://example.com",
                    ),
                    ProfileAttribute(
                        profile=owner_profile,
                        attribute_type="instrument",
                        value="Piano",
                    ),
                    ProfileLink(
                        profile=member_profile,
                        link_type="website",
                        url="https://member.example.com/private",
                    ),
                    ProfileAttribute(
                        profile=member_profile,
                        attribute_type="private-note",
                        value="Sensitive member attribute",
                    ),
                    ProfilePreference(
                        profile=owner_profile,
                        locale="en-US",
                        interface_theme="system",
                    ),
                    ProfilePreference(
                        profile=member_profile,
                        locale="fr-FR",
                        interface_theme="dark",
                        email_notifications_enabled=False,
                        notification_preferences={"digest": "weekly"},
                    ),
                ]
            )
            await session.commit()
            return SeededProfiles(
                user_id=owner.id,
                member_user_id=member.id,
                outside_user_id=outside.id,
                workspace_id=workspace.id,
                outside_workspace_id=outside_workspace.id,
                profile_id=owner_profile.id,
                member_profile_id=member_profile.id,
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


def _set_context(
    client: TestClient,
    seeded: SeededProfiles,
    *,
    user_id: UUID | None = None,
    email: str = "owner@example.com",
    display_name: str = "Owner",
    first_name: str | None = None,
    last_name: str | None = None,
    profile_image_url: str | None = None,
    memberships: tuple[MembershipContext, ...] | None = None,
) -> None:
    async def override_context() -> CurrentUserContext:
        return CurrentUserContext(
            user=User(
                id=user_id or seeded.user_id,
                email=email,
                display_name=display_name,
                first_name=first_name,
                last_name=last_name,
                profile_image_url=profile_image_url,
            ),
            principal=AuthenticatedPrincipal(
                provider="workos",
                subject="user_WORKOS_OWNER",
                session_id="session_SECRET",
                email=email,
                display_name=display_name,
                organization_id="org_ALPHA",
                role="owner",
                roles=("owner",),
            ),
            memberships=(
                memberships
                if memberships is not None
                else (
                    MembershipContext(
                        organization_id=seeded.workspace_id,
                        organization_name="Alpha Label",
                        organization_slug="alpha-label",
                        workos_organization_id="org_ALPHA",
                        workspace_permission=WorkspacePermission.owner,
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
            .order_by(RealtimeEvent.created_at.asc(), RealtimeEvent.id.asc())
        )
        return list(rows.all())


async def _profile_for_user(
    sessionmaker: async_sessionmaker[AsyncSession],
    user_id: UUID,
) -> UniversalProfile | None:
    async with sessionmaker() as session:
        return await session.scalar(
            select(UniversalProfile).where(UniversalProfile.user_id == user_id)
        )


async def _profile_count_for_user(
    sessionmaker: async_sessionmaker[AsyncSession],
    user_id: UUID,
) -> int:
    async with sessionmaker() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(UniversalProfile)
            .where(UniversalProfile.user_id == user_id)
        )
        return count or 0


async def _set_workspace_permission(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID,
    workspace_id: UUID,
    permission: WorkspacePermission,
) -> None:
    async with sessionmaker() as session:
        membership = await session.scalar(
            select(OrganizationMembership)
            .where(OrganizationMembership.user_id == user_id)
            .where(OrganizationMembership.organization_id == workspace_id)
        )
        assert membership is not None
        membership.role = MembershipRole(permission.value)
        membership.workspace_permission = permission
        await session.commit()


async def _grant_workspace_role(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    profile_id: UUID,
    workspace_id: UUID,
    role_key: str,
    capability_keys: tuple[str, ...],
    departments: tuple[str, ...] = (),
) -> None:
    async with sessionmaker() as session:
        workspace_membership = await session.scalar(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .where(WorkspaceMembership.profile_id == profile_id)
        )
        assert workspace_membership is not None
        role = Role(
            key=role_key,
            display_name=role_key.replace("_", " ").title(),
            description=f"{role_key} test role.",
        )
        session.add(role)
        await session.flush()
        for capability_key in capability_keys:
            capability = await session.scalar(
                select(Capability).where(Capability.key == capability_key)
            )
            if capability is None:
                capability = Capability(
                    key=capability_key,
                    display_name=capability_key,
                    description=f"{capability_key} capability.",
                    system_capability=True,
                )
                session.add(capability)
                await session.flush()
            session.add(RoleCapability(role=role, capability=capability))
        session.add(
            WorkspaceMembershipRole(
                workspace_membership=workspace_membership,
                role=role,
            )
        )
        if workspace_membership.organization_membership_id is not None:
            for department_slug in departments:
                department = await session.scalar(
                    select(Department).where(Department.slug == department_slug)
                )
                if department is None:
                    department = Department(
                        slug=department_slug,
                        display_name=department_slug.title(),
                        description=f"{department_slug} department.",
                    )
                    session.add(department)
                    await session.flush()
                session.add(
                    MembershipDepartmentAccess(
                        membership_id=workspace_membership.organization_membership_id,
                        department=department,
                        access_level="member",
                        source="test",
                    )
                )
        await session.commit()


async def _seed_artist_profile_for_member(
    sessionmaker: async_sessionmaker[AsyncSession],
    seeded: SeededProfiles,
) -> tuple[UUID, UUID]:
    async with sessionmaker() as session:
        workspace = await session.get(Organization, seeded.workspace_id)
        member_profile = await session.get(UniversalProfile, seeded.member_profile_id)
        assert workspace is not None
        assert member_profile is not None
        artist = Artist(name="Member Artist", organization=workspace)
        session.add(artist)
        await session.flush()
        artist_profile = ArtistProfile(
            artist=artist,
            universal_profile=member_profile,
            stage_name="Member Artist",
        )
        session.add(artist_profile)
        await session.commit()
        return artist.id, artist_profile.id


def test_profiles_require_authentication(client: TestClient) -> None:
    response = client.get(f"/api/v1/profiles/{uuid4()}")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_get_my_profile_returns_safe_universal_profile(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, _sessionmaker, seeded = profiles_client
    _set_context(client, seeded)

    response = client.get("/api/v1/profiles/me")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(seeded.profile_id)
    assert body["slug"] == "owner-profile"
    assert body["first_name"] == "Original"
    assert body["last_name"] == "Owner"
    assert body["display_name"] == "Owner Profile"
    assert body["headline"] == "Label owner"
    assert body["location"] == "Los Angeles, CA"
    assert body["timezone"] == "America/Los_Angeles"
    assert body["primary_email"] == "owner@example.com"
    assert body["links"][0]["url"] == "https://example.com"
    assert body["attributes"][0]["value"] == "Piano"
    assert body["preferences"]["locale"] == "en-US"
    assert body["profile_completion"]["ruleset"] == "professional"
    assert body["profile_completion"]["is_complete"] is True
    assert body["profile_completion"]["guidance"] is None
    assert "workos_user_id" not in response.text
    assert "session_SECRET" not in response.text


def test_get_my_profile_creates_universal_profile_from_authenticated_user(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, sessionmaker, seeded = profiles_client

    async def seed_legacy_user_without_profile() -> UUID:
        async with sessionmaker() as session:
            legacy_user = User(
                email="legacy@example.com",
                first_name="Legacy",
                last_name="Creator",
                display_name="Legacy Creator",
                profile_image_url="https://cdn.example.com/legacy.jpg",
            )
            workspace = await session.get(Organization, seeded.workspace_id)
            assert workspace is not None
            membership = OrganizationMembership(
                organization=workspace,
                user=legacy_user,
                role=MembershipRole.member,
                workspace_permission=WorkspacePermission.member,
                status="active",
            )
            session.add_all([legacy_user, membership])
            await session.commit()
            return legacy_user.id

    legacy_user_id = asyncio.run(seed_legacy_user_without_profile())
    _set_context(
        client,
        seeded,
        user_id=legacy_user_id,
        email="legacy@example.com",
        display_name="Legacy Creator",
        first_name="Legacy",
        last_name="Creator",
        profile_image_url="https://cdn.example.com/legacy.jpg",
        memberships=(
            MembershipContext(
                organization_id=seeded.workspace_id,
                organization_name="Alpha Label",
                organization_slug="alpha-label",
                workos_organization_id="org_ALPHA",
                workspace_permission=WorkspacePermission.member,
            ),
        ),
    )

    response = client.get("/api/v1/profiles/me")

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(legacy_user_id)
    assert body["display_name"] == "Legacy Creator"
    assert body["avatar_url"] == "https://cdn.example.com/legacy.jpg"
    assert body["first_name"] == "Legacy"
    assert body["last_name"] == "Creator"
    assert body["primary_email"] == "legacy@example.com"
    assert body["profile_status"] == "active"
    assert body["onboarding_status"] == "not_started"
    profile = asyncio.run(_profile_for_user(sessionmaker, legacy_user_id))
    assert profile is not None
    assert profile.primary_email == "legacy@example.com"


def test_patch_my_profile_does_not_duplicate_existing_user_profile(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, sessionmaker, seeded = profiles_client
    _set_context(client, seeded)

    response = client.patch(
        "/api/v1/profiles/me",
        json={"display_name": "Owner Once"},
    )

    assert response.status_code == 200
    assert asyncio.run(_profile_count_for_user(sessionmaker, seeded.user_id)) == 1


def test_patch_my_profile_updates_allowed_fields_and_replaces_metadata(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, sessionmaker, seeded = profiles_client
    _set_context(client, seeded)

    response = client.patch(
        "/api/v1/profiles/me",
        json={
            "slug": "owner-renamed",
            "display_name": "Updated Owner",
            "headline": "Catalog strategist",
            "biography": "Updated biography",
            "avatar_url": "https://cdn.example.com/avatar.jpg",
            "location": "New York, NY",
            "timezone": "America/New_York",
            "links": [
                {
                    "link_type": "spotify",
                    "label": "Spotify",
                    "url": "https://open.spotify.com/artist/example",
                    "username": "owner",
                    "metadata": {"followers": 1200},
                }
            ],
            "attributes": [
                {
                    "attribute_type": "skill",
                    "label": "Skill",
                    "value": "A&R",
                    "is_primary": True,
                }
            ],
            "preferences": {
                "push_notifications_enabled": False,
                "interface_density": "compact",
                "notification_preferences": {"digest": "daily"},
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "owner-renamed"
    assert body["display_name"] == "Updated Owner"
    assert body["headline"] == "Catalog strategist"
    assert body["biography"] == "Updated biography"
    assert body["avatar_url"] == "https://cdn.example.com/avatar.jpg"
    assert body["location"] == "New York, NY"
    assert body["timezone"] == "America/New_York"
    assert [(link["link_type"], link["url"]) for link in body["links"]] == [
        ("spotify", "https://open.spotify.com/artist/example")
    ]
    assert body["links"][0]["metadata"] == {"followers": 1200}
    assert [(item["attribute_type"], item["value"]) for item in body["attributes"]] == [
        ("skill", "A&R")
    ]
    assert body["preferences"]["locale"] == "en-US"
    assert body["preferences"]["push_notifications_enabled"] is False
    assert body["preferences"]["interface_density"] == "compact"
    assert body["preferences"]["notification_preferences"] == {"digest": "daily"}
    assert body["profile_completion"]["is_complete"] is True
    events = asyncio.run(_realtime_events(sessionmaker, seeded.workspace_id))
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "profile.updated"
    assert event.actor_user_id == seeded.user_id
    assert event.entity_type == "profile"
    assert event.entity_id == str(seeded.profile_id)
    assert event.created_at is not None
    assert event.payload["profileId"] == str(seeded.profile_id)
    assert event.payload["workspaceId"] == str(seeded.workspace_id)
    assert event.payload["changedFields"] == [
        "attributes",
        "avatar_url",
        "biography",
        "display_name",
        "headline",
        "links",
        "location",
        "preferences",
        "slug",
        "timezone",
    ]
    assert "Updated biography" not in str(event.payload)
    assert "https://open.spotify.com/artist/example" not in str(event.payload)


def test_patch_my_profile_requires_database_profile_edit_capability(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, sessionmaker, seeded = profiles_client
    asyncio.run(
        _set_workspace_permission(
            sessionmaker,
            user_id=seeded.user_id,
            workspace_id=seeded.workspace_id,
            permission=WorkspacePermission.guest,
        )
    )
    _set_context(
        client,
        seeded,
        memberships=(
            MembershipContext(
                organization_id=seeded.workspace_id,
                organization_name="Alpha Label",
                organization_slug="alpha-label",
                workos_organization_id="org_ALPHA",
                workspace_permission=WorkspacePermission.guest,
            ),
        ),
    )

    response = client.patch(
        "/api/v1/profiles/me",
        json={"display_name": "Blocked Owner"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient capability permission"}


def test_patch_my_profile_without_active_workspace_does_not_publish_activity(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, sessionmaker, seeded = profiles_client
    _set_context(client, seeded, memberships=())

    response = client.patch(
        "/api/v1/profiles/me",
        json={"display_name": "Solo Profile"},
    )

    assert response.status_code == 200
    assert response.json()["display_name"] == "Solo Profile"
    assert asyncio.run(_realtime_events(sessionmaker, seeded.workspace_id)) == []


def test_patch_my_profile_rejects_empty_body(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, _sessionmaker, seeded = profiles_client
    _set_context(client, seeded)

    response = client.patch("/api/v1/profiles/me", json={})

    assert response.status_code == 422
    assert response.json() == {"detail": "Request validation failed"}


def test_get_my_profile_uses_artist_completion_rules_for_artist_responsibilities(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, sessionmaker, seeded = profiles_client

    async def seed_artist_profile() -> None:
        async with sessionmaker() as session:
            workspace = await session.get(Organization, seeded.workspace_id)
            universal_profile = await session.get(UniversalProfile, seeded.profile_id)
            assert workspace is not None
            assert universal_profile is not None
            artist = Artist(name="Owner Artist", organization=workspace)
            session.add(artist)
            await session.flush()
            session.add(
                ArtistProfile(
                    artist=artist,
                    universal_profile=universal_profile,
                    stage_name="Owner Artist",
                    imagery={"avatar": "https://cdn.example.com/artist.jpg"},
                    dsp_links={},
                )
            )
            await session.commit()

    asyncio.run(seed_artist_profile())
    _set_context(
        client,
        seeded,
        memberships=(
            MembershipContext(
                organization_id=seeded.workspace_id,
                organization_name="Alpha Label",
                organization_slug="alpha-label",
                workos_organization_id="org_ALPHA",
                workspace_permission=WorkspacePermission.member,
                professional_roles=("Artist",),
            ),
        ),
    )

    response = client.get("/api/v1/profiles/me")

    assert response.status_code == 200
    completion = response.json()["profile_completion"]
    assert completion["ruleset"] == "artist"
    assert completion["percent"] == 75
    assert completion["completed_fields"] == [
        "Artist name",
        "Artist image",
        "Biography",
    ]
    assert completion["missing_fields"] == ["DSP links"]
    assert completion["guidance"] == "Complete your artist profile"
    assert completion["is_blocking"] is False


def test_patch_my_profile_can_complete_onboarding(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, _sessionmaker, seeded = profiles_client
    _set_context(client, seeded)

    response = client.patch(
        "/api/v1/profiles/me",
        json={
            "display_name": "Updated Owner",
            "onboarding_status": "complete",
            "preferences": {"timezone": "America/New_York"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["onboarding_status"] == "complete"
    assert body["preferences"]["timezone"] == "America/New_York"


def test_patch_my_profile_rejects_unknown_onboarding_status(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, _sessionmaker, seeded = profiles_client
    _set_context(client, seeded)

    response = client.patch(
        "/api/v1/profiles/me",
        json={"onboarding_status": "skipped"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Request validation failed"}


def test_patch_my_profile_rejects_duplicate_slug(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, _sessionmaker, seeded = profiles_client
    _set_context(client, seeded)

    response = client.patch(
        "/api/v1/profiles/me",
        json={"slug": "member-profile"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Profile update conflicts with an existing record"
    }


def test_patch_my_profile_rejects_invalid_slug(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, _sessionmaker, seeded = profiles_client
    _set_context(client, seeded)

    response = client.patch(
        "/api/v1/profiles/me",
        json={"slug": "Bad Slug"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Request validation failed"}


def test_patch_my_profile_rejects_workos_managed_identity_fields(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, _sessionmaker, seeded = profiles_client
    _set_context(client, seeded)

    response = client.patch(
        "/api/v1/profiles/me",
        json={
            "display_name": "Updated Owner",
            "primary_email": "attacker@example.com",
            "first_name": "Changed",
            "last_name": "Person",
            "profile_status": "suspended",
            "workos_user_id": "user_ATTACKER",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Request validation failed"}


def test_patch_my_profile_validates_urls(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, _sessionmaker, seeded = profiles_client
    _set_context(client, seeded)

    response = client.patch(
        "/api/v1/profiles/me",
        json={"avatar_url": "javascript:alert(1)"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Request validation failed"}


def test_list_workspace_profiles_requires_workspace_membership(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, _sessionmaker, seeded = profiles_client
    _set_context(client, seeded)

    response = client.get(f"/api/v1/workspaces/{seeded.outside_workspace_id}/profiles")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_list_workspace_profiles_allows_standalone_workspace_member(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, sessionmaker, seeded = profiles_client

    async def seed_standalone_member() -> tuple[UUID, UUID]:
        async with sessionmaker() as session:
            workspace = await session.get(Organization, seeded.workspace_id)
            assert workspace is not None
            user = User(
                email="external@example.com",
                display_name="External Collaborator",
            )
            profile = UniversalProfile(
                user=user,
                display_name="External Collaborator",
                primary_email="external@example.com",
            )
            session.add(
                WorkspaceMembership(
                    workspace=workspace,
                    profile=profile,
                    status="active",
                )
            )
            await session.commit()
            return user.id, profile.id

    user_id, profile_id = asyncio.run(seed_standalone_member())
    _set_context(
        client,
        seeded,
        user_id=user_id,
        email="external@example.com",
        display_name="External Collaborator",
        memberships=(
            MembershipContext(
                organization_id=seeded.workspace_id,
                organization_name="Alpha Label",
                organization_slug="alpha-label",
                workos_organization_id="org_ALPHA",
                workspace_permission=WorkspacePermission.guest,
            ),
        ),
    )

    list_response = client.get(f"/api/v1/workspaces/{seeded.workspace_id}/profiles")
    direct_response = client.get(f"/api/v1/profiles/{seeded.member_profile_id}")

    assert list_response.status_code == 200
    profile_ids = {item["profile"]["id"] for item in list_response.json()["profiles"]}
    assert str(profile_id) in profile_ids
    assert str(seeded.member_profile_id) in profile_ids
    assert direct_response.status_code == 200
    assert direct_response.json()["id"] == str(seeded.member_profile_id)


def test_list_workspace_profiles_rechecks_removed_actor_workspace_membership(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, sessionmaker, seeded = profiles_client
    _set_context(client, seeded)

    async def remove_actor_membership() -> None:
        async with sessionmaker() as session:
            membership = await session.scalar(
                select(WorkspaceMembership)
                .join(WorkspaceMembership.profile)
                .where(UniversalProfile.user_id == seeded.user_id)
                .where(WorkspaceMembership.workspace_id == seeded.workspace_id)
            )
            assert membership is not None
            membership.status = "removed"
            await session.commit()

    asyncio.run(remove_actor_membership())

    response = client.get(f"/api/v1/workspaces/{seeded.workspace_id}/profiles")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_list_workspace_profiles_returns_only_workspace_members(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, _sessionmaker, seeded = profiles_client
    _set_context(client, seeded)

    response = client.get(f"/api/v1/workspaces/{seeded.workspace_id}/profiles")

    assert response.status_code == 200
    body = response.json()
    profile_ids = {item["profile"]["id"] for item in body["profiles"]}
    assert body["total"] == 2
    assert profile_ids == {str(seeded.profile_id), str(seeded.member_profile_id)}
    assert str(seeded.outside_profile_id) not in profile_ids


def test_list_workspace_profiles_excludes_inactive_workspace_memberships(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, sessionmaker, seeded = profiles_client

    async def deactivate_member_workspace_membership() -> None:
        async with sessionmaker() as session:
            membership = await session.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.profile_id == seeded.member_profile_id,
                    WorkspaceMembership.workspace_id == seeded.workspace_id,
                )
            )
            assert membership is not None
            membership.status = "removed"
            await session.commit()

    asyncio.run(deactivate_member_workspace_membership())
    _set_context(client, seeded)

    response = client.get(f"/api/v1/workspaces/{seeded.workspace_id}/profiles")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["profile"]["id"] for item in body["profiles"]] == [
        str(seeded.profile_id)
    ]


def test_list_workspace_people_directory_returns_safe_paginated_entries(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, sessionmaker, seeded = profiles_client

    async def seed_directory_metadata() -> None:
        async with sessionmaker() as session:
            member_profile = await session.get(
                UniversalProfile, seeded.member_profile_id
            )
            member_membership = await session.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.profile_id == seeded.member_profile_id,
                    WorkspaceMembership.workspace_id == seeded.workspace_id,
                )
            )
            assert member_profile is not None
            assert member_membership is not None
            assert member_membership.organization_membership_id is not None
            member_profile.headline = "Digital marketing lead"
            member_profile.biography = "Sensitive internal biography"
            marketing_role = Role(
                key="marketing-lead",
                display_name="Marketing Lead",
                description="Leads marketing campaigns.",
            )
            campaigns = Department(
                slug="campaigns",
                display_name="Campaigns",
                description="Campaign planning.",
            )
            session.add_all([marketing_role, campaigns])
            await session.flush()
            session.add_all(
                [
                    WorkspaceMembershipRole(
                        workspace_membership=member_membership,
                        role=marketing_role,
                    ),
                    MembershipDepartmentAccess(
                        membership_id=member_membership.organization_membership_id,
                        department=campaigns,
                        access_level="member",
                        source="test",
                    ),
                ]
            )
            await session.commit()

    asyncio.run(seed_directory_metadata())
    _set_context(client, seeded)

    response = client.get(
        f"/api/v1/workspaces/{seeded.workspace_id}/people?limit=1&offset=0"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert body["total"] == 2
    assert len(body["people"]) == 1
    person = body["people"][0]
    assert person["profile_id"] == str(seeded.member_profile_id)
    assert person["display_name"] == "Member Profile"
    assert person["headline"] == "Digital marketing lead"
    assert person["roles"] == ["marketing-lead", "member"]
    assert person["departments"] == ["campaigns"]
    assert person["profile_modules"] == ["universal"]
    assert person["artist_profile_id"] is None
    assert person["membership_status"] == "active"
    assert "biography" not in person
    assert "primary_email" not in response.text
    assert "member@example.com" not in response.text
    assert "Sensitive internal biography" not in response.text


def test_list_workspace_people_directory_marks_artist_profile_module(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, sessionmaker, seeded = profiles_client

    async def seed_artist_module() -> UUID:
        async with sessionmaker() as session:
            workspace = await session.get(Organization, seeded.workspace_id)
            member_profile = await session.get(
                UniversalProfile, seeded.member_profile_id
            )
            assert workspace is not None
            assert member_profile is not None
            artist = Artist(name="Member Artist", organization=workspace)
            session.add(artist)
            await session.flush()
            artist_profile = ArtistProfile(
                artist=artist,
                universal_profile=member_profile,
                stage_name="Member Artist",
                dsp_links={"spotify": "https://open.spotify.com/artist/member"},
            )
            session.add(artist_profile)
            await session.commit()
            return artist_profile.id

    artist_profile_id = asyncio.run(seed_artist_module())
    _set_context(client, seeded)

    response = client.get(
        f"/api/v1/workspaces/{seeded.workspace_id}/people?query=Member"
    )

    assert response.status_code == 200
    people = response.json()["people"]
    assert len(people) == 1
    assert people[0]["profile_id"] == str(seeded.member_profile_id)
    assert people[0]["profile_modules"] == ["artist"]
    assert people[0]["artist_profile_id"] == str(artist_profile_id)


def test_list_workspace_people_directory_searches_name_role_and_department(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, sessionmaker, seeded = profiles_client

    async def seed_search_metadata() -> None:
        async with sessionmaker() as session:
            member_membership = await session.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.profile_id == seeded.member_profile_id,
                    WorkspaceMembership.workspace_id == seeded.workspace_id,
                )
            )
            assert member_membership is not None
            assert member_membership.organization_membership_id is not None
            legal_role = Role(
                key="legal-reviewer",
                display_name="Legal Reviewer",
                description="Reviews legal work.",
            )
            legal_department = Department(
                slug="contracts",
                display_name="Contracts",
                description="Contracts department.",
            )
            session.add_all([legal_role, legal_department])
            await session.flush()
            session.add_all(
                [
                    WorkspaceMembershipRole(
                        workspace_membership=member_membership,
                        role=legal_role,
                    ),
                    MembershipDepartmentAccess(
                        membership_id=member_membership.organization_membership_id,
                        department=legal_department,
                        access_level="member",
                        source="test",
                    ),
                ]
            )
            await session.commit()

    asyncio.run(seed_search_metadata())
    _set_context(client, seeded)

    name_response = client.get(
        f"/api/v1/workspaces/{seeded.workspace_id}/people?query=Owner"
    )
    role_response = client.get(
        f"/api/v1/workspaces/{seeded.workspace_id}/people?query=Legal"
    )
    department_response = client.get(
        f"/api/v1/workspaces/{seeded.workspace_id}/people?query=Contracts"
    )

    assert name_response.status_code == 200
    assert role_response.status_code == 200
    assert department_response.status_code == 200
    assert [item["profile_id"] for item in name_response.json()["people"]] == [
        str(seeded.profile_id)
    ]
    assert [item["profile_id"] for item in role_response.json()["people"]] == [
        str(seeded.member_profile_id)
    ]
    assert [item["profile_id"] for item in department_response.json()["people"]] == [
        str(seeded.member_profile_id)
    ]


def test_list_workspace_people_directory_requires_workspace_membership(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, _sessionmaker, seeded = profiles_client
    _set_context(client, seeded)

    response = client.get(f"/api/v1/workspaces/{seeded.outside_workspace_id}/people")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_get_workspace_profile_requires_profile_in_workspace(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, _sessionmaker, seeded = profiles_client
    _set_context(client, seeded)

    response = client.get(
        f"/api/v1/workspaces/{seeded.workspace_id}/profiles/"
        f"{seeded.outside_profile_id}"
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_direct_profile_read_hides_profiles_without_shared_workspace(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, _sessionmaker, seeded = profiles_client
    _set_context(client, seeded)

    response = client.get(f"/api/v1/profiles/{seeded.outside_profile_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_direct_profile_read_allows_shared_workspace_member(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, _sessionmaker, seeded = profiles_client
    _set_context(client, seeded)

    response = client.get(f"/api/v1/profiles/{seeded.member_profile_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(seeded.member_profile_id)
    assert body["slug"] == "member-profile"
    assert body["display_name"] == "Member Profile"
    assert body["headline"] == "Member headline"
    assert body["user_id"] is None
    assert body["first_name"] is None
    assert body["last_name"] is None
    assert body["biography"] is None
    assert body["timezone"] is None
    assert body["primary_email"] is None
    assert body["profile_status"] is None
    assert body["onboarding_status"] is None
    assert body["links"] == []
    assert body["attributes"] == []
    assert body["profile_completion"] is None
    assert body["preferences"]["locale"] is None
    assert body["preferences"]["interface_theme"] is None
    assert body["preferences"]["email_notifications_enabled"] is True
    assert body["preferences"]["notification_preferences"] == {}
    assert "member@example.com" not in response.text
    assert "Member private biography" not in response.text
    assert "https://member.example.com/private" not in response.text
    assert "Sensitive member attribute" not in response.text


def test_direct_profile_read_requires_database_profile_view_capability(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, sessionmaker, seeded = profiles_client
    asyncio.run(
        _set_workspace_permission(
            sessionmaker,
            user_id=seeded.user_id,
            workspace_id=seeded.workspace_id,
            permission=WorkspacePermission.guest,
        )
    )
    _set_context(
        client,
        seeded,
        memberships=(
            MembershipContext(
                organization_id=seeded.workspace_id,
                organization_name="Alpha Label",
                organization_slug="alpha-label",
                workos_organization_id="org_ALPHA",
                workspace_permission=WorkspacePermission.owner,
            ),
        ),
    )

    response = client.get(f"/api/v1/profiles/{seeded.member_profile_id}")

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient capability permission"}


def test_direct_profile_read_rechecks_removed_actor_workspace_membership(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, sessionmaker, seeded = profiles_client
    _set_context(client, seeded)

    async def remove_actor_membership() -> None:
        async with sessionmaker() as session:
            membership = await session.scalar(
                select(WorkspaceMembership)
                .join(WorkspaceMembership.profile)
                .where(UniversalProfile.user_id == seeded.user_id)
                .where(WorkspaceMembership.workspace_id == seeded.workspace_id)
            )
            assert membership is not None
            membership.status = "removed"
            await session.commit()

    asyncio.run(remove_actor_membership())

    response = client.get(f"/api/v1/profiles/{seeded.member_profile_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_get_workspace_profile_returns_membership_context(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, _sessionmaker, seeded = profiles_client
    _set_context(client, seeded)

    response = client.get(
        f"/api/v1/workspaces/{seeded.workspace_id}/profiles/{seeded.member_profile_id}"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["workspace_id"] == str(seeded.workspace_id)
    assert body["profile"]["id"] == str(seeded.member_profile_id)
    assert body["role"] == "member"
    assert body["status"] == "active"
    assert body["profile"]["user_id"] is None
    assert body["profile"]["first_name"] is None
    assert body["profile"]["last_name"] is None
    assert body["profile"]["biography"] is None
    assert body["profile"]["timezone"] is None
    assert body["profile"]["primary_email"] is None
    assert body["profile"]["profile_status"] is None
    assert body["profile"]["onboarding_status"] is None
    assert body["profile"]["links"] == []
    assert body["profile"]["attributes"] == []
    assert body["profile"]["profile_completion"] is None
    assert body["profile"]["preferences"]["locale"] is None
    assert body["profile"]["preferences"]["interface_theme"] is None
    assert body["profile"]["preferences"]["email_notifications_enabled"] is True
    assert "member@example.com" not in response.text
    assert "Member private biography" not in response.text
    assert "https://member.example.com/private" not in response.text
    assert "Sensitive member attribute" not in response.text


def test_workspace_profile_view_allows_admin_profile_capability(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, sessionmaker, seeded = profiles_client
    asyncio.run(
        _set_workspace_permission(
            sessionmaker,
            user_id=seeded.user_id,
            workspace_id=seeded.workspace_id,
            permission=WorkspacePermission.admin,
        )
    )
    _set_context(
        client,
        seeded,
        memberships=(
            MembershipContext(
                organization_id=seeded.workspace_id,
                organization_name="Alpha Label",
                organization_slug="alpha-label",
                workos_organization_id="org_ALPHA",
                workspace_permission=WorkspacePermission.admin,
            ),
        ),
    )

    response = client.get(f"/api/v1/workspaces/{seeded.workspace_id}/profiles")

    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_workspace_profile_view_unions_multiple_roles(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, sessionmaker, seeded = profiles_client
    asyncio.run(
        _set_workspace_permission(
            sessionmaker,
            user_id=seeded.member_user_id,
            workspace_id=seeded.workspace_id,
            permission=WorkspacePermission.guest,
        )
    )
    asyncio.run(
        _grant_workspace_role(
            sessionmaker,
            profile_id=seeded.member_profile_id,
            workspace_id=seeded.workspace_id,
            role_key="release_editor",
            capability_keys=("release.edit",),
        )
    )
    asyncio.run(
        _grant_workspace_role(
            sessionmaker,
            profile_id=seeded.member_profile_id,
            workspace_id=seeded.workspace_id,
            role_key="profile_reader",
            capability_keys=("profile.view",),
        )
    )
    _set_context(
        client,
        seeded,
        user_id=seeded.member_user_id,
        email="member@example.com",
        display_name="Member",
        memberships=(
            MembershipContext(
                organization_id=seeded.workspace_id,
                organization_name="Alpha Label",
                organization_slug="alpha-label",
                workos_organization_id="org_ALPHA",
                workspace_permission=WorkspacePermission.guest,
            ),
        ),
    )

    response = client.get(f"/api/v1/profiles/{seeded.profile_id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(seeded.profile_id)


def test_workspace_switch_resolves_different_profile_context_without_duplication(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, sessionmaker, seeded = profiles_client

    async def seed_second_workspace() -> UUID:
        async with sessionmaker() as session:
            owner = await session.get(User, seeded.user_id)
            assert owner is not None
            alpha_membership = await session.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.profile_id == seeded.profile_id,
                    WorkspaceMembership.workspace_id == seeded.workspace_id,
                )
            )
            assert alpha_membership is not None
            assert alpha_membership.organization_membership_id is not None
            beta_workspace = Organization(
                name="Beta Label",
                slug="beta-label",
                owner=owner,
                workos_organization_id="org_BETA",
            )
            beta_org_membership = OrganizationMembership(
                organization=beta_workspace,
                user=owner,
                role=MembershipRole.member,
                workspace_permission=WorkspacePermission.member,
                status="active",
            )
            beta_membership = WorkspaceMembership(
                workspace=beta_workspace,
                profile_id=seeded.profile_id,
                organization_membership=beta_org_membership,
                status="active",
            )
            artist_role = Role(
                key="artist",
                display_name="Artist",
                description="Artist role.",
            )
            legal_role = Role(
                key="legal",
                display_name="Legal",
                description="Legal role.",
            )
            artist_view = Capability(
                key="artist.profile.view",
                display_name="View artists",
                description="View artists.",
            )
            contract_view = Capability(
                key="contract.view",
                display_name="View contracts",
                description="View contracts.",
            )
            creative = Department(
                slug="creative",
                display_name="Creative",
                description="Creative department.",
            )
            contracts = Department(
                slug="contracts",
                display_name="Contracts",
                description="Contracts department.",
            )
            session.add_all(
                [
                    beta_workspace,
                    beta_org_membership,
                    beta_membership,
                    artist_role,
                    legal_role,
                    artist_view,
                    contract_view,
                    creative,
                    contracts,
                ]
            )
            await session.flush()
            session.add_all(
                [
                    RoleCapability(role=artist_role, capability=artist_view),
                    RoleCapability(role=legal_role, capability=contract_view),
                    WorkspaceMembershipRole(
                        workspace_membership=alpha_membership,
                        role=artist_role,
                    ),
                    WorkspaceMembershipRole(
                        workspace_membership=beta_membership,
                        role=legal_role,
                    ),
                    MembershipDepartmentAccess(
                        membership_id=alpha_membership.organization_membership_id,
                        department=creative,
                        access_level="member",
                        source="test",
                    ),
                    MembershipDepartmentAccess(
                        membership=beta_org_membership,
                        department=contracts,
                        access_level="member",
                        source="test",
                    ),
                ]
            )
            await session.commit()
            return beta_workspace.id

    beta_workspace_id = asyncio.run(seed_second_workspace())
    _set_context(
        client,
        seeded,
        memberships=(
            MembershipContext(
                organization_id=seeded.workspace_id,
                organization_name="Alpha Label",
                organization_slug="alpha-label",
                workos_organization_id="org_ALPHA",
                workspace_permission=WorkspacePermission.owner,
            ),
            MembershipContext(
                organization_id=beta_workspace_id,
                organization_name="Beta Label",
                organization_slug="beta-label",
                workos_organization_id="org_BETA",
                workspace_permission=WorkspacePermission.member,
            ),
        ),
    )

    alpha_response = client.get(
        f"/api/v1/workspaces/{seeded.workspace_id}/profiles/{seeded.profile_id}"
    )
    beta_response = client.get(
        f"/api/v1/workspaces/{beta_workspace_id}/profiles/{seeded.profile_id}"
    )

    assert alpha_response.status_code == 200
    assert beta_response.status_code == 200
    alpha = alpha_response.json()
    beta = beta_response.json()
    assert alpha["profile"]["id"] == beta["profile"]["id"] == str(seeded.profile_id)
    assert alpha["workspace_id"] == str(seeded.workspace_id)
    assert beta["workspace_id"] == str(beta_workspace_id)
    assert alpha["workspace_roles"] == ["artist"]
    assert beta["workspace_roles"] == ["legal"]
    assert alpha["department_access"] == ["creative"]
    assert beta["department_access"] == ["contracts"]
    assert alpha["capability_permissions"] == ["artist.profile.view"]
    assert beta["capability_permissions"] == ["contract.view"]


def test_artist_role_can_view_and_edit_linked_artist_profile(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, sessionmaker, seeded = profiles_client
    _artist_id, artist_profile_id = asyncio.run(
        _seed_artist_profile_for_member(sessionmaker, seeded)
    )
    asyncio.run(
        _set_workspace_permission(
            sessionmaker,
            user_id=seeded.member_user_id,
            workspace_id=seeded.workspace_id,
            permission=WorkspacePermission.guest,
        )
    )
    asyncio.run(
        _grant_workspace_role(
            sessionmaker,
            profile_id=seeded.member_profile_id,
            workspace_id=seeded.workspace_id,
            role_key="artist",
            capability_keys=("artist.profile.view", "artist.profile.edit"),
            departments=("artist",),
        )
    )
    _set_context(
        client,
        seeded,
        user_id=seeded.member_user_id,
        email="member@example.com",
        display_name="Member",
        memberships=(
            MembershipContext(
                organization_id=seeded.workspace_id,
                organization_name="Alpha Label",
                organization_slug="alpha-label",
                workos_organization_id="org_ALPHA",
                workspace_permission=WorkspacePermission.guest,
            ),
        ),
    )

    view_response = client.get(
        f"/api/v1/workspaces/{seeded.workspace_id}/artist-profiles/"
        f"{artist_profile_id}"
    )
    update_response = client.patch(
        f"/api/v1/workspaces/{seeded.workspace_id}/artist-profiles/"
        f"{artist_profile_id}",
        json={"stage_name": "Updated Member Artist"},
    )

    assert view_response.status_code == 200
    assert view_response.json()["id"] == str(artist_profile_id)
    assert update_response.status_code == 200
    assert update_response.json()["stage_name"] == "Updated Member Artist"


def test_artist_profile_create_requires_create_capability(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, sessionmaker, seeded = profiles_client

    async def seed_unlinked_artist() -> UUID:
        async with sessionmaker() as session:
            workspace = await session.get(Organization, seeded.workspace_id)
            assert workspace is not None
            artist = Artist(name="New Artist", organization=workspace)
            session.add(artist)
            await session.commit()
            return artist.id

    artist_id = asyncio.run(seed_unlinked_artist())
    asyncio.run(
        _set_workspace_permission(
            sessionmaker,
            user_id=seeded.member_user_id,
            workspace_id=seeded.workspace_id,
            permission=WorkspacePermission.guest,
        )
    )
    asyncio.run(
        _grant_workspace_role(
            sessionmaker,
            profile_id=seeded.member_profile_id,
            workspace_id=seeded.workspace_id,
            role_key="artist_editor_only",
            capability_keys=("artist.profile.edit",),
            departments=("a&r",),
        )
    )
    _set_context(
        client,
        seeded,
        user_id=seeded.member_user_id,
        email="member@example.com",
        display_name="Member",
        memberships=(
            MembershipContext(
                organization_id=seeded.workspace_id,
                organization_name="Alpha Label",
                organization_slug="alpha-label",
                workos_organization_id="org_ALPHA",
                workspace_permission=WorkspacePermission.guest,
            ),
        ),
    )

    denied_response = client.post(
        f"/api/v1/workspaces/{seeded.workspace_id}/artist-profiles",
        json={
            "artist_id": str(artist_id),
            "universal_profile_id": str(seeded.member_profile_id),
            "stage_name": "New Artist",
        },
    )

    assert denied_response.status_code == 403
    assert denied_response.json() == {"detail": "Insufficient capability permission"}


def test_profile_openapi_contract_exposes_stable_response_fields(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, _sessionmaker, _seeded = profiles_client

    schema = client.get("/openapi.json").json()
    profile_schema = schema["components"]["schemas"]["ProfileResponse"]
    preference_schema = schema["components"]["schemas"]["ProfilePreferencesResponse"]

    assert set(profile_schema["properties"]) == {
        "id",
        "user_id",
        "slug",
        "first_name",
        "last_name",
        "display_name",
        "headline",
        "biography",
        "avatar_url",
        "location",
        "timezone",
        "primary_email",
        "profile_status",
        "onboarding_status",
        "links",
        "attributes",
        "preferences",
        "profile_completion",
    }
    assert set(preference_schema["properties"]) == {
        "locale",
        "timezone",
        "default_workspace_id",
        "email_notifications_enabled",
        "push_notifications_enabled",
        "sms_notifications_enabled",
        "marketing_notifications_enabled",
        "interface_theme",
        "interface_density",
        "notification_preferences",
        "interface_preferences",
        "integration_preferences",
    }


def test_artist_profile_openapi_contract_exposes_module_response_fields(
    profiles_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededProfiles,
    ],
) -> None:
    client, _sessionmaker, _seeded = profiles_client

    schema = client.get("/openapi.json").json()
    artist_profile_create_schema = schema["components"]["schemas"][
        "ArtistProfileCreateRequest"
    ]
    artist_profile_schema = schema["components"]["schemas"]["ArtistProfileResponse"]
    artist_profile_detail_schema = schema["components"]["schemas"][
        "ArtistProfileDetailResponse"
    ]

    assert set(artist_profile_create_schema["properties"]) == {
        "artist_id",
        "universal_profile_id",
        "stage_name",
        "genres",
        "influences",
        "imagery",
        "dsp_links",
        "catalog_references",
        "creative_metadata",
        "career_stage",
        "audience",
        "preferences",
    }
    assert set(artist_profile_create_schema["required"]) == {
        "artist_id",
        "universal_profile_id",
    }
    assert set(artist_profile_schema["properties"]) == {
        "id",
        "artist_id",
        "universal_profile_id",
        "stage_name",
        "genres",
        "influences",
        "imagery",
        "dsp_links",
        "catalog_references",
        "creative_metadata",
        "career_stage",
        "audience",
        "preferences",
    }
    assert set(artist_profile_detail_schema["properties"]) == {
        "id",
        "artist_id",
        "workspace_id",
        "universal_profile_id",
        "artist_name",
        "stage_name",
        "genres",
        "influences",
        "imagery",
        "dsp_links",
        "catalog_references",
        "creative_metadata",
        "career_stage",
        "audience",
        "preferences",
    }
