from datetime import date

import pytest

from labelos_api.repositories.dashboard_summary import DashboardSummaryCounts
from labelos_api.services.dashboard_service import (
    aggregate_kpis,
    aggregate_performance,
    aggregate_release_counts,
    build_dashboard_summary,
)
from labelos_api.services.performance_service import (
    LabelPerformanceMetric,
    LabelPerformancePeriod,
    PerformanceDataValidationError,
    ProviderPerformancePoint,
    ProviderPerformanceSeries,
    normalize_provider_performance_series,
)


def test_dashboard_summary_aggregates_repository_counts() -> None:
    counts = DashboardSummaryCounts(
        active_artists=4,
        upcoming_releases=3,
        active_campaigns=2,
        pending_approvals=1,
        release_pipeline_total=3,
    )

    summary = build_dashboard_summary(counts)

    assert summary.active_artists == 4
    assert summary.upcoming_releases == 3
    assert summary.release_counts.planning == 3
    assert summary.release_counts.production == 0
    assert summary.release_counts.distribution == 0
    assert summary.release_counts.scheduled == 0
    assert summary.release_counts.released == 0
    assert summary.active_campaigns == 2
    assert summary.pending_approvals == 1


def test_dashboard_aggregation_functions_are_independently_testable() -> None:
    counts = DashboardSummaryCounts(
        active_artists=7,
        upcoming_releases=5,
        active_campaigns=6,
        pending_approvals=2,
        release_pipeline_total=5,
    )

    assert aggregate_kpis(counts).active_artists == 7
    assert aggregate_release_counts(counts).upcoming_releases == 5
    assert aggregate_release_counts(counts).planning == 5
    assert aggregate_performance(counts).active_campaigns == 6
    assert aggregate_performance(counts).pending_approvals == 2


def test_performance_normalization_calculates_stable_contract_values() -> None:
    normalized = normalize_provider_performance_series(
        ProviderPerformanceSeries(
            provider="spotify",
            metric=LabelPerformanceMetric.streams,
            period=LabelPerformancePeriod.thirty_days,
            points=(
                ProviderPerformancePoint(date(2026, 7, 13), 100),
                ProviderPerformancePoint(date(2026, 7, 14), 125),
            ),
        )
    )

    assert normalized.metric == LabelPerformanceMetric.streams
    assert normalized.period == LabelPerformancePeriod.thirty_days
    assert normalized.total == 125
    assert normalized.change_percent == 25
    assert normalized.series[0].date == date(2026, 7, 13)
    assert normalized.source == "spotify"
    assert normalized.is_mock is False


@pytest.mark.parametrize(
    ("points", "message"),
    [
        (
            (
                ProviderPerformancePoint(date(2026, 7, 14), 125),
                ProviderPerformancePoint(date(2026, 7, 13), 100),
            ),
            "series dates must be sorted ascending",
        ),
        (
            (
                ProviderPerformancePoint(date(2026, 7, 13), 100),
                ProviderPerformancePoint(date(2026, 7, 13), 125),
            ),
            "series dates must be unique",
        ),
        (
            (ProviderPerformancePoint(date(2026, 7, 13), -1),),
            "series value must be greater than or equal to 0",
        ),
    ],
)
def test_performance_normalization_validates_provider_data(
    points: tuple[ProviderPerformancePoint, ...],
    message: str,
) -> None:
    with pytest.raises(PerformanceDataValidationError, match=message):
        normalize_provider_performance_series(
            ProviderPerformanceSeries(
                provider="spotify",
                metric=LabelPerformanceMetric.streams,
                period=LabelPerformancePeriod.thirty_days,
                points=points,
            )
        )
