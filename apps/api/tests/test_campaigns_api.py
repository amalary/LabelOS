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
    CampaignMember,
    CampaignStatus,
    CampaignType,
    Department,
    MembershipDepartmentAccess,
    MembershipRole,
    Organization,
    OrganizationMembership,
    RealtimeEvent,
    Release,
    UniversalProfile,
    User,
    WorkspaceMembership,
    WorkspacePermission,
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
    viewer_workspace_membership_id: UUID
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
                viewer_workspace_membership_id=viewer_workspace_membership.id,
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


async def _grant_campaign_capabilities(
    sessionmaker: async_sessionmaker[AsyncSession],
    seeded: SeededCampaignApi,
    *capabilities: str,
) -> None:
    async with sessionmaker() as session:
        membership = await session.scalar(
            select(OrganizationMembership)
            .where(OrganizationMembership.organization_id == seeded.workspace_id)
            .where(OrganizationMembership.user_id == seeded.viewer_user_id)
        )
        assert membership is not None
        membership.capability_permissions = list(capabilities)
        await session.commit()


async def _add_viewer_to_campaign(
    sessionmaker: async_sessionmaker[AsyncSession],
    seeded: SeededCampaignApi,
) -> None:
    async with sessionmaker() as session:
        session.add(
            CampaignMember(
                campaign_id=seeded.campaign_id,
                workspace_membership_id=seeded.viewer_workspace_membership_id,
            )
        )
        await session.commit()


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
            "responsibility_label": "campaign lead",
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
    assert member.json()["responsibility_label"] == "campaign lead"
    assert member.json()["is_owner"] is True
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
    assert body["limit"] == 50
    assert body["offset"] == 0
    created_record = next(
        item for item in body["campaigns"] if item["id"] == campaign_id
    )
    assert created_record["members"][0]["participation_status"] == "confirmed"
    assert created_record["members"][0]["responsibility_label"] == "campaign lead"
    assert created_record["members"][0]["is_owner"] is True
    assert created_record["owner"] == {
        "profile_id": str(seeded.member_profile_id),
        "display_name": "Campaign Member",
    }
    assert created_record["artists"][0]["relationship_kind"] == "primary"
    assert created_record["releases"][0]["relationship_kind"] == "focus"

    archived = client.post(f"{base}/{campaign_id}/archive")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"


def test_campaign_list_supports_bounded_pagination(
    campaigns_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededCampaignApi,
    ],
) -> None:
    client, _sessionmaker, seeded = campaigns_client
    _set_context(client, seeded)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/campaigns"

    created = client.post(base, json={"name": "Paged Campaign"})
    assert created.status_code == 201

    first_page = client.get(base, params={"limit": 1, "offset": 0})
    second_page = client.get(base, params={"limit": 1, "offset": 1})
    invalid_page = client.get(base, params={"limit": 101})

    assert first_page.status_code == 200
    assert first_page.json()["total"] == 2
    assert first_page.json()["limit"] == 1
    assert first_page.json()["offset"] == 0
    assert len(first_page.json()["campaigns"]) == 1
    assert second_page.status_code == 200
    assert second_page.json()["total"] == 2
    assert second_page.json()["offset"] == 1
    assert len(second_page.json()["campaigns"]) == 1
    assert invalid_page.status_code == 422


def test_campaign_team_membership_changes_publish_activity_events(
    campaigns_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededCampaignApi,
    ],
) -> None:
    client, sessionmaker, seeded = campaigns_client
    _set_context(client, seeded)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/campaigns/{seeded.campaign_id}"

    added = client.put(
        f"{base}/members",
        json={
            "workspace_membership_id": str(seeded.member_workspace_membership_id),
            "participation_status": "active",
            "responsibility_label": "marketing lead",
        },
    )
    updated = client.put(
        f"{base}/members",
        json={
            "workspace_membership_id": str(seeded.member_workspace_membership_id),
            "participation_status": "active",
            "responsibility_label": "creative lead",
        },
    )
    removed = client.delete(
        f"{base}/members/{seeded.member_workspace_membership_id}",
    )

    assert added.status_code == 200
    assert updated.status_code == 200
    assert removed.status_code == 204

    records = asyncio.run(_realtime_events(sessionmaker, seeded.workspace_id))
    assert [record.event_type for record in records] == [
        "campaign.member_added",
        "campaign.member_updated",
        "campaign.member_removed",
    ]
    assert records[0].entity_type == "campaign"
    assert records[0].entity_id == str(seeded.campaign_id)
    assert records[0].actor_user_id == seeded.owner_user_id
    assert records[0].payload["displayName"] == "Campaign Member"
    assert records[1].payload["responsibilityLabel"] == "creative lead"


def test_campaign_mutations_publish_structured_activity_events(
    campaigns_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededCampaignApi,
    ],
) -> None:
    client, sessionmaker, seeded = campaigns_client
    _set_context(client, seeded)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/campaigns"

    created = client.post(
        base,
        json={
            "name": "Evented Campaign",
            "campaign_type": "release",
            "status": "planning",
        },
    )
    assert created.status_code == 201
    campaign_id = created.json()["id"]

    updated = client.patch(
        f"{base}/{campaign_id}",
        json={"name": "Evented Campaign Updated"},
    )
    activated = client.patch(f"{base}/{campaign_id}/status", json={"status": "active"})
    artist = client.put(
        f"{base}/{campaign_id}/artists",
        json={"artist_id": str(seeded.artist_id), "relationship_kind": "primary"},
    )
    release = client.put(
        f"{base}/{campaign_id}/releases",
        json={"release_id": str(seeded.release_id), "relationship_kind": "focus"},
    )
    goal = client.post(f"{base}/{campaign_id}/goals", json={"title": "Reach fans"})
    goal_completed = client.patch(
        f"{base}/{campaign_id}/goals/{goal.json()['id']}",
        json={"status": "completed"},
    )
    milestone = client.post(
        f"{base}/{campaign_id}/milestones",
        json={"title": "Creative locked"},
    )
    milestone_completed = client.post(
        f"{base}/{campaign_id}/milestones/{milestone.json()['id']}/complete"
    )

    for response in (
        updated,
        activated,
        artist,
        release,
        goal,
        goal_completed,
        milestone,
        milestone_completed,
    ):
        assert response.status_code in {200, 201}

    records = [
        record
        for record in asyncio.run(_realtime_events(sessionmaker, seeded.workspace_id))
        if record.entity_id == campaign_id
    ]

    assert [record.event_type for record in records] == [
        "campaign.created",
        "campaign.updated",
        "campaign.status_changed",
        "campaign.artist_associated",
        "campaign.release_associated",
        "campaign.goal_created",
        "campaign.goal_completed",
        "campaign.milestone_created",
        "campaign.milestone_completed",
    ]
    assert all(record.entity_type == "campaign" for record in records)
    assert all(record.actor_user_id == seeded.owner_user_id for record in records)
    assert records[0].payload["campaignName"] == "Evented Campaign"
    assert records[1].payload["changedFields"] == "name"
    assert records[2].payload["previousStatus"] == "planning"
    assert records[2].payload["status"] == "active"
    assert records[3].payload["artistName"] == "Alpha Artist"
    assert records[4].payload["releaseTitle"] == "Alpha Single"
    assert records[7].payload["milestoneTitle"] == "Creative locked"


def test_campaign_activity_events_preserve_workspace_isolation(
    campaigns_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededCampaignApi,
    ],
) -> None:
    client, sessionmaker, seeded = campaigns_client
    _set_context(client, seeded)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/campaigns/{seeded.campaign_id}"

    invalid_artist = client.put(
        f"{base}/artists",
        json={"artist_id": str(seeded.outside_artist_id)},
    )
    invalid_release = client.put(
        f"{base}/releases",
        json={"release_id": str(seeded.outside_release_id)},
    )
    invalid_member = client.put(
        f"{base}/members",
        json={"workspace_membership_id": str(seeded.outside_workspace_membership_id)},
    )

    assert invalid_artist.status_code == 400
    assert invalid_release.status_code == 400
    assert invalid_member.status_code == 400
    assert asyncio.run(_realtime_events(sessionmaker, seeded.workspace_id)) == []
    assert (
        asyncio.run(_realtime_events(sessionmaker, seeded.outside_workspace_id)) == []
    )


def test_campaign_api_manages_goals_and_milestones(
    campaigns_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededCampaignApi,
    ],
) -> None:
    client, _sessionmaker, seeded = campaigns_client
    _set_context(client, seeded)
    base = f"/api/v1/workspaces/{seeded.workspace_id}/campaigns/{seeded.campaign_id}"

    created_goal = client.post(
        f"{base}/goals",
        json={
            "title": "Reach launch audience",
            "description": "Topline launch target",
            "target_value": "25000 streams",
            "success_criteria": "Hit target within first week",
        },
    )
    assert created_goal.status_code == 201
    goal = created_goal.json()
    assert goal["campaign_id"] == str(seeded.campaign_id)
    assert goal["status"] == "active"

    updated_goal = client.patch(
        f"{base}/goals/{goal['id']}",
        json={
            "title": "Reach first-week audience",
            "status": "at_risk",
        },
    )
    archived_goal = client.post(f"{base}/goals/{goal['id']}/archive")
    listed_goals = client.get(f"{base}/goals")

    assert updated_goal.status_code == 200
    assert updated_goal.json()["title"] == "Reach first-week audience"
    assert archived_goal.status_code == 200
    assert archived_goal.json()["status"] == "archived"
    assert listed_goals.status_code == 200
    assert listed_goals.json()["goals"][0]["id"] == goal["id"]

    created_milestone = client.post(
        f"{base}/milestones",
        json={
            "title": "Creative locked",
            "description": "Assets approved for rollout",
            "target_date": "2026-09-15",
        },
    )
    assert created_milestone.status_code == 201
    milestone = created_milestone.json()
    assert milestone["campaign_id"] == str(seeded.campaign_id)
    assert milestone["created_by_user_id"] == str(seeded.owner_user_id)

    updated_milestone = client.patch(
        f"{base}/milestones/{milestone['id']}",
        json={"target_date": "2026-09-20"},
    )
    completed_milestone = client.post(f"{base}/milestones/{milestone['id']}/complete")
    archived_milestone = client.post(f"{base}/milestones/{milestone['id']}/archive")
    listed_milestones = client.get(f"{base}/milestones")

    assert updated_milestone.status_code == 200
    assert updated_milestone.json()["target_date"] == "2026-09-20"
    assert completed_milestone.status_code == 200
    assert completed_milestone.json()["status"] == "completed"
    assert completed_milestone.json()["completed_at"] is not None
    assert archived_milestone.status_code == 200
    assert archived_milestone.json()["status"] == "archived"
    assert listed_milestones.status_code == 200
    assert listed_milestones.json()["milestones"][0]["id"] == milestone["id"]

    deleted_goal = client.delete(f"{base}/goals/{goal['id']}")
    deleted_milestone = client.delete(f"{base}/milestones/{milestone['id']}")

    assert deleted_goal.status_code == 204
    assert deleted_milestone.status_code == 204
    assert client.delete(f"{base}/goals/{goal['id']}").status_code == 404
    assert client.delete(f"{base}/milestones/{milestone['id']}").status_code == 404


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
    invalid_member_campaign = client.put(
        f"{base}/{seeded.outside_campaign_id}/members",
        json={"workspace_membership_id": str(seeded.member_workspace_membership_id)},
    )
    invalid_artist_campaign = client.put(
        f"{base}/{seeded.outside_campaign_id}/artists",
        json={"artist_id": str(seeded.artist_id)},
    )
    invalid_release_campaign = client.put(
        f"{base}/{seeded.outside_campaign_id}/releases",
        json={"release_id": str(seeded.release_id)},
    )
    invalid_goal_scope = client.get(
        f"{base}/{seeded.outside_campaign_id}/goals",
    )
    invalid_milestone_scope = client.post(
        f"{base}/{seeded.outside_campaign_id}/milestones",
        json={"title": "Blocked milestone"},
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
    assert invalid_member_campaign.status_code == 404
    assert invalid_artist_campaign.status_code == 404
    assert invalid_release_campaign.status_code == 404
    assert invalid_goal_scope.status_code == 404
    assert invalid_milestone_scope.status_code == 404
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


def test_campaign_api_allows_explicit_campaign_capability_grants(
    campaigns_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededCampaignApi,
    ],
) -> None:
    client, sessionmaker, seeded = campaigns_client
    asyncio.run(
        _grant_campaign_capabilities(
            sessionmaker,
            seeded,
            "marketing.campaign.view",
            "marketing.campaign.create",
            "marketing.campaign.edit",
            "marketing.campaign.approve",
        )
    )
    _set_context(
        client,
        seeded,
        user_id=seeded.viewer_user_id,
        email="campaign-viewer@example.com",
        display_name="Viewer",
        workspace_permission=WorkspacePermission.guest,
    )
    base = f"/api/v1/workspaces/{seeded.workspace_id}/campaigns"

    listed = client.get(base)
    created = client.post(base, json={"name": "Viewer Created Campaign"})
    campaign_id = created.json()["id"]
    updated = client.patch(f"{base}/{campaign_id}", json={"name": "Viewer Updated"})
    planned = client.patch(f"{base}/{campaign_id}/status", json={"status": "planning"})
    archived = client.post(f"{base}/{campaign_id}/archive")

    assert listed.status_code == 200
    assert created.status_code == 201
    assert updated.status_code == 200
    assert updated.json()["name"] == "Viewer Updated"
    assert planned.status_code == 200
    assert planned.json()["status"] == "planning"
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"


def test_campaign_api_denies_actions_without_required_campaign_capability(
    campaigns_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededCampaignApi,
    ],
) -> None:
    client, sessionmaker, seeded = campaigns_client
    asyncio.run(
        _grant_campaign_capabilities(
            sessionmaker,
            seeded,
            "marketing.campaign.view",
        )
    )
    _set_context(
        client,
        seeded,
        user_id=seeded.viewer_user_id,
        email="campaign-viewer@example.com",
        display_name="Viewer",
        workspace_permission=WorkspacePermission.guest,
    )
    base = f"/api/v1/workspaces/{seeded.workspace_id}/campaigns"

    listed = client.get(base)
    created = client.post(base, json={"name": "Denied Campaign"})
    updated = client.patch(f"{base}/{seeded.campaign_id}", json={"name": "Denied"})
    status_update = client.patch(
        f"{base}/{seeded.campaign_id}/status",
        json={"status": "planning"},
    )
    member_update = client.put(
        f"{base}/{seeded.campaign_id}/members",
        json={"workspace_membership_id": str(seeded.member_workspace_membership_id)},
    )
    goal_create = client.post(
        f"{base}/{seeded.campaign_id}/goals",
        json={"title": "Denied goal"},
    )
    milestone_create = client.post(
        f"{base}/{seeded.campaign_id}/milestones",
        json={"title": "Denied milestone"},
    )

    assert listed.status_code == 200
    for response in (
        created,
        updated,
        status_update,
        member_update,
        goal_create,
        milestone_create,
    ):
        assert response.status_code == 403
        assert response.json() == {"detail": "Insufficient capability permission"}


def test_campaign_membership_does_not_bypass_campaign_authorization(
    campaigns_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededCampaignApi,
    ],
) -> None:
    client, sessionmaker, seeded = campaigns_client
    asyncio.run(_add_viewer_to_campaign(sessionmaker, seeded))
    _set_context(
        client,
        seeded,
        user_id=seeded.viewer_user_id,
        email="campaign-viewer@example.com",
        display_name="Viewer",
        workspace_permission=WorkspacePermission.guest,
    )

    response = client.get(
        f"/api/v1/workspaces/{seeded.workspace_id}/campaigns/"
        f"{seeded.campaign_id}/members"
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient capability permission"}


def test_campaign_api_preserves_workspace_isolation_with_campaign_capability(
    campaigns_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededCampaignApi,
    ],
) -> None:
    client, sessionmaker, seeded = campaigns_client
    asyncio.run(
        _grant_campaign_capabilities(
            sessionmaker,
            seeded,
            "marketing.campaign.view",
        )
    )
    _set_context(
        client,
        seeded,
        user_id=seeded.viewer_user_id,
        email="campaign-viewer@example.com",
        display_name="Viewer",
        workspace_permission=WorkspacePermission.guest,
    )

    response = client.get(
        f"/api/v1/workspaces/{seeded.workspace_id}/campaigns/"
        f"{seeded.outside_campaign_id}"
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


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
    goal_create_schema = schema["components"]["schemas"]["CampaignGoalCreateRequest"]
    goal_schema = schema["components"]["schemas"]["CampaignGoalResponse"]
    milestone_create_schema = schema["components"]["schemas"][
        "CampaignMilestoneCreateRequest"
    ]
    milestone_schema = schema["components"]["schemas"]["CampaignMilestoneResponse"]

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
        "owner",
        "primary_artist",
        "release",
        "members",
        "artists",
        "releases",
        "created_at",
        "updated_at",
    }
    assert set(goal_create_schema["properties"]) == {
        "title",
        "description",
        "target_value",
        "success_criteria",
        "status",
    }
    assert set(goal_schema["properties"]) == {
        "id",
        "campaign_id",
        "title",
        "description",
        "target_value",
        "success_criteria",
        "status",
        "created_at",
        "updated_at",
    }
    assert set(milestone_create_schema["properties"]) == {
        "title",
        "description",
        "target_date",
        "status",
    }
    assert set(milestone_schema["properties"]) == {
        "id",
        "campaign_id",
        "title",
        "description",
        "target_date",
        "status",
        "completed_at",
        "created_by_user_id",
        "created_at",
        "updated_at",
    }
