import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from labelos_database.base import Base
from labelos_database.capabilities import Capability
from labelos_database.models import (
    ApprovalRequest,
    ApprovalRequestStage,
    ApprovalRequestStatus,
    ApprovalStageStatus,
    Artist,
    Campaign,
    CampaignMilestone,
    CampaignStatus,
    CampaignType,
    MarketingContentItem,
    MarketingContentItemChannel,
    MarketingContentItemStatus,
    MembershipRole,
    Organization,
    OrganizationMembership,
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
from labelos_api.repositories import campaign_calendar
from labelos_api.repositories.approval_resources import (
    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
)


@dataclass(frozen=True)
class SeededCampaignCalendarApi:
    owner_user_id: UUID
    viewer_user_id: UUID
    workspace_id: UUID
    outside_workspace_id: UUID
    campaign_id: UUID
    second_campaign_id: UUID
    outside_campaign_id: UUID
    artist_id: UUID
    second_artist_id: UUID
    release_id: UUID
    second_release_id: UUID
    milestone_id: UUID
    content_item_id: UUID
    channel_id: UUID
    approval_request_id: UUID
    archived_content_id: UUID
    published_content_id: UUID


@pytest.fixture
def campaign_calendar_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[
    tuple[TestClient, async_sessionmaker[AsyncSession], SeededCampaignCalendarApi]
]:
    monkeypatch.setenv("APP_ENV", "test")
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def prepare_database() -> SeededCampaignCalendarApi:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with sessionmaker() as session:
            owner = User(email="calendar-owner@example.com", display_name="Owner")
            viewer = User(email="calendar-viewer@example.com", display_name="Viewer")
            outside_owner = User(email="calendar-outside@example.com")
            workspace = Organization(
                name="Alpha Label",
                slug=f"alpha-calendar-api-{uuid4().hex}",
                owner=owner,
                workos_organization_id="org_ALPHA_CALENDAR",
            )
            outside_workspace = Organization(
                name="Beta Label",
                slug=f"beta-calendar-api-{uuid4().hex}",
                owner=outside_owner,
                workos_organization_id="org_BETA_CALENDAR",
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
                capability_permissions=[
                    Capability.marketing_campaign_view.value,
                    Capability.marketing_content_view.value,
                ],
            )
            outside_membership = OrganizationMembership(
                organization=outside_workspace,
                user=outside_owner,
                role=MembershipRole.owner,
                workspace_permission=WorkspacePermission.owner,
                department_access=["marketing", "management"],
            )
            owner_profile = UniversalProfile(user=owner, slug="calendar-owner")
            viewer_profile = UniversalProfile(user=viewer, slug="calendar-viewer")
            outside_profile = UniversalProfile(
                user=outside_owner,
                slug="calendar-outside",
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
                workspace=outside_workspace,
                profile=outside_profile,
                organization_membership=outside_membership,
                status="active",
            )
            artist = Artist(name="Alpha Artist", organization=workspace)
            second_artist = Artist(name="Second Artist", organization=workspace)
            outside_artist = Artist(name="Beta Artist", organization=outside_workspace)
            release = Release(
                title="Alpha Release", organization=workspace, artist=artist
            )
            second_release = Release(
                title="Second Release",
                organization=workspace,
                artist=second_artist,
            )
            campaign = Campaign(
                name="Alpha Campaign",
                organization=workspace,
                primary_artist=artist,
                release=release,
                campaign_type=CampaignType.release,
                status=CampaignStatus.active,
                start_date=date(2026, 9, 4),
                target_end_date=date(2026, 9, 30),
            )
            second_campaign = Campaign(
                name="Second Campaign",
                organization=workspace,
                primary_artist=second_artist,
                release=second_release,
                status=CampaignStatus.planning,
                start_date=date(2026, 9, 5),
            )
            outside_campaign = Campaign(
                name="Beta Campaign",
                organization=outside_workspace,
                primary_artist=outside_artist,
                start_date=date(2026, 9, 4),
            )
            milestone = CampaignMilestone(
                campaign=campaign,
                title="Trailer Lock",
                target_date=date(2026, 9, 6),
            )
            content = MarketingContentItem(
                organization=workspace,
                campaign=campaign,
                artist=artist,
                release=release,
                title="Hero Clip",
                content_type="video",
                status=MarketingContentItemStatus.scheduled,
                scheduled_at=datetime(2026, 9, 7, 16, tzinfo=UTC),
                channels=[
                    MarketingContentItemChannel(
                        channel="Instagram",
                        placement="Reel",
                        scheduled_at=datetime(2026, 9, 7, 17, tzinfo=UTC),
                    )
                ],
            )
            archived = MarketingContentItem(
                organization=workspace,
                campaign=campaign,
                title="Archived Clip",
                content_type="video",
                status=MarketingContentItemStatus.archived,
                scheduled_at=datetime(2026, 9, 8, 16, tzinfo=UTC),
            )
            published = MarketingContentItem(
                organization=workspace,
                campaign=campaign,
                title="Published Clip",
                content_type="video",
                status=MarketingContentItemStatus.published,
                published_at=datetime(2026, 9, 9, 16, tzinfo=UTC),
            )
            review_item = MarketingContentItem(
                organization=workspace,
                campaign=campaign,
                title="Approval Clip",
                content_type="image",
                status=MarketingContentItemStatus.in_review,
            )
            session.add_all(
                [
                    viewer_membership,
                    release,
                    second_release,
                    campaign,
                    second_campaign,
                    outside_campaign,
                    milestone,
                    content,
                    archived,
                    published,
                    review_item,
                ]
            )
            await session.flush()
            approval_request = ApprovalRequest(
                organization=workspace,
                resource_type=MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                resource_id=review_item.id,
                resource_revision=review_item.content_revision,
                title="Review Approval Clip",
                status=ApprovalRequestStatus.in_review,
                submitted_at=datetime(2026, 9, 10, 16, tzinfo=UTC),
            )
            approval_request.stages = [
                ApprovalRequestStage(
                    stage_order=1,
                    required_capability=Capability.marketing_content_approve.value,
                    status=ApprovalStageStatus.in_review,
                    started_at=datetime(2026, 9, 10, 16, tzinfo=UTC),
                )
            ]
            review_item.approval_request = approval_request
            await session.commit()
            return SeededCampaignCalendarApi(
                owner_user_id=owner.id,
                viewer_user_id=viewer.id,
                workspace_id=workspace.id,
                outside_workspace_id=outside_workspace.id,
                campaign_id=campaign.id,
                second_campaign_id=second_campaign.id,
                outside_campaign_id=outside_campaign.id,
                artist_id=artist.id,
                second_artist_id=second_artist.id,
                release_id=release.id,
                second_release_id=second_release.id,
                milestone_id=milestone.id,
                content_item_id=content.id,
                channel_id=content.channels[0].id,
                approval_request_id=approval_request.id,
                archived_content_id=archived.id,
                published_content_id=published.id,
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
    seeded: SeededCampaignCalendarApi,
    *,
    user_id: UUID | None = None,
    email: str = "calendar-owner@example.com",
    workspace_permission: WorkspacePermission = WorkspacePermission.owner,
    capability_permissions: tuple[str, ...] = (),
    memberships: tuple[MembershipContext, ...] | None = None,
) -> None:
    resolved_user_id = user_id or seeded.owner_user_id

    async def override_context() -> CurrentUserContext:
        return CurrentUserContext(
            user=User(id=resolved_user_id, email=email),
            principal=AuthenticatedPrincipal(
                provider="workos",
                subject=f"user_{resolved_user_id}",
                session_id="session_SECRET",
                email=email,
                organization_id="org_ALPHA_CALENDAR",
                role=workspace_permission.value,
                roles=(workspace_permission.value,),
            ),
            memberships=memberships
            or (
                MembershipContext(
                    organization_id=seeded.workspace_id,
                    organization_name="Alpha Label",
                    organization_slug="alpha-calendar-api",
                    workos_organization_id="org_ALPHA_CALENDAR",
                    workspace_permission=workspace_permission,
                    department_access=("marketing",),
                    capability_permissions=capability_permissions,
                ),
            ),
        )

    client.app.dependency_overrides[get_current_user_context] = override_context


async def _set_viewer_capabilities(
    sessionmaker: async_sessionmaker[AsyncSession],
    seeded: SeededCampaignCalendarApi,
    capabilities: tuple[str, ...],
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


def _base(seeded: SeededCampaignCalendarApi) -> str:
    return f"/api/v1/workspaces/{seeded.workspace_id}/campaign-calendar"


def _range_params(**overrides: str) -> dict[str, str]:
    params = {
        "start": "2026-09-01T00:00:00+00:00",
        "end": "2026-09-30T23:59:59+00:00",
    }
    params.update(overrides)
    return params


def test_campaign_calendar_api_successful_retrieval(
    campaign_calendar_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededCampaignCalendarApi,
    ],
) -> None:
    client, _sessionmaker, seeded = campaign_calendar_client
    _set_context(client, seeded)

    response = client.get(
        _base(seeded), params=_range_params(timezone="America/Los_Angeles")
    )

    assert response.status_code == 200
    body = response.json()
    assert body["workspace_id"] == str(seeded.workspace_id)
    assert body["start"] == "2026-09-01T00:00:00Z"
    assert body["end"] == "2026-09-30T23:59:59Z"
    assert body["timezone"] == "America/Los_Angeles"
    assert body["limit"] == 1000
    assert body["offset"] == 0
    assert "Beta Campaign starts" not in [event["title"] for event in body["events"]]
    assert {event["event_type"] for event in body["events"]} >= {
        campaign_calendar.CAMPAIGN_START,
        campaign_calendar.CAMPAIGN_TARGET_END,
        campaign_calendar.CAMPAIGN_MILESTONE_TARGET,
        campaign_calendar.MARKETING_CONTENT_SCHEDULED,
        campaign_calendar.MARKETING_CONTENT_CHANNEL_SCHEDULED,
        campaign_calendar.MARKETING_CONTENT_APPROVAL_REQUESTED,
    }


def test_campaign_calendar_api_missing_capability(
    campaign_calendar_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededCampaignCalendarApi,
    ],
) -> None:
    client, sessionmaker, seeded = campaign_calendar_client
    asyncio.run(
        _set_viewer_capabilities(
            sessionmaker,
            seeded,
            (Capability.marketing_campaign_view.value,),
        )
    )
    _set_context(
        client,
        seeded,
        user_id=seeded.viewer_user_id,
        email="calendar-viewer@example.com",
        workspace_permission=WorkspacePermission.guest,
        capability_permissions=(Capability.marketing_campaign_view.value,),
    )

    response = client.get(_base(seeded), params=_range_params())

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient capability permission"}


def test_campaign_calendar_api_workspace_isolation(
    campaign_calendar_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededCampaignCalendarApi,
    ],
) -> None:
    client, _sessionmaker, seeded = campaign_calendar_client
    _set_context(
        client,
        seeded,
        memberships=(
            MembershipContext(
                organization_id=seeded.workspace_id,
                organization_name="Alpha Label",
                organization_slug="alpha-calendar-api",
                workos_organization_id="org_ALPHA_CALENDAR",
                workspace_permission=WorkspacePermission.owner,
            ),
        ),
    )

    response = client.get(
        f"/api/v1/workspaces/{seeded.outside_workspace_id}/campaign-calendar",
        params=_range_params(),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


@pytest.mark.parametrize(
    ("params", "detail"),
    [
        (_range_params(timezone="Not/AZone"), "Invalid campaign calendar timezone"),
        (
            _range_params(start="2026-09-01T00:00:00", end="2026-09-02T00:00:00+00:00"),
            "Campaign calendar start must be timezone-aware",
        ),
        (
            _range_params(
                start="2026-09-02T00:00:00+00:00", end="2026-09-01T00:00:00+00:00"
            ),
            "Campaign calendar end must be after start",
        ),
    ],
)
def test_campaign_calendar_api_validation_errors(
    campaign_calendar_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededCampaignCalendarApi,
    ],
    params: dict[str, str],
    detail: str,
) -> None:
    client, _sessionmaker, seeded = campaign_calendar_client
    _set_context(client, seeded)

    response = client.get(_base(seeded), params=params)

    assert response.status_code == 400
    assert response.json() == {"detail": detail}


def test_campaign_calendar_api_filters_include_flags_and_pagination(
    campaign_calendar_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededCampaignCalendarApi,
    ],
) -> None:
    client, _sessionmaker, seeded = campaign_calendar_client
    _set_context(client, seeded)
    base = _base(seeded)

    campaign_filtered = client.get(
        base,
        params=_range_params(campaign_id=str(seeded.campaign_id)),
    )
    artist_filtered = client.get(
        base,
        params=_range_params(artist_id=str(seeded.second_artist_id)),
    )
    release_filtered = client.get(
        base,
        params=_range_params(release_id=str(seeded.release_id)),
    )
    status_filtered = client.get(base, params=_range_params(status="planning"))
    type_filtered = client.get(
        base,
        params=[
            ("start", "2026-09-01T00:00:00+00:00"),
            ("end", "2026-09-30T23:59:59+00:00"),
            ("event_types", campaign_calendar.CAMPAIGN_START),
            ("event_types", campaign_calendar.CAMPAIGN_TARGET_END),
        ],
    )
    csv_type_filtered = client.get(
        base,
        params=_range_params(
            event_types=(
                f"{campaign_calendar.MARKETING_CONTENT_SCHEDULED},"
                f"{campaign_calendar.MARKETING_CONTENT_CHANNEL_SCHEDULED}"
            )
        ),
    )
    published = client.get(
        base,
        params=_range_params(
            event_types=campaign_calendar.MARKETING_CONTENT_PUBLISHED,
            include_published="true",
        ),
    )
    archived = client.get(
        base,
        params=_range_params(
            event_types=campaign_calendar.MARKETING_CONTENT_SCHEDULED,
            include_archived="true",
        ),
    )
    paged = client.get(base, params=_range_params(limit="2", offset="1"))

    assert {
        event["campaign"]["name"] for event in campaign_filtered.json()["events"]
    } == {"Alpha Campaign"}
    assert {event["artist"]["name"] for event in artist_filtered.json()["events"]} == {
        "Second Artist"
    }
    assert {
        event["release"]["title"] for event in release_filtered.json()["events"]
    } == {"Alpha Release"}
    assert {
        event["campaign"]["name"] for event in status_filtered.json()["events"]
    } == {"Second Campaign"}
    assert {event["event_type"] for event in type_filtered.json()["events"]} == {
        campaign_calendar.CAMPAIGN_START,
        campaign_calendar.CAMPAIGN_TARGET_END,
    }
    assert {event["event_type"] for event in csv_type_filtered.json()["events"]} == {
        campaign_calendar.MARKETING_CONTENT_SCHEDULED,
        campaign_calendar.MARKETING_CONTENT_CHANNEL_SCHEDULED,
    }
    assert [event["title"] for event in published.json()["events"]] == [
        "Published Clip"
    ]
    assert "Archived Clip" in [event["title"] for event in archived.json()["events"]]
    assert paged.status_code == 200
    assert paged.json()["total"] > 2
    assert paged.json()["limit"] == 2
    assert paged.json()["offset"] == 1
    assert len(paged.json()["events"]) == 2
    assert client.get(base, params=_range_params(limit="1001")).status_code == 422


def test_campaign_calendar_api_projected_event_shapes(
    campaign_calendar_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededCampaignCalendarApi,
    ],
) -> None:
    client, _sessionmaker, seeded = campaign_calendar_client
    _set_context(client, seeded)

    response = client.get(
        _base(seeded),
        params=_range_params(timezone="UTC", campaign_id=str(seeded.campaign_id)),
    )

    assert response.status_code == 200
    events = {event["event_type"]: event for event in response.json()["events"]}
    campaign_event = events[campaign_calendar.CAMPAIGN_START]
    milestone_event = events[campaign_calendar.CAMPAIGN_MILESTONE_TARGET]
    content_event = events[campaign_calendar.MARKETING_CONTENT_SCHEDULED]
    channel_event = events[campaign_calendar.MARKETING_CONTENT_CHANNEL_SCHEDULED]
    approval_event = events[campaign_calendar.MARKETING_CONTENT_APPROVAL_REQUESTED]

    assert campaign_event["all_day"] is True
    assert campaign_event["date"] == "2026-09-04"
    assert campaign_event["id"] == f"campaign:{seeded.campaign_id}:start"
    assert milestone_event["source_type"] == "campaign_milestone"
    assert milestone_event["id"] == f"campaign_milestone:{seeded.milestone_id}:target"
    assert content_event["source_type"] == "marketing_content_item"
    assert content_event["source_id"] == str(seeded.content_item_id)
    assert channel_event["source_type"] == "marketing_content_channel"
    assert channel_event["source_parent_id"] == str(seeded.content_item_id)
    assert channel_event["channel"] == {
        "id": str(seeded.channel_id),
        "channel": "Instagram",
        "placement": "Reel",
    }
    assert approval_event["source_type"] == "approval_request"
    assert approval_event["approval"]["request_id"] == str(seeded.approval_request_id)
    assert approval_event["approval"]["state"] == "in_review"


def test_campaign_calendar_openapi_contract_exposes_stable_fields(
    campaign_calendar_client: tuple[
        TestClient,
        async_sessionmaker[AsyncSession],
        SeededCampaignCalendarApi,
    ],
) -> None:
    client, _sessionmaker, _seeded = campaign_calendar_client

    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    schemas = schema["components"]["schemas"]

    assert "/api/v1/workspaces/{workspace_id}/campaign-calendar" in paths
    operation = paths["/api/v1/workspaces/{workspace_id}/campaign-calendar"]["get"]
    assert {param["name"] for param in operation["parameters"]} >= {
        "workspace_id",
        "start",
        "end",
        "timezone",
        "campaign_id",
        "artist_id",
        "release_id",
        "status",
        "event_types",
        "include_archived",
        "include_published",
        "limit",
        "offset",
    }
    assert set(schemas["CampaignCalendarResponse"]["properties"]) == {
        "workspace_id",
        "start",
        "end",
        "timezone",
        "events",
        "total",
        "limit",
        "offset",
    }
    assert set(schemas["CampaignCalendarEventResponse"]["properties"]) == {
        "id",
        "event_type",
        "source_type",
        "source_id",
        "source_parent_id",
        "title",
        "description",
        "starts_at",
        "ends_at",
        "date",
        "all_day",
        "timezone",
        "status",
        "campaign",
        "artist",
        "release",
        "channel",
        "approval",
        "url",
        "sort_key",
    }
