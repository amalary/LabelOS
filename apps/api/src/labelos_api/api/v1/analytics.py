from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from labelos_database.models import (
    AnalyticsMetricDefinition,
    AnalyticsMetricValueType,
    AnalyticsObservation,
)
from pydantic import BaseModel, ConfigDict, Field

from labelos_api.auth import CurrentUserContext, SessionDep, get_current_user_context
from labelos_api.services import analytics_service
from labelos_api.services.analytics_service import (
    AnalyticsAggregation,
    AnalyticsAuthorizationError,
    AnalyticsBulkIngestionError,
    AnalyticsComparisonStatus,
    AnalyticsHistoricalSeries,
    AnalyticsIdempotencyConflictError,
    AnalyticsMetricDefinitionCreate,
    AnalyticsNotFoundError,
    AnalyticsObservationCreate,
    AnalyticsObservationQuery,
    AnalyticsPreviousPeriodComparison,
    AnalyticsProviderRef,
    AnalyticsRelationshipError,
)

router = APIRouter(prefix="/workspaces", tags=["analytics"])


class AnalyticsProviderRefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=120)
    display_name: str | None = Field(default=None, max_length=200)
    provider_type: str = Field(default="internal", min_length=1, max_length=80)
    external_account_id: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] | None = None


class AnalyticsMetricDefinitionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=200)
    provider: AnalyticsProviderRefRequest
    description: str | None = Field(default=None, max_length=1000)
    value_type: AnalyticsMetricValueType = AnalyticsMetricValueType.decimal
    default_unit: str | None = Field(default=None, max_length=80)
    aggregation: str | None = Field(default=None, max_length=80)
    metadata: dict[str, Any] | None = None


class AnalyticsProviderResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    key: str
    display_name: str
    provider_type: str
    external_account_id: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AnalyticsMetricDefinitionResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    provider: AnalyticsProviderResponse
    key: str
    display_name: str
    description: str | None
    value_type: AnalyticsMetricValueType
    default_unit: str | None
    aggregation: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AnalyticsMetricDefinitionsListResponse(BaseModel):
    metric_definitions: list[AnalyticsMetricDefinitionResponse]


class AnalyticsProvidersListResponse(BaseModel):
    providers: list[AnalyticsProviderResponse]


class AnalyticsObservationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_definition_id: UUID
    target_type: str = Field(min_length=1, max_length=80)
    observed_at: datetime
    target_id: UUID | None = None
    artist_profile_id: UUID | None = None
    campaign_id: UUID | None = None
    campaign_object_type: str | None = Field(default=None, max_length=120)
    campaign_object_id: UUID | None = None
    value_numeric: Decimal | int | float | str | None = None
    value_text: str | None = Field(default=None, max_length=1000)
    value_boolean: bool | None = None
    value_json: dict[str, Any] | None = None
    unit: str | None = Field(default=None, max_length=80)
    source_record_id: str | None = Field(default=None, max_length=255)
    idempotency_key: str | None = Field(default=None, max_length=255)
    dimensions: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class AnalyticsObservationResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    metric_definition_id: UUID
    metric_key: str
    provider_id: UUID
    provider_key: str
    target_type: str
    target_id: UUID | None
    artist_profile_id: UUID | None
    campaign_id: UUID | None
    campaign_name: str | None
    campaign_object_type: str | None
    campaign_object_id: UUID | None
    value_numeric: Decimal | None
    value_text: str | None
    value_boolean: bool | None
    value_json: dict[str, Any] | None
    unit: str | None
    observed_at: datetime
    source_record_id: str | None
    idempotency_key: str | None
    dimensions: dict[str, Any]
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AnalyticsObservationsListResponse(BaseModel):
    observations: list[AnalyticsObservationResponse]
    total: int
    limit: int
    offset: int


class AnalyticsBulkObservationsCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observations: list[AnalyticsObservationCreateRequest] = Field(
        min_length=1,
        max_length=500,
    )


class AnalyticsBulkObservationItemResponse(BaseModel):
    index: int
    created: bool
    observation: AnalyticsObservationResponse


class AnalyticsBulkObservationsResponse(BaseModel):
    observations: list[AnalyticsBulkObservationItemResponse]
    created_count: int
    existing_count: int
    transaction: str


class AnalyticsBulkObservationErrorResponse(BaseModel):
    index: int
    code: str
    detail: str


class AnalyticsBulkObservationsErrorResponse(BaseModel):
    detail: str
    transaction: str
    errors: list[AnalyticsBulkObservationErrorResponse]


class AnalyticsSeriesPointResponse(BaseModel):
    bucket_date: date
    value: Decimal | str | bool | dict[str, Any] | None
    observation_count: int


class AnalyticsHistoricalSeriesResponse(BaseModel):
    aggregation: AnalyticsAggregation
    points: list[AnalyticsSeriesPointResponse]
    value_type: AnalyticsMetricValueType | None
    unit: str | None
    provider_id: UUID | None
    metric_definition_id: UUID | None
    observation_count: int


class AnalyticsPreviousPeriodComparisonResponse(BaseModel):
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


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _raise_capability_denial(reason: str) -> NoReturn:
    if reason in {"invalid_resource_scope", "membership_not_found"}:
        raise _not_found()
    if reason == "insufficient_department_access":
        raise _forbidden("Insufficient department access")
    raise _forbidden("Insufficient capability permission")


def _service_error(
    exc: (
        AnalyticsNotFoundError
        | AnalyticsRelationshipError
        | AnalyticsIdempotencyConflictError
        | AnalyticsAuthorizationError
    ),
) -> NoReturn:
    if isinstance(exc, AnalyticsAuthorizationError):
        _raise_capability_denial(exc.reason)
    if isinstance(exc, AnalyticsIdempotencyConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if isinstance(exc, AnalyticsNotFoundError):
        raise _not_found() from exc
    raise _bad_request(str(exc)) from exc


def _bulk_service_error(exc: AnalyticsBulkIngestionError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": AnalyticsBulkObservationsErrorResponse(
                detail="Analytics bulk ingestion batch is invalid",
                transaction="all_or_nothing",
                errors=[
                    AnalyticsBulkObservationErrorResponse(
                        index=error.index,
                        code=error.code,
                        detail=error.detail,
                    )
                    for error in exc.errors
                ],
            ).model_dump()
        },
    )


def _provider_response(provider) -> AnalyticsProviderResponse:
    return AnalyticsProviderResponse(
        id=provider.id,
        workspace_id=provider.organization_id,
        key=provider.key,
        display_name=provider.display_name,
        provider_type=provider.provider_type,
        external_account_id=provider.external_account_id,
        metadata=dict(provider.metadata_json),
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


def _metric_definition_response(
    metric_definition: AnalyticsMetricDefinition,
) -> AnalyticsMetricDefinitionResponse:
    return AnalyticsMetricDefinitionResponse(
        id=metric_definition.id,
        workspace_id=metric_definition.organization_id,
        provider=_provider_response(metric_definition.provider),
        key=metric_definition.key,
        display_name=metric_definition.display_name,
        description=metric_definition.description,
        value_type=metric_definition.value_type,
        default_unit=metric_definition.default_unit,
        aggregation=metric_definition.aggregation,
        metadata=dict(metric_definition.metadata_json),
        created_at=metric_definition.created_at,
        updated_at=metric_definition.updated_at,
    )


def _numeric_response(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal("0.000001"))


def _analytics_value_response(
    value: Decimal | str | bool | dict[str, Any] | None,
) -> Decimal | str | bool | dict[str, Any] | None:
    if isinstance(value, Decimal):
        return _numeric_response(value)
    return value


def _observation_response(
    observation: AnalyticsObservation,
) -> AnalyticsObservationResponse:
    campaign = observation.__dict__.get("campaign")
    return AnalyticsObservationResponse(
        id=observation.id,
        workspace_id=observation.organization_id,
        metric_definition_id=observation.metric_definition_id,
        metric_key=observation.metric_definition.key,
        provider_id=observation.provider_id,
        provider_key=observation.provider.key,
        target_type=observation.target_type,
        target_id=observation.target_id,
        artist_profile_id=observation.artist_profile_id,
        campaign_id=observation.campaign_id,
        campaign_name=campaign.name if campaign is not None else None,
        campaign_object_type=observation.campaign_object_type,
        campaign_object_id=observation.campaign_object_id,
        value_numeric=_numeric_response(observation.value_numeric),
        value_text=observation.value_text,
        value_boolean=observation.value_boolean,
        value_json=observation.value_json,
        unit=observation.unit,
        observed_at=observation.observed_at,
        source_record_id=observation.source_record_id,
        idempotency_key=observation.idempotency_key,
        dimensions=dict(observation.dimensions),
        metadata=dict(observation.metadata_json),
        created_at=observation.created_at,
        updated_at=observation.updated_at,
    )


def _observation_query(
    *,
    metric_definition_id: UUID | None = None,
    provider_id: UUID | None = None,
    target_type: str | None = None,
    target_id: UUID | None = None,
    artist_profile_id: UUID | None = None,
    campaign_id: UUID | None = None,
    campaign_object_type: str | None = None,
    campaign_object_id: UUID | None = None,
    observed_start: datetime | None = None,
    observed_end: datetime | None = None,
) -> AnalyticsObservationQuery:
    return AnalyticsObservationQuery(
        metric_definition_id=metric_definition_id,
        provider_id=provider_id,
        target_type=target_type,
        target_id=target_id,
        artist_profile_id=artist_profile_id,
        campaign_id=campaign_id,
        campaign_object_type=campaign_object_type,
        campaign_object_id=campaign_object_id,
        observed_start=observed_start,
        observed_end=observed_end,
    )


def _historical_series_response(
    series: AnalyticsHistoricalSeries,
) -> AnalyticsHistoricalSeriesResponse:
    return AnalyticsHistoricalSeriesResponse(
        aggregation=series.aggregation,
        points=[
            AnalyticsSeriesPointResponse(
                bucket_date=point.bucket_date,
                value=_analytics_value_response(point.value),
                observation_count=point.observation_count,
            )
            for point in series.points
        ],
        value_type=series.value_type,
        unit=series.unit,
        provider_id=series.provider_id,
        metric_definition_id=series.metric_definition_id,
        observation_count=series.observation_count,
    )


def _comparison_response(
    comparison: AnalyticsPreviousPeriodComparison,
) -> AnalyticsPreviousPeriodComparisonResponse:
    return AnalyticsPreviousPeriodComparisonResponse(
        aggregation=comparison.aggregation,
        current_start=comparison.current_start,
        current_end=comparison.current_end,
        previous_start=comparison.previous_start,
        previous_end=comparison.previous_end,
        current_value=_analytics_value_response(comparison.current_value),
        previous_value=_analytics_value_response(comparison.previous_value),
        current_observation_count=comparison.current_observation_count,
        previous_observation_count=comparison.previous_observation_count,
        absolute_change=_numeric_response(comparison.absolute_change),
        percentage_change=_numeric_response(comparison.percentage_change),
        status=comparison.status,
    )


def _bulk_observations_response(
    result: analytics_service.AnalyticsBulkObservationIngestResult,
) -> AnalyticsBulkObservationsResponse:
    return AnalyticsBulkObservationsResponse(
        observations=[
            AnalyticsBulkObservationItemResponse(
                index=item.index,
                created=item.created,
                observation=_observation_response(item.observation),
            )
            for item in result.results
        ],
        created_count=result.created_count,
        existing_count=result.existing_count,
        transaction=result.transaction,
    )


@router.get(
    "/{workspace_id}/analytics/metric-definitions",
    response_model=AnalyticsMetricDefinitionsListResponse,
)
async def list_metric_definitions(
    workspace_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> AnalyticsMetricDefinitionsListResponse:
    try:
        metric_definitions = await analytics_service.list_metric_definitions(
            session,
            workspace_id,
            actor=context,
        )
    except AnalyticsAuthorizationError as exc:
        _service_error(exc)
    return AnalyticsMetricDefinitionsListResponse(
        metric_definitions=[
            _metric_definition_response(metric_definition)
            for metric_definition in metric_definitions
        ]
    )


@router.get(
    "/{workspace_id}/analytics/providers",
    response_model=AnalyticsProvidersListResponse,
)
async def list_providers(
    workspace_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> AnalyticsProvidersListResponse:
    try:
        providers = await analytics_service.list_providers(
            session,
            workspace_id,
            actor=context,
        )
    except AnalyticsAuthorizationError as exc:
        _service_error(exc)
    return AnalyticsProvidersListResponse(
        providers=[_provider_response(provider) for provider in providers]
    )


@router.post(
    "/{workspace_id}/analytics/metric-definitions",
    response_model=AnalyticsMetricDefinitionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_metric_definition(
    workspace_id: UUID,
    payload: AnalyticsMetricDefinitionCreateRequest,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> AnalyticsMetricDefinitionResponse:
    try:
        metric_definition = await analytics_service.create_metric_definition(
            session,
            workspace_id,
            AnalyticsMetricDefinitionCreate(
                provider=AnalyticsProviderRef(**payload.provider.model_dump()),
                **payload.model_dump(exclude={"provider"}),
            ),
            actor=context,
        )
    except (
        AnalyticsNotFoundError,
        AnalyticsRelationshipError,
        AnalyticsAuthorizationError,
    ) as exc:
        _service_error(exc)
    return _metric_definition_response(metric_definition)


@router.get(
    "/{workspace_id}/analytics/observations",
    response_model=AnalyticsObservationsListResponse,
)
async def list_observations(
    workspace_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
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
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AnalyticsObservationsListResponse:
    try:
        page = await analytics_service.list_observations(
            session,
            workspace_id,
            actor=context,
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
            limit=limit,
            offset=offset,
        )
    except (
        AnalyticsNotFoundError,
        AnalyticsRelationshipError,
        AnalyticsAuthorizationError,
    ) as exc:
        _service_error(exc)
    return AnalyticsObservationsListResponse(
        observations=[
            _observation_response(observation) for observation in page.observations
        ],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{workspace_id}/analytics/observations/latest",
    response_model=AnalyticsObservationResponse | None,
)
async def get_latest_observation(
    workspace_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
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
) -> AnalyticsObservationResponse | None:
    try:
        observation = await analytics_service.get_latest_observation(
            session,
            workspace_id,
            actor=context,
            query=_observation_query(
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
            ),
        )
    except (
        AnalyticsNotFoundError,
        AnalyticsRelationshipError,
        AnalyticsAuthorizationError,
    ) as exc:
        _service_error(exc)
    return _observation_response(observation) if observation is not None else None


@router.get(
    "/{workspace_id}/analytics/series",
    response_model=AnalyticsHistoricalSeriesResponse,
)
async def get_historical_series(
    workspace_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
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
    aggregation: AnalyticsAggregation | None = None,
) -> AnalyticsHistoricalSeriesResponse:
    try:
        series = await analytics_service.get_historical_series(
            session,
            workspace_id,
            actor=context,
            query=_observation_query(
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
            ),
            aggregation=aggregation,
        )
    except (
        AnalyticsNotFoundError,
        AnalyticsRelationshipError,
        AnalyticsAuthorizationError,
    ) as exc:
        _service_error(exc)
    return _historical_series_response(series)


@router.get(
    "/{workspace_id}/analytics/comparison",
    response_model=AnalyticsPreviousPeriodComparisonResponse,
)
async def compare_previous_period(
    workspace_id: UUID,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
    current_start: datetime,
    current_end: datetime,
    metric_definition_id: UUID | None = None,
    provider_id: UUID | None = None,
    target_type: str | None = None,
    target_id: UUID | None = None,
    campaign_id: UUID | None = None,
    artist_profile_id: UUID | None = None,
    campaign_object_type: str | None = None,
    campaign_object_id: UUID | None = None,
    aggregation: AnalyticsAggregation | None = None,
) -> AnalyticsPreviousPeriodComparisonResponse:
    try:
        comparison = await analytics_service.compare_previous_period(
            session,
            workspace_id,
            actor=context,
            current_start=current_start,
            current_end=current_end,
            query=_observation_query(
                metric_definition_id=metric_definition_id,
                provider_id=provider_id,
                target_type=target_type,
                target_id=target_id,
                campaign_id=campaign_id,
                artist_profile_id=artist_profile_id,
                campaign_object_type=campaign_object_type,
                campaign_object_id=campaign_object_id,
            ),
            aggregation=aggregation,
        )
    except (
        AnalyticsNotFoundError,
        AnalyticsRelationshipError,
        AnalyticsAuthorizationError,
    ) as exc:
        _service_error(exc)
    return _comparison_response(comparison)


@router.post(
    "/{workspace_id}/analytics/observations",
    response_model=AnalyticsObservationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_observation(
    workspace_id: UUID,
    payload: AnalyticsObservationCreateRequest,
    response: Response,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> AnalyticsObservationResponse:
    try:
        result = await analytics_service.create_observation_result(
            session,
            workspace_id,
            AnalyticsObservationCreate(**payload.model_dump()),
            actor=context,
        )
    except (
        AnalyticsNotFoundError,
        AnalyticsRelationshipError,
        AnalyticsIdempotencyConflictError,
        AnalyticsAuthorizationError,
    ) as exc:
        _service_error(exc)
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return _observation_response(result.observation)


@router.post(
    "/{workspace_id}/analytics/observations/bulk",
    response_model=AnalyticsBulkObservationsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_observations_bulk(
    workspace_id: UUID,
    payload: AnalyticsBulkObservationsCreateRequest,
    response: Response,
    session: SessionDep,
    context: Annotated[CurrentUserContext, Depends(get_current_user_context)],
) -> AnalyticsBulkObservationsResponse | JSONResponse:
    try:
        result = await analytics_service.ingest_observations_bulk(
            session,
            workspace_id,
            [
                AnalyticsObservationCreate(**observation.model_dump())
                for observation in payload.observations
            ],
            actor=context,
        )
    except AnalyticsBulkIngestionError as exc:
        return _bulk_service_error(exc)
    except (
        AnalyticsNotFoundError,
        AnalyticsRelationshipError,
        AnalyticsIdempotencyConflictError,
        AnalyticsAuthorizationError,
    ) as exc:
        _service_error(exc)
    if result.created_count == 0:
        response.status_code = status.HTTP_200_OK
    return _bulk_observations_response(result)
