from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.repositories.dashboard_summary import (
    DashboardSummaryCounts,
    get_dashboard_summary_counts,
)

RELEASE_LIFECYCLE_STATUSES = (
    "planning",
    "production",
    "distribution",
    "scheduled",
    "released",
)


@dataclass(frozen=True)
class DashboardKpis:
    active_artists: int


@dataclass(frozen=True)
class DashboardReleaseCounts:
    upcoming_releases: int
    planning: int
    production: int
    distribution: int
    scheduled: int
    released: int


@dataclass(frozen=True)
class DashboardPerformanceAggregation:
    active_campaigns: int
    pending_approvals: int


@dataclass(frozen=True)
class DashboardSummary:
    kpis: DashboardKpis
    release_counts: DashboardReleaseCounts
    performance: DashboardPerformanceAggregation

    @property
    def active_artists(self) -> int:
        return self.kpis.active_artists

    @property
    def upcoming_releases(self) -> int:
        return self.release_counts.upcoming_releases

    @property
    def active_campaigns(self) -> int:
        return self.performance.active_campaigns

    @property
    def pending_approvals(self) -> int:
        return self.performance.pending_approvals


def aggregate_kpis(counts: DashboardSummaryCounts) -> DashboardKpis:
    return DashboardKpis(active_artists=counts.active_artists)


def aggregate_release_counts(
    counts: DashboardSummaryCounts,
) -> DashboardReleaseCounts:
    # The current releases table has no lifecycle/status column. Until a real
    # release status source exists, persisted releases map to the earliest
    # lifecycle bucket instead of changing schema solely for this dashboard.
    return DashboardReleaseCounts(
        upcoming_releases=counts.upcoming_releases,
        planning=counts.release_pipeline_total,
        production=0,
        distribution=0,
        scheduled=0,
        released=0,
    )


def aggregate_performance(
    counts: DashboardSummaryCounts,
) -> DashboardPerformanceAggregation:
    return DashboardPerformanceAggregation(
        active_campaigns=counts.active_campaigns,
        pending_approvals=counts.pending_approvals,
    )


def build_dashboard_summary(counts: DashboardSummaryCounts) -> DashboardSummary:
    return DashboardSummary(
        kpis=aggregate_kpis(counts),
        release_counts=aggregate_release_counts(counts),
        performance=aggregate_performance(counts),
    )


async def get_dashboard_summary(
    session: AsyncSession,
    organization_id: UUID,
) -> DashboardSummary:
    counts = await get_dashboard_summary_counts(session, organization_id)
    return build_dashboard_summary(counts)
