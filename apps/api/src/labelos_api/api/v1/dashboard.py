from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from labelos_api.auth import (
    CurrentUserContext,
    SessionDep,
    require_active_organization_id,
)
from labelos_api.authorization import Permission, require_permission
from labelos_api.services.dashboard_service import get_dashboard_summary as get_summary
from labelos_api.services.performance_service import (
    LabelPerformanceMetric,
    LabelPerformancePeriod,
    get_label_performance_series,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class DashboardSummaryResponse(BaseModel):
    active_artists: int = Field(ge=0)
    upcoming_releases: int = Field(ge=0)
    active_campaigns: int = Field(ge=0)
    pending_approvals: int = Field(ge=0)
    release_pipeline: dict[str, int] = Field(alias="releasePipeline")


class LabelPerformancePointResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    value: float = Field(ge=0)


class LabelPerformanceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    metric: LabelPerformanceMetric
    period: LabelPerformancePeriod
    total: float = Field(ge=0)
    change_percent: float = Field(alias="changePercent")
    series: list[LabelPerformancePointResponse]
    source: str = Field(min_length=1)
    is_mock: bool = Field(alias="isMock")

    @field_validator("total", "change_percent")
    @classmethod
    def validate_finite_number(cls, value: float) -> float:
        if value in {float("inf"), float("-inf")} or value != value:
            raise ValueError("value must be finite")
        return value

    @model_validator(mode="after")
    def validate_series_dates(self) -> "LabelPerformanceResponse":
        dates = [point.date for point in self.series]
        if dates != sorted(dates):
            raise ValueError("series dates must be sorted ascending")
        if len(set(dates)) != len(dates):
            raise ValueError("series dates must be unique")
        return self


@router.get("/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(
    session: SessionDep,
    context: Annotated[
        CurrentUserContext,
        Depends(require_permission(Permission.analytics_view)),
    ],
) -> DashboardSummaryResponse:
    organization_id = require_active_organization_id(context)
    summary = await get_summary(session, organization_id)
    return DashboardSummaryResponse(
        active_artists=summary.active_artists,
        upcoming_releases=summary.upcoming_releases,
        active_campaigns=summary.active_campaigns,
        pending_approvals=summary.pending_approvals,
        releasePipeline={
            "planning": summary.release_counts.planning,
            "production": summary.release_counts.production,
            "distribution": summary.release_counts.distribution,
            "scheduled": summary.release_counts.scheduled,
            "released": summary.release_counts.released,
        },
    )


@router.get("/performance", response_model=LabelPerformanceResponse)
async def get_label_performance(
    context: Annotated[
        CurrentUserContext,
        Depends(require_permission(Permission.analytics_view)),
    ],
    metric: Annotated[LabelPerformanceMetric, Query()],
    period: Annotated[LabelPerformancePeriod, Query()],
) -> LabelPerformanceResponse:
    organization_id = require_active_organization_id(context)
    performance = await get_label_performance_series(organization_id, metric, period)
    return LabelPerformanceResponse(
        metric=performance.metric,
        period=performance.period,
        total=performance.total,
        changePercent=performance.change_percent,
        series=[
            LabelPerformancePointResponse(date=point.date, value=point.value)
            for point in performance.series
        ],
        source=performance.source,
        isMock=performance.is_mock,
    )
