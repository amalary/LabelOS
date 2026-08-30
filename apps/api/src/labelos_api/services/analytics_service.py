from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum, StrEnum
from typing import Any
from uuid import UUID

from labelos_database.models import (
    AnalyticsMetricDefinition,
    AnalyticsMetricValueType,
    AnalyticsObservation,
    AnalyticsProvider,
)
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.authorization import (
    AuthorizationActorInput,
    AuthorizationResource,
    Capability,
    ResourceKind,
    authorization_service,
)
from labelos_api.repositories import analytics


class AnalyticsServiceError(ValueError):
    """Base error for analytics business-rule failures."""


class AnalyticsNotFoundError(AnalyticsServiceError):
    pass


class AnalyticsRelationshipError(AnalyticsServiceError):
    pass


class AnalyticsAuthorizationError(AnalyticsServiceError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


MAX_ANALYTICS_LIST_LIMIT = 500
MAX_ANALYTICS_REPORTING_OBSERVATIONS = 10_000
ANALYTICS_TARGET_TYPES = frozenset(
    {"workspace", "artist_profile", "campaign", "campaign_object"}
)
SUPPORTED_CAMPAIGN_OBJECT_TYPES = frozenset({"goal", "milestone"})
NUMERIC_ANALYTICS_VALUE_TYPES = frozenset(
    {AnalyticsMetricValueType.decimal, AnalyticsMetricValueType.integer}
)


class AnalyticsAggregation(Enum):
    sum = "sum"
    average = "average"
    min = "min"
    max = "max"
    latest = "latest"
    count = "count"


class AnalyticsComparisonStatus(StrEnum):
    compared = "compared"
    no_current_data = "no_current_data"
    no_previous_period = "no_previous_period"
    zero_previous_value = "zero_previous_value"


@dataclass(frozen=True, kw_only=True)
class AnalyticsProviderRef:
    key: str
    display_name: str | None = None
    provider_type: str = "internal"
    external_account_id: str | None = None
    metadata: dict | None = None


@dataclass(frozen=True, kw_only=True)
class AnalyticsMetricDefinitionCreate:
    key: str
    display_name: str
    provider: AnalyticsProviderRef
    description: str | None = None
    value_type: AnalyticsMetricValueType | str = AnalyticsMetricValueType.decimal
    default_unit: str | None = None
    aggregation: str | None = None
    metadata: dict | None = None


@dataclass(frozen=True, kw_only=True)
class AnalyticsObservationCreate:
    metric_definition_id: UUID
    target_type: str
    observed_at: datetime
    target_id: UUID | None = None
    artist_profile_id: UUID | None = None
    campaign_id: UUID | None = None
    campaign_object_type: str | None = None
    campaign_object_id: UUID | None = None
    value_numeric: Decimal | int | float | str | None = None
    value_text: str | None = None
    value_boolean: bool | None = None
    value_json: dict | None = None
    unit: str | None = None
    source_record_id: str | None = None
    idempotency_key: str | None = None
    dimensions: dict | None = None
    metadata: dict | None = None


@dataclass(frozen=True, kw_only=True)
class AnalyticsObservationCreateResult:
    observation: AnalyticsObservation
    created: bool


@dataclass(frozen=True, kw_only=True)
class AnalyticsObservationQuery:
    metric_definition_id: UUID | None = None
    provider_id: UUID | None = None
    target_type: str | None = None
    target_id: UUID | None = None
    artist_profile_id: UUID | None = None
    campaign_id: UUID | None = None
    campaign_object_type: str | None = None
    campaign_object_id: UUID | None = None
    observed_start: datetime | None = None
    observed_end: datetime | None = None
    observed_before: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class AnalyticsSeriesPoint:
    bucket_date: date
    value: Decimal | str | bool | dict[str, Any] | None
    observation_count: int


@dataclass(frozen=True, kw_only=True)
class AnalyticsHistoricalSeries:
    aggregation: AnalyticsAggregation
    points: tuple[AnalyticsSeriesPoint, ...]
    value_type: AnalyticsMetricValueType | None
    unit: str | None
    provider_id: UUID | None
    metric_definition_id: UUID | None
    observation_count: int


@dataclass(frozen=True, kw_only=True)
class AnalyticsPreviousPeriodComparison:
    aggregation: AnalyticsAggregation
    current_start: datetime
    current_end: datetime
    previous_start: datetime
    previous_end: datetime
    current_value: Decimal | str | bool | dict[str, Any] | None
    previous_value: Decimal | str | bool | dict[str, Any] | None
    current_observation_count: int
    previous_observation_count: int
    absolute_change: Decimal | None
    percentage_change: Decimal | None
    status: AnalyticsComparisonStatus


def _coerce_metric_value_type(
    value: AnalyticsMetricValueType | str,
) -> AnalyticsMetricValueType:
    try:
        return (
            value
            if isinstance(value, AnalyticsMetricValueType)
            else AnalyticsMetricValueType(value)
        )
    except ValueError as exc:
        raise AnalyticsRelationshipError("Invalid analytics metric value type") from exc


def _normalize_text(value: str | None, field_name: str) -> str:
    if value is None or not value.strip():
        raise AnalyticsRelationshipError(f"{field_name} is required")
    return value.strip()


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _json_object(value: dict | None, field_name: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AnalyticsRelationshipError(f"{field_name} must be a JSON object")
    return value


def _validate_list_pagination(*, limit: int, offset: int) -> None:
    if limit < 1 or limit > MAX_ANALYTICS_LIST_LIMIT:
        raise AnalyticsRelationshipError(
            "Analytics list limit must be between 1 and 500"
        )
    if offset < 0:
        raise AnalyticsRelationshipError(
            "Analytics list offset must be greater than or equal to 0"
        )


def _normalize_aggregation(
    value: AnalyticsAggregation | str | None,
    *,
    fallback: str | None = None,
) -> AnalyticsAggregation:
    raw_value = value or fallback or AnalyticsAggregation.latest
    try:
        return (
            raw_value
            if isinstance(raw_value, AnalyticsAggregation)
            else AnalyticsAggregation(str(raw_value))
        )
    except ValueError as exc:
        raise AnalyticsRelationshipError("Invalid analytics aggregation") from exc


def _observation_typed_value(
    observation: AnalyticsObservation,
) -> Decimal | str | bool | dict[str, Any] | None:
    value_type = observation.metric_definition.value_type
    if value_type in NUMERIC_ANALYTICS_VALUE_TYPES:
        return observation.value_numeric
    if value_type == AnalyticsMetricValueType.string:
        return observation.value_text
    if value_type == AnalyticsMetricValueType.boolean:
        return observation.value_boolean
    return observation.value_json


def _bucket_date(observed_at: datetime) -> date:
    if observed_at.tzinfo is None:
        return observed_at.date()
    return observed_at.astimezone(UTC).date()


def _require_single_metric_context(
    observations: list[AnalyticsObservation],
) -> AnalyticsMetricDefinition | None:
    metric_definitions = {
        observation.metric_definition_id: observation.metric_definition
        for observation in observations
    }
    if len(metric_definitions) > 1:
        raise AnalyticsRelationshipError(
            "Numeric analytics aggregation requires a single metric definition"
        )
    return next(iter(metric_definitions.values()), None)


def _require_numeric_aggregation_context(
    observations: list[AnalyticsObservation],
    aggregation: AnalyticsAggregation,
) -> None:
    if aggregation not in {
        AnalyticsAggregation.sum,
        AnalyticsAggregation.average,
        AnalyticsAggregation.min,
        AnalyticsAggregation.max,
    }:
        return
    metric_definition = _require_single_metric_context(observations)
    if metric_definition is None:
        return
    if metric_definition.value_type not in NUMERIC_ANALYTICS_VALUE_TYPES:
        raise AnalyticsRelationshipError(
            "Numeric analytics aggregation is only valid for numeric metrics"
        )
    units = {observation.unit for observation in observations}
    if len(units) > 1:
        raise AnalyticsRelationshipError(
            "Numeric analytics aggregation requires a single unit"
        )
    providers = {observation.provider_id for observation in observations}
    if len(providers) > 1:
        raise AnalyticsRelationshipError(
            "Numeric analytics aggregation requires a single provider"
        )


def _aggregate_observations(
    observations: list[AnalyticsObservation],
    aggregation: AnalyticsAggregation,
) -> Decimal | str | bool | dict[str, Any] | None:
    if not observations:
        return None
    if aggregation == AnalyticsAggregation.count:
        return Decimal(len(observations))
    if aggregation == AnalyticsAggregation.latest:
        return _observation_typed_value(observations[-1])
    _require_numeric_aggregation_context(observations, aggregation)
    numeric_values = [
        observation.value_numeric
        for observation in observations
        if observation.value_numeric is not None
    ]
    if not numeric_values:
        return None
    if aggregation == AnalyticsAggregation.sum:
        return sum(numeric_values, Decimal("0"))
    if aggregation == AnalyticsAggregation.average:
        return sum(numeric_values, Decimal("0")) / Decimal(len(numeric_values))
    if aggregation == AnalyticsAggregation.min:
        return min(numeric_values)
    if aggregation == AnalyticsAggregation.max:
        return max(numeric_values)
    raise AnalyticsRelationshipError("Invalid analytics aggregation")


def _series_metadata(
    observations: list[AnalyticsObservation],
) -> tuple[AnalyticsMetricValueType | None, str | None, UUID | None, UUID | None]:
    metric_ids = {observation.metric_definition_id for observation in observations}
    provider_ids = {observation.provider_id for observation in observations}
    value_types = {
        observation.metric_definition.value_type for observation in observations
    }
    units = {observation.unit for observation in observations}
    return (
        next(iter(value_types), None) if len(value_types) == 1 else None,
        next(iter(units), None) if len(units) == 1 else None,
        next(iter(provider_ids), None) if len(provider_ids) == 1 else None,
        next(iter(metric_ids), None) if len(metric_ids) == 1 else None,
    )


def _with_query_window(
    query: AnalyticsObservationQuery | None,
    *,
    observed_start: datetime,
    observed_before: datetime,
) -> AnalyticsObservationQuery:
    base = query or AnalyticsObservationQuery()
    return AnalyticsObservationQuery(
        metric_definition_id=base.metric_definition_id,
        provider_id=base.provider_id,
        target_type=base.target_type,
        target_id=base.target_id,
        artist_profile_id=base.artist_profile_id,
        campaign_id=base.campaign_id,
        campaign_object_type=base.campaign_object_type,
        campaign_object_id=base.campaign_object_id,
        observed_start=observed_start,
        observed_end=None,
        observed_before=observed_before,
    )


@dataclass(frozen=True, kw_only=True)
class _AnalyticsAggregateResult:
    value: Decimal | str | bool | dict[str, Any] | None
    observation_count: int
    aggregation: AnalyticsAggregation


async def _aggregate_query_observations(
    session: AsyncSession,
    workspace_id: UUID,
    query: AnalyticsObservationQuery,
    aggregation: AnalyticsAggregation,
) -> _AnalyticsAggregateResult:
    page = await _list_observations_for_query(
        session,
        workspace_id,
        query,
        limit=MAX_ANALYTICS_REPORTING_OBSERVATIONS,
        sort_desc=False,
    )
    observations = page.observations
    _require_numeric_aggregation_context(observations, aggregation)
    return _AnalyticsAggregateResult(
        value=_aggregate_observations(observations, aggregation),
        observation_count=page.total,
        aggregation=aggregation,
    )


def _absolute_change(
    current_value: Decimal | str | bool | dict[str, Any] | None,
    previous_value: Decimal | str | bool | dict[str, Any] | None,
) -> Decimal | None:
    if isinstance(current_value, Decimal) and isinstance(previous_value, Decimal):
        return current_value - previous_value
    return None


def _percentage_change(
    current_value: Decimal | str | bool | dict[str, Any] | None,
    previous_value: Decimal | str | bool | dict[str, Any] | None,
) -> Decimal | None:
    if not isinstance(current_value, Decimal) or not isinstance(
        previous_value,
        Decimal,
    ):
        return None
    if previous_value == 0:
        return None
    return (current_value - previous_value) / previous_value


def _comparison_status(
    current_count: int,
    previous_count: int,
    previous_value: Decimal | str | bool | dict[str, Any] | None,
    percentage_change: Decimal | None,
) -> AnalyticsComparisonStatus:
    if current_count == 0:
        return AnalyticsComparisonStatus.no_current_data
    if previous_count == 0:
        return AnalyticsComparisonStatus.no_previous_period
    if isinstance(previous_value, Decimal) and previous_value == 0:
        return AnalyticsComparisonStatus.zero_previous_value
    if percentage_change is None:
        return AnalyticsComparisonStatus.compared
    return AnalyticsComparisonStatus.compared


async def _require_capability(
    session: AsyncSession,
    *,
    actor: AuthorizationActorInput | None,
    workspace_id: UUID,
    capability: Capability,
    resource: AuthorizationResource | None = None,
) -> None:
    if actor is None:
        return
    decision = await authorization_service.decide_capability(
        session,
        actor=actor,
        workspace=workspace_id,
        capability=capability,
        resource=resource
        or AuthorizationResource(
            kind=ResourceKind.analytics,
            id=workspace_id,
            workspace_id=workspace_id,
            department="analytics",
        ),
    )
    if not decision.allowed:
        raise AnalyticsAuthorizationError(decision.reason)


async def _ensure_provider(
    session: AsyncSession,
    workspace_id: UUID,
    provider_ref: AnalyticsProviderRef,
) -> AnalyticsProvider:
    provider_key = _normalize_text(provider_ref.key, "provider.key")
    provider = await analytics.get_provider_by_key(session, workspace_id, provider_key)
    if provider is not None:
        return provider
    return await analytics.create_provider(
        session,
        workspace_id,
        {
            "key": provider_key,
            "display_name": _normalize_optional_text(provider_ref.display_name)
            or provider_key,
            "provider_type": _normalize_text(
                provider_ref.provider_type,
                "provider.provider_type",
            ),
            "external_account_id": _normalize_optional_text(
                provider_ref.external_account_id
            ),
            "metadata_json": _json_object(provider_ref.metadata, "provider.metadata"),
        },
    )


def _metric_definition_values(
    payload: AnalyticsMetricDefinitionCreate,
    provider: AnalyticsProvider,
) -> dict[str, object]:
    return {
        "provider_id": provider.id,
        "key": _normalize_text(payload.key, "key"),
        "display_name": _normalize_text(payload.display_name, "display_name"),
        "description": _normalize_optional_text(payload.description),
        "value_type": _coerce_metric_value_type(payload.value_type),
        "default_unit": _normalize_optional_text(payload.default_unit),
        "aggregation": _normalize_optional_text(payload.aggregation),
        "metadata_json": _json_object(payload.metadata, "metadata"),
    }


def _target_values(payload: AnalyticsObservationCreate) -> dict[str, object | None]:
    target_type = _normalize_text(payload.target_type, "target_type")
    if target_type not in ANALYTICS_TARGET_TYPES:
        raise AnalyticsRelationshipError("Invalid analytics target type")
    target_id = payload.target_id
    artist_profile_id = payload.artist_profile_id
    campaign_id = payload.campaign_id
    campaign_object_type = _normalize_optional_text(payload.campaign_object_type)
    campaign_object_id = payload.campaign_object_id

    if target_type == "workspace":
        target_id = target_id
    elif target_type == "artist_profile":
        if artist_profile_id is None:
            artist_profile_id = target_id
        if artist_profile_id is None:
            raise AnalyticsRelationshipError("artist_profile_id is required")
        target_id = artist_profile_id
    elif target_type == "campaign":
        if campaign_id is None:
            campaign_id = target_id
        if campaign_id is None:
            raise AnalyticsRelationshipError("campaign_id is required")
        target_id = campaign_id
    elif target_type == "campaign_object":
        if campaign_id is None:
            raise AnalyticsRelationshipError("campaign_id is required")
        if campaign_object_type is None or campaign_object_id is None:
            raise AnalyticsRelationshipError(
                "campaign_object_type and campaign_object_id are required"
            )
        if campaign_object_type not in SUPPORTED_CAMPAIGN_OBJECT_TYPES:
            raise AnalyticsRelationshipError("Unsupported campaign object type")
        target_id = campaign_object_id

    return {
        "target_type": target_type,
        "target_id": target_id,
        "artist_profile_id": artist_profile_id,
        "campaign_id": campaign_id,
        "campaign_object_type": campaign_object_type,
        "campaign_object_id": campaign_object_id,
    }


def _value_values(
    payload: AnalyticsObservationCreate,
    value_type: AnalyticsMetricValueType,
) -> dict[str, object | None]:
    values: dict[str, object | None] = {
        "value_numeric": None,
        "value_text": None,
        "value_boolean": None,
        "value_json": None,
    }
    if value_type in {
        AnalyticsMetricValueType.decimal,
        AnalyticsMetricValueType.integer,
    }:
        if payload.value_numeric is None:
            raise AnalyticsRelationshipError("value_numeric is required")
        try:
            values["value_numeric"] = Decimal(str(payload.value_numeric))
        except (InvalidOperation, ValueError) as exc:
            raise AnalyticsRelationshipError("value_numeric must be numeric") from exc
        return values
    if value_type == AnalyticsMetricValueType.string:
        values["value_text"] = _normalize_text(payload.value_text, "value_text")
        return values
    if value_type == AnalyticsMetricValueType.boolean:
        if payload.value_boolean is None:
            raise AnalyticsRelationshipError("value_boolean is required")
        values["value_boolean"] = payload.value_boolean
        return values
    if payload.value_json is None:
        raise AnalyticsRelationshipError("value_json is required")
    values["value_json"] = _json_object(payload.value_json, "value_json")
    return values


async def _validate_target_scope(
    session: AsyncSession,
    workspace_id: UUID,
    target_values: dict[str, object | None],
) -> None:
    artist_profile_id = target_values["artist_profile_id"]
    campaign_id = target_values["campaign_id"]
    campaign_object_id = target_values["campaign_object_id"]
    if isinstance(
        artist_profile_id, UUID
    ) and not await analytics.artist_profile_in_workspace(
        session,
        workspace_id,
        artist_profile_id,
    ):
        raise AnalyticsNotFoundError("Artist profile not found")
    if isinstance(campaign_id, UUID) and not await analytics.campaign_in_workspace(
        session,
        workspace_id,
        campaign_id,
    ):
        raise AnalyticsNotFoundError("Campaign not found")
    if target_values["target_type"] != "campaign_object":
        return
    if not isinstance(campaign_id, UUID) or not isinstance(campaign_object_id, UUID):
        raise AnalyticsRelationshipError("campaign object target is incomplete")
    child_type = target_values["campaign_object_type"]
    child_checkers = {
        "goal": analytics.campaign_goal_in_workspace,
        "milestone": analytics.campaign_milestone_in_workspace,
    }
    child_checker = child_checkers.get(str(child_type))
    if child_checker is None:
        raise AnalyticsRelationshipError("Unsupported campaign object type")
    if not await child_checker(session, workspace_id, campaign_id, campaign_object_id):
        raise AnalyticsNotFoundError("Campaign object not found")


async def create_metric_definition(
    session: AsyncSession,
    workspace_id: UUID,
    payload: AnalyticsMetricDefinitionCreate,
    *,
    actor: AuthorizationActorInput | None = None,
) -> AnalyticsMetricDefinition:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.analytics_create,
    )
    provider = await _ensure_provider(session, workspace_id, payload.provider)
    values = _metric_definition_values(payload, provider)
    existing = await analytics.get_metric_definition_by_key(
        session,
        workspace_id,
        provider.id,
        str(values["key"]),
    )
    if existing is not None:
        return existing
    metric_definition = await analytics.create_metric_definition(
        session,
        workspace_id,
        values,
    )
    metric_definition.provider = provider
    await session.commit()
    return metric_definition


async def list_metric_definitions(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
) -> list[AnalyticsMetricDefinition]:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.analytics_view,
    )
    return await analytics.list_metric_definitions(session, workspace_id)


async def create_observation_result(
    session: AsyncSession,
    workspace_id: UUID,
    payload: AnalyticsObservationCreate,
    *,
    actor: AuthorizationActorInput | None = None,
) -> AnalyticsObservationCreateResult:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.analytics_create,
    )
    metric_definition = await analytics.get_metric_definition(
        session,
        workspace_id,
        payload.metric_definition_id,
    )
    if metric_definition is None:
        raise AnalyticsNotFoundError("Metric definition not found")

    idempotency_key = _normalize_optional_text(payload.idempotency_key)
    if idempotency_key is not None:
        existing = await analytics.get_observation_by_idempotency_key(
            session,
            workspace_id,
            metric_definition.provider_id,
            idempotency_key,
        )
        if existing is not None:
            return AnalyticsObservationCreateResult(
                observation=existing,
                created=False,
            )

    target_values = _target_values(payload)
    if target_values["target_type"] == "workspace":
        target_values["target_id"] = workspace_id
    await _validate_target_scope(session, workspace_id, target_values)
    observation = await analytics.create_observation(
        session,
        workspace_id,
        {
            "metric_definition_id": metric_definition.id,
            "provider_id": metric_definition.provider_id,
            **target_values,
            **_value_values(payload, metric_definition.value_type),
            "unit": _normalize_optional_text(payload.unit)
            or metric_definition.default_unit,
            "observed_at": payload.observed_at,
            "source_record_id": _normalize_optional_text(payload.source_record_id),
            "idempotency_key": idempotency_key,
            "dimensions": _json_object(payload.dimensions, "dimensions"),
            "metadata_json": _json_object(payload.metadata, "metadata"),
        },
    )
    observation.metric_definition = metric_definition
    observation.provider = metric_definition.provider
    await session.commit()
    return AnalyticsObservationCreateResult(
        observation=observation,
        created=True,
    )


async def create_observation(
    session: AsyncSession,
    workspace_id: UUID,
    payload: AnalyticsObservationCreate,
    *,
    actor: AuthorizationActorInput | None = None,
) -> AnalyticsObservation:
    result = await create_observation_result(
        session,
        workspace_id,
        payload,
        actor=actor,
    )
    return result.observation


async def _validate_observation_query_scope(
    session: AsyncSession,
    workspace_id: UUID,
    query: AnalyticsObservationQuery,
) -> AnalyticsMetricDefinition | None:
    metric_definition = None
    if (
        query.target_type is not None
        and query.target_type not in ANALYTICS_TARGET_TYPES
    ):
        raise AnalyticsRelationshipError("Invalid analytics target type")
    if query.metric_definition_id is not None:
        metric_definition = await analytics.get_metric_definition(
            session,
            workspace_id,
            query.metric_definition_id,
        )
        if metric_definition is None:
            raise AnalyticsNotFoundError("Metric definition not found")
    if query.provider_id is not None:
        provider = await analytics.get_provider(
            session, workspace_id, query.provider_id
        )
        if provider is None:
            raise AnalyticsNotFoundError("Provider not found")
    if (
        query.artist_profile_id is not None
        and not await analytics.artist_profile_in_workspace(
            session,
            workspace_id,
            query.artist_profile_id,
        )
    ):
        raise AnalyticsNotFoundError("Artist profile not found")
    if query.campaign_id is not None and not await analytics.campaign_in_workspace(
        session,
        workspace_id,
        query.campaign_id,
    ):
        raise AnalyticsNotFoundError("Campaign not found")
    if query.campaign_object_type is not None:
        if query.campaign_object_type not in SUPPORTED_CAMPAIGN_OBJECT_TYPES:
            raise AnalyticsRelationshipError("Unsupported campaign object type")
        if query.campaign_id is None or query.campaign_object_id is None:
            raise AnalyticsRelationshipError(
                "campaign_id and campaign_object_id are required "
                "for campaign object filters"
            )
        await _validate_target_scope(
            session,
            workspace_id,
            {
                "target_type": "campaign_object",
                "artist_profile_id": query.artist_profile_id,
                "campaign_id": query.campaign_id,
                "campaign_object_type": query.campaign_object_type,
                "campaign_object_id": query.campaign_object_id,
            },
        )
    elif query.campaign_object_id is not None:
        raise AnalyticsRelationshipError(
            "campaign_object_type is required for campaign object filters"
        )
    return metric_definition


def _query_from_filters(
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
) -> AnalyticsObservationQuery:
    return AnalyticsObservationQuery(
        metric_definition_id=metric_definition_id,
        provider_id=provider_id,
        target_type=_normalize_optional_text(target_type),
        target_id=target_id,
        campaign_id=campaign_id,
        artist_profile_id=artist_profile_id,
        campaign_object_type=_normalize_optional_text(campaign_object_type),
        campaign_object_id=campaign_object_id,
        observed_start=observed_start,
        observed_end=observed_end,
        observed_before=observed_before,
    )


async def _list_observations_for_query(
    session: AsyncSession,
    workspace_id: UUID,
    query: AnalyticsObservationQuery,
    *,
    limit: int,
    offset: int = 0,
    sort_desc: bool = True,
) -> analytics.AnalyticsObservationListPage:
    return await analytics.list_observations(
        session,
        workspace_id,
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
        observed_before=query.observed_before,
        limit=limit,
        offset=offset,
        sort_desc=sort_desc,
    )


async def list_observations(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
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
    limit: int = 100,
    offset: int = 0,
) -> analytics.AnalyticsObservationListPage:
    _validate_list_pagination(limit=limit, offset=offset)
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.analytics_view,
    )
    query = _query_from_filters(
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
    )
    await _validate_observation_query_scope(session, workspace_id, query)
    return await _list_observations_for_query(
        session,
        workspace_id,
        query,
        limit=limit,
        offset=offset,
    )


async def list_observations_by_workspace(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    limit: int = 100,
    offset: int = 0,
) -> analytics.AnalyticsObservationListPage:
    return await list_observations(
        session,
        workspace_id,
        actor=actor,
        target_type="workspace",
        target_id=workspace_id,
        limit=limit,
        offset=offset,
    )


async def list_observations_by_artist_profile(
    session: AsyncSession,
    workspace_id: UUID,
    artist_profile_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    limit: int = 100,
    offset: int = 0,
) -> analytics.AnalyticsObservationListPage:
    return await list_observations(
        session,
        workspace_id,
        actor=actor,
        target_type="artist_profile",
        target_id=artist_profile_id,
        artist_profile_id=artist_profile_id,
        limit=limit,
        offset=offset,
    )


async def list_observations_by_campaign(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    include_child_objects: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> analytics.AnalyticsObservationListPage:
    return await list_observations(
        session,
        workspace_id,
        actor=actor,
        target_type=None if include_child_objects else "campaign",
        target_id=None if include_child_objects else campaign_id,
        campaign_id=campaign_id,
        limit=limit,
        offset=offset,
    )


async def list_observations_by_campaign_child_object(
    session: AsyncSession,
    workspace_id: UUID,
    campaign_id: UUID,
    campaign_object_type: str,
    campaign_object_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    limit: int = 100,
    offset: int = 0,
) -> analytics.AnalyticsObservationListPage:
    return await list_observations(
        session,
        workspace_id,
        actor=actor,
        target_type="campaign_object",
        target_id=campaign_object_id,
        campaign_id=campaign_id,
        campaign_object_type=campaign_object_type,
        campaign_object_id=campaign_object_id,
        limit=limit,
        offset=offset,
    )


async def list_observations_by_metric_definition(
    session: AsyncSession,
    workspace_id: UUID,
    metric_definition_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    limit: int = 100,
    offset: int = 0,
) -> analytics.AnalyticsObservationListPage:
    return await list_observations(
        session,
        workspace_id,
        actor=actor,
        metric_definition_id=metric_definition_id,
        limit=limit,
        offset=offset,
    )


async def list_observations_by_provider(
    session: AsyncSession,
    workspace_id: UUID,
    provider_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    limit: int = 100,
    offset: int = 0,
) -> analytics.AnalyticsObservationListPage:
    return await list_observations(
        session,
        workspace_id,
        actor=actor,
        provider_id=provider_id,
        limit=limit,
        offset=offset,
    )


async def list_observations_by_date_range(
    session: AsyncSession,
    workspace_id: UUID,
    observed_start: datetime,
    observed_end: datetime,
    *,
    actor: AuthorizationActorInput | None = None,
    limit: int = 100,
    offset: int = 0,
) -> analytics.AnalyticsObservationListPage:
    if observed_end < observed_start:
        raise AnalyticsRelationshipError("observed_end must be after observed_start")
    return await list_observations(
        session,
        workspace_id,
        actor=actor,
        observed_start=observed_start,
        observed_end=observed_end,
        limit=limit,
        offset=offset,
    )


async def get_latest_observation(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    query: AnalyticsObservationQuery | None = None,
) -> AnalyticsObservation | None:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.analytics_view,
    )
    normalized_query = query or AnalyticsObservationQuery()
    await _validate_observation_query_scope(session, workspace_id, normalized_query)
    return await analytics.get_latest_observation(
        session,
        workspace_id,
        metric_definition_id=normalized_query.metric_definition_id,
        provider_id=normalized_query.provider_id,
        target_type=normalized_query.target_type,
        target_id=normalized_query.target_id,
        campaign_id=normalized_query.campaign_id,
        artist_profile_id=normalized_query.artist_profile_id,
        campaign_object_type=normalized_query.campaign_object_type,
        campaign_object_id=normalized_query.campaign_object_id,
        observed_start=normalized_query.observed_start,
        observed_end=normalized_query.observed_end,
        observed_before=normalized_query.observed_before,
    )


async def get_historical_series(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    query: AnalyticsObservationQuery | None = None,
    aggregation: AnalyticsAggregation | str | None = None,
) -> AnalyticsHistoricalSeries:
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.analytics_view,
    )
    normalized_query = query or AnalyticsObservationQuery()
    metric_definition = await _validate_observation_query_scope(
        session,
        workspace_id,
        normalized_query,
    )
    normalized_aggregation = _normalize_aggregation(
        aggregation,
        fallback=metric_definition.aggregation if metric_definition else None,
    )
    page = await _list_observations_for_query(
        session,
        workspace_id,
        normalized_query,
        limit=MAX_ANALYTICS_REPORTING_OBSERVATIONS,
        sort_desc=False,
    )
    observations = page.observations
    _require_numeric_aggregation_context(observations, normalized_aggregation)
    grouped: dict[date, list[AnalyticsObservation]] = {}
    for observation in observations:
        grouped.setdefault(_bucket_date(observation.observed_at), []).append(
            observation
        )
    points = tuple(
        AnalyticsSeriesPoint(
            bucket_date=bucket,
            value=_aggregate_observations(bucket_observations, normalized_aggregation),
            observation_count=len(bucket_observations),
        )
        for bucket, bucket_observations in sorted(grouped.items())
    )
    value_type, unit, provider_id, metric_definition_id = _series_metadata(observations)
    return AnalyticsHistoricalSeries(
        aggregation=normalized_aggregation,
        points=points,
        value_type=value_type,
        unit=unit,
        provider_id=provider_id,
        metric_definition_id=metric_definition_id,
        observation_count=page.total,
    )


async def compare_previous_period(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    current_start: datetime,
    current_end: datetime,
    actor: AuthorizationActorInput | None = None,
    query: AnalyticsObservationQuery | None = None,
    aggregation: AnalyticsAggregation | str | None = None,
) -> AnalyticsPreviousPeriodComparison:
    if current_end <= current_start:
        raise AnalyticsRelationshipError("current_end must be after current_start")
    await _require_capability(
        session,
        actor=actor,
        workspace_id=workspace_id,
        capability=Capability.analytics_view,
    )
    normalized_query = query or AnalyticsObservationQuery()
    metric_definition = await _validate_observation_query_scope(
        session,
        workspace_id,
        normalized_query,
    )
    normalized_aggregation = _normalize_aggregation(
        aggregation,
        fallback=metric_definition.aggregation if metric_definition else None,
    )
    period = current_end - current_start
    previous_start = current_start - period
    previous_end = current_start
    current_query = _with_query_window(
        normalized_query,
        observed_start=current_start,
        observed_before=current_end,
    )
    previous_query = _with_query_window(
        normalized_query,
        observed_start=previous_start,
        observed_before=previous_end,
    )
    current_result = await _aggregate_query_observations(
        session,
        workspace_id,
        query=current_query,
        aggregation=normalized_aggregation,
    )
    previous_result = await _aggregate_query_observations(
        session,
        workspace_id,
        query=previous_query,
        aggregation=normalized_aggregation,
    )
    current_value = current_result.value
    previous_value = previous_result.value
    absolute_change = _absolute_change(current_value, previous_value)
    percentage_change = _percentage_change(current_value, previous_value)
    status = _comparison_status(
        current_result.observation_count,
        previous_result.observation_count,
        previous_value,
        percentage_change,
    )
    return AnalyticsPreviousPeriodComparison(
        aggregation=normalized_aggregation,
        current_start=current_start,
        current_end=current_end,
        previous_start=previous_start,
        previous_end=previous_end,
        current_value=current_value,
        previous_value=previous_value,
        current_observation_count=current_result.observation_count,
        previous_observation_count=previous_result.observation_count,
        absolute_change=absolute_change,
        percentage_change=percentage_change,
        status=status,
    )
