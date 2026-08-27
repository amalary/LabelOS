import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from labelos_database.base import Base
from labelos_database.models import (
    Artist,
    Campaign,
    CampaignStatus,
    CampaignType,
    Department,
    MembershipDepartmentAccess,
    MembershipRole,
    Organization,
    OrganizationMembership,
    Release,
    UniversalProfile,
    User,
    WorkspaceMembership,
    WorkspacePermission,
)
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
class SeededCampaignApi:
    owner_user_id: UUID
    viewer_user_id: UUID
    workspace_id: UUID
    outside_workspace_id: UUID
    owner_profile_id: UUID
    member_profile_id: UUID
    viewer_profile_id: UUID
    outside_profile_id: UUID
    owner_workspace_membership_id: UUID
    member_workspace_membership_id: UUID
    outside_workspace_membership_id: UUID
    artist_id: UUID
    outside_artist_id: UUID
    release_id: UUID
    outside_release_id: UUID
    campaign_id: UUID
    outside_campaign_id: UUID


@pytest.fixture
def campaigns_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, async_sessionmaker[AsyncSession], SeededCampaignApi]]:
    monkeypatch.setenv("APP_ENV", "test")
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def prepare_database() -> SeededCampaignApi:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with sessionmaker() as session:
            owner = User(email="campaign-owner@example.com", display_name="Owner")
            viewer = User(email="campaign-viewer@example.com", display_name="Viewer")
            outside_owner = User(
                email="outside-campaign-owner@example.com",
                display_name="Outside Owner",
            )
            workspace = Organization(
                name="Alpha Label",
                slug="alpha-campaign-api",
                owner=owner,
                workos_organization_id="org_ALPHA_CAMPAIGN",
            )
            outside_workspace = Organization(
                name="Beta Label",
                slug="beta-campaign-api",
                owner=outside_owner,
                workos_organization_id="org_BETA_CAMPAIGN",
            )
            owner_membership = OrganizationMembership(
                organization=workspace,
                user=owner,
                role=MembershipRole.owner,
                workspace_permission=WorkspacePermission.owner,
            )
            viewer_membership = OrganizationMembership(
                organization=workspace,
                user=viewer,
                role=MembershipRole.guest,
                workspace_permission=WorkspacePermission.guest,
            )
            marketing_department = Department(
                slug="marketing",
                display_name="Marketing",
                description="Marketing department.",
            )
            outside_membership = OrganizationMembership(
                organization=outside_workspace,
                user=outside_owner,
                role=MembershipRole.owner,
                workspace_permission=WorkspacePermission.owner,
            )
            owner_profile = UniversalProfile(
                user=owner,
                slug="campaign-owner",
                display_name="Campaign Owner",
            )
            member_profile = UniversalProfile(
                user=User(email="campaign-member@example.com"),
                slug="campaign-member",
                display_name="Campaign Member",
            )
            viewer_profile = UniversalProfile(
                user=viewer,
                slug="campaign-viewer",
                display_name="Campaign Viewer",
            )
            outside_profile = UniversalProfile(
                user=outside_owner,
                slug="outside-campaign-owner",
                display_name="Outside Campaign Owner",
            )
            owner_workspace_membership = WorkspaceMembership(
                workspace=workspace,
                profile=owner_profile,
                organization_membership=owner_membership,
                status="active",
            )
            member_workspace_membership = WorkspaceMembership(
                workspace=workspace,
                profile=member_profile,
                status="active",
            )
            viewer_workspace_membership = WorkspaceMembership(
                workspace=workspace,
                profile=viewer_profile,
                organization_membership=viewer_membership,
                status="active",
            )
            outside_workspace_membership = WorkspaceMembership(
                workspace=outside_workspace,
                profile=outside_profile,
                organization_membership=outside_membership,
                status="active",
            )
            artist = Artist(name="Alpha Artist", organization=workspace)
            outside_artist = Artist(
                name="Outside Artist",
                organization=outside_workspace,
            )
            release = Release(
                title="Alpha Single",
                organization=workspace,
                artist=artist,
            )
            outside_release = Release(
                title="Outside Single",
                organization=outside_workspace,
                artist=outside_artist,
            )
            campaign = Campaign(
                name="Existing Campaign",
                organization=workspace,
                campaign_type=CampaignType.marketing,
                status=CampaignStatus.draft,
                primary_artist=artist,
                release=release,
            )
            outside_campaign = Campaign(
                name="Outside Campaign",
                organization=outside_workspace,
                primary_artist=outside_artist,
                release=outside_release,
            )
            session.add_all(
                [
                    marketing_department,
                    owner_workspace_membership,
                    member_workspace_membership,
                    viewer_workspace_membership,
                    outside_workspace_membership,
                    release,
                    outside_release,
                    campaign,
                    outside_campaign,
                ]
            )
            session.add(
                MembershipDepartmentAccess(
                    membership=viewer_membership,
                    department=marketing_department,
                    access_level="member",
                    source="test",
                )
            )
            await session.commit()
            return SeededCampaignApi(
                owner_user_id=owner.id,
                viewer_user_id=viewer.id,
                workspace_id=workspace.id,
                outside_workspace_id=outside_workspace.id,
                owner_profile_id=owner_profile.id,
                member_profile_id=member_profile.id,
                viewer_profile_id=viewer_profile.id,
                outside_profile_id=outside_profile.id,
                owner_workspace_membership_id=owner_workspace_membership.id,
                member_workspace_membership_id=member_workspace_membership.id,
                outside_workspace_membership_id=outside_workspace_membership.id,
                artist_id=artist.id,
                outside_artist_id=outside_artist.id,
                release_id=release.id,
                outside_release_id=outside_release.id,
                campaign_id=campaign.id,
                outside_campaign_id=outside_campaign.id,
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
    seeded: SeededCampaignApi,
    *,
    user_id: UUID | None = None,
    email: str = "campaign-owner@example.com",
    display_name: str = "Owner",
    workspace_permission: WorkspacePermission = WorkspacePermission.owner,
    memberships: tuple[MembershipContext, ...] | None = None,
) -> None:
    async def override_context() -> CurrentUserContext:
        return CurrentUserContext(
            user=User(
                id=user_id or seeded.owner_user_id,
                email=email,
                display_name=display_name,
            ),
            principal=AuthenticatedPrincipal(
                provider="workos",
                subject=f"user_{user_id or seeded.owner_user_id}",
                session_id="session_SECRET",
                email=email,
                display_name=display_name,
                organization_id="org_ALPHA_CAMPAIGN",
                role=workspace_permission.value,
                roles=(workspace_permission.value,),
            ),
            memberships=memberships
            or (
                MembershipContext(
                    organization_id=seeded.workspace_id,
                    organization_name="Alpha Label",
                    organization_slug="alpha-campaign-api",
                    workos_organization_id="org_ALPHA_CAMPAIGN",
                    workspace_permission=workspace_permission,
                ),
            ),
        )

    client.app.dependency_overrides[get_current_user_context] = override_context


def test_campaigns_require_authentication(client: TestClient) -> None:
    response = client.get(f"/api/v1/workspaces/{uuid4()}/campaigns")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_campaign_api_supports_core_workflow_and_normalized_relationships(
    campaigns_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededCampaignApi,
    ],
) -> None:
    client, _sessionmaker, seeded = campaigns_client
    _set_context(client, seeded)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/campaigns"

    created = client.post(
        base,
        json={
            "name": "Launch Campaign",
            "description": "Audience launch plan",
            "campaign_type": "release",
            "status": "planning",
            "owner_profile_id": str(seeded.member_profile_id),
            "primary_artist_id": str(seeded.artist_id),
            "release_id": str(seeded.release_id),
        },
    )
    assert created.status_code == 201
    campaign = created.json()
    campaign_id = campaign["id"]
    assert campaign["workspace_id"] == str(seeded.workspace_id)
    assert campaign["created_by_user_id"] == str(seeded.owner_user_id)
    assert campaign["created_by_profile_id"] == str(seeded.owner_profile_id)
    assert campaign["primary_artist"] == {
        "id": str(seeded.artist_id),
        "name": "Alpha Artist",
    }
    assert campaign["release"]["title"] == "Alpha Single"

    member = client.put(
        f"{base}/{campaign_id}/members",
        json={
            "workspace_membership_id": str(seeded.member_workspace_membership_id),
            "participation_status": "confirmed",
        },
    )
    artist = client.put(
        f"{base}/{campaign_id}/artists",
        json={
            "artist_id": str(seeded.artist_id),
            "relationship_kind": "primary",
            "sort_order": 1,
        },
    )
    release = client.put(
        f"{base}/{campaign_id}/releases",
        json={
            "release_id": str(seeded.release_id),
            "relationship_kind": "focus",
        },
    )
    assert member.status_code == 200
    assert member.json()["display_name"] == "Campaign Member"
    assert artist.status_code == 200
    assert artist.json()["artist"]["name"] == "Alpha Artist"
    assert release.status_code == 200
    assert release.json()["release"]["title"] == "Alpha Single"

    updated = client.patch(f"{base}/{campaign_id}", json={"name": "Updated Launch"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Updated Launch"

    activated = client.patch(f"{base}/{campaign_id}/status", json={"status": "active"})
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"

    listed = client.get(base)
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 2
    created_record = next(
        item for item in body["campaigns"] if item["id"] == campaign_id
    )
    assert created_record["members"][0]["participation_status"] == "confirmed"
    assert created_record["artists"][0]["relationship_kind"] == "primary"
    assert created_record["releases"][0]["relationship_kind"] == "focus"

    archived = client.post(f"{base}/{campaign_id}/archive")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"


def test_campaign_api_returns_clear_errors_for_scope_capability_and_state(
    campaigns_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededCampaignApi,
    ],
) -> None:
    client, _sessionmaker, seeded = campaigns_client
    _set_context(client, seeded)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/campaigns"

    outside_campaign = client.get(f"{base}/{seeded.outside_campaign_id}")
    invalid_artist = client.put(
        f"{base}/{seeded.campaign_id}/artists",
        json={"artist_id": str(seeded.outside_artist_id)},
    )
    invalid_release = client.put(
        f"{base}/{seeded.campaign_id}/releases",
        json={"release_id": str(seeded.outside_release_id)},
    )
    invalid_member = client.put(
        f"{base}/{seeded.campaign_id}/members",
        json={"workspace_membership_id": str(seeded.outside_workspace_membership_id)},
    )
    invalid_transition = client.patch(
        f"{base}/{seeded.campaign_id}/status",
        json={"status": "active"},
    )

    assert outside_campaign.status_code == 404
    assert invalid_artist.status_code == 400
    assert "artist must belong" in invalid_artist.json()["detail"]
    assert invalid_release.status_code == 400
    assert "release must belong" in invalid_release.json()["detail"]
    assert invalid_member.status_code == 400
    assert "workspace membership must belong" in invalid_member.json()["detail"]
    assert invalid_transition.status_code == 409
    assert "Cannot transition" in invalid_transition.json()["detail"]

    _set_context(
        client,
        seeded,
        user_id=seeded.viewer_user_id,
        email="campaign-viewer@example.com",
        display_name="Viewer",
        workspace_permission=WorkspacePermission.guest,
    )
    denied = client.get(base)
    assert denied.status_code == 403
    assert denied.json() == {"detail": "Insufficient capability permission"}

    _set_context(
        client,
        seeded,
        memberships=(
            MembershipContext(
                organization_id=seeded.workspace_id,
                organization_name="Alpha Label",
                organization_slug="alpha-campaign-api",
                workos_organization_id="org_ALPHA_CAMPAIGN",
                workspace_permission=WorkspacePermission.owner,
            ),
        ),
    )
    cross_workspace = client.get(
        f"/api/v1/workspaces/{seeded.outside_workspace_id}/campaigns"
    )
    assert cross_workspace.status_code == 404
    assert cross_workspace.json() == {"detail": "Not found"}


def test_campaign_openapi_contract_exposes_stable_fields(
    campaigns_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededCampaignApi,
    ],
) -> None:
    client, _sessionmaker, _seeded = campaigns_client

    schema = client.get("/openapi.json").json()
    campaign_schema = schema["components"]["schemas"]["CampaignResponse"]
    create_schema = schema["components"]["schemas"]["CampaignCreateRequest"]

    assert set(create_schema["properties"]) == {
        "name",
        "description",
        "campaign_type",
        "status",
        "start_date",
        "target_end_date",
        "owner_profile_id",
        "primary_artist_id",
        "release_id",
    }
    assert set(campaign_schema["properties"]) == {
        "id",
        "workspace_id",
        "name",
        "description",
        "campaign_type",
        "status",
        "start_date",
        "target_end_date",
        "created_by_user_id",
        "created_by_profile_id",
        "owner_profile_id",
        "primary_artist",
        "release",
        "members",
        "artists",
        "releases",
        "created_at",
        "updated_at",
    }
