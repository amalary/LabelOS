import asyncio
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from labelos_database.base import Base
from labelos_database.models import (
    Artist,
    ArtistProfile,
    Campaign,
    CampaignGoal,
    CampaignMilestone,
    Organization,
    UniversalProfile,
    User,
    WorkspaceMembership,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from labelos_api.services.analytics_service import (
    AnalyticsAggregation,
    AnalyticsMetricDefinitionCreate,
    AnalyticsNotFoundError,
    AnalyticsObservationCreate,
    AnalyticsObservationQuery,
    AnalyticsProviderRef,
    AnalyticsRelationshipError,
    compare_previous_period,
    create_metric_definition,
    create_observation,
    get_historical_series,
    get_latest_observation,
    list_observations,
    list_observations_by_artist_profile,
    list_observations_by_campaign,
    list_observations_by_campaign_child_object,
    list_observations_by_date_range,
    list_observations_by_metric_definition,
    list_observations_by_provider,
    list_observations_by_workspace,
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
        slug="alpha-analytics-service",
        owner=User(email="owner-alpha-analytics@example.com"),
    )
    other_workspace = Organization(
        name="Beta Label",
        slug="beta-analytics-service",
        owner=User(email="owner-beta-analytics@example.com"),
    )
    profile = UniversalProfile(
        user=User(email="artist-alpha-analytics@example.com"),
        slug="artist-alpha-analytics",
    )
    other_profile = UniversalProfile(
        user=User(email="artist-beta-analytics@example.com"),
        slug="artist-beta-analytics",
    )
    WorkspaceMembership(workspace=workspace, profile=profile)
    WorkspaceMembership(workspace=other_workspace, profile=other_profile)
    artist = Artist(name="Alpha Artist", organization=workspace)
    other_artist = Artist(name="Beta Artist", organization=other_workspace)
    artist_profile = ArtistProfile(
        artist=artist,
        universal_profile=profile,
        stage_name="Alpha Artist",
    )
    other_artist_profile = ArtistProfile(
        artist=other_artist,
        universal_profile=other_profile,
        stage_name="Beta Artist",
    )
    campaign = Campaign(name="Alpha Campaign", organization=workspace)
    other_campaign = Campaign(name="Beta Campaign", organization=other_workspace)
    campaign_goal = CampaignGoal(campaign=campaign, title="Pre-save Goal")
    campaign_milestone = CampaignMilestone(
        campaign=campaign,
        title="Creative Approved",
    )
    other_campaign_goal = CampaignGoal(campaign=other_campaign, title="Outside Goal")
    session.add_all(
        [
            artist_profile,
            other_artist_profile,
            campaign_goal,
            campaign_milestone,
            other_campaign_goal,
        ]
    )
    await session.flush()
    return {
        "workspace": workspace,
        "other_workspace": other_workspace,
        "artist_profile": artist_profile,
        "other_artist_profile": other_artist_profile,
        "campaign": campaign,
        "other_campaign": other_campaign,
        "campaign_goal": campaign_goal,
        "campaign_milestone": campaign_milestone,
        "other_campaign_goal": other_campaign_goal,
    }


async def _create_streams_metric(session: AsyncSession, workspace_id):
    return await create_metric_definition(
        session,
        workspace_id,
        AnalyticsMetricDefinitionCreate(
            key="streams",
            display_name="Streams",
            value_type="integer",
            default_unit="count",
            aggregation="sum",
            provider=AnalyticsProviderRef(
                key="internal",
                display_name="Internal Analytics",
            ),
        ),
    )


def test_analytics_service_records_historical_observations(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[list[Decimal | None], int, str | None, str]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            metric = await _create_streams_metric(session, workspace.id)
            older_observed_at = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
            newer_observed_at = older_observed_at + timedelta(days=1)

            await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="campaign",
                    campaign_id=campaign.id,
                    observed_at=older_observed_at,
                    value_numeric=100,
                    dimensions={"market": "US"},
                    idempotency_key="campaign-streams-older",
                ),
            )
            newer = await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="campaign",
                    campaign_id=campaign.id,
                    observed_at=newer_observed_at,
                    value_numeric=125,
                    source_record_id="provider-row-2",
                ),
            )
            page = await list_observations(
                session,
                workspace.id,
                metric_definition_id=metric.id,
                campaign_id=campaign.id,
            )

            return (
                [observation.value_numeric for observation in page.observations],
                page.total,
                newer.unit,
                page.observations[0].metric_definition.key,
            )

    assert asyncio.run(run()) == (
        [Decimal("125.000000"), Decimal("100.000000")],
        2,
        "count",
        "streams",
    )


def test_analytics_service_deduplicates_by_workspace_provider_idempotency_key(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[bool, Decimal | None, int]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            metric = await _create_streams_metric(session, workspace.id)
            observed_at = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
            first = await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="campaign",
                    campaign_id=campaign.id,
                    observed_at=observed_at,
                    value_numeric=100,
                    idempotency_key="dup-key",
                ),
            )
            duplicate = await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="campaign",
                    campaign_id=campaign.id,
                    observed_at=observed_at,
                    value_numeric=200,
                    idempotency_key="dup-key",
                ),
            )
            page = await list_observations(session, workspace.id)
            return first.id == duplicate.id, duplicate.value_numeric, page.total

    assert asyncio.run(run()) == (True, Decimal("100.000000"), 1)


def test_analytics_service_blocks_cross_workspace_targets(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[bool, bool]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            other_campaign = data["other_campaign"]
            other_artist_profile = data["other_artist_profile"]
            other_campaign_goal = data["other_campaign_goal"]
            assert isinstance(workspace, Organization)
            assert isinstance(other_campaign, Campaign)
            assert isinstance(other_artist_profile, ArtistProfile)
            assert isinstance(other_campaign_goal, CampaignGoal)
            metric = await _create_streams_metric(session, workspace.id)
            campaign_blocked = False
            artist_profile_blocked = False
            campaign_object_blocked = False
            try:
                await create_observation(
                    session,
                    workspace.id,
                    AnalyticsObservationCreate(
                        metric_definition_id=metric.id,
                        target_type="campaign",
                        campaign_id=other_campaign.id,
                        observed_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
                        value_numeric=1,
                    ),
                )
            except AnalyticsNotFoundError:
                campaign_blocked = True
            try:
                await create_observation(
                    session,
                    workspace.id,
                    AnalyticsObservationCreate(
                        metric_definition_id=metric.id,
                        target_type="artist_profile",
                        artist_profile_id=other_artist_profile.id,
                        observed_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
                        value_numeric=1,
                    ),
                )
            except AnalyticsNotFoundError:
                artist_profile_blocked = True
            try:
                await create_observation(
                    session,
                    workspace.id,
                    AnalyticsObservationCreate(
                        metric_definition_id=metric.id,
                        target_type="campaign_object",
                        campaign_id=other_campaign.id,
                        campaign_object_type="goal",
                        campaign_object_id=other_campaign_goal.id,
                        observed_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
                        value_numeric=1,
                    ),
                )
            except AnalyticsNotFoundError:
                campaign_object_blocked = True
            return campaign_blocked, artist_profile_blocked, campaign_object_blocked

    assert asyncio.run(run()) == (True, True, True)


def test_analytics_service_supports_future_campaign_object_targets(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[str, bool, Decimal | None]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            campaign_goal = data["campaign_goal"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            assert isinstance(campaign_goal, CampaignGoal)
            metric = await _create_streams_metric(session, workspace.id)
            observation = await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="campaign_object",
                    campaign_id=campaign.id,
                    campaign_object_type="goal",
                    campaign_object_id=campaign_goal.id,
                    observed_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
                    value_numeric=25,
                ),
            )
            return (
                observation.target_type,
                observation.target_id == campaign_goal.id,
                observation.value_numeric,
            )

    assert asyncio.run(run()) == ("campaign_object", True, Decimal("25.000000"))


def test_analytics_service_validates_metric_value_type(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> bool:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            assert isinstance(workspace, Organization)
            metric = await _create_streams_metric(session, workspace.id)
            try:
                await create_observation(
                    session,
                    workspace.id,
                    AnalyticsObservationCreate(
                        metric_definition_id=metric.id,
                        target_type="workspace",
                        observed_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
                        value_text="not numeric",
                    ),
                )
            except AnalyticsRelationshipError:
                return True
            return False

    assert asyncio.run(run()) is True


def test_analytics_service_exposes_reporting_query_operations(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[int, int, int, int, int, int, int]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            artist_profile = data["artist_profile"]
            campaign = data["campaign"]
            campaign_goal = data["campaign_goal"]
            assert isinstance(workspace, Organization)
            assert isinstance(artist_profile, ArtistProfile)
            assert isinstance(campaign, Campaign)
            assert isinstance(campaign_goal, CampaignGoal)
            metric = await _create_streams_metric(session, workspace.id)
            observed_at = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
            await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="workspace",
                    observed_at=observed_at,
                    value_numeric=10,
                ),
            )
            await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="artist_profile",
                    artist_profile_id=artist_profile.id,
                    observed_at=observed_at + timedelta(hours=1),
                    value_numeric=20,
                ),
            )
            await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="campaign",
                    campaign_id=campaign.id,
                    observed_at=observed_at + timedelta(hours=2),
                    value_numeric=30,
                ),
            )
            await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="campaign_object",
                    campaign_id=campaign.id,
                    campaign_object_type="goal",
                    campaign_object_id=campaign_goal.id,
                    observed_at=observed_at + timedelta(hours=3),
                    value_numeric=40,
                ),
            )
            workspace_page = await list_observations_by_workspace(
                session,
                workspace.id,
            )
            artist_page = await list_observations_by_artist_profile(
                session,
                workspace.id,
                artist_profile.id,
            )
            campaign_page = await list_observations_by_campaign(
                session,
                workspace.id,
                campaign.id,
            )
            child_page = await list_observations_by_campaign_child_object(
                session,
                workspace.id,
                campaign.id,
                "goal",
                campaign_goal.id,
            )
            metric_page = await list_observations_by_metric_definition(
                session,
                workspace.id,
                metric.id,
            )
            provider_page = await list_observations_by_provider(
                session,
                workspace.id,
                metric.provider_id,
            )
            date_page = await list_observations_by_date_range(
                session,
                workspace.id,
                observed_at + timedelta(minutes=30),
                observed_at + timedelta(hours=2, minutes=30),
            )
            return (
                workspace_page.total,
                artist_page.total,
                campaign_page.total,
                child_page.total,
                metric_page.total,
                provider_page.total,
                date_page.total,
            )

    assert asyncio.run(run()) == (1, 1, 2, 1, 4, 4, 2)


def test_analytics_service_returns_latest_observation_for_query(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> Decimal | None:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            metric = await _create_streams_metric(session, workspace.id)
            base = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
            await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="campaign",
                    campaign_id=campaign.id,
                    observed_at=base,
                    value_numeric=100,
                ),
            )
            await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="campaign",
                    campaign_id=campaign.id,
                    observed_at=base + timedelta(days=1),
                    value_numeric=125,
                ),
            )
            latest = await get_latest_observation(
                session,
                workspace.id,
                query=AnalyticsObservationQuery(
                    metric_definition_id=metric.id,
                    campaign_id=campaign.id,
                ),
            )
            return latest.value_numeric if latest else None

    assert asyncio.run(run()) == Decimal("125.000000")


def test_analytics_service_builds_sparse_historical_series_with_duplicates(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[tuple[date, Decimal | None, int], ...]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            metric = await _create_streams_metric(session, workspace.id)
            first_day = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
            for value in (100, 50):
                await create_observation(
                    session,
                    workspace.id,
                    AnalyticsObservationCreate(
                        metric_definition_id=metric.id,
                        target_type="campaign",
                        campaign_id=campaign.id,
                        observed_at=first_day,
                        value_numeric=value,
                    ),
                )
            await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="campaign",
                    campaign_id=campaign.id,
                    observed_at=first_day + timedelta(days=2),
                    value_numeric=25,
                ),
            )
            series = await get_historical_series(
                session,
                workspace.id,
                query=AnalyticsObservationQuery(
                    metric_definition_id=metric.id,
                    campaign_id=campaign.id,
                ),
                aggregation=AnalyticsAggregation.sum,
            )
            return tuple(
                (point.bucket_date, point.value, point.observation_count)
                for point in series.points
            )

    assert asyncio.run(run()) == (
        (date(2026, 8, 27), Decimal("150.000000"), 2),
        (date(2026, 8, 29), Decimal("25.000000"), 1),
    )


def test_analytics_service_blocks_invalid_numeric_aggregations(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[bool, Decimal | None, str | bool | dict | None]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            text_metric = await create_metric_definition(
                session,
                workspace.id,
                AnalyticsMetricDefinitionCreate(
                    key="sentiment",
                    display_name="Sentiment",
                    value_type="string",
                    aggregation="latest",
                    provider=AnalyticsProviderRef(key="internal"),
                ),
            )
            observed_at = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
            await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=text_metric.id,
                    target_type="campaign",
                    campaign_id=campaign.id,
                    observed_at=observed_at,
                    value_text="positive",
                ),
            )
            blocked = False
            try:
                await get_historical_series(
                    session,
                    workspace.id,
                    query=AnalyticsObservationQuery(
                        metric_definition_id=text_metric.id,
                        campaign_id=campaign.id,
                    ),
                    aggregation=AnalyticsAggregation.sum,
                )
            except AnalyticsRelationshipError:
                blocked = True
            counted = await get_historical_series(
                session,
                workspace.id,
                query=AnalyticsObservationQuery(
                    metric_definition_id=text_metric.id,
                    campaign_id=campaign.id,
                ),
                aggregation=AnalyticsAggregation.count,
            )
            latest = await get_historical_series(
                session,
                workspace.id,
                query=AnalyticsObservationQuery(
                    metric_definition_id=text_metric.id,
                    campaign_id=campaign.id,
                ),
                aggregation=AnalyticsAggregation.latest,
            )
            return blocked, counted.points[0].value, latest.points[0].value

    assert asyncio.run(run()) == (True, Decimal("1"), "positive")


def test_analytics_service_blocks_mixed_units_for_numeric_aggregation(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[bool, Decimal | None]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            metric = await _create_streams_metric(session, workspace.id)
            observed_at = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
            await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="campaign",
                    campaign_id=campaign.id,
                    observed_at=observed_at,
                    value_numeric=10,
                    unit="count",
                ),
            )
            await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="campaign",
                    campaign_id=campaign.id,
                    observed_at=observed_at + timedelta(hours=1),
                    value_numeric=20,
                    unit="plays",
                ),
            )
            blocked = False
            try:
                await get_historical_series(
                    session,
                    workspace.id,
                    query=AnalyticsObservationQuery(
                        metric_definition_id=metric.id,
                        campaign_id=campaign.id,
                    ),
                    aggregation=AnalyticsAggregation.sum,
                )
            except AnalyticsRelationshipError:
                blocked = True
            counted = await get_historical_series(
                session,
                workspace.id,
                query=AnalyticsObservationQuery(
                    metric_definition_id=metric.id,
                    campaign_id=campaign.id,
                ),
                aggregation=AnalyticsAggregation.count,
            )
            return blocked, counted.points[0].value

    assert asyncio.run(run()) == (True, Decimal("2"))


def test_analytics_service_previous_period_comparison(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[Decimal | None, Decimal | None, Decimal | None, str]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            metric = await _create_streams_metric(session, workspace.id)
            start = datetime(2026, 8, 22, 0, 0, tzinfo=UTC)
            current_start = start + timedelta(days=7)
            current_end = current_start + timedelta(days=7)
            await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="campaign",
                    campaign_id=campaign.id,
                    observed_at=start + timedelta(days=1),
                    value_numeric=50,
                ),
            )
            await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="campaign",
                    campaign_id=campaign.id,
                    observed_at=current_start + timedelta(days=1),
                    value_numeric=75,
                ),
            )
            await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="campaign",
                    campaign_id=campaign.id,
                    observed_at=current_start + timedelta(days=2),
                    value_numeric=25,
                ),
            )
            comparison = await compare_previous_period(
                session,
                workspace.id,
                current_start=current_start,
                current_end=current_end,
                query=AnalyticsObservationQuery(
                    metric_definition_id=metric.id,
                    campaign_id=campaign.id,
                ),
                aggregation=AnalyticsAggregation.sum,
            )
            return (
                comparison.current_value,
                comparison.previous_value,
                comparison.percentage_change,
                comparison.status.value,
            )

    assert asyncio.run(run()) == (
        Decimal("100.000000"),
        Decimal("50.000000"),
        Decimal("1.000000"),
        "compared",
    )


def test_analytics_service_previous_period_handles_edge_cases(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> tuple[str, str, str, Decimal | None]:
        async with sessionmaker() as session:
            data = await _seed_workspace_graph(session)
            workspace = data["workspace"]
            campaign = data["campaign"]
            assert isinstance(workspace, Organization)
            assert isinstance(campaign, Campaign)
            metric = await _create_streams_metric(session, workspace.id)
            current_start = datetime(2026, 8, 29, 0, 0, tzinfo=UTC)
            current_end = current_start + timedelta(days=7)
            no_previous = await compare_previous_period(
                session,
                workspace.id,
                current_start=current_start,
                current_end=current_end,
                query=AnalyticsObservationQuery(
                    metric_definition_id=metric.id,
                    campaign_id=campaign.id,
                ),
                aggregation=AnalyticsAggregation.sum,
            )
            await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="campaign",
                    campaign_id=campaign.id,
                    observed_at=current_start + timedelta(hours=1),
                    value_numeric=5,
                ),
            )
            no_previous_period = await compare_previous_period(
                session,
                workspace.id,
                current_start=current_start,
                current_end=current_end,
                query=AnalyticsObservationQuery(
                    metric_definition_id=metric.id,
                    campaign_id=campaign.id,
                ),
                aggregation=AnalyticsAggregation.sum,
            )
            await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="campaign",
                    campaign_id=campaign.id,
                    observed_at=current_start - timedelta(days=1),
                    value_numeric=0,
                ),
            )
            await create_observation(
                session,
                workspace.id,
                AnalyticsObservationCreate(
                    metric_definition_id=metric.id,
                    target_type="campaign",
                    campaign_id=campaign.id,
                    observed_at=current_start + timedelta(days=1),
                    value_numeric=10,
                ),
            )
            zero_denominator = await compare_previous_period(
                session,
                workspace.id,
                current_start=current_start,
                current_end=current_end,
                query=AnalyticsObservationQuery(
                    metric_definition_id=metric.id,
                    campaign_id=campaign.id,
                ),
                aggregation=AnalyticsAggregation.sum,
            )
            return (
                no_previous.status.value,
                no_previous_period.status.value,
                zero_denominator.status.value,
                zero_denominator.percentage_change,
            )

    assert asyncio.run(run()) == (
        "no_current_data",
        "no_previous_period",
        "zero_previous_value",
        None,
    )
