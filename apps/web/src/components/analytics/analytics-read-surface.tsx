"use client";

import { Badge, Card, EmptyState, Input, LoadingState, cn } from "@label-os/ui";
import { useEffect, useMemo, useState } from "react";

import {
  type AnalyticsAggregation,
  type AnalyticsMetricDefinition,
  type AnalyticsObservation,
  type AnalyticsQueryOptions,
  type AnalyticsSeriesPoint,
  useAnalyticsHistoricalSeries,
  useAnalyticsMetricDefinitions,
  useAnalyticsObservationsByCampaign,
  useAnalyticsObservationsByCampaignChildObject,
  useAnalyticsSummary,
} from "../../lib/analytics";

export type AnalyticsChildResource = {
  id: string;
  label: string;
  type: "goal" | "milestone";
};

export type AnalyticsSelectedChildResource = AnalyticsChildResource | null;

type AnalyticsDateRange = {
  observedEnd: string;
  observedStart: string;
};

type AnalyticsReadSurfaceProps = {
  campaignId: string;
  childResources?: AnalyticsChildResource[];
  className?: string;
  selectedChild?: AnalyticsSelectedChildResource;
  title?: string;
  workspaceId: string;
};

const numericAggregations: AnalyticsAggregation[] = [
  "sum",
  "average",
  "min",
  "max",
  "latest",
  "count",
];
const nonNumericAggregations: AnalyticsAggregation[] = ["latest", "count"];

function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function defaultDateRange(): AnalyticsDateRange {
  const end = new Date();
  const start = new Date(end);
  start.setDate(end.getDate() - 30);
  return {
    observedEnd: isoDate(end),
    observedStart: isoDate(start),
  };
}

function toStartIso(dateValue: string): string | null {
  return dateValue ? `${dateValue}T00:00:00Z` : null;
}

function toEndIso(dateValue: string): string | null {
  return dateValue ? `${dateValue}T23:59:59Z` : null;
}

function formatLabel(value: string | null | undefined): string {
  if (!value) {
    return "Not set";
  }
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function metricSupportsNumericAggregation(metric: AnalyticsMetricDefinition | null): boolean {
  return metric?.value_type === "integer" || metric?.value_type === "decimal";
}

function metricDefaultAggregation(metric: AnalyticsMetricDefinition | null): AnalyticsAggregation {
  const options = metricSupportsNumericAggregation(metric)
    ? numericAggregations
    : nonNumericAggregations;
  return options.includes(metric?.aggregation as AnalyticsAggregation)
    ? (metric?.aggregation as AnalyticsAggregation)
    : (options[0] ?? "latest");
}

function formatMetricValue(value: string | boolean | Record<string, unknown> | null): string {
  if (typeof value === "boolean") {
    return value ? "True" : "False";
  }
  if (value && typeof value === "object") {
    return "JSON value";
  }
  if (value === null || value === "") {
    return "No data";
  }
  const numeric = Number(value);
  if (Number.isFinite(numeric)) {
    return new Intl.NumberFormat("en-US", {
      maximumFractionDigits: 2,
    }).format(numeric);
  }
  return value;
}

function observationValue(observation: AnalyticsObservation): string | boolean | Record<string, unknown> | null {
  return (
    observation.value_numeric ??
    observation.value_text ??
    observation.value_boolean ??
    observation.value_json ??
    null
  );
}

function formatObservedAt(value: string): string {
  return new Intl.DateTimeFormat("en", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}

function buildTargetOptions({
  campaignId,
  dateRange,
  metric,
  selectedChild,
}: {
  campaignId: string;
  dateRange: AnalyticsDateRange;
  metric: AnalyticsMetricDefinition | null;
  selectedChild: AnalyticsSelectedChildResource;
}): AnalyticsQueryOptions | null {
  if (!metric) {
    return null;
  }

  const aggregation = metricDefaultAggregation(metric);
  const base = {
    aggregation,
    campaign_id: campaignId,
    metric_definition_id: metric.id,
    observed_end: toEndIso(dateRange.observedEnd),
    observed_start: toStartIso(dateRange.observedStart),
  };

  if (selectedChild) {
    return {
      ...base,
      campaign_object_id: selectedChild.id,
      campaign_object_type: selectedChild.type,
      target_id: selectedChild.id,
      target_type: "campaign_object",
    };
  }

  return {
    ...base,
    target_id: campaignId,
    target_type: "campaign",
  };
}

function AnalyticsSparkline({ points }: { points: AnalyticsSeriesPoint[] }) {
  const numericPoints = points
    .map((point) => ({
      ...point,
      numericValue: typeof point.value === "string" ? Number(point.value) : Number.NaN,
    }))
    .filter((point) => Number.isFinite(point.numericValue));

  if (numericPoints.length < 2) {
    return (
      <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
        Not enough numeric points to show a trend.
      </div>
    );
  }

  const width = 640;
  const height = 180;
  const padding = 18;
  const chartWidth = width - padding * 2;
  const chartHeight = height - padding * 2;
  const values = numericPoints.map((point) => point.numericValue);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const coordinates = numericPoints.map((point, index) => {
    const x = padding + (index / (numericPoints.length - 1)) * chartWidth;
    const y = padding + chartHeight - ((point.numericValue - min) / range) * chartHeight;
    return { ...point, x, y };
  });
  const path = coordinates
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
    .join(" ");

  return (
    <figure
      aria-label="Campaign analytics trend"
      className="rounded-md border border-slate-200 bg-white p-3"
    >
      <div className="h-40 w-full">
        <svg
          aria-hidden="true"
          className="h-full w-full overflow-visible"
          preserveAspectRatio="none"
          viewBox={`0 0 ${width} ${height}`}
        >
          {[0, 0.5, 1].map((step) => (
            <line
              key={step}
              stroke="rgb(148 163 184 / 0.3)"
              strokeWidth="1"
              x1={padding}
              x2={width - padding}
              y1={padding + chartHeight * step}
              y2={padding + chartHeight * step}
            />
          ))}
          <path
            d={path}
            fill="none"
            stroke="#0f766e"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="3"
            vectorEffect="non-scaling-stroke"
          />
          {coordinates.map((point) => (
            <circle
              cx={point.x}
              cy={point.y}
              fill="#14b8a6"
              key={`${point.bucket_date}-${String(point.value)}`}
              r="4"
              stroke="#ffffff"
              strokeWidth="2"
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </svg>
      </div>
    </figure>
  );
}

function HeadlineMetricCard({
  dateRange,
  metric,
  queryOptions,
  workspaceId,
}: {
  dateRange: AnalyticsDateRange;
  metric: AnalyticsMetricDefinition;
  queryOptions: AnalyticsQueryOptions | null;
  workspaceId: string;
}) {
  const summary = useAnalyticsSummary(workspaceId, queryOptions);
  const latestPoint = summary.data?.points.at(-1) ?? null;
  const value = latestPoint ? formatMetricValue(latestPoint.value) : "No data";
  const unsupported = !metricSupportsNumericAggregation(metric) && metric.value_type !== "boolean";

  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold uppercase tracking-normal text-slate-500">
            {metric.display_name}
          </p>
          <p className="mt-2 text-2xl font-semibold text-slate-950">
            {summary.isLoading && !summary.data ? "Loading" : value}
          </p>
        </div>
        <Badge variant={summary.error || unsupported ? "warning" : "neutral"}>
          {formatLabel(metricDefaultAggregation(metric))}
        </Badge>
      </div>
      <p className="mt-2 text-sm text-slate-500">
        {metric.default_unit ?? summary.data?.unit ?? "value"} from {metric.provider.display_name}
      </p>
      {summary.error ? (
        <p className="mt-2 text-sm text-amber-800">This metric could not be summarized.</p>
      ) : null}
      {unsupported ? (
        <p className="mt-2 text-sm text-slate-500">
          {formatLabel(metric.value_type)} metrics are shown as latest values only.
        </p>
      ) : null}
      <p className="sr-only">
        Range {dateRange.observedStart} through {dateRange.observedEnd}
      </p>
    </div>
  );
}

function RecentMetricValues({ observations }: { observations: AnalyticsObservation[] }) {
  if (observations.length === 0) {
    return (
      <div className="rounded-md border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
        No recent metric values match this range.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Recent campaign metric values</caption>
        <thead className="bg-slate-50 text-xs uppercase tracking-normal text-slate-500">
          <tr>
            <th className="px-4 py-3" scope="col">
              Metric
            </th>
            <th className="px-4 py-3" scope="col">
              Value
            </th>
            <th className="px-4 py-3" scope="col">
              Source
            </th>
            <th className="px-4 py-3" scope="col">
              Observed
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {observations.map((observation) => (
            <tr key={observation.id}>
              <td className="px-4 py-3 font-medium text-slate-900">
                {formatLabel(observation.metric_key)}
              </td>
              <td className="px-4 py-3 text-slate-700">
                {formatMetricValue(observationValue(observation))}
                {observation.unit ? (
                  <span className="ml-1 text-slate-500">{observation.unit}</span>
                ) : null}
              </td>
              <td className="px-4 py-3 text-slate-500">
                {formatLabel(observation.provider_key)}
                {observation.source_record_id ? (
                  <span className="block truncate text-xs">{observation.source_record_id}</span>
                ) : null}
              </td>
              <td className="px-4 py-3 text-slate-500">
                {formatObservedAt(observation.observed_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ProviderList({ metrics }: { metrics: AnalyticsMetricDefinition[] }) {
  const providers = Array.from(
    new Map(metrics.map((metric) => [metric.provider.id, metric.provider])).values(),
  );

  if (providers.length === 0) {
    return null;
  }

  return (
    <div className="grid gap-2">
      {providers.map((provider) => (
        <div
          className="flex flex-col gap-1 rounded-md border border-slate-200 bg-white px-3 py-3 sm:flex-row sm:items-center sm:justify-between"
          key={provider.id}
        >
          <div>
            <p className="text-sm font-semibold text-slate-950">{provider.display_name}</p>
            <p className="text-sm text-slate-500">{formatLabel(provider.provider_type)}</p>
          </div>
          <Badge variant="neutral">{provider.key}</Badge>
        </div>
      ))}
    </div>
  );
}

export function AnalyticsReadSurface({
  campaignId,
  childResources = [],
  className,
  selectedChild = null,
  title = "Analytics",
  workspaceId,
}: AnalyticsReadSurfaceProps) {
  const initialRange = useMemo(() => defaultDateRange(), []);
  const [dateRange, setDateRange] = useState<AnalyticsDateRange>(initialRange);
  const metrics = useAnalyticsMetricDefinitions(workspaceId);
  const metricDefinitions = metrics.data?.metric_definitions ?? [];
  const [selectedMetricId, setSelectedMetricId] = useState("");

  useEffect(() => {
    const firstMetric = metricDefinitions[0] ?? null;
    if (!selectedMetricId && firstMetric) {
      setSelectedMetricId(firstMetric.id);
    }
  }, [metricDefinitions, selectedMetricId]);

  const selectedMetric =
    metricDefinitions.find((metric) => metric.id === selectedMetricId) ??
    metricDefinitions[0] ??
    null;
  const selectedMetricAggregation = metricDefaultAggregation(selectedMetric);
  const observationFilters = useMemo(
    () => ({
      limit: 8,
      observed_end: toEndIso(dateRange.observedEnd),
      observed_start: toStartIso(dateRange.observedStart),
    }),
    [dateRange.observedEnd, dateRange.observedStart],
  );
  const campaignObservations = useAnalyticsObservationsByCampaign(
    workspaceId,
    campaignId,
    selectedChild ? { ...observationFilters, include_child_objects: false } : observationFilters,
  );
  const childObservations = useAnalyticsObservationsByCampaignChildObject(
    workspaceId,
    campaignId,
    selectedChild?.type ?? null,
    selectedChild?.id ?? null,
    observationFilters,
  );
  const recentObservations = selectedChild
    ? childObservations.data?.observations ?? []
    : campaignObservations.data?.observations ?? [];
  const recentLoading = selectedChild ? childObservations.isLoading : campaignObservations.isLoading;
  const recentError = selectedChild ? childObservations.error : campaignObservations.error;

  const selectedQueryOptions = useMemo(
    () =>
      buildTargetOptions({
        campaignId,
        dateRange,
        metric: selectedMetric,
        selectedChild,
      }),
    [campaignId, dateRange, selectedChild, selectedMetric],
  );
  const series = useAnalyticsHistoricalSeries(workspaceId, selectedQueryOptions);
  const headlineMetrics = metricDefinitions.slice(0, 3);
  const partialData = Boolean(metrics.error || recentError || series.error);
  const noAnalytics =
    !metrics.isLoading &&
    metricDefinitions.length === 0 &&
    !campaignObservations.isLoading &&
    !childObservations.isLoading;

  return (
    <Card className={cn("grid gap-5", className)}>
      <div className="flex flex-col gap-3 border-b border-slate-200 pb-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
            {selectedChild ? (
              <Badge variant="neutral">
                {formatLabel(selectedChild.type)}: {selectedChild.label}
              </Badge>
            ) : (
              <Badge variant="neutral">Campaign</Badge>
            )}
            {partialData ? <Badge variant="warning">Partial data</Badge> : null}
          </div>
          <p className="mt-1 text-sm text-slate-500">
            Campaign metrics, recent observations, source providers, and trends.
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="grid gap-1 text-xs font-semibold uppercase tracking-normal text-slate-500">
            Start
            <Input
              aria-label="Analytics start date"
              onChange={(event) =>
                setDateRange((current) => ({ ...current, observedStart: event.target.value }))
              }
              type="date"
              value={dateRange.observedStart}
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold uppercase tracking-normal text-slate-500">
            End
            <Input
              aria-label="Analytics end date"
              onChange={(event) =>
                setDateRange((current) => ({ ...current, observedEnd: event.target.value }))
              }
              type="date"
              value={dateRange.observedEnd}
            />
          </label>
        </div>
      </div>

      {metrics.isLoading && !metrics.data ? (
        <div className="grid gap-3">
          <LoadingState label="Loading campaign analytics" />
          <div className="h-28 rounded-md bg-slate-100 auth-shimmer" />
        </div>
      ) : null}

      {metrics.error ? (
        <div
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
          role="alert"
        >
          Analytics metric definitions could not be loaded.
        </div>
      ) : null}

      {noAnalytics ? (
        <EmptyState
          description="Campaign analytics will appear after metric definitions and observations are connected."
          title="No analytics yet"
        />
      ) : null}

      {metricDefinitions.length > 0 ? (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            {headlineMetrics.map((metric) => (
              <HeadlineMetricCard
                dateRange={dateRange}
                key={metric.id}
                metric={metric}
                queryOptions={buildTargetOptions({
                  campaignId,
                  dateRange,
                  metric,
                  selectedChild,
                })}
                workspaceId={workspaceId}
              />
            ))}
          </div>

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_300px]">
            <div className="grid gap-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h3 className="text-base font-semibold text-slate-950">Trend</h3>
                  <p className="mt-1 text-sm text-slate-500">
                    Backend {formatLabel(selectedMetricAggregation)} series for the selected metric.
                  </p>
                </div>
                <select
                  aria-label="Trend metric"
                  className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200"
                  onChange={(event) => setSelectedMetricId(event.target.value)}
                  value={selectedMetric?.id ?? ""}
                >
                  {metricDefinitions.map((metric) => (
                    <option key={metric.id} value={metric.id}>
                      {metric.display_name}
                    </option>
                  ))}
                </select>
              </div>

              {series.error ? (
                <div
                  className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
                  role="alert"
                >
                  {series.error.message}
                </div>
              ) : null}
              {series.isLoading && !series.data ? (
                <LoadingState label="Loading trend" />
              ) : selectedMetric && !metricSupportsNumericAggregation(selectedMetric) ? (
                <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                  {formatLabel(selectedMetric.value_type)} metrics do not support numeric trend
                  visualization yet.
                </div>
              ) : series.data && series.data.points.length > 0 ? (
                <AnalyticsSparkline points={series.data.points} />
              ) : (
                <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                  No trend points match the selected range.
                </div>
              )}
            </div>

            <div className="grid content-start gap-3">
              <h3 className="text-base font-semibold text-slate-950">Providers</h3>
              <ProviderList metrics={metricDefinitions} />
              {childResources.length > 0 ? (
                <p className="text-sm leading-6 text-slate-500">
                  Goals and milestones can be inspected from the planning section.
                </p>
              ) : null}
            </div>
          </div>

          <div className="grid gap-3">
            <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <h3 className="text-base font-semibold text-slate-950">Recent metric values</h3>
              {recentError ? <Badge variant="warning">Recent values unavailable</Badge> : null}
            </div>
            {recentLoading && recentObservations.length === 0 ? (
              <LoadingState label="Loading recent values" />
            ) : recentError ? (
              <div
                className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
                role="alert"
              >
                {recentError.message}
              </div>
            ) : (
              <RecentMetricValues observations={recentObservations} />
            )}
          </div>
        </>
      ) : null}
    </Card>
  );
}
