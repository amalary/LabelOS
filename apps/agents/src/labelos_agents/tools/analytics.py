from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field


class AnalyticsOperationName(StrEnum):
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


class AnalyticsMetricSelector(BaseModel):
    metric_definition_id: str | None = None
    metric_key: str | None = Field(default=None, min_length=1)
    provider_id: str | None = None
    provider_key: str | None = Field(default=None, min_length=1)


class AnalyticsObjectRef(BaseModel):
    object_type: AnalyticsObjectType
    object_id: str
    campaign_id: str | None = None


class AnalyticsDateRange(BaseModel):
    observed_start: datetime | None = None
    observed_end: datetime | None = None


class AnalyticsOperationRequest(BaseModel):
    operation: AnalyticsOperationName
    workspace_id: str
    target: AnalyticsObjectRef | None = None
    metric_selectors: list[AnalyticsMetricSelector] = Field(default_factory=list)
    date_range: AnalyticsDateRange | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class AnalyticsMetricValue(BaseModel):
    metric_definition_id: str
    metric_key: str
    provider_id: str
    provider_key: str
    value_type: str
    unit: str | None = None
    value: Decimal | str | bool | dict[str, Any] | None = None
    aggregation: str | None = None
    observation_count: int | None = None


class AnalyticsOperationResponse(BaseModel):
    operation: AnalyticsOperationName
    workspace_id: str
    values: list[AnalyticsMetricValue] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class AnalyticsOperationsAdapter(Protocol):
    async def execute(
        self,
        request: AnalyticsOperationRequest,
    ) -> AnalyticsOperationResponse:
        """Run a structured analytics operation outside agent reasoning."""
