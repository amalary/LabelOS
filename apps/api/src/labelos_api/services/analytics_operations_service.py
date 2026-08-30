from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from labelos_database.models import AnalyticsMetricValueType, AnalyticsObservation
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.authorization import AuthorizationActorInput
from labelos_api.services.analytics_service import (
    AnalyticsAggregation,
    AnalyticsHistoricalSeries,
    AnalyticsObservationQuery,
    AnalyticsPreviousPeriodComparison,
    AnalyticsRelationshipError,
    _aggregate_observations,
    _list_observations_for_query,
    _normalize_aggregation,
    _require_numeric_aggregation_context,
    compare_previous_period,
    get_historical_series,
    get_latest_observation,
    list_metric_definitions,
    list_observations,
)


class AnalyticsOperation(StrEnum):
    summarize_campaign_metrics = "summarize_campaign_metrics"
    retrieve_artist_metric_trends = "retrieve_artist_metric_trends"
    compare_campaigns = "compare_campaigns"
    compare_campaign_goals = "compare_campaign_goals"
    compare_campaign_milestones = "compare_campaign_milestones"
    retrieve_latest_metric_values = "retrieve_latest_metric_values"
    retrieve_previous_period_changes = "retrieve_previous_period_changes"
    retrieve_provider_analytics = "retrieve_provider_analytics"
    retrieve_analytics_date_range = "retrieve_analytics_date_range"


class AnalyticsObjectType(StrEnum):
    campaign = "campaign"
    artist_profile = "artist_profile"
    goal = "goal"
    milestone = "milestone"
    workspace = "workspace"


@dataclass(frozen=True, kw_only=True)
class AnalyticsMetricSelector:
    metric_definition_id: UUID | None = None
    metric_key: str | None = None
    provider_id: UUID | None = None
    provider_key: str | None = None


@dataclass(frozen=True, kw_only=True)
class AnalyticsDateRange:
    observed_start: datetime | None = None
    observed_end: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class AnalyticsObjectRef:
    object_type: AnalyticsObjectType | str
    object_id: UUID
    campaign_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class AnalyticsMetricValue:
    metric_definition_id: UUID
    metric_key: str
    provider_id: UUID
    provider_key: str
    value_type: AnalyticsMetricValueType
    unit: str | None
    value: Decimal | str | bool | dict[str, Any] | None


@dataclass(frozen=True, kw_only=True)
class AnalyticsAggregatedMetricValue(AnalyticsMetricValue):
    aggregation: AnalyticsAggregation
    observation_count: int


@dataclass(frozen=True, kw_only=True)
class AnalyticsLatestMetricValue(AnalyticsMetricValue):
    observed_at: datetime
    target_type: str
    target_id: UUID | None
    campaign_id: UUID | None
    campaign_object_type: str | None
    campaign_object_id: UUID | None


@dataclass(frozen=True, kw_only=True)
class AnalyticsObjectMetricSet:
    target: AnalyticsObjectRef
    metrics: tuple[AnalyticsAggregatedMetricValue, ...]


@dataclass(frozen=True, kw_only=True)
class AnalyticsComparisonResult:
    operation: AnalyticsOperation
    workspace_id: UUID
    targets: tuple[AnalyticsObjectMetricSet, ...]


@dataclass(frozen=True, kw_only=True)
class CampaignMetricsSummary:
    operation: AnalyticsOperation
    workspace_id: UUID
    campaign_id: UUID
    metrics: tuple[AnalyticsAggregatedMetricValue, ...]


@dataclass(frozen=True, kw_only=True)
class ArtistMetricTrends:
    operation: AnalyticsOperation
    workspace_id: UUID
    artist_profile_id: UUID
    series: AnalyticsHistoricalSeries


@dataclass(frozen=True, kw_only=True)
class LatestMetricValuesResult:
    operation: AnalyticsOperation
    workspace_id: UUID
    target: AnalyticsObjectRef | None
    values: tuple[AnalyticsLatestMetricValue, ...]


@dataclass(frozen=True, kw_only=True)
class PreviousPeriodChangesResult:
    operation: AnalyticsOperation
    workspace_id: UUID
    changes: tuple[AnalyticsPreviousPeriodComparison, ...]


@dataclass(frozen=True, kw_only=True)
class ProviderAnalyticsResult:
    operation: AnalyticsOperation
    workspace_id: UUID
    provider_id: UUID | None
    provider_key: str | None
    metrics: tuple[AnalyticsAggregatedMetricValue, ...]


@dataclass(frozen=True, kw_only=True)
class AnalyticsDateRangeResult:
    operation: AnalyticsOperation
    workspace_id: UUID
    date_range: AnalyticsDateRange
    metrics: tuple[AnalyticsAggregatedMetricValue, ...]


def _normalize_object_type(value: AnalyticsObjectType | str) -> AnalyticsObjectType:
    try:
        return (
            value
            if isinstance(value, AnalyticsObjectType)
            else AnalyticsObjectType(value)
        )
    except ValueError as exc:
        raise AnalyticsRelationshipError("Unsupported analytics object type") from exc


def _validate_date_range(date_range: AnalyticsDateRange | None) -> None:
    if (
        date_range is not None
        and date_range.observed_start is not None
        and date_range.observed_end is not None
        and date_range.observed_end < date_range.observed_start
    ):
        raise AnalyticsRelationshipError("observed_end must be after observed_start")


def _observation_typed_value(
    observation: AnalyticsObservation,
) -> Decimal | str | bool | dict[str, Any] | None:
    value_type = observation.metric_definition.value_type
    if value_type in {
        AnalyticsMetricValueType.decimal,
        AnalyticsMetricValueType.integer,
    }:
        return observation.value_numeric
    if value_type == AnalyticsMetricValueType.string:
        return observation.value_text
    if value_type == AnalyticsMetricValueType.boolean:
        return observation.value_boolean
    return observation.value_json


def _latest_metric_value(
    observation: AnalyticsObservation,
) -> AnalyticsLatestMetricValue:
    return AnalyticsLatestMetricValue(
        metric_definition_id=observation.metric_definition_id,
        metric_key=observation.metric_definition.key,
        provider_id=observation.provider_id,
        provider_key=observation.provider.key,
        value_type=observation.metric_definition.value_type,
        unit=observation.unit,
        value=_observation_typed_value(observation),
        observed_at=observation.observed_at,
        target_type=observation.target_type,
        target_id=observation.target_id,
        campaign_id=observation.campaign_id,
        campaign_object_type=observation.campaign_object_type,
        campaign_object_id=observation.campaign_object_id,
    )


def _target_query(target: AnalyticsObjectRef | None) -> AnalyticsObservationQuery:
    if target is None:
        return AnalyticsObservationQuery()
    object_type = _normalize_object_type(target.object_type)
    if object_type == AnalyticsObjectType.workspace:
        return AnalyticsObservationQuery(
            target_type="workspace",
            target_id=target.object_id,
        )
    if object_type == AnalyticsObjectType.artist_profile:
        return AnalyticsObservationQuery(artist_profile_id=target.object_id)
    if object_type == AnalyticsObjectType.campaign:
        return AnalyticsObservationQuery(campaign_id=target.object_id)
    if target.campaign_id is None:
        raise AnalyticsRelationshipError(
            "campaign_id is required for campaign child analytics targets"
        )
    return AnalyticsObservationQuery(
        target_type="campaign_object",
        target_id=target.object_id,
        campaign_id=target.campaign_id,
        campaign_object_type=object_type.value,
        campaign_object_id=target.object_id,
    )


def _merge_query(
    base: AnalyticsObservationQuery,
    *,
    selector: AnalyticsMetricSelector | None = None,
    date_range: AnalyticsDateRange | None = None,
) -> AnalyticsObservationQuery:
    return AnalyticsObservationQuery(
        metric_definition_id=selector.metric_definition_id if selector else None,
        provider_id=selector.provider_id if selector else None,
        target_type=base.target_type,
        target_id=base.target_id,
        artist_profile_id=base.artist_profile_id,
        campaign_id=base.campaign_id,
        campaign_object_type=base.campaign_object_type,
        campaign_object_id=base.campaign_object_id,
        observed_start=date_range.observed_start if date_range else None,
        observed_end=date_range.observed_end if date_range else None,
    )


def _series_metric_value(
    *,
    metric_definition_id: UUID,
    metric_key: str,
    provider_id: UUID,
    provider_key: str,
    value_type: AnalyticsMetricValueType,
    unit: str | None,
    aggregation: AnalyticsAggregation,
    value: Decimal | str | bool | dict[str, Any] | None,
    observation_count: int,
) -> AnalyticsAggregatedMetricValue:
    return AnalyticsAggregatedMetricValue(
        metric_definition_id=metric_definition_id,
        metric_key=metric_key,
        provider_id=provider_id,
        provider_key=provider_key,
        value_type=value_type,
        unit=unit,
        value=value,
        aggregation=aggregation,
        observation_count=observation_count,
    )


async def _resolve_metric_selectors(
    session: AsyncSession,
    workspace_id: UUID,
    selectors: tuple[AnalyticsMetricSelector, ...],
    *,
    actor: AuthorizationActorInput | None,
) -> tuple[AnalyticsMetricSelector, ...]:
    if not selectors:
        definitions = await list_metric_definitions(session, workspace_id, actor=actor)
        return tuple(
            AnalyticsMetricSelector(metric_definition_id=definition.id)
            for definition in definitions
        )

    definitions_by_key = None
    resolved: list[AnalyticsMetricSelector] = []
    for selector in selectors:
        if selector.metric_definition_id is not None:
            resolved.append(selector)
            continue
        if selector.metric_key is None and (
            selector.provider_id is not None or selector.provider_key is not None
        ):
            if definitions_by_key is None:
                definitions = await list_metric_definitions(
                    session,
                    workspace_id,
                    actor=actor,
                )
                definitions_by_key = {
                    (definition.provider.key, definition.key): definition
                    for definition in definitions
                }
            resolved.extend(
                AnalyticsMetricSelector(metric_definition_id=definition.id)
                for (provider_key, _metric_key), definition in (
                    definitions_by_key.items()
                )
                if (
                    selector.provider_key is None
                    or provider_key == selector.provider_key
                )
                and (
                    selector.provider_id is None
                    or definition.provider_id == selector.provider_id
                )
            )
            continue
        if selector.metric_key is None:
            raise AnalyticsRelationshipError(
                "metric_definition_id, metric_key, or provider selector is required"
            )
        if definitions_by_key is None:
            definitions = await list_metric_definitions(
                session,
                workspace_id,
                actor=actor,
            )
            definitions_by_key = {
                (definition.provider.key, definition.key): definition
                for definition in definitions
            }
        matches = [
            definition
            for (provider_key, metric_key), definition in definitions_by_key.items()
            if metric_key == selector.metric_key
            and (
                selector.provider_key is None
                or provider_key == selector.provider_key
            )
            and (
                selector.provider_id is None
                or definition.provider_id == selector.provider_id
            )
        ]
        if len(matches) != 1:
            raise AnalyticsRelationshipError("Metric selector must resolve uniquely")
        resolved.append(
            AnalyticsMetricSelector(
                metric_definition_id=matches[0].id,
                provider_id=selector.provider_id,
            )
        )
    return tuple(resolved)


async def _aggregate_target_metrics(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    target: AnalyticsObjectRef | None,
    selectors: tuple[AnalyticsMetricSelector, ...],
    date_range: AnalyticsDateRange | None = None,
    aggregation: AnalyticsAggregation | str | None = None,
    actor: AuthorizationActorInput | None = None,
) -> tuple[AnalyticsAggregatedMetricValue, ...]:
    _validate_date_range(date_range)
    resolved_selectors = await _resolve_metric_selectors(
        session,
        workspace_id,
        selectors,
        actor=actor,
    )
    values: list[AnalyticsAggregatedMetricValue] = []
    for selector in resolved_selectors:
        query = _merge_query(
            _target_query(target),
            selector=selector,
            date_range=date_range,
        )
        latest = await get_latest_observation(
            session,
            workspace_id,
            actor=actor,
            query=query,
        )
        if latest is None:
            continue
        normalized_aggregation = _normalize_aggregation(
            aggregation,
            fallback=latest.metric_definition.aggregation,
        )
        page = await _list_observations_for_query(
            session,
            workspace_id,
            query,
            sort_desc=True,
            limit=10_000,
        )
        _require_numeric_aggregation_context(page.observations, normalized_aggregation)
        values.append(
            _series_metric_value(
                metric_definition_id=latest.metric_definition_id,
                metric_key=latest.metric_definition.key,
                provider_id=latest.provider_id,
                provider_key=latest.provider.key,
                value_type=latest.metric_definition.value_type,
                unit=latest.unit,
                aggregation=normalized_aggregation,
                value=_aggregate_observations(
                    list(reversed(page.observations)),
                    normalized_aggregation,
                ),
                observation_count=page.total,
            )
        )
    return tuple(values)


async def summarize_campaign_metrics(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    *,
    metric_selectors: tuple[AnalyticsMetricSelector, ...] = (),
    date_range: AnalyticsDateRange | None = None,
    aggregation: AnalyticsAggregation | str | None = None,
    actor: AuthorizationActorInput | None = None,
) -> CampaignMetricsSummary:
    metrics = await _aggregate_target_metrics(
        session,
        workspace_id,
        target=AnalyticsObjectRef(
            object_type=AnalyticsObjectType.campaign,
            object_id=campaign_id,
        ),
        selectors=metric_selectors,
        date_range=date_range,
        aggregation=aggregation,
        actor=actor,
    )
    return CampaignMetricsSummary(
        operation=AnalyticsOperation.summarize_campaign_metrics,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        metrics=metrics,
    )


async def retrieve_artist_metric_trends(
    session: AsyncSession,
    workspace_id: UUID,
    artist_profile_id: UUID,
    metric_selector: AnalyticsMetricSelector,
    *,
    date_range: AnalyticsDateRange | None = None,
    aggregation: AnalyticsAggregation | str | None = None,
    actor: AuthorizationActorInput | None = None,
) -> ArtistMetricTrends:
    _validate_date_range(date_range)
    (selector,) = await _resolve_metric_selectors(
        session,
        workspace_id,
        (metric_selector,),
        actor=actor,
    )
    series = await get_historical_series(
        session,
        workspace_id,
        actor=actor,
        query=_merge_query(
            AnalyticsObservationQuery(artist_profile_id=artist_profile_id),
            selector=selector,
            date_range=date_range,
        ),
        aggregation=aggregation,
    )
    return ArtistMetricTrends(
        operation=AnalyticsOperation.retrieve_artist_metric_trends,
        workspace_id=workspace_id,
        artist_profile_id=artist_profile_id,
        series=series,
    )


async def _compare_targets(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    operation: AnalyticsOperation,
    targets: tuple[AnalyticsObjectRef, ...],
    metric_selectors: tuple[AnalyticsMetricSelector, ...],
    date_range: AnalyticsDateRange | None = None,
    aggregation: AnalyticsAggregation | str | None = None,
    actor: AuthorizationActorInput | None = None,
) -> AnalyticsComparisonResult:
    if len(targets) < 2:
        raise AnalyticsRelationshipError("At least two analytics targets are required")
    metric_sets: list[AnalyticsObjectMetricSet] = []
    for target in targets:
        metric_sets.append(
            AnalyticsObjectMetricSet(
                target=target,
                metrics=await _aggregate_target_metrics(
                    session,
                    workspace_id,
                    target=target,
                    selectors=metric_selectors,
                    date_range=date_range,
                    aggregation=aggregation,
                    actor=actor,
                ),
            )
        )
    return AnalyticsComparisonResult(
        operation=operation,
        workspace_id=workspace_id,
        targets=tuple(metric_sets),
    )


async def compare_campaigns(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_ids: tuple[UUID, ...],
    *,
    metric_selectors: tuple[AnalyticsMetricSelector, ...] = (),
    date_range: AnalyticsDateRange | None = None,
    aggregation: AnalyticsAggregation | str | None = None,
    actor: AuthorizationActorInput | None = None,
) -> AnalyticsComparisonResult:
    return await _compare_targets(
        session,
        workspace_id,
        operation=AnalyticsOperation.compare_campaigns,
        targets=tuple(
            AnalyticsObjectRef(
                object_type=AnalyticsObjectType.campaign,
                object_id=campaign_id,
            )
            for campaign_id in campaign_ids
        ),
        metric_selectors=metric_selectors,
        date_range=date_range,
        aggregation=aggregation,
        actor=actor,
    )


async def compare_campaign_goals(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    goal_ids: tuple[UUID, ...],
    *,
    metric_selectors: tuple[AnalyticsMetricSelector, ...] = (),
    date_range: AnalyticsDateRange | None = None,
    aggregation: AnalyticsAggregation | str | None = None,
    actor: AuthorizationActorInput | None = None,
) -> AnalyticsComparisonResult:
    return await _compare_targets(
        session,
        workspace_id,
        operation=AnalyticsOperation.compare_campaign_goals,
        targets=tuple(
            AnalyticsObjectRef(
                object_type=AnalyticsObjectType.goal,
                object_id=goal_id,
                campaign_id=campaign_id,
            )
            for goal_id in goal_ids
        ),
        metric_selectors=metric_selectors,
        date_range=date_range,
        aggregation=aggregation,
        actor=actor,
    )


async def compare_campaign_milestones(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    milestone_ids: tuple[UUID, ...],
    *,
    metric_selectors: tuple[AnalyticsMetricSelector, ...] = (),
    date_range: AnalyticsDateRange | None = None,
    aggregation: AnalyticsAggregation | str | None = None,
    actor: AuthorizationActorInput | None = None,
) -> AnalyticsComparisonResult:
    return await _compare_targets(
        session,
        workspace_id,
        operation=AnalyticsOperation.compare_campaign_milestones,
        targets=tuple(
            AnalyticsObjectRef(
                object_type=AnalyticsObjectType.milestone,
                object_id=milestone_id,
                campaign_id=campaign_id,
            )
            for milestone_id in milestone_ids
        ),
        metric_selectors=metric_selectors,
        date_range=date_range,
        aggregation=aggregation,
        actor=actor,
    )


async def retrieve_latest_metric_values(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    target: AnalyticsObjectRef | None = None,
    metric_selectors: tuple[AnalyticsMetricSelector, ...] = (),
    date_range: AnalyticsDateRange | None = None,
    actor: AuthorizationActorInput | None = None,
) -> LatestMetricValuesResult:
    _validate_date_range(date_range)
    resolved_selectors = await _resolve_metric_selectors(
        session,
        workspace_id,
        metric_selectors,
        actor=actor,
    )
    values: list[AnalyticsLatestMetricValue] = []
    for selector in resolved_selectors:
        observation = await get_latest_observation(
            session,
            workspace_id,
            actor=actor,
            query=_merge_query(
                _target_query(target),
                selector=selector,
                date_range=date_range,
            ),
        )
        if observation is not None:
            values.append(_latest_metric_value(observation))
    return LatestMetricValuesResult(
        operation=AnalyticsOperation.retrieve_latest_metric_values,
        workspace_id=workspace_id,
        target=target,
        values=tuple(values),
    )


async def retrieve_previous_period_changes(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    current_start: datetime,
    current_end: datetime,
    target: AnalyticsObjectRef | None = None,
    metric_selectors: tuple[AnalyticsMetricSelector, ...] = (),
    aggregation: AnalyticsAggregation | str | None = None,
    actor: AuthorizationActorInput | None = None,
) -> PreviousPeriodChangesResult:
    resolved_selectors = await _resolve_metric_selectors(
        session,
        workspace_id,
        metric_selectors,
        actor=actor,
    )
    changes = []
    for selector in resolved_selectors:
        changes.append(
            await compare_previous_period(
                session,
                workspace_id,
                current_start=current_start,
                current_end=current_end,
                actor=actor,
                query=_merge_query(_target_query(target), selector=selector),
                aggregation=aggregation,
            )
        )
    return PreviousPeriodChangesResult(
        operation=AnalyticsOperation.retrieve_previous_period_changes,
        workspace_id=workspace_id,
        changes=tuple(changes),
    )


async def retrieve_provider_analytics(
    session: AsyncSession,
    workspace_id: UUID,
    provider: AnalyticsMetricSelector,
    *,
    target: AnalyticsObjectRef | None = None,
    date_range: AnalyticsDateRange | None = None,
    aggregation: AnalyticsAggregation | str | None = None,
    actor: AuthorizationActorInput | None = None,
) -> ProviderAnalyticsResult:
    selector = AnalyticsMetricSelector(
        provider_id=provider.provider_id,
        provider_key=provider.provider_key,
    )
    metrics = await _aggregate_target_metrics(
        session,
        workspace_id,
        target=target,
        selectors=(selector,),
        date_range=date_range,
        aggregation=aggregation,
        actor=actor,
    )
    return ProviderAnalyticsResult(
        operation=AnalyticsOperation.retrieve_provider_analytics,
        workspace_id=workspace_id,
        provider_id=provider.provider_id,
        provider_key=provider.provider_key,
        metrics=metrics,
    )


async def retrieve_analytics_date_range(
    session: AsyncSession,
    workspace_id: UUID,
    date_range: AnalyticsDateRange,
    *,
    target: AnalyticsObjectRef | None = None,
    metric_selectors: tuple[AnalyticsMetricSelector, ...] = (),
    aggregation: AnalyticsAggregation | str | None = None,
    actor: AuthorizationActorInput | None = None,
) -> AnalyticsDateRangeResult:
    metrics = await _aggregate_target_metrics(
        session,
        workspace_id,
        target=target,
        selectors=metric_selectors,
        date_range=date_range,
        aggregation=aggregation,
        actor=actor,
    )
    return AnalyticsDateRangeResult(
        operation=AnalyticsOperation.retrieve_analytics_date_range,
        workspace_id=workspace_id,
        date_range=date_range,
        metrics=metrics,
    )


async def retrieve_observations_for_date_range(
    session: AsyncSession,
    workspace_id: UUID,
    date_range: AnalyticsDateRange,
    *,
    target: AnalyticsObjectRef | None = None,
    metric_selector: AnalyticsMetricSelector | None = None,
    actor: AuthorizationActorInput | None = None,
    limit: int = 100,
    offset: int = 0,
):
    _validate_date_range(date_range)
    selector = metric_selector or AnalyticsMetricSelector()
    query = _merge_query(
        _target_query(target),
        selector=selector,
        date_range=date_range,
    )
    return await list_observations(
        session,
        workspace_id,
        actor=actor,
        metric_definition_id=query.metric_definition_id,
        provider_id=query.provider_id,
        target_type=query.target_type,
        target_id=query.target_id,
        campaign_id=query.campaign_id,
        artist_profile_id=query.artist_profile_id,
        campaign_object_type=query.campaign_object_type,
        campaign_object_id=query.campaign_object_id,
        observed_start=query.observed_start,
        observed_end=query.observed_end,
        limit=limit,
        offset=offset,
    )
