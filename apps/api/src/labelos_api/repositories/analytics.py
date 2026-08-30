from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from labelos_database.models import (
    AnalyticsMetricDefinition,
    AnalyticsObservation,
    AnalyticsProvider,
    Artist,
    ArtistProfile,
    Campaign,
    CampaignGoal,
    CampaignMilestone,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


def _observation_load_options():
    return (
        selectinload(AnalyticsObservation.metric_definition),
        selectinload(AnalyticsObservation.provider),
        selectinload(AnalyticsObservation.campaign),
    )


@dataclass(frozen=True, kw_only=True)
class AnalyticsObservationListPage:
    observations: list[AnalyticsObservation]
    total: int
    limit: int
    offset: int


async def get_provider_by_key(
    session: AsyncSession,
    workspace_id: UUID,
    key: str,
) -> AnalyticsProvider | None:
    return await session.scalar(
        select(AnalyticsProvider)
        .where(AnalyticsProvider.organization_id == workspace_id)
        .where(AnalyticsProvider.key == key)
    )


async def get_provider(
    session: AsyncSession,
    workspace_id: UUID,
    provider_id: UUID,
) -> AnalyticsProvider | None:
    return await session.scalar(
        select(AnalyticsProvider)
        .where(AnalyticsProvider.organization_id == workspace_id)
        .where(AnalyticsProvider.id == provider_id)
    )


async def create_provider(
    session: AsyncSession,
    workspace_id: UUID,
    values: Mapping[str, object],
) -> AnalyticsProvider:
    provider = AnalyticsProvider(organization_id=workspace_id, **dict(values))
    session.add(provider)
    await session.flush()
    return provider


async def list_metric_definitions(
    session: AsyncSession,
    workspace_id: UUID,
) -> list[AnalyticsMetricDefinition]:
    rows = await session.scalars(
        select(AnalyticsMetricDefinition)
        .options(selectinload(AnalyticsMetricDefinition.provider))
        .where(AnalyticsMetricDefinition.organization_id == workspace_id)
        .order_by(
            AnalyticsMetricDefinition.key.asc(), AnalyticsMetricDefinition.id.asc()
        )
    )
    return list(rows.all())


async def get_metric_definition(
    session: AsyncSession,
    workspace_id: UUID,
    metric_definition_id: UUID,
) -> AnalyticsMetricDefinition | None:
    return await session.scalar(
        select(AnalyticsMetricDefinition)
        .options(selectinload(AnalyticsMetricDefinition.provider))
        .where(AnalyticsMetricDefinition.organization_id == workspace_id)
        .where(AnalyticsMetricDefinition.id == metric_definition_id)
    )


async def get_metric_definition_by_key(
    session: AsyncSession,
    workspace_id: UUID,
    provider_id: UUID,
    key: str,
) -> AnalyticsMetricDefinition | None:
    return await session.scalar(
        select(AnalyticsMetricDefinition)
        .options(selectinload(AnalyticsMetricDefinition.provider))
        .where(AnalyticsMetricDefinition.organization_id == workspace_id)
        .where(AnalyticsMetricDefinition.provider_id == provider_id)
        .where(AnalyticsMetricDefinition.key == key)
    )


async def create_metric_definition(
    session: AsyncSession,
    workspace_id: UUID,
    values: Mapping[str, object],
) -> AnalyticsMetricDefinition:
    metric_definition = AnalyticsMetricDefinition(
        organization_id=workspace_id,
        **dict(values),
    )
    session.add(metric_definition)
    await session.flush()
    return metric_definition


async def get_observation_by_idempotency_key(
    session: AsyncSession,
    workspace_id: UUID,
    provider_id: UUID,
    idempotency_key: str,
) -> AnalyticsObservation | None:
    return await session.scalar(
        select(AnalyticsObservation)
        .options(*_observation_load_options())
        .where(AnalyticsObservation.organization_id == workspace_id)
        .where(AnalyticsObservation.provider_id == provider_id)
        .where(AnalyticsObservation.idempotency_key == idempotency_key)
    )


async def create_observation(
    session: AsyncSession,
    workspace_id: UUID,
    values: Mapping[str, object],
) -> AnalyticsObservation:
    observation = AnalyticsObservation(organization_id=workspace_id, **dict(values))
    session.add(observation)
    await session.flush()
    return observation


async def list_observations(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    metric_definition_id: UUID | None = None,
    provider_id: UUID | None = None,
    target_type: str | None = None,
    target_id: UUID | None = None,
    campaign_id: UUID | None = None,
    artist_profile_id: UUID | None = None,
    campaign_object_type: str | None = None,
    campaign_object_id: UUID | None = None,
    observed_start: datetime | None = None,
    observed_end: datetime | None = None,
    observed_before: datetime | None = None,
    limit: int,
    offset: int,
    sort_desc: bool = True,
) -> AnalyticsObservationListPage:
    statement = select(AnalyticsObservation).where(
        AnalyticsObservation.organization_id == workspace_id
    )
    if metric_definition_id is not None:
        statement = statement.where(
            AnalyticsObservation.metric_definition_id == metric_definition_id
        )
    if provider_id is not None:
        statement = statement.where(AnalyticsObservation.provider_id == provider_id)
    if target_type is not None:
        statement = statement.where(AnalyticsObservation.target_type == target_type)
    if target_id is not None:
        statement = statement.where(AnalyticsObservation.target_id == target_id)
    if campaign_id is not None:
        statement = statement.where(AnalyticsObservation.campaign_id == campaign_id)
    if artist_profile_id is not None:
        statement = statement.where(
            AnalyticsObservation.artist_profile_id == artist_profile_id
        )
    if campaign_object_type is not None:
        statement = statement.where(
            AnalyticsObservation.campaign_object_type == campaign_object_type
        )
    if campaign_object_id is not None:
        statement = statement.where(
            AnalyticsObservation.campaign_object_id == campaign_object_id
        )
    if observed_start is not None:
        statement = statement.where(AnalyticsObservation.observed_at >= observed_start)
    if observed_end is not None:
        statement = statement.where(AnalyticsObservation.observed_at <= observed_end)
    if observed_before is not None:
        statement = statement.where(AnalyticsObservation.observed_at < observed_before)

    total = await session.scalar(select(func.count()).select_from(statement.subquery()))
    ordering = (
        (
            AnalyticsObservation.observed_at.desc(),
            AnalyticsObservation.created_at.desc(),
            AnalyticsObservation.id.desc(),
        )
        if sort_desc
        else (
            AnalyticsObservation.observed_at.asc(),
            AnalyticsObservation.created_at.asc(),
            AnalyticsObservation.id.asc(),
        )
    )
    rows = await session.scalars(
        statement.options(*_observation_load_options())
        .order_by(*ordering)
        .limit(limit)
        .offset(offset)
    )
    return AnalyticsObservationListPage(
        observations=list(rows.all()),
        total=total or 0,
        limit=limit,
        offset=offset,
    )


async def get_latest_observation(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    metric_definition_id: UUID | None = None,
    provider_id: UUID | None = None,
    target_type: str | None = None,
    target_id: UUID | None = None,
    campaign_id: UUID | None = None,
    artist_profile_id: UUID | None = None,
    campaign_object_type: str | None = None,
    campaign_object_id: UUID | None = None,
    observed_start: datetime | None = None,
    observed_end: datetime | None = None,
    observed_before: datetime | None = None,
) -> AnalyticsObservation | None:
    page = await list_observations(
        session,
        workspace_id,
        metric_definition_id=metric_definition_id,
        provider_id=provider_id,
        target_type=target_type,
        target_id=target_id,
        campaign_id=campaign_id,
        artist_profile_id=artist_profile_id,
        campaign_object_type=campaign_object_type,
        campaign_object_id=campaign_object_id,
        observed_start=observed_start,
        observed_end=observed_end,
        observed_before=observed_before,
        limit=1,
        offset=0,
    )
    return page.observations[0] if page.observations else None


async def artist_profile_in_workspace(
    session: AsyncSession,
    workspace_id: UUID,
    artist_profile_id: UUID,
) -> bool:
    return (
        await session.scalar(
            select(ArtistProfile.id)
            .join(ArtistProfile.artist)
            .where(ArtistProfile.id == artist_profile_id)
            .where(Artist.organization_id == workspace_id)
        )
        is not None
    )


async def campaign_in_workspace(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
) -> bool:
    return (
        await session.scalar(
            select(Campaign.id)
            .where(Campaign.id == campaign_id)
            .where(Campaign.organization_id == workspace_id)
        )
        is not None
    )


async def campaign_goal_in_workspace(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    goal_id: UUID,
) -> bool:
    return (
        await session.scalar(
            select(CampaignGoal.id)
            .join(CampaignGoal.campaign)
            .where(CampaignGoal.id == goal_id)
            .where(CampaignGoal.campaign_id == campaign_id)
            .where(Campaign.organization_id == workspace_id)
        )
        is not None
    )


async def campaign_milestone_in_workspace(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    milestone_id: UUID,
) -> bool:
    return (
        await session.scalar(
            select(CampaignMilestone.id)
            .join(CampaignMilestone.campaign)
            .where(CampaignMilestone.id == milestone_id)
            .where(CampaignMilestone.campaign_id == campaign_id)
            .where(Campaign.organization_id == workspace_id)
        )
        is not None
    )
