import asyncio
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from labelos_database.base import Base
from labelos_database.capabilities import Capability
from labelos_database.models import (
    ApprovalRequest,
    ApprovalRequestStatus,
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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from labelos_api.repositories import campaign_calendar
from labelos_api.repositories.approval_resources import (
    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
)
from labelos_api.services.campaign_calendar_service import (
    CampaignCalendarAuthorizationError,
    CampaignCalendarEventQuery,
    CampaignCalendarValidationError,
    list_campaign_calendar_events,
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
        name="Alpha Label",
        slug="alpha-calendar-service",
        owner=User(email="owner-alpha-calendar-service@example.com"),
    )
    other_workspace = Organization(
        name="Beta Label",
        slug="beta-calendar-service",
        owner=User(email="owner-beta-calendar-service@example.com"),
    )
    artist = Artist(name="Alpha Artist", organization=workspace)
    second_artist = Artist(name="Second Artist", organization=workspace)
    other_artist = Artist(name="Beta Artist", organization=other_workspace)
    release = Release(title="Alpha Release", organization=workspace, artist=artist)
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
        campaign_type=CampaignType.marketing,
        status=CampaignStatus.planning,
        start_date=date(2026, 9, 5),
    )
    other_campaign = Campaign(
        name="Beta Campaign",
        organization=other_workspace,
        primary_artist=other_artist,
        start_date=date(2026, 9, 4),
    )
    session.add_all(
        [release, second_release, campaign, second_campaign, other_campaign]
    )
    await session.flush()
    return {
        "workspace": workspace,
        "other_workspace": other_workspace,
        "artist": artist,
        "second_artist": second_artist,
        "release": release,
        "second_release": second_release,
        "campaign": campaign,
        "second_campaign": second_campaign,
        "other_campaign": other_campaign,
    }


async def _seed_actor(
    session: AsyncSession,
    workspace: Organization,
    *,
    email: str,
    capabilities: tuple[str, ...],
) -> User:
    user = User(email=email)
    profile = UniversalProfile(user=user, slug=email.split("@", maxsplit=1)[0])
    membership = OrganizationMembership(
        organization=workspace,
        user=user,
        role=MembershipRole.guest,
        workspace_permission=WorkspacePermission.guest,
        department_access=["marketing"],
        capability_permissions=list(capabilities),
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


def _query(**overrides: object) -> CampaignCalendarEventQuery:
    values = {
        "start": datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
        "end": datetime(2026, 9, 30, 23, 59, tzinfo=UTC),
        "timezone": "America/Los_Angeles",
    }
    values.update(overrides)
    return CampaignCalendarEventQuery(**values)


def test_campaign_calendar_service_authorization_requires_campaign_and_content_view(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[int, str, str, str]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            other_campaign = data["other_campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(other_campaign, Campaign)
            allowed = await _seed_actor(
                session,
                workspace,
                email="calendar-viewer@example.com",
                capabilities=(
                    Capability.marketing_campaign_view.value,
                    Capability.marketing_content_view.value,
                ),
            )
            missing_content = await _seed_actor(
                session,
                workspace,
                email="campaign-only@example.com",
                capabilities=(Capability.marketing_campaign_view.value,),
            )
            missing_campaign = await _seed_actor(
                session,
                workspace,
                email="content-only@example.com",
                capabilities=(Capability.marketing_content_view.value,),
            )

            page = await list_campaign_calendar_events(
                session,
                workspace.id,
                actor=allowed,
                query=_query(),
            )
            with pytest.raises(CampaignCalendarAuthorizationError) as exc_info:
                await list_campaign_calendar_events(
                    session,
                    workspace.id,
                    actor=missing_content,
                    query=_query(),
                )
            with pytest.raises(CampaignCalendarAuthorizationError) as campaign_exc:
                await list_campaign_calendar_events(
                    session,
                    workspace.id,
                    actor=missing_campaign,
                    query=_query(),
                )
            with pytest.raises(CampaignCalendarAuthorizationError) as cross_exc:
                await list_campaign_calendar_events(
                    session,
                    workspace.id,
                    actor=allowed,
                    query=_query(campaign_id=other_campaign.id),
                )
            return (
                page.total,
                exc_info.value.reason,
                campaign_exc.value.reason,
                cross_exc.value.reason,
            )

    total, missing_content_reason, missing_campaign_reason, cross_reason = asyncio.run(
        run()
    )

    assert total == 3
    assert missing_content_reason == "missing_capability"
    assert missing_campaign_reason == "missing_capability"
    assert cross_reason == "invalid_resource_scope"


def test_campaign_calendar_service_normalizes_ids_all_day_timezone_and_sorting(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, object]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            milestone = CampaignMilestone(
                campaign=campaign,
                title="Trailer Lock",
                target_date=date(2026, 9, 4),
            )
            item = MarketingContentItem(
                organization=workspace,
                campaign=campaign,
                title="Morning Clip",
                content_type="video",
                status=MarketingContentItemStatus.scheduled,
                scheduled_at=datetime(2026, 9, 4, 15, 30, tzinfo=UTC),
                channels=[
                    MarketingContentItemChannel(
                        channel="instagram",
                        placement="reel",
                        scheduled_at=datetime(2026, 9, 4, 16, 0, tzinfo=UTC),
                    )
                ],
            )
            session.add_all([milestone, item])
            await session.flush()

            page = await list_campaign_calendar_events(
                session,
                workspace.id,
                query=_query(
                    start=datetime(2026, 9, 4, 0, 0, tzinfo=UTC),
                    end=datetime(2026, 9, 4, 23, 59, tzinfo=UTC),
                    event_types=(
                        campaign_calendar.CAMPAIGN_START,
                        campaign_calendar.CAMPAIGN_MILESTONE_TARGET,
                        campaign_calendar.MARKETING_CONTENT_SCHEDULED,
                        campaign_calendar.MARKETING_CONTENT_CHANNEL_SCHEDULED,
                    ),
                ),
            )
            return {
                "ids": [event.id for event in page.events],
                "starts": [event.starts_at for event in page.events],
                "all_day": [event.all_day for event in page.events],
                "dates": [event.date for event in page.events],
                "source_types": [event.source_type for event in page.events],
                "channel": page.events[-1].channel,
                "campaign": page.events[0].campaign,
                "expected_ids": {
                    f"campaign:{campaign.id}:start",
                    f"campaign_milestone:{milestone.id}:target",
                    f"marketing_content:{item.id}:scheduled",
                    f"marketing_content_channel:{item.channels[0].id}:scheduled",
                },
            }

    result = asyncio.run(run())

    assert set(result["ids"]) == result["expected_ids"]
    assert result["all_day"] == [True, True, False, False]
    assert result["dates"][:2] == ["2026-09-04", "2026-09-04"]
    assert str(result["starts"][0]).startswith("2026-09-04T00:00:00-07:00")
    assert str(result["starts"][2]).startswith("2026-09-04T08:30:00-07:00")
    assert result["source_types"][-1] == "marketing_content_channel"
    assert result["channel"].channel == "instagram"
    assert result["campaign"].campaign_type == "release"


def test_campaign_calendar_service_validates_timezone_ranges_and_pagination(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> list[str]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            assert isinstance(workspace, Organization)
            failures = []
            invalid_inputs = [
                _query(timezone="Not/AZone"),
                _query(
                    start=datetime(2026, 9, 2, tzinfo=UTC),
                    end=datetime(2026, 9, 1, tzinfo=UTC),
                ),
                _query(
                    start=datetime(2026, 9, 1),
                    end=datetime(2026, 9, 2, tzinfo=UTC),
                ),
            ]
            for invalid in invalid_inputs:
                with pytest.raises(CampaignCalendarValidationError) as exc_info:
                    await list_campaign_calendar_events(
                        session,
                        workspace.id,
                        query=invalid,
                    )
                failures.append(str(exc_info.value))
            with pytest.raises(CampaignCalendarValidationError):
                await list_campaign_calendar_events(
                    session,
                    workspace.id,
                    query=_query(),
                    limit=0,
                )
            return failures

    failures = asyncio.run(run())

    assert "timezone" in failures[0]
    assert "end must be after start" in failures[1]
    assert "start must be timezone-aware" in failures[2]


def test_campaign_calendar_service_paginates_filters_and_isolates_workspace(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, object]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            second_campaign = data["second_campaign"]
            artist = data["artist"]
            release = data["release"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(second_campaign, Campaign)
            assert isinstance(artist, Artist)
            assert isinstance(release, Release)
            archived = MarketingContentItem(
                organization=workspace,
                campaign=campaign,
                title="Archived Clip",
                content_type="video",
                status=MarketingContentItemStatus.archived,
                scheduled_at=datetime(2026, 9, 10, 12, tzinfo=UTC),
            )
            published = MarketingContentItem(
                organization=workspace,
                campaign=campaign,
                title="Published Clip",
                content_type="video",
                status=MarketingContentItemStatus.published,
                published_at=datetime(2026, 9, 11, 12, tzinfo=UTC),
            )
            session.add_all([archived, published])
            await session.flush()

            all_default = await list_campaign_calendar_events(
                session,
                workspace.id,
                query=_query(),
            )
            paged = await list_campaign_calendar_events(
                session,
                workspace.id,
                query=_query(),
                limit=1,
                offset=1,
            )
            campaign_filtered = await list_campaign_calendar_events(
                session,
                workspace.id,
                query=_query(campaign_id=campaign.id),
            )
            artist_filtered = await list_campaign_calendar_events(
                session,
                workspace.id,
                query=_query(artist_id=artist.id),
            )
            release_filtered = await list_campaign_calendar_events(
                session,
                workspace.id,
                query=_query(release_id=release.id),
            )
            type_filtered = await list_campaign_calendar_events(
                session,
                workspace.id,
                query=_query(event_types=(campaign_calendar.CAMPAIGN_START,)),
            )
            status_filtered = await list_campaign_calendar_events(
                session,
                workspace.id,
                query=_query(statuses=(CampaignStatus.planning,)),
            )
            with_published = await list_campaign_calendar_events(
                session,
                workspace.id,
                query=_query(
                    event_types=(campaign_calendar.MARKETING_CONTENT_PUBLISHED,),
                    include_published=True,
                ),
            )
            with_archived = await list_campaign_calendar_events(
                session,
                workspace.id,
                query=_query(
                    event_types=(campaign_calendar.MARKETING_CONTENT_SCHEDULED,),
                    include_archived=True,
                ),
            )
            return {
                "default_titles": [event.title for event in all_default.events],
                "paged": (paged.total, len(paged.events), paged.events[0].title),
                "campaign": {event.campaign.name for event in campaign_filtered.events},
                "artist": {
                    event.artist.name
                    for event in artist_filtered.events
                    if event.artist
                },
                "release": {
                    event.release.title
                    for event in release_filtered.events
                    if event.release
                },
                "type": [event.event_type for event in type_filtered.events],
                "status": {event.campaign.name for event in status_filtered.events},
                "published": [event.title for event in with_published.events],
                "archived": [event.title for event in with_archived.events],
            }

    result = asyncio.run(run())

    assert "Beta Campaign starts" not in result["default_titles"]
    assert "Archived Clip" not in result["default_titles"]
    assert "Published Clip" not in result["default_titles"]
    assert result["paged"][0] == 3
    assert result["paged"][1] == 1
    assert result["campaign"] == {"Alpha Campaign"}
    assert result["artist"] == {"Alpha Artist"}
    assert result["release"] == {"Alpha Release"}
    assert set(result["type"]) == {campaign_calendar.CAMPAIGN_START}
    assert result["status"] == {"Second Campaign"}
    assert result["published"] == ["Published Clip"]
    assert result["archived"] == ["Archived Clip"]


def test_campaign_calendar_service_projects_approval_context_without_persistence(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, object]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            requested_item = MarketingContentItem(
                organization=workspace,
                campaign=campaign,
                title="Needs Review",
                content_type="image",
                status=MarketingContentItemStatus.in_review,
            )
            approved_item = MarketingContentItem(
                organization=workspace,
                campaign=campaign,
                title="Approved Review",
                content_type="image",
                status=MarketingContentItemStatus.approved,
                scheduled_at=datetime(2026, 9, 13, 12, tzinfo=UTC),
                approved_revision=1,
            )
            session.add_all([requested_item, approved_item])
            await session.flush()
            requested = ApprovalRequest(
                organization=workspace,
                resource_type=MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                resource_id=requested_item.id,
                resource_revision=requested_item.content_revision,
                title="Review Needs Review",
                status=ApprovalRequestStatus.in_review,
                submitted_at=datetime(2026, 9, 12, 12, tzinfo=UTC),
            )
            approved = ApprovalRequest(
                organization=workspace,
                resource_type=MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                resource_id=approved_item.id,
                resource_revision=approved_item.content_revision,
                title="Review Approved Review",
                status=ApprovalRequestStatus.approved,
                submitted_at=datetime(2026, 9, 12, 13, tzinfo=UTC),
                resolved_at=datetime(2026, 9, 12, 14, tzinfo=UTC),
            )
            requested_item.approval_request = requested
            approved_item.approval_request = approved
            await session.flush()

            page = await list_campaign_calendar_events(
                session,
                workspace.id,
                query=_query(
                    event_types=(
                        campaign_calendar.MARKETING_CONTENT_APPROVAL_REQUESTED,
                        campaign_calendar.MARKETING_CONTENT_APPROVED,
                    )
                ),
            )
            return {
                "events": {event.title: event for event in page.events},
                "calendar_table_exists": (
                    "campaign_calendar_events" in Base.metadata.tables
                ),
            }

    result = asyncio.run(run())
    events = result["events"]

    assert events["Needs Review"].id.startswith("approval_request:")
    assert events["Needs Review"].approval.state == "in_review"
    assert events["Needs Review"].approval.label == "Review Needs Review"
    assert events["Needs Review"].approval.approved_revision_is_current is False
    assert events["Approved Review"].approval.state == "approved"
    assert events["Approved Review"].approval.approved_revision_is_current is True
    assert events["Approved Review"].approval.can_schedule is True
    assert result["calendar_table_exists"] is False


def test_campaign_calendar_service_timed_events_use_inclusive_aware_range(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> list[str]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            included = MarketingContentItem(
                organization=workspace,
                campaign=campaign,
                title="Boundary Clip",
                content_type="video",
                scheduled_at=datetime(2026, 9, 5, 7, 0, tzinfo=UTC),
            )
            excluded = MarketingContentItem(
                organization=workspace,
                campaign=campaign,
                title="Too Early",
                content_type="video",
                scheduled_at=datetime(2026, 9, 5, 6, 59, 59, tzinfo=UTC),
            )
            session.add_all([included, excluded])
            await session.flush()

            page = await list_campaign_calendar_events(
                session,
                workspace.id,
                query=_query(
                    start=datetime(
                        2026,
                        9,
                        5,
                        0,
                        0,
                        tzinfo=timezone(timedelta(hours=-7)),
                    ),
                    end=datetime(
                        2026,
                        9,
                        5,
                        0,
                        0,
                        tzinfo=timezone(timedelta(hours=-7)),
                    ),
                    event_types=(campaign_calendar.MARKETING_CONTENT_SCHEDULED,),
                ),
            )
            return [event.title for event in page.events]

    assert asyncio.run(run()) == ["Boundary Clip"]


def test_campaign_calendar_service_projects_parent_and_channel_schedule_cases(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> list[tuple[str, str, str | None]]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            same_timestamp = datetime(2026, 9, 15, 16, tzinfo=UTC)
            items = [
                MarketingContentItem(
                    organization=workspace,
                    campaign=campaign,
                    title="Parent Only",
                    content_type="video",
                    scheduled_at=datetime(2026, 9, 15, 10, tzinfo=UTC),
                ),
                MarketingContentItem(
                    organization=workspace,
                    campaign=campaign,
                    title="Channel Only",
                    content_type="video",
                    channels=[
                        MarketingContentItemChannel(
                            channel="instagram",
                            placement="reel",
                            scheduled_at=datetime(2026, 9, 15, 11, tzinfo=UTC),
                        )
                    ],
                ),
                MarketingContentItem(
                    organization=workspace,
                    campaign=campaign,
                    title="Same Timestamp",
                    content_type="video",
                    scheduled_at=same_timestamp,
                    channels=[
                        MarketingContentItemChannel(
                            channel="tiktok",
                            placement="feed",
                            scheduled_at=same_timestamp,
                        )
                    ],
                ),
                MarketingContentItem(
                    organization=workspace,
                    campaign=campaign,
                    title="Different Timestamp",
                    content_type="video",
                    scheduled_at=datetime(2026, 9, 15, 17, tzinfo=UTC),
                    channels=[
                        MarketingContentItemChannel(
                            channel="youtube",
                            placement="shorts",
                            scheduled_at=datetime(2026, 9, 15, 18, tzinfo=UTC),
                        )
                    ],
                ),
                MarketingContentItem(
                    organization=workspace,
                    campaign=campaign,
                    title="Multiple Channels",
                    content_type="video",
                    channels=[
                        MarketingContentItemChannel(
                            channel="email",
                            placement="newsletter",
                            scheduled_at=datetime(2026, 9, 15, 19, tzinfo=UTC),
                        ),
                        MarketingContentItemChannel(
                            channel="sms",
                            placement="blast",
                            scheduled_at=datetime(2026, 9, 15, 20, tzinfo=UTC),
                        ),
                    ],
                ),
            ]
            session.add_all(items)
            await session.flush()

            page = await list_campaign_calendar_events(
                session,
                workspace.id,
                query=_query(
                    start=datetime(2026, 9, 15, 0, 0, tzinfo=UTC),
                    end=datetime(2026, 9, 15, 23, 59, tzinfo=UTC),
                    timezone="UTC",
                    event_types=(
                        campaign_calendar.MARKETING_CONTENT_SCHEDULED,
                        campaign_calendar.MARKETING_CONTENT_CHANNEL_SCHEDULED,
                    ),
                ),
            )
            return [
                (
                    event.title,
                    event.event_type,
                    event.channel.channel if event.channel else None,
                )
                for event in page.events
            ]

    assert asyncio.run(run()) == [
        ("Parent Only", campaign_calendar.MARKETING_CONTENT_SCHEDULED, None),
        (
            "Channel Only - instagram",
            campaign_calendar.MARKETING_CONTENT_CHANNEL_SCHEDULED,
            "instagram",
        ),
        (
            "Same Timestamp - tiktok",
            campaign_calendar.MARKETING_CONTENT_CHANNEL_SCHEDULED,
            "tiktok",
        ),
        ("Same Timestamp", campaign_calendar.MARKETING_CONTENT_SCHEDULED, None),
        ("Different Timestamp", campaign_calendar.MARKETING_CONTENT_SCHEDULED, None),
        (
            "Different Timestamp - youtube",
            campaign_calendar.MARKETING_CONTENT_CHANNEL_SCHEDULED,
            "youtube",
        ),
        (
            "Multiple Channels - email",
            campaign_calendar.MARKETING_CONTENT_CHANNEL_SCHEDULED,
            "email",
        ),
        (
            "Multiple Channels - sms",
            campaign_calendar.MARKETING_CONTENT_CHANNEL_SCHEDULED,
            "sms",
        ),
    ]


@pytest.mark.parametrize(
    ("timezone_name", "starts_at", "expected_date"),
    [
        ("UTC", datetime(2026, 3, 8, 0, 30, tzinfo=UTC), "2026-03-08"),
        (
            "America/Los_Angeles",
            datetime(2026, 3, 8, 7, 30, tzinfo=UTC),
            "2026-03-07",
        ),
        (
            "America/New_York",
            datetime(2026, 3, 8, 4, 30, tzinfo=UTC),
            "2026-03-07",
        ),
    ],
)
def test_campaign_calendar_service_timezone_projection_and_dst_boundaries(
    sessionmaker: async_sessionmaker[AsyncSession],
    timezone_name: str,
    starts_at: datetime,
    expected_date: str,
) -> None:
    async def run() -> dict[str, str | bool | None]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            assert isinstance(workspace, Organization)
            campaign = Campaign(
                name=f"DST Campaign {timezone_name}",
                organization=workspace,
                start_date=date(2026, 3, 8),
                status=CampaignStatus.active,
            )
            item = MarketingContentItem(
                organization=workspace,
                campaign=campaign,
                title=f"DST Timed {timezone_name}",
                content_type="video",
                scheduled_at=starts_at,
            )
            session.add_all([campaign, item])
            await session.flush()

            page = await list_campaign_calendar_events(
                session,
                workspace.id,
                query=CampaignCalendarEventQuery(
                    start=datetime(2026, 3, 7, 0, 0, tzinfo=UTC),
                    end=datetime(2026, 3, 8, 23, 59, tzinfo=UTC),
                    timezone=timezone_name,
                    campaign_id=campaign.id,
                    event_types=(
                        campaign_calendar.CAMPAIGN_START,
                        campaign_calendar.MARKETING_CONTENT_SCHEDULED,
                    ),
                ),
            )
            events = {event.event_type: event for event in page.events}
            return {
                "campaign_date": events[campaign_calendar.CAMPAIGN_START].date,
                "campaign_all_day": events[campaign_calendar.CAMPAIGN_START].all_day,
                "timed_date": events[
                    campaign_calendar.MARKETING_CONTENT_SCHEDULED
                ].starts_at[:10],
            }

    assert asyncio.run(run()) == {
        "campaign_date": "2026-03-08",
        "campaign_all_day": True,
        "timed_date": expected_date,
    }


def test_campaign_calendar_service_includes_late_local_month_boundary_event(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> list[str]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            session.add(
                MarketingContentItem(
                    organization=workspace,
                    campaign=campaign,
                    title="Late Month Boundary",
                    content_type="video",
                    scheduled_at=datetime(2026, 10, 4, 6, 30, tzinfo=UTC),
                )
            )
            await session.flush()

            page = await list_campaign_calendar_events(
                session,
                workspace.id,
                query=CampaignCalendarEventQuery(
                    start=datetime(2026, 8, 30, 7, 0, tzinfo=UTC),
                    end=datetime(2026, 10, 4, 6, 59, 59, tzinfo=UTC),
                    timezone="America/Los_Angeles",
                    event_types=(campaign_calendar.MARKETING_CONTENT_SCHEDULED,),
                ),
            )
            return [event.title for event in page.events]

    assert asyncio.run(run()) == ["Late Month Boundary"]


def test_campaign_calendar_service_approval_completed_uses_queue_terminal_state(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> list[str]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            stale_projection = MarketingContentItem(
                organization=workspace,
                campaign=campaign,
                title="Stale Item Projection",
                content_type="image",
                status=MarketingContentItemStatus.in_review,
                approved_at=datetime(2026, 9, 14, 12, tzinfo=UTC),
            )
            approved = MarketingContentItem(
                organization=workspace,
                campaign=campaign,
                title="Queue Approved",
                content_type="image",
                status=MarketingContentItemStatus.approved,
                approved_at=datetime(2026, 9, 14, 12, tzinfo=UTC),
                approved_revision=1,
            )
            session.add_all([stale_projection, approved])
            await session.flush()
            stale_projection.approval_request = ApprovalRequest(
                organization=workspace,
                resource_type=MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                resource_id=stale_projection.id,
                resource_revision=stale_projection.content_revision,
                title="Review Stale Item Projection",
                status=ApprovalRequestStatus.in_review,
                submitted_at=datetime(2026, 9, 14, 10, tzinfo=UTC),
            )
            approved.approval_request = ApprovalRequest(
                organization=workspace,
                resource_type=MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                resource_id=approved.id,
                resource_revision=approved.content_revision,
                title="Review Queue Approved",
                status=ApprovalRequestStatus.approved,
                submitted_at=datetime(2026, 9, 14, 10, tzinfo=UTC),
                resolved_at=datetime(2026, 9, 14, 13, tzinfo=UTC),
            )
            await session.flush()

            page = await list_campaign_calendar_events(
                session,
                workspace.id,
                query=_query(
                    event_types=(campaign_calendar.MARKETING_CONTENT_APPROVED,)
                ),
            )
            return [event.title for event in page.events]

    assert asyncio.run(run()) == ["Queue Approved"]
