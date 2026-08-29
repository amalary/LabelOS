from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from labelos_database.models import (
    AnalyticsMetricDefinition,
    AnalyticsMetricValueType,
    AnalyticsObservation,
)
from pydantic import BaseModel, ConfigDict, Field

from labelos_api.auth import CurrentUserContext, SessionDep, get_current_user_context
from labelos_api.services import analytics_service
from labelos_api.services.analytics_service import (
    AnalyticsAuthorizationError,
    AnalyticsMetricDefinitionCreate,
    AnalyticsNotFoundError,
    AnalyticsObservationCreate,
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


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _raise_capability_denial(reason: str) -> None:
    if reason in {"invalid_resource_scope", "membership_not_found"}:
        raise _not_found()
    if reason == "insufficient_department_access":
        raise _forbidden("Insufficient department access")
    raise _forbidden("Insufficient capability permission")


def _service_error(
    exc: (
        AnalyticsNotFoundError
        | AnalyticsRelationshipError
        | AnalyticsAuthorizationError
    ),
) -> None:
    if isinstance(exc, AnalyticsAuthorizationError):
        _raise_capability_denial(exc.reason)
    if isinstance(exc, AnalyticsNotFoundError):
        raise _not_found() from exc
    raise _bad_request(str(exc)) from exc


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


def _observation_response(
    observation: AnalyticsObservation,
) -> AnalyticsObservationResponse:
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
    target_type: str | None = None,
    target_id: UUID | None = None,
    campaign_id: UUID | None = None,
    artist_profile_id: UUID | None = None,
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
            target_type=target_type,
            target_id=target_id,
            campaign_id=campaign_id,
            artist_profile_id=artist_profile_id,
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
        AnalyticsAuthorizationError,
    ) as exc:
        _service_error(exc)
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return _observation_response(result.observation)
