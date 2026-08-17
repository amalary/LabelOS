import type {
  LabelPerformanceData,
  LabelPerformanceApiPeriod,
  LabelPerformanceApiSeries,
  LabelPerformanceMetricConfig,
  LabelPerformanceMetricId,
  LabelPerformancePoint,
  LabelPerformanceTimeRange,
} from "./dashboard.types";

export type LabelPerformanceViewModel = {
  metric: LabelPerformanceMetricConfig;
  range: LabelPerformanceTimeRange;
  totalLabel: string;
  changeLabel: string;
  changeDirection: "positive" | "negative" | "neutral";
  chartPoints: LabelPerformancePoint[];
  summary: string;
};

const compactFormatter = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
  notation: "compact",
});

const currencyFormatter = new Intl.NumberFormat("en-US", {
  currency: "USD",
  maximumFractionDigits: 1,
  notation: "compact",
  style: "currency",
});

const percentFormatter = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
  style: "percent",
});

export const periodToRange = {
  "7d": "7D",
  "30d": "30D",
  "90d": "90D",
  "1y": "1Y",
} satisfies Record<LabelPerformanceApiPeriod, LabelPerformanceTimeRange>;

function formatMetricValue(value: number, metric: LabelPerformanceMetricConfig) {
  if (metric.unit === "currency") {
    return currencyFormatter.format(value);
  }

  if (metric.unit === "percent") {
    return percentFormatter.format(value / 100);
  }

  return compactFormatter.format(value);
}

function formatPointLabel(dateValue: string, range: LabelPerformanceTimeRange) {
  const date = new Date(`${dateValue}T00:00:00.000Z`);
  if (Number.isNaN(date.getTime())) {
    return dateValue;
  }

  if (range === "1Y") {
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      timeZone: "UTC",
    }).format(date);
  }

  return new Intl.DateTimeFormat("en-US", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(date);
}

export function toLabelPerformanceData(
  metrics: LabelPerformanceMetricConfig[],
  apiSeries: LabelPerformanceApiSeries[],
): LabelPerformanceData {
  const ranges = new Map<
    LabelPerformanceTimeRange,
    Map<
      string,
      { date: string; label: string; values: Partial<Record<LabelPerformanceMetricId, number>> }
    >
  >();

  for (const series of apiSeries) {
    const range = periodToRange[series.period];
    const rangePoints = ranges.get(range) ?? new Map();

    for (const point of series.series) {
      const existingPoint = rangePoints.get(point.date) ?? {
        date: point.date,
        label: formatPointLabel(point.date, range),
        values: {},
      };

      existingPoint.values[series.metric] = point.value;
      rangePoints.set(point.date, existingPoint);
    }

    ranges.set(range, rangePoints);
  }

  return {
    metrics,
    ranges: Array.from(ranges.entries()).map(([range, points]) => ({
      range,
      points: Array.from(points.values())
        .sort((left, right) => left.date.localeCompare(right.date))
        .map((point) => ({
          ...point,
          values: point.values as Record<LabelPerformanceMetricId, number>,
        })),
    })),
    source: apiSeries[0]?.source,
    isMock: apiSeries.every((series) => series.isMock),
  };
}

function formatChange(value: number) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

export function getLabelPerformanceViewModel(
  data: LabelPerformanceData,
  metricId: LabelPerformanceMetricId,
  range: LabelPerformanceTimeRange,
): LabelPerformanceViewModel | null {
  const metric = data.metrics.find((item) => item.id === metricId);
  const series = data.ranges.find((item) => item.range === range);

  if (!metric || !series || series.points.length === 0) {
    return null;
  }

  const chartPoints = series.points.map((point) => ({
    date: point.date,
    label: point.label,
    value: point.values[metric.id] ?? 0,
  }));
  const firstValue = chartPoints[0]?.value ?? 0;
  const latestValue = chartPoints.at(-1)?.value ?? 0;
  const totalValue = latestValue;
  const changePercent = firstValue === 0 ? 0 : ((latestValue - firstValue) / firstValue) * 100;
  const changeDirection =
    changePercent > 0 ? "positive" : changePercent < 0 ? "negative" : "neutral";
  const totalLabel = formatMetricValue(totalValue, metric);
  const changeLabel = formatChange(changePercent);

  return {
    metric,
    range,
    totalLabel,
    changeLabel,
    changeDirection,
    chartPoints,
    summary: `${metric.label} for ${range}: ${totalLabel}, ${changeLabel} versus the first point in the selected range.`,
  };
}
