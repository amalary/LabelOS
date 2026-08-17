from dataclasses import dataclass
from uuid import UUID

from labelos_database.models import Artist, Campaign, Contract, Release
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class DashboardSummaryCounts:
    active_artists: int
    upcoming_releases: int
    active_campaigns: int
    pending_approvals: int
    release_pipeline_total: int


def _organization_count(model, organization_id: UUID):
    return (
        select(func.count())
        .select_from(model)
        .where(model.organization_id == organization_id)
        .scalar_subquery()
    )


async def get_dashboard_summary_counts(
    session: AsyncSession,
    organization_id: UUID,
) -> DashboardSummaryCounts:
    row = await session.execute(
        select(
            _organization_count(Artist, organization_id).label("active_artists"),
            _organization_count(Release, organization_id).label("upcoming_releases"),
            _organization_count(Campaign, organization_id).label("active_campaigns"),
            _organization_count(Contract, organization_id).label("pending_approvals"),
        )
    )
    counts = row.one()
    return DashboardSummaryCounts(
        active_artists=counts.active_artists,
        upcoming_releases=counts.upcoming_releases,
        active_campaigns=counts.active_campaigns,
        pending_approvals=counts.pending_approvals,
        release_pipeline_total=counts.upcoming_releases,
    )
