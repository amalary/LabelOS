"use client";

import { Badge, Card, EmptyState, Input, LoadingState, cn } from "@label-os/ui";
import { useEffect, useMemo, useState } from "react";

import {
  type AnalyticsAggregation,
  type AnalyticsMetricDefinition,
  type AnalyticsObservation,
  type AnalyticsPreviousPeriodComparison,
  type AnalyticsQueryOptions,
  type AnalyticsSeriesPoint,
  useAnalyticsHistoricalSeries,
  useAnalyticsMetricDefinitions,
  useAnalyticsObservationsByArtist,
  useAnalyticsObservationsByCampaign,
  useAnalyticsObservationsByCampaignChildObject,
  useAnalyticsPreviousPeriodComparison,
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
  artistProfileId?: string;
  campaignId?: string;
  childResources?: AnalyticsChildResource[];
  className?: string;
  selectedChild?: AnalyticsSelectedChildResource;
  title?: string;
  workspaceId: string;
};

type AnalyticsScope =
  | {
      campaignId: string;
      kind: "campaign";
      selectedChild: AnalyticsSelectedChildResource;
    }
  | {
      artistProfileId: string;
      kind: "artist_profile";
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

function formatPercentChange(value: string | null): string {
  if (value === null) {
    return "No comparison";
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "No comparison";
  }
  const percentage = numeric * 100;
  const sign = percentage > 0 ? "+" : "";
  return `${sign}${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(
    percentage,
  )}%`;
}

function observationValue(
  observation: AnalyticsObservation,
): string | boolean | Record<string, unknown> | null {
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

function buildScopedQueryOptions({
  dateRange,
  metric,
  scope,
}: {
  dateRange: AnalyticsDateRange;
  metric: AnalyticsMetricDefinition | null;
  scope: AnalyticsScope;
}): AnalyticsQueryOptions | null {
  if (!metric) {
    return null;
  }

  const aggregation = metricDefaultAggregation(metric);
  const base = {
    aggregation,
    metric_definition_id: metric.id,
    observed_end: toEndIso(dateRange.observedEnd),
    observed_start: toStartIso(dateRange.observedStart),
  };

  if (scope.kind === "artist_profile") {
    return {
      ...base,
      artist_profile_id: scope.artistProfileId,
    };
  }

  if (scope.selectedChild) {
    return {
      ...base,
      campaign_id: scope.campaignId,
      campaign_object_id: scope.selectedChild.id,
      campaign_object_type: scope.selectedChild.type,
      target_id: scope.selectedChild.id,
      target_type: "campaign_object",
    };
  }

  return {
    ...base,
    campaign_id: scope.campaignId,
    target_id: scope.campaignId,
    target_type: "campaign",
  };
}

function buildComparisonOptions({
  dateRange,
  metric,
  scope,
}: {
  dateRange: AnalyticsDateRange;
  metric: AnalyticsMetricDefinition | null;
  scope: AnalyticsScope;
}) {
  const scopedOptions = buildScopedQueryOptions({ dateRange, metric, scope });
  if (!scopedOptions) {
    return null;
  }
  const currentStart = toStartIso(dateRange.observedStart);
  const currentEnd = toEndIso(dateRange.observedEnd);
  if (!currentStart || !currentEnd) {
    return null;
  }
  return {
    ...scopedOptions,
    current_end: currentEnd,
    current_start: currentStart,
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
      aria-label="Analytics trend"
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
        <caption className="sr-only">Recent analytics metric values</caption>
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

function ComparisonPanel({
  comparison,
  isLoading,
  metric,
}: {
  comparison: AnalyticsPreviousPeriodComparison | null;
  isLoading: boolean;
  metric: AnalyticsMetricDefinition | null;
}) {
  if (!metric) {
    return null;
  }

  if (isLoading && !comparison) {
    return <LoadingState label="Loading comparison" />;
  }

  if (!comparison) {
    return (
      <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
        No comparison is available for this range.
      </div>
    );
  }

  return (
    <div className="grid gap-3 rounded-md border border-slate-200 bg-white p-4 sm:grid-cols-3">
      <div>
        <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">Current</p>
        <p className="mt-2 text-lg font-semibold text-slate-950">
          {formatMetricValue(comparison.current_value)}
        </p>
      </div>
      <div>
        <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">Previous</p>
        <p className="mt-2 text-lg font-semibold text-slate-950">
          {formatMetricValue(comparison.previous_value)}
        </p>
      </div>
      <div>
        <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">Change</p>
        <p className="mt-2 text-lg font-semibold text-slate-950">
          {formatPercentChange(comparison.percentage_change)}
        </p>
        <p className="mt-1 text-xs font-medium uppercase tracking-normal text-slate-500">
          {formatLabel(comparison.status)}
        </p>
      </div>
    </div>
  );
}

export function AnalyticsReadSurface({
  artistProfileId,
  campaignId,
  childResources = [],
  className,
  selectedChild = null,
  title = "Analytics",
  workspaceId,
}: AnalyticsReadSurfaceProps) {
  const scope = useMemo<AnalyticsScope | null>(() => {
    if (artistProfileId) {
      return { artistProfileId, kind: "artist_profile" };
    }
    if (campaignId) {
      return { campaignId, kind: "campaign", selectedChild };
    }
    return null;
  }, [artistProfileId, campaignId, selectedChild]);
  const initialRange = useMemo(() => defaultDateRange(), []);
  const [dateRange, setDateRange] = useState<AnalyticsDateRange>(initialRange);
  const metrics = useAnalyticsMetricDefinitions(workspaceId);
  const metricDefinitions = metrics.data?.metric_definitions ?? [];
  const [selectedMetricId, setSelectedMetricId] = useState("all");
  const [selectedProviderId, setSelectedProviderId] = useState("all");
  const providerOptions = useMemo(
    () =>
      Array.from(
        new Map(metricDefinitions.map((metric) => [metric.provider.id, metric.provider])).values(),
      ),
    [metricDefinitions],
  );
  const filteredMetricDefinitions = useMemo(
    () =>
      selectedProviderId === "all"
        ? metricDefinitions
        : metricDefinitions.filter((metric) => metric.provider.id === selectedProviderId),
    [metricDefinitions, selectedProviderId],
  );

  useEffect(() => {
    if (
      selectedMetricId !== "all" &&
      !filteredMetricDefinitions.some((metric) => metric.id === selectedMetricId)
    ) {
      setSelectedMetricId("all");
    }
  }, [filteredMetricDefinitions, selectedMetricId]);

  const selectedMetric =
    selectedMetricId === "all"
      ? (filteredMetricDefinitions[0] ?? null)
      : (filteredMetricDefinitions.find((metric) => metric.id === selectedMetricId) ?? null);
  const selectedMetricFilter =
    selectedMetricId === "all" ? null : (selectedMetric?.id ?? selectedMetricId);
  const selectedMetricAggregation = metricDefaultAggregation(selectedMetric);
  const observationFilters = useMemo(
    () => ({
      limit: 8,
      metric_definition_id: selectedMetricFilter,
      observed_end: toEndIso(dateRange.observedEnd),
      observed_start: toStartIso(dateRange.observedStart),
      provider_id: selectedProviderId === "all" ? null : selectedProviderId,
    }),
    [dateRange.observedEnd, dateRange.observedStart, selectedMetricFilter, selectedProviderId],
  );
  const campaignObservations = useAnalyticsObservationsByCampaign(
    workspaceId,
    scope?.kind === "campaign" ? scope.campaignId : null,
    selectedChild ? { ...observationFilters, include_child_objects: false } : observationFilters,
  );
  const childObservations = useAnalyticsObservationsByCampaignChildObject(
    workspaceId,
    scope?.kind === "campaign" ? scope.campaignId : null,
    selectedChild?.type ?? null,
    selectedChild?.id ?? null,
    observationFilters,
  );
  const artistObservations = useAnalyticsObservationsByArtist(
    workspaceId,
    scope?.kind === "artist_profile" ? scope.artistProfileId : null,
    observationFilters,
  );
  const recentObservations =
    scope?.kind === "artist_profile"
      ? (artistObservations.data?.observations ?? [])
      : selectedChild
        ? (childObservations.data?.observations ?? [])
        : (campaignObservations.data?.observations ?? []);
  const recentLoading =
    scope?.kind === "artist_profile"
      ? artistObservations.isLoading
      : selectedChild
        ? childObservations.isLoading
        : campaignObservations.isLoading;
  const recentError =
    scope?.kind === "artist_profile"
      ? artistObservations.error
      : selectedChild
        ? childObservations.error
        : campaignObservations.error;

  const selectedQueryOptions = useMemo(
    () =>
      scope
        ? buildScopedQueryOptions({
            dateRange,
            metric: selectedMetric,
            scope,
          })
        : null,
    [dateRange, scope, selectedMetric],
  );
  const series = useAnalyticsHistoricalSeries(workspaceId, selectedQueryOptions);
  const comparisonOptions = useMemo(
    () =>
      scope
        ? buildComparisonOptions({
            dateRange,
            metric: selectedMetric,
            scope,
          })
        : null,
    [dateRange, scope, selectedMetric],
  );
  const comparison = useAnalyticsPreviousPeriodComparison(workspaceId, comparisonOptions);
  const headlineMetrics =
    selectedMetricId === "all"
      ? filteredMetricDefinitions.slice(0, 3)
      : filteredMetricDefinitions.filter((metric) => metric.id === selectedMetricId).slice(0, 1);
  const campaignAttributedCount =
    scope?.kind === "artist_profile"
      ? recentObservations.filter((observation) => observation.campaign_id).length
      : 0;
  const campaignAttributionBreakdown = Array.from(
    recentObservations
      .filter((observation) => observation.campaign_id)
      .reduce((campaigns, observation) => {
        const label =
          observation.campaign_name ?? `Campaign ${observation.campaign_id?.slice(0, 8)}`;
        campaigns.set(label, (campaigns.get(label) ?? 0) + 1);
        return campaigns;
      }, new Map<string, number>())
      .entries(),
  );
  const providerObservationBreakdown = Array.from(
    recentObservations
      .reduce((providers, observation) => {
        providers.set(observation.provider_key, (providers.get(observation.provider_key) ?? 0) + 1);
        return providers;
      }, new Map<string, number>())
      .entries(),
  );
  const partialData = Boolean(metrics.error || recentError || series.error || comparison.error);
  const noAnalytics =
    !metrics.isLoading &&
    metricDefinitions.length === 0 &&
    !campaignObservations.isLoading &&
    !childObservations.isLoading &&
    !artistObservations.isLoading;
  const noFilteredMetrics = metricDefinitions.length > 0 && filteredMetricDefinitions.length === 0;

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
            ) : scope?.kind === "artist_profile" ? (
              <Badge variant="neutral">Artist profile</Badge>
            ) : (
              <Badge variant="neutral">Campaign</Badge>
            )}
            {partialData ? <Badge variant="warning">Partial data</Badge> : null}
          </div>
          <p className="mt-1 text-sm text-slate-500">
            Latest metrics, history, source providers, trends, and range comparisons.
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
          <LoadingState label="Loading analytics" />
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
          description="Analytics will appear after metric definitions and observations are connected."
          title="No analytics yet"
        />
      ) : null}

      {metricDefinitions.length > 0 ? (
        <>
          <div className="grid gap-3 rounded-md border border-slate-200 bg-slate-50 p-3 md:grid-cols-2">
            <label className="grid gap-1 text-xs font-semibold uppercase tracking-normal text-slate-500">
              Provider
              <select
                aria-label="Analytics provider filter"
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200"
                onChange={(event) => setSelectedProviderId(event.target.value)}
                value={selectedProviderId}
              >
                <option value="all">All providers</option>
                {providerOptions.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-xs font-semibold uppercase tracking-normal text-slate-500">
              Metric
              <select
                aria-label="Analytics metric filter"
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200"
                onChange={(event) => setSelectedMetricId(event.target.value)}
                value={selectedMetricId}
              >
                <option value="all">All metrics</option>
                {filteredMetricDefinitions.map((metric) => (
                  <option key={metric.id} value={metric.id}>
                    {metric.display_name}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {noFilteredMetrics ? (
            <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
              No metrics match the selected provider.
            </div>
          ) : null}

          <div className="grid gap-3 md:grid-cols-3">
            {headlineMetrics.map((metric) => (
              <HeadlineMetricCard
                dateRange={dateRange}
                key={metric.id}
                metric={metric}
                queryOptions={
                  scope
                    ? buildScopedQueryOptions({
                        dateRange,
                        metric,
                        scope,
                      })
                    : null
                }
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
                    {formatLabel(selectedMetricAggregation)} history for the selected metric.
                  </p>
                </div>
                <select
                  aria-label="Trend metric"
                  className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200"
                  onChange={(event) => setSelectedMetricId(event.target.value)}
                  value={selectedMetric?.id ?? "all"}
                >
                  {filteredMetricDefinitions.map((metric) => (
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
              <ProviderList metrics={filteredMetricDefinitions} />
              {providerObservationBreakdown.length > 0 ? (
                <div className="grid gap-2">
                  {providerObservationBreakdown.map(([providerKey, count]) => (
                    <div
                      className="flex items-center justify-between rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm"
                      key={providerKey}
                    >
                      <span className="font-medium text-slate-800">{formatLabel(providerKey)}</span>
                      <Badge variant="neutral">{count} recent</Badge>
                    </div>
                  ))}
                </div>
              ) : null}
              {scope?.kind === "artist_profile" ? (
                <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-3">
                  <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">
                    Campaign attributed
                  </p>
                  <p className="mt-2 text-2xl font-semibold text-slate-950">
                    {campaignAttributedCount}
                  </p>
                  <p className="mt-1 text-sm text-slate-500">Recent artist observations</p>
                  {campaignAttributionBreakdown.length > 0 ? (
                    <div className="mt-3 grid gap-2">
                      {campaignAttributionBreakdown.slice(0, 4).map(([campaignName, count]) => (
                        <div
                          className="flex items-center justify-between gap-3 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                          key={campaignName}
                        >
                          <span className="min-w-0 truncate font-medium text-slate-800">
                            {campaignName}
                          </span>
                          <Badge variant="neutral">{count}</Badge>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
              {childResources.length > 0 ? (
                <p className="text-sm leading-6 text-slate-500">
                  Goals and milestones can be inspected from the planning section.
                </p>
              ) : null}
            </div>
          </div>

          <div className="grid gap-3">
            <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <h3 className="text-base font-semibold text-slate-950">Range comparison</h3>
              {comparison.error ? <Badge variant="warning">Comparison unavailable</Badge> : null}
            </div>
            {comparison.error ? (
              <div
                className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
                role="alert"
              >
                {comparison.error.message}
              </div>
            ) : (
              <ComparisonPanel
                comparison={comparison.data}
                isLoading={comparison.isLoading}
                metric={selectedMetric}
              />
            )}
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
