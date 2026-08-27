from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from labelos_database.models import MembershipRole
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from labelos_api.auth import (
    CurrentUserContext,
    MembershipContext,
    SessionDep,
    require_active_organization_id,
)
from labelos_api.authorization import (
    Capability,
    Permission,
    has_capability,
    require_capability,
    require_organization,
)
from labelos_api.services.dashboard_service import get_dashboard_summary as get_summary
from labelos_api.services.performance_service import (
    LabelPerformanceMetric,
    LabelPerformancePeriod,
    get_label_performance_series,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class DashboardAuthorizationResponse(BaseModel):
    role: MembershipRole
    permissions: list[Permission]


class DashboardSummaryResponse(BaseModel):
    active_artists: int | None = Field(default=None, ge=0)
    upcoming_releases: int | None = Field(default=None, ge=0)
    active_campaigns: int | None = Field(default=None, ge=0)
    pending_approvals: int | None = Field(default=None, ge=0)
    release_pipeline: dict[str, int] | None = Field(
        default=None, alias="releasePipeline"
    )
    available_cards: list[str] = Field(alias="availableCards")
    available_sections: list[str] = Field(alias="availableSections")
    authorization: DashboardAuthorizationResponse


def _active_membership(context: CurrentUserContext) -> MembershipContext:
    organization_id = require_active_organization_id(context)
    for membership in context.memberships:
        if (
            membership.organization_id == organization_id
            and membership.status == "active"
        ):
            return membership
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Organization context required",
    )


def _has_permission(context: CurrentUserContext, permission: Permission) -> bool:
    return permission.value in context.principal.permissions


def _has_capability(context: CurrentUserContext, capability: Capability) -> bool:
    return has_capability(context, capability)


def _authorization_response(
    context: CurrentUserContext, membership: MembershipContext
) -> DashboardAuthorizationResponse:
    granted = []
    for permission in Permission:
        if _has_permission(context, permission):
            granted.append(permission)
    return DashboardAuthorizationResponse(role=membership.role, permissions=granted)


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


@router.get(
    "/summary",
    response_model=DashboardSummaryResponse,
    response_model_exclude_none=True,
)
async def get_dashboard_summary(
    session: SessionDep,
    context: Annotated[
        CurrentUserContext,
        Depends(require_organization()),
    ],
) -> DashboardSummaryResponse:
    organization_id = require_active_organization_id(context)
    membership = _active_membership(context)
    summary = await get_summary(session, organization_id)
    available_cards: list[str] = []
    available_sections: list[str] = []
    payload: dict[str, object] = {
        "availableCards": available_cards,
        "availableSections": available_sections,
        "authorization": _authorization_response(context, membership),
    }

    if _has_capability(context, Capability.artist_profile_view):
        available_cards.append("active-artists")
        payload["active_artists"] = summary.active_artists
    if _has_capability(context, Capability.release_view):
        available_cards.append("upcoming-releases")
        available_sections.append("release-pipeline")
        payload["upcoming_releases"] = summary.upcoming_releases
        payload["releasePipeline"] = {
            "planning": summary.release_counts.planning,
            "production": summary.release_counts.production,
            "distribution": summary.release_counts.distribution,
            "scheduled": summary.release_counts.scheduled,
            "released": summary.release_counts.released,
        }
    if _has_capability(context, Capability.marketing_campaign_view):
        available_cards.append("active-campaigns")
        payload["active_campaigns"] = summary.active_campaigns
    if _has_capability(context, Capability.contract_approve):
        available_cards.append("tasks-approvals")
        payload["pending_approvals"] = summary.pending_approvals
    if _has_capability(context, Capability.finance_report_view):
        available_sections.append("label-performance")
    if _has_capability(context, Capability.workspace_member_view):
        available_sections.append("member-activity")

    return DashboardSummaryResponse.model_validate(payload)


@router.get("/performance", response_model=LabelPerformanceResponse)
async def get_label_performance(
    context: Annotated[
        CurrentUserContext,
        Depends(require_capability(Capability.analytics_view)),
    ],
    metric: Annotated[LabelPerformanceMetric, Query()],
    period: Annotated[LabelPerformancePeriod, Query()],
) -> LabelPerformanceResponse:
    organization_id = require_active_organization_id(context)
    if not _has_capability(context, Capability.finance_report_view):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient capability permission",
        )
    if metric == LabelPerformanceMetric.revenue and not _has_capability(
        context,
        Capability.royalty_view,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient capability permission",
        )
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
