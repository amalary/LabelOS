from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from math import isfinite
from uuid import UUID


class LabelPerformanceMetric(StrEnum):
    streams = "streams"
    listeners = "listeners"
    followers = "followers"
    revenue = "revenue"
    engagement = "engagement"


class LabelPerformancePeriod(StrEnum):
    seven_days = "7d"
    thirty_days = "30d"
    ninety_days = "90d"
    one_year = "1y"


@dataclass(frozen=True)
class NormalizedPerformancePoint:
    date: date
    value: float


@dataclass(frozen=True)
class NormalizedPerformanceSeries:
    metric: LabelPerformanceMetric
    period: LabelPerformancePeriod
    total: float
    change_percent: float
    series: tuple[NormalizedPerformancePoint, ...]
    source: str
    is_mock: bool


@dataclass(frozen=True)
class ProviderPerformancePoint:
    observed_on: date
    value: float


@dataclass(frozen=True)
class ProviderPerformanceSeries:
    provider: str
    metric: LabelPerformanceMetric
    period: LabelPerformancePeriod
    points: tuple[ProviderPerformancePoint, ...]
    is_mock: bool = False


PERIOD_DAYS: dict[LabelPerformancePeriod, int] = {
    LabelPerformancePeriod.seven_days: 7,
    LabelPerformancePeriod.thirty_days: 30,
    LabelPerformancePeriod.ninety_days: 90,
    LabelPerformancePeriod.one_year: 365,
}


class PerformanceDataValidationError(ValueError):
    pass


def _validate_numeric_value(value: float, *, field_name: str) -> None:
    if not isfinite(value):
        raise PerformanceDataValidationError(f"{field_name} must be a finite number")
    if value < 0:
        raise PerformanceDataValidationError(
            f"{field_name} must be greater than or equal to 0"
        )


def _validate_series_dates(
    points: tuple[ProviderPerformancePoint, ...],
    period: LabelPerformancePeriod,
) -> None:
    if not points:
        return

    ordered_dates = [point.observed_on for point in points]
    if ordered_dates != sorted(ordered_dates):
        raise PerformanceDataValidationError("series dates must be sorted ascending")
    if len(set(ordered_dates)) != len(ordered_dates):
        raise PerformanceDataValidationError("series dates must be unique")

    max_span_days = PERIOD_DAYS[period]
    if (ordered_dates[-1] - ordered_dates[0]).days > max_span_days:
        raise PerformanceDataValidationError("series dates exceed the requested period")


def normalize_provider_performance_series(
    provider_series: ProviderPerformanceSeries,
) -> NormalizedPerformanceSeries:
    for point in provider_series.points:
        _validate_numeric_value(point.value, field_name="series value")

    _validate_series_dates(provider_series.points, provider_series.period)

    latest_value = provider_series.points[-1].value if provider_series.points else 0
    first_value = provider_series.points[0].value if provider_series.points else 0
    change_percent = (
        0.0 if first_value == 0 else ((latest_value - first_value) / first_value) * 100
    )

    _validate_numeric_value(latest_value, field_name="total")
    if not isfinite(change_percent):
        raise PerformanceDataValidationError("change_percent must be a finite number")

    return NormalizedPerformanceSeries(
        metric=provider_series.metric,
        period=provider_series.period,
        total=latest_value,
        change_percent=change_percent,
        series=tuple(
            NormalizedPerformancePoint(date=point.observed_on, value=point.value)
            for point in provider_series.points
        ),
        source=provider_series.provider,
        is_mock=provider_series.is_mock,
    )


class DevelopmentMockPerformanceProvider:
    source = "development_mock"

    def get_series(
        self,
        organization_id: UUID,
        metric: LabelPerformanceMetric,
        period: LabelPerformancePeriod,
    ) -> ProviderPerformanceSeries:
        # Keep development data deterministic and explicit; production providers
        # should adapt their native payloads into ProviderPerformanceSeries.
        _ = organization_id
        end_date = date(2026, 8, 12)
        days = PERIOD_DAYS[period]
        point_count = 12 if period == LabelPerformancePeriod.one_year else min(days, 10)
        step_days = max(1, days // point_count)
        start_date = end_date - timedelta(days=step_days * (point_count - 1))

        base_by_metric = {
            LabelPerformanceMetric.streams: 7355000,
            LabelPerformanceMetric.listeners: 2210000,
            LabelPerformanceMetric.followers: 312000,
            LabelPerformanceMetric.revenue: 312000,
            LabelPerformanceMetric.engagement: 5.9,
        }
        growth_by_metric = {
            LabelPerformanceMetric.streams: 104444,
            LabelPerformanceMetric.listeners: 75555,
            LabelPerformanceMetric.followers: 8111,
            LabelPerformanceMetric.revenue: 15111,
            LabelPerformanceMetric.engagement: 0.13,
        }
        period_factor = {
            LabelPerformancePeriod.seven_days: 0.55,
            LabelPerformancePeriod.thirty_days: 1.0,
            LabelPerformancePeriod.ninety_days: 1.85,
            LabelPerformancePeriod.one_year: 4.8,
        }[period]

        points = tuple(
            ProviderPerformancePoint(
                observed_on=start_date + timedelta(days=step_days * index),
                value=round(
                    (base_by_metric[metric] + growth_by_metric[metric] * index)
                    * period_factor,
                    2,
                ),
            )
            for index in range(point_count)
        )

        return ProviderPerformanceSeries(
            provider=self.source,
            metric=metric,
            period=period,
            points=points,
            is_mock=True,
        )


async def get_label_performance_series(
    organization_id: UUID,
    metric: LabelPerformanceMetric,
    period: LabelPerformancePeriod,
) -> NormalizedPerformanceSeries:
    provider = DevelopmentMockPerformanceProvider()
    return normalize_provider_performance_series(
        provider.get_series(organization_id, metric, period)
    )
