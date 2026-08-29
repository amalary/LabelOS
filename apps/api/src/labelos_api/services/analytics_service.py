from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
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
ANALYTICS_TARGET_TYPES = frozenset(
    {"workspace", "artist_profile", "campaign", "campaign_object"}
)
SUPPORTED_CAMPAIGN_OBJECT_TYPES = frozenset({"goal", "milestone"})


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
    values = {
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
    if target_values[
        "campaign_object_type"
    ] == "goal" and not await analytics.campaign_goal_in_workspace(
        session,
        workspace_id,
        campaign_id,
        campaign_object_id,
    ):
        raise AnalyticsNotFoundError("Campaign object not found")
    if target_values[
        "campaign_object_type"
    ] == "milestone" and not await analytics.campaign_milestone_in_workspace(
        session,
        workspace_id,
        campaign_id,
        campaign_object_id,
    ):
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


async def list_observations(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    actor: AuthorizationActorInput | None = None,
    metric_definition_id: UUID | None = None,
    target_type: str | None = None,
    target_id: UUID | None = None,
    campaign_id: UUID | None = None,
    artist_profile_id: UUID | None = None,
    observed_start: datetime | None = None,
    observed_end: datetime | None = None,
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
    if metric_definition_id is not None:
        metric_definition = await analytics.get_metric_definition(
            session,
            workspace_id,
            metric_definition_id,
        )
        if metric_definition is None:
            raise AnalyticsNotFoundError("Metric definition not found")
    return await analytics.list_observations(
        session,
        workspace_id,
        metric_definition_id=metric_definition_id,
        target_type=_normalize_optional_text(target_type),
        target_id=target_id,
        campaign_id=campaign_id,
        artist_profile_id=artist_profile_id,
        observed_start=observed_start,
        observed_end=observed_end,
        limit=limit,
        offset=offset,
    )
