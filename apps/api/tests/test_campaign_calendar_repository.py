import asyncio
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from labelos_database.base import Base
from labelos_database.models import (
    ApprovalRequest,
    ApprovalRequestStatus,
    Artist,
    Campaign,
    CampaignArtist,
    CampaignMilestone,
    CampaignRelease,
    CampaignStatus,
    MarketingContentItem,
    MarketingContentItemChannel,
    MarketingContentItemStatus,
    Organization,
    Release,
    User,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from labelos_api.repositories import campaign_calendar
from labelos_api.repositories.approval_resources import (
    MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
)
from labelos_api.repositories.campaign_calendar import CampaignCalendarEventQuery


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
        slug="alpha-calendar",
        owner=User(email="owner-alpha-calendar@example.com"),
    )
    other_workspace = Organization(
        name="Beta Label",
        slug="beta-calendar",
        owner=User(email="owner-beta-calendar@example.com"),
    )
    artist = Artist(name="Alpha Artist", organization=workspace)
    linked_artist = Artist(name="Linked Artist", organization=workspace)
    other_artist = Artist(name="Beta Artist", organization=other_workspace)
    release = Release(title="Alpha Release", organization=workspace, artist=artist)
    linked_release = Release(title="Linked Release", organization=workspace)
    other_release = Release(
        title="Beta Release",
        organization=other_workspace,
        artist=other_artist,
    )
    campaign = Campaign(
        name="Alpha Campaign",
        organization=workspace,
        primary_artist=artist,
        release=release,
        start_date=date(2026, 9, 1),
        target_end_date=date(2026, 9, 30),
        status=CampaignStatus.active,
    )
    linked_campaign = Campaign(
        name="Linked Campaign",
        organization=workspace,
        start_date=date(2026, 10, 1),
        status=CampaignStatus.planning,
    )
    linked_campaign.artist_links = [
        CampaignArtist(artist=linked_artist, relationship_kind="primary")
    ]
    linked_campaign.release_links = [
        CampaignRelease(release=linked_release, relationship_kind="focus")
    ]
    other_campaign = Campaign(
        name="Beta Campaign",
        organization=other_workspace,
        primary_artist=other_artist,
        release=other_release,
        start_date=date(2026, 9, 2),
    )
    session.add_all(
        [
            release,
            linked_release,
            other_release,
            campaign,
            linked_campaign,
            other_campaign,
        ]
    )
    await session.flush()
    return {
        "workspace": workspace,
        "other_workspace": other_workspace,
        "artist": artist,
        "linked_artist": linked_artist,
        "other_artist": other_artist,
        "release": release,
        "linked_release": linked_release,
        "campaign": campaign,
        "linked_campaign": linked_campaign,
        "other_campaign": other_campaign,
    }


def test_campaign_calendar_projects_campaign_and_milestone_events_with_workspace_range(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[list[str], dict[str, str | None], list[str]]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            other_campaign = data["other_campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(other_campaign, Campaign)
            milestone = CampaignMilestone(
                campaign=campaign,
                title="Finish Trailer",
                target_date=date(2026, 9, 15),
            )
            outside = CampaignMilestone(
                campaign=campaign,
                title="Outside Range",
                target_date=date(2026, 11, 1),
            )
            other = CampaignMilestone(
                campaign=other_campaign,
                title="Other Workspace",
                target_date=date(2026, 9, 15),
            )
            session.add_all([milestone, outside, other])
            await session.flush()

            events = await campaign_calendar.list_events(
                session,
                workspace.id,
                CampaignCalendarEventQuery(
                    range_start=date(2026, 9, 1),
                    range_end=date(2026, 9, 30),
                ),
            )
            open_milestones = await campaign_calendar.list_events(
                session,
                workspace.id,
                CampaignCalendarEventQuery(
                    event_types=[campaign_calendar.CAMPAIGN_MILESTONE_TARGET],
                    statuses=["open"],
                    range_start=date(2026, 9, 1),
                    range_end=date(2026, 9, 30),
                ),
            )
            by_type = {event.event_type: event for event in events}
            return (
                [event.event_type for event in events],
                {
                    "campaign": by_type[campaign_calendar.CAMPAIGN_START].campaign_name,
                    "artist": by_type[
                        campaign_calendar.CAMPAIGN_MILESTONE_TARGET
                    ].artist_name,
                    "release": by_type[
                        campaign_calendar.CAMPAIGN_MILESTONE_TARGET
                    ].release_title,
                },
                [event.title for event in open_milestones],
            )

    event_types, context, open_milestones = asyncio.run(run())

    assert event_types == [
        campaign_calendar.CAMPAIGN_START,
        campaign_calendar.CAMPAIGN_MILESTONE_TARGET,
        campaign_calendar.CAMPAIGN_TARGET_END,
    ]
    assert context == {
        "campaign": "Alpha Campaign",
        "artist": "Alpha Artist",
        "release": "Alpha Release",
    }
    assert open_milestones == ["Finish Trailer"]


def test_campaign_calendar_projects_parent_and_channel_content_schedules(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[list[tuple[str, str, str | None]], list[str]]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            artist = data["artist"]
            release = data["release"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(artist, Artist)
            assert isinstance(release, Release)
            item = MarketingContentItem(
                organization=workspace,
                campaign=campaign,
                artist=artist,
                release=release,
                title="Hero Clip",
                content_type="video",
                status=MarketingContentItemStatus.scheduled,
                scheduled_at=datetime(2026, 9, 10, 16, tzinfo=UTC),
                published_at=datetime(2026, 9, 12, 16, tzinfo=UTC),
                channels=[
                    MarketingContentItemChannel(
                        channel="instagram",
                        placement="reel",
                        scheduled_at=datetime(2026, 9, 11, 16, tzinfo=UTC),
                        published_at=datetime(2026, 9, 13, 16, tzinfo=UTC),
                    )
                ],
            )
            session.add(item)
            await session.flush()

            scheduled = await campaign_calendar.list_events(
                session,
                workspace.id,
                CampaignCalendarEventQuery(
                    event_types=[
                        campaign_calendar.MARKETING_CONTENT_SCHEDULED,
                        campaign_calendar.MARKETING_CONTENT_CHANNEL_SCHEDULED,
                    ],
                    range_start=datetime(2026, 9, 10, tzinfo=UTC),
                    range_end=datetime(2026, 9, 11, 23, 59, tzinfo=UTC),
                ),
            )
            with_published = await campaign_calendar.list_events(
                session,
                workspace.id,
                CampaignCalendarEventQuery(
                    event_types=[
                        campaign_calendar.MARKETING_CONTENT_PUBLISHED,
                        campaign_calendar.MARKETING_CONTENT_CHANNEL_PUBLISHED,
                    ],
                    include_published=True,
                ),
            )
            return (
                [
                    (event.event_type, event.content_item_title or "", event.channel)
                    for event in scheduled
                ],
                [event.event_type for event in with_published],
            )

    scheduled, published = asyncio.run(run())

    assert scheduled == [
        (campaign_calendar.MARKETING_CONTENT_SCHEDULED, "Hero Clip", None),
        (
            campaign_calendar.MARKETING_CONTENT_CHANNEL_SCHEDULED,
            "Hero Clip",
            "instagram",
        ),
    ]
    assert published == [
        campaign_calendar.MARKETING_CONTENT_PUBLISHED,
        campaign_calendar.MARKETING_CONTENT_CHANNEL_PUBLISHED,
    ]


def test_campaign_calendar_projects_approval_timestamps_with_fallbacks(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, tuple[str, datetime, str | None]]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            requested_item = MarketingContentItem(
                organization=workspace,
                campaign=campaign,
                title="Approval Source",
                content_type="image",
                status=MarketingContentItemStatus.in_review,
                approval_requested_at=datetime(2026, 9, 4, 10, tzinfo=UTC),
            )
            fallback_item = MarketingContentItem(
                organization=workspace,
                campaign=campaign,
                title="Approval Fallback",
                content_type="image",
                status=MarketingContentItemStatus.in_review,
                approval_requested_at=datetime(2026, 9, 6, 10, tzinfo=UTC),
            )
            approved_item = MarketingContentItem(
                organization=workspace,
                campaign=campaign,
                title="Approved Source",
                content_type="image",
                status=MarketingContentItemStatus.approved,
            )
            session.add_all([requested_item, fallback_item, approved_item])
            await session.flush()
            requested = ApprovalRequest(
                organization=workspace,
                resource_type=MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                resource_id=requested_item.id,
                resource_revision=requested_item.content_revision,
                title="Request Approval Source",
                status=ApprovalRequestStatus.in_review,
                submitted_at=datetime(2026, 9, 5, 10, tzinfo=UTC),
            )
            approved = ApprovalRequest(
                organization=workspace,
                resource_type=MARKETING_CONTENT_ITEM_RESOURCE_TYPE,
                resource_id=approved_item.id,
                resource_revision=approved_item.content_revision,
                title="Request Approved Source",
                status=ApprovalRequestStatus.approved,
                submitted_at=datetime(2026, 9, 7, 10, tzinfo=UTC),
                resolved_at=datetime(2026, 9, 8, 10, tzinfo=UTC),
            )
            requested_item.approval_request = requested
            approved_item.approval_request = approved
            await session.flush()

            events = await campaign_calendar.list_events(
                session,
                workspace.id,
                CampaignCalendarEventQuery(
                    event_types=[
                        campaign_calendar.MARKETING_CONTENT_APPROVAL_REQUESTED,
                        campaign_calendar.MARKETING_CONTENT_APPROVED,
                    ]
                ),
            )
            return {
                event.content_item_title
                or "": (
                    event.source_type,
                    event.event_at,
                    event.status,
                )
                for event in events
            }

    events = asyncio.run(run())

    assert events == {
        "Approval Source": (
            "approval_request",
            datetime(2026, 9, 5, 10, tzinfo=UTC),
            "in_review",
        ),
        "Approval Fallback": (
            "marketing_content_item",
            datetime(2026, 9, 6, 10, tzinfo=UTC),
            "in_review",
        ),
        "Approved Source": (
            "approval_request",
            datetime(2026, 9, 8, 10, tzinfo=UTC),
            "approved",
        ),
    }


def test_campaign_calendar_filters_artist_release_status_archived_and_published(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[list[str], list[str], list[str], bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            linked_campaign = data["linked_campaign"]
            linked_artist = data["linked_artist"]
            linked_release = data["linked_release"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(linked_campaign, Campaign)
            assert isinstance(linked_artist, Artist)
            assert isinstance(linked_release, Release)
            archived_campaign = Campaign(
                name="Archived Campaign",
                organization=workspace,
                start_date=date(2026, 9, 20),
                status=CampaignStatus.archived,
            )
            archived_item = MarketingContentItem(
                organization=workspace,
                campaign=campaign,
                title="Archived Content",
                content_type="image",
                status=MarketingContentItemStatus.archived,
                scheduled_at=datetime(2026, 9, 21, 10, tzinfo=UTC),
            )
            session.add_all([archived_campaign, archived_item])
            await session.flush()

            artist_events = await campaign_calendar.list_events(
                session,
                workspace.id,
                CampaignCalendarEventQuery(artist_id=linked_artist.id),
            )
            release_events = await campaign_calendar.list_events(
                session,
                workspace.id,
                CampaignCalendarEventQuery(release_id=linked_release.id),
            )
            archived_events = await campaign_calendar.list_events(
                session,
                workspace.id,
                CampaignCalendarEventQuery(include_archived=True),
            )
            published_default = await campaign_calendar.list_events(
                session,
                workspace.id,
                CampaignCalendarEventQuery(
                    event_types=[
                        campaign_calendar.MARKETING_CONTENT_PUBLISHED,
                        campaign_calendar.MARKETING_CONTENT_CHANNEL_PUBLISHED,
                    ]
                ),
            )
            status_filtered = await campaign_calendar.list_events(
                session,
                workspace.id,
                CampaignCalendarEventQuery(statuses=[CampaignStatus.planning]),
            )
            return (
                [event.campaign_name for event in artist_events],
                [event.release_title or "" for event in release_events],
                [event.title for event in archived_events],
                published_default == []
                and [event.campaign_name for event in status_filtered]
                == ["Linked Campaign"],
            )

    artist_campaigns, release_titles, archived_titles, filtered = asyncio.run(run())

    assert artist_campaigns == ["Linked Campaign"]
    assert release_titles == ["Linked Release"]
    assert "Archived Campaign starts" in archived_titles
    assert "Archived Content" in archived_titles
    assert filtered is True
