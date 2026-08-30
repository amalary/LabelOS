"use client";

import { Badge, Button, Card, EmptyState, Input, LoadingState, PageHeader, cn } from "@label-os/ui";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import {
  createAnalyticsMetricDefinition,
  createAnalyticsObservation,
  type AnalyticsAggregation,
  type AnalyticsHistoricalSeries,
  type AnalyticsMetricDefinition,
  type AnalyticsMetricValueType,
  type AnalyticsPreviousPeriodComparison,
  type AnalyticsQueryOptions,
  type AnalyticsSeriesPoint,
  clearAnalyticsCache,
  useAnalyticsHistoricalSeries,
  useAnalyticsMetricDefinitions,
  useAnalyticsPreviousPeriodComparison,
} from "../../lib/analytics";
import { can, capabilities } from "../../lib/authorization";
import { useCampaignGoals, useCampaignMilestones, useCampaigns } from "../../lib/campaigns";
import { useWorkspacePeopleDirectory } from "../../lib/profiles";
import { useActiveWorkspace, useActiveWorkspaceProfile } from "../../lib/workspace-context";

type TargetType = "workspace" | "artist_profile" | "campaign" | "campaign_object";
type CampaignObjectType = "goal" | "milestone";
type AnalyticsWriterTab = "metric" | "observation";

type AnalyticsFilterState = {
  metricDefinitionId: string;
  targetType: TargetType;
  artistProfileId: string;
  campaignId: string;
  campaignObjectType: CampaignObjectType;
  campaignObjectId: string;
  aggregation: AnalyticsAggregation;
  observedStart: string;
  observedEnd: string;
};

type MetricDefinitionFormState = {
  aggregation: AnalyticsAggregation;
  defaultUnit: string;
  description: string;
  displayName: string;
  key: string;
  providerDisplayName: string;
  providerKey: string;
  providerType: string;
  valueType: AnalyticsMetricValueType;
};

type ObservationFormState = {
  idempotencyKey: string;
  observedAt: string;
  sourceRecordId: string;
  unit: string;
  value: string;
};

type ObservationTargetFields = {
  artist_profile_id?: string | null;
  campaign_id?: string | null;
  campaign_object_id?: string | null;
  campaign_object_type?: string | null;
  target_id?: string | null;
  target_type: string;
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
const metricValueTypes: AnalyticsMetricValueType[] = [
  "integer",
  "decimal",
  "string",
  "boolean",
  "json",
];

function initialMetricDefinitionForm(): MetricDefinitionFormState {
  return {
    aggregation: "sum",
    defaultUnit: "count",
    description: "",
    displayName: "",
    key: "",
    providerDisplayName: "Internal Analytics",
    providerKey: "internal",
    providerType: "internal",
    valueType: "integer",
  };
}

function initialObservationForm(metric: AnalyticsMetricDefinition | null): ObservationFormState {
  const now = new Date();
  now.setSeconds(0, 0);
  return {
    idempotencyKey: "",
    observedAt: now.toISOString().slice(0, 16),
    sourceRecordId: "",
    unit: metric?.default_unit ?? "",
    value: metric?.value_type === "boolean" ? "true" : "",
  };
}

function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function initialDateRange(): Pick<AnalyticsFilterState, "observedStart" | "observedEnd"> {
  const end = new Date();
  const start = new Date(end);
  start.setDate(end.getDate() - 30);
  return {
    observedStart: isoDate(start),
    observedEnd: isoDate(end),
  };
}

function toStartIso(dateValue: string): string | null {
  return dateValue ? `${dateValue}T00:00:00Z` : null;
}

function toEndIso(dateValue: string): string | null {
  return dateValue ? `${dateValue}T23:59:59Z` : null;
}

function toExclusiveEndIso(dateValue: string): string | null {
  if (!dateValue) {
    return null;
  }
  const end = new Date(`${dateValue}T00:00:00Z`);
  end.setUTCDate(end.getUTCDate() + 1);
  return end.toISOString();
}

function toObservedAtIso(value: string): string {
  return new Date(value).toISOString();
}

function formatLabel(value: string | null | undefined): string {
  if (!value) {
    return "Not set";
  }
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function metricKeyFromName(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function formatNumber(value: string | boolean | Record<string, unknown> | null): string {
  if (typeof value === "boolean") {
    return value ? "True" : "False";
  }
  if (value && typeof value === "object") {
    return JSON.stringify(value);
  }
  if (value === null) {
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

function formatPercent(value: string | null): string {
  if (value === null) {
    return "n/a";
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "n/a";
  }
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 1,
    style: "percent",
  }).format(numeric);
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

function buildQueryOptions(
  workspaceId: string,
  filters: AnalyticsFilterState,
): AnalyticsQueryOptions | null {
  if (!filters.metricDefinitionId) {
    return null;
  }

  const base: AnalyticsQueryOptions = {
    aggregation: filters.aggregation,
    metric_definition_id: filters.metricDefinitionId,
    observed_end: toEndIso(filters.observedEnd),
    observed_start: toStartIso(filters.observedStart),
    target_type: filters.targetType,
  };

  if (filters.targetType === "workspace") {
    return {
      ...base,
      target_id: workspaceId,
    };
  }
  if (filters.targetType === "artist_profile" && filters.artistProfileId) {
    return {
      ...base,
      artist_profile_id: filters.artistProfileId,
      target_id: filters.artistProfileId,
    };
  }
  if (filters.targetType === "campaign" && filters.campaignId) {
    return {
      ...base,
      campaign_id: filters.campaignId,
      target_id: filters.campaignId,
    };
  }
  if (filters.targetType === "campaign_object" && filters.campaignId && filters.campaignObjectId) {
    return {
      ...base,
      campaign_id: filters.campaignId,
      campaign_object_id: filters.campaignObjectId,
      campaign_object_type: filters.campaignObjectType,
      target_id: filters.campaignObjectId,
    };
  }

  return base;
}

function buildTargetFields(
  workspaceId: string,
  filters: AnalyticsFilterState,
): ObservationTargetFields {
  if (filters.targetType === "artist_profile" && filters.artistProfileId) {
    return {
      artist_profile_id: filters.artistProfileId,
      target_id: filters.artistProfileId,
      target_type: filters.targetType,
    };
  }
  if (filters.targetType === "campaign" && filters.campaignId) {
    return {
      campaign_id: filters.campaignId,
      target_id: filters.campaignId,
      target_type: filters.targetType,
    };
  }
  if (filters.targetType === "campaign_object" && filters.campaignId && filters.campaignObjectId) {
    return {
      campaign_id: filters.campaignId,
      campaign_object_id: filters.campaignObjectId,
      campaign_object_type: filters.campaignObjectType,
      target_id: filters.campaignObjectId,
      target_type: filters.targetType,
    };
  }
  return {
    target_id: workspaceId,
    target_type: "workspace",
  };
}

function buildComparisonOptions(
  options: AnalyticsQueryOptions | null,
  filters: AnalyticsFilterState,
) {
  const current_start = toStartIso(filters.observedStart);
  const current_end = toExclusiveEndIso(filters.observedEnd);
  if (!options || !current_start || !current_end) {
    return null;
  }
  const rest = { ...options };
  delete rest.observed_end;
  delete rest.observed_start;
  return {
    ...rest,
    current_end,
    current_start,
  };
}

function metricValuePayload(metric: AnalyticsMetricDefinition, value: string) {
  if (metric.value_type === "integer" || metric.value_type === "decimal") {
    if (!value.trim()) {
      throw new Error("Enter a numeric value.");
    }
    return { value_numeric: value.trim() };
  }
  if (metric.value_type === "string") {
    return { value_text: value };
  }
  if (metric.value_type === "boolean") {
    return { value_boolean: value === "true" };
  }
  if (!value.trim()) {
    return { value_json: {} };
  }
  const parsed = JSON.parse(value) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("JSON metric values must be an object.");
  }
  return { value_json: parsed as Record<string, unknown> };
}

function MetricSummary({
  comparison,
  metric,
  series,
}: {
  comparison: AnalyticsPreviousPeriodComparison | null;
  metric: AnalyticsMetricDefinition | null;
  series: AnalyticsHistoricalSeries | null;
}) {
  const latestPoint = series?.points.at(-1);
  const latestValue = latestPoint ? formatNumber(latestPoint.value) : "No data";
  const unit = series?.unit ?? metric?.default_unit ?? "value";

  return (
    <div className="grid gap-3 md:grid-cols-3">
      <Card>
        <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">Latest</p>
        <p className="mt-2 text-2xl font-semibold text-slate-950">{latestValue}</p>
        <p className="mt-1 text-sm text-slate-500">{unit}</p>
      </Card>
      <Card>
        <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">Observed</p>
        <p className="mt-2 text-2xl font-semibold text-slate-950">
          {series?.observation_count ?? 0}
        </p>
        <p className="mt-1 text-sm text-slate-500">raw observations</p>
      </Card>
      <Card>
        <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">Change</p>
        <p className="mt-2 text-2xl font-semibold text-slate-950">
          {comparison ? formatPercent(comparison.percentage_change) : "n/a"}
        </p>
        <p className="mt-1 text-sm text-slate-500">
          {comparison ? formatLabel(comparison.status) : "No comparison"}
        </p>
      </Card>
    </div>
  );
}

function AnalyticsSeriesChart({ points }: { points: AnalyticsSeriesPoint[] }) {
  const numericPoints = points
    .map((point) => ({
      ...point,
      numericValue: typeof point.value === "string" ? Number(point.value) : Number.NaN,
    }))
    .filter((point) => Number.isFinite(point.numericValue));

  if (numericPoints.length === 0) {
    return null;
  }

  const width = 720;
  const height = 240;
  const padding = { bottom: 34, left: 34, right: 18, top: 18 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const values = numericPoints.map((point) => point.numericValue);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const range = maxValue - minValue || 1;
  const coordinates = numericPoints.map((point, index) => {
    const x =
      padding.left +
      (numericPoints.length === 1 ? chartWidth : (index / (numericPoints.length - 1)) * chartWidth);
    const y = padding.top + chartHeight - ((point.numericValue - minValue) / range) * chartHeight;
    return { ...point, x, y };
  });
  const path = coordinates
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
    .join(" ");
  const firstPoint = coordinates[0];
  const lastPoint = coordinates.at(-1);

  return (
    <figure
      aria-label="Analytics series chart"
      className="rounded-md border border-slate-200 bg-white p-3"
    >
      <div className="h-56 w-full">
        <svg
          aria-hidden="true"
          className="h-full w-full overflow-visible"
          preserveAspectRatio="none"
          viewBox={`0 0 ${width} ${height}`}
        >
          {[0, 0.25, 0.5, 0.75, 1].map((step) => (
            <line
              key={step}
              stroke="rgb(148 163 184 / 0.28)"
              strokeWidth="1"
              x1={padding.left}
              x2={width - padding.right}
              y1={padding.top + chartHeight * step}
              y2={padding.top + chartHeight * step}
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
              key={`${point.bucket_date}-${point.value}`}
              r="4"
              stroke="#ffffff"
              strokeWidth="2"
              vectorEffect="non-scaling-stroke"
            />
          ))}
          {firstPoint ? (
            <text fill="#64748b" fontSize="12" x={firstPoint.x} y={height - 10}>
              {firstPoint.bucket_date}
            </text>
          ) : null}
          {lastPoint ? (
            <text fill="#64748b" fontSize="12" textAnchor="end" x={lastPoint.x} y={height - 10}>
              {lastPoint.bucket_date}
            </text>
          ) : null}
        </svg>
      </div>
    </figure>
  );
}

function AnalyticsSeriesTable({ points }: { points: AnalyticsSeriesPoint[] }) {
  return (
    <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Analytics series data</caption>
        <thead className="bg-slate-50 text-xs uppercase tracking-normal text-slate-500">
          <tr>
            <th className="px-4 py-3" scope="col">
              Date
            </th>
            <th className="px-4 py-3" scope="col">
              Value
            </th>
            <th className="px-4 py-3" scope="col">
              Observations
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {points.map((point) => (
            <tr key={`${point.bucket_date}-${point.observation_count}-${String(point.value)}`}>
              <td className="px-4 py-3 font-medium text-slate-900">{point.bucket_date}</td>
              <td className="px-4 py-3 text-slate-700">{formatNumber(point.value)}</td>
              <td className="px-4 py-3 text-slate-500">{point.observation_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AnalyticsFilters({
  campaigns,
  campaignObjectOptions,
  filters,
  metrics,
  onChange,
  people,
}: {
  campaigns: Array<{ id: string; name: string }>;
  campaignObjectOptions: Array<{ id: string; label: string; type: CampaignObjectType }>;
  filters: AnalyticsFilterState;
  metrics: AnalyticsMetricDefinition[];
  onChange: (updates: Partial<AnalyticsFilterState>) => void;
  people: Array<{ artist_profile_id: string | null; display_name: string | null }>;
}) {
  const selectedMetric = metrics.find((metric) => metric.id === filters.metricDefinitionId) ?? null;
  const aggregationOptions = metricSupportsNumericAggregation(selectedMetric)
    ? numericAggregations
    : nonNumericAggregations;

  return (
    <Card>
      <div className="grid gap-4 lg:grid-cols-4">
        <label className="grid gap-2 text-sm font-medium text-slate-700 lg:col-span-2">
          Metric
          <select
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200"
            onChange={(event) => onChange({ metricDefinitionId: event.target.value })}
            value={filters.metricDefinitionId}
          >
            <option value="">Select metric</option>
            {metrics.map((metric) => (
              <option key={metric.id} value={metric.id}>
                {metric.display_name} ({metric.provider.display_name})
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-2 text-sm font-medium text-slate-700">
          Aggregation
          <select
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200"
            onChange={(event) =>
              onChange({ aggregation: event.target.value as AnalyticsAggregation })
            }
            value={filters.aggregation}
          >
            {aggregationOptions.map((aggregation) => (
              <option key={aggregation} value={aggregation}>
                {formatLabel(aggregation)}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-2 text-sm font-medium text-slate-700">
          Target
          <select
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200"
            onChange={(event) => onChange({ targetType: event.target.value as TargetType })}
            value={filters.targetType}
          >
            <option value="workspace">Workspace</option>
            <option value="artist_profile">Artist</option>
            <option value="campaign">Campaign</option>
            <option value="campaign_object">Campaign item</option>
          </select>
        </label>

        {filters.targetType === "artist_profile" ? (
          <label className="grid gap-2 text-sm font-medium text-slate-700 lg:col-span-2">
            Artist
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200"
              onChange={(event) => onChange({ artistProfileId: event.target.value })}
              value={filters.artistProfileId}
            >
              <option value="">All artists</option>
              {people
                .filter((person) => person.artist_profile_id)
                .map((person) => (
                  <option key={person.artist_profile_id} value={person.artist_profile_id ?? ""}>
                    {person.display_name ?? "Unnamed artist"}
                  </option>
                ))}
            </select>
          </label>
        ) : null}

        {filters.targetType === "campaign" || filters.targetType === "campaign_object" ? (
          <label className="grid gap-2 text-sm font-medium text-slate-700 lg:col-span-2">
            Campaign
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200"
              onChange={(event) => onChange({ campaignId: event.target.value })}
              value={filters.campaignId}
            >
              <option value="">All campaigns</option>
              {campaigns.map((campaign) => (
                <option key={campaign.id} value={campaign.id}>
                  {campaign.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        {filters.targetType === "campaign_object" ? (
          <>
            <label className="grid gap-2 text-sm font-medium text-slate-700">
              Item type
              <select
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200"
                onChange={(event) =>
                  onChange({
                    campaignObjectId: "",
                    campaignObjectType: event.target.value as CampaignObjectType,
                  })
                }
                value={filters.campaignObjectType}
              >
                <option value="goal">Goal</option>
                <option value="milestone">Milestone</option>
              </select>
            </label>
            <label className="grid gap-2 text-sm font-medium text-slate-700 lg:col-span-2">
              Item
              <select
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500"
                disabled={!filters.campaignId}
                onChange={(event) => onChange({ campaignObjectId: event.target.value })}
                value={filters.campaignObjectId}
              >
                <option value="">All {filters.campaignObjectType}s</option>
                {campaignObjectOptions
                  .filter((option) => option.type === filters.campaignObjectType)
                  .map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
              </select>
            </label>
          </>
        ) : null}

        <label className="grid gap-2 text-sm font-medium text-slate-700">
          Start
          <Input
            onChange={(event) => onChange({ observedStart: event.target.value })}
            type="date"
            value={filters.observedStart}
          />
        </label>
        <label className="grid gap-2 text-sm font-medium text-slate-700">
          End
          <Input
            onChange={(event) => onChange({ observedEnd: event.target.value })}
            type="date"
            value={filters.observedEnd}
          />
        </label>
      </div>
    </Card>
  );
}

function AnalyticsWriterPanel({
  canCreate,
  filters,
  metric,
  onMetricCreated,
  onObservationCreated,
  workspaceId,
}: {
  canCreate: boolean;
  filters: AnalyticsFilterState;
  metric: AnalyticsMetricDefinition | null;
  onMetricCreated: (metricId: string) => void;
  onObservationCreated: () => void;
  workspaceId: string;
}) {
  const [activeTab, setActiveTab] = useState<AnalyticsWriterTab>("observation");
  const [metricForm, setMetricForm] = useState<MetricDefinitionFormState>(
    initialMetricDefinitionForm,
  );
  const [observationForm, setObservationForm] = useState<ObservationFormState>(() =>
    initialObservationForm(metric),
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setObservationForm((current) => ({
      ...current,
      unit: current.unit || metric?.default_unit || "",
      value: current.value || metric?.value_type !== "boolean" ? current.value : "true",
    }));
  }, [metric]);

  async function submitMetricDefinition(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    const displayName = metricForm.displayName.trim();
    const key = (metricForm.key.trim() || metricKeyFromName(displayName)).trim();
    if (!displayName || !key) {
      setError("Metric name and key are required.");
      return;
    }

    setIsSubmitting(true);
    try {
      const created = await createAnalyticsMetricDefinition(workspaceId, {
        aggregation: metricForm.aggregation,
        default_unit: metricForm.defaultUnit.trim() || null,
        description: metricForm.description.trim() || null,
        display_name: displayName,
        key,
        metadata: {},
        provider: {
          display_name: metricForm.providerDisplayName.trim() || metricForm.providerKey.trim(),
          key: metricForm.providerKey.trim() || "internal",
          provider_type: metricForm.providerType.trim() || "internal",
        },
        value_type: metricForm.valueType,
      });
      clearAnalyticsCache();
      setMetricForm(initialMetricDefinitionForm());
      setMessage("Metric definition created.");
      onMetricCreated(created.id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Metric definition could not be created.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function submitObservation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    if (!metric) {
      setError("Select a metric before recording an observation.");
      return;
    }

    setIsSubmitting(true);
    try {
      const created = await createAnalyticsObservation(workspaceId, {
        ...buildTargetFields(workspaceId, filters),
        ...metricValuePayload(metric, observationForm.value),
        dimensions: {},
        idempotency_key: observationForm.idempotencyKey.trim() || null,
        metadata: {},
        metric_definition_id: metric.id,
        observed_at: toObservedAtIso(observationForm.observedAt),
        source_record_id: observationForm.sourceRecordId.trim() || null,
        unit: observationForm.unit.trim() || metric.default_unit,
      });
      clearAnalyticsCache();
      setObservationForm(initialObservationForm(metric));
      setMessage(`Observation recorded for ${created.metric_key}.`);
      onObservationCreated();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Observation could not be recorded.");
    } finally {
      setIsSubmitting(false);
    }
  }

  const canRecordObservation = canCreate && Boolean(metric);
  const metricAggregationOptions =
    metricForm.valueType === "integer" || metricForm.valueType === "decimal"
      ? numericAggregations
      : nonNumericAggregations;

  return (
    <Card className="grid gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">Analytics inputs</h2>
          <p className="mt-1 text-sm text-slate-500">
            Create reporting metrics and record raw observations.
          </p>
        </div>
        <div className="inline-flex rounded-md border border-slate-200 bg-slate-50 p-1">
          {(["observation", "metric"] as const).map((tab) => (
            <button
              aria-pressed={activeTab === tab}
              className={cn(
                "h-8 rounded px-3 text-sm font-medium capitalize transition-colors",
                activeTab === tab ? "bg-white text-slate-950 shadow-sm" : "text-slate-600",
              )}
              key={tab}
              onClick={() => {
                setActiveTab(tab);
                setError(null);
                setMessage(null);
              }}
              type="button"
            >
              {tab === "observation" ? "Record observation" : "Add metric"}
            </button>
          ))}
        </div>
      </div>

      {!canCreate ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          You need analytics create access to add metrics or observations.
        </div>
      ) : null}

      {message ? (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
          {message}
        </div>
      ) : null}
      {error ? (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900" role="alert">
          {error}
        </div>
      ) : null}

      {activeTab === "metric" ? (
        <form className="grid gap-4 lg:grid-cols-4" onSubmit={submitMetricDefinition}>
          <label className="grid gap-2 text-sm font-medium text-slate-700 lg:col-span-2">
            Metric name
            <Input
              disabled={!canCreate || isSubmitting}
              onChange={(event) =>
                setMetricForm((current) => ({
                  ...current,
                  displayName: event.target.value,
                  key: current.key || metricKeyFromName(event.target.value),
                }))
              }
              placeholder="Streams"
              value={metricForm.displayName}
            />
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Metric key
            <Input
              disabled={!canCreate || isSubmitting}
              onChange={(event) =>
                setMetricForm((current) => ({ ...current, key: event.target.value }))
              }
              placeholder="streams"
              value={metricForm.key}
            />
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Value type
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:bg-slate-100"
              disabled={!canCreate || isSubmitting}
              onChange={(event) =>
                setMetricForm((current) => ({
                  ...current,
                  aggregation:
                    event.target.value === "integer" || event.target.value === "decimal"
                      ? current.aggregation
                      : "latest",
                  valueType: event.target.value as AnalyticsMetricValueType,
                }))
              }
              value={metricForm.valueType}
            >
              {metricValueTypes.map((valueType) => (
                <option key={valueType} value={valueType}>
                  {formatLabel(valueType)}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Default unit
            <Input
              disabled={!canCreate || isSubmitting}
              onChange={(event) =>
                setMetricForm((current) => ({ ...current, defaultUnit: event.target.value }))
              }
              placeholder="count"
              value={metricForm.defaultUnit}
            />
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Default aggregation
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:bg-slate-100"
              disabled={!canCreate || isSubmitting}
              onChange={(event) =>
                setMetricForm((current) => ({
                  ...current,
                  aggregation: event.target.value as AnalyticsAggregation,
                }))
              }
              value={metricForm.aggregation}
            >
              {metricAggregationOptions.map((aggregation) => (
                <option key={aggregation} value={aggregation}>
                  {formatLabel(aggregation)}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Provider key
            <Input
              disabled={!canCreate || isSubmitting}
              onChange={(event) =>
                setMetricForm((current) => ({ ...current, providerKey: event.target.value }))
              }
              value={metricForm.providerKey}
            />
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700 lg:col-span-2">
            Provider name
            <Input
              disabled={!canCreate || isSubmitting}
              onChange={(event) =>
                setMetricForm((current) => ({
                  ...current,
                  providerDisplayName: event.target.value,
                }))
              }
              value={metricForm.providerDisplayName}
            />
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700 lg:col-span-4">
            Description
            <Input
              disabled={!canCreate || isSubmitting}
              onChange={(event) =>
                setMetricForm((current) => ({ ...current, description: event.target.value }))
              }
              placeholder="Optional reporting context"
              value={metricForm.description}
            />
          </label>
          <div className="lg:col-span-4">
            <Button disabled={!canCreate || isSubmitting} type="submit">
              Create metric
            </Button>
          </div>
        </form>
      ) : (
        <form className="grid gap-4 lg:grid-cols-4" onSubmit={submitObservation}>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Observed at
            <Input
              disabled={!canRecordObservation || isSubmitting}
              onChange={(event) =>
                setObservationForm((current) => ({ ...current, observedAt: event.target.value }))
              }
              type="datetime-local"
              value={observationForm.observedAt}
            />
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Value
            {metric?.value_type === "boolean" ? (
              <select
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:bg-slate-100"
                disabled={!canRecordObservation || isSubmitting}
                onChange={(event) =>
                  setObservationForm((current) => ({ ...current, value: event.target.value }))
                }
                value={observationForm.value || "true"}
              >
                <option value="true">True</option>
                <option value="false">False</option>
              </select>
            ) : (
              <Input
                disabled={!canRecordObservation || isSubmitting}
                onChange={(event) =>
                  setObservationForm((current) => ({ ...current, value: event.target.value }))
                }
                placeholder={metric?.value_type === "json" ? "{\"source\":\"manual\"}" : "125"}
                value={observationForm.value}
              />
            )}
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Unit
            <Input
              disabled={!canRecordObservation || isSubmitting}
              onChange={(event) =>
                setObservationForm((current) => ({ ...current, unit: event.target.value }))
              }
              placeholder={metric?.default_unit ?? "count"}
              value={observationForm.unit}
            />
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Source record
            <Input
              disabled={!canRecordObservation || isSubmitting}
              onChange={(event) =>
                setObservationForm((current) => ({
                  ...current,
                  sourceRecordId: event.target.value,
                }))
              }
              placeholder="optional"
              value={observationForm.sourceRecordId}
            />
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700 lg:col-span-2">
            Idempotency key
            <Input
              disabled={!canRecordObservation || isSubmitting}
              onChange={(event) =>
                setObservationForm((current) => ({
                  ...current,
                  idempotencyKey: event.target.value,
                }))
              }
              placeholder="optional"
              value={observationForm.idempotencyKey}
            />
          </label>
          <div className="flex items-end lg:col-span-2">
            <Button disabled={!canRecordObservation || isSubmitting} type="submit">
              Record observation
            </Button>
          </div>
        </form>
      )}
    </Card>
  );
}

export function AnalyticsWorkspace() {
  const { activeWorkspace } = useActiveWorkspace();
  const workspaceProfile = useActiveWorkspaceProfile();
  const workspaceId = activeWorkspace?.id ?? null;
  const metrics = useAnalyticsMetricDefinitions(workspaceId);
  const campaigns = useCampaigns(workspaceId, { limit: 100, offset: 0 });
  const people = useWorkspacePeopleDirectory(workspaceId, { limit: 100, offset: 0 });
  const dateRange = useMemo(() => initialDateRange(), []);
  const [filters, setFilters] = useState<AnalyticsFilterState>({
    aggregation: "sum",
    artistProfileId: "",
    campaignId: "",
    campaignObjectId: "",
    campaignObjectType: "goal",
    metricDefinitionId: "",
    observedEnd: dateRange.observedEnd,
    observedStart: dateRange.observedStart,
    targetType: "workspace",
  });

  const metricDefinitions = metrics.data?.metric_definitions ?? [];
  const selectedMetric =
    metricDefinitions.find((metric) => metric.id === filters.metricDefinitionId) ?? null;

  useEffect(() => {
    const firstMetric = metricDefinitions[0] ?? null;
    if (!filters.metricDefinitionId && firstMetric) {
      setFilters((current) => ({
        ...current,
        aggregation: metricDefaultAggregation(firstMetric),
        metricDefinitionId: firstMetric.id,
      }));
    }
  }, [filters.metricDefinitionId, metricDefinitions]);

  useEffect(() => {
    if (!selectedMetric) {
      return;
    }
    const nextAggregation = metricDefaultAggregation(selectedMetric);
    const validAggregations = metricSupportsNumericAggregation(selectedMetric)
      ? numericAggregations
      : nonNumericAggregations;
    if (!validAggregations.includes(filters.aggregation)) {
      setFilters((current) => ({ ...current, aggregation: nextAggregation }));
    }
  }, [filters.aggregation, selectedMetric]);

  const queryOptions = useMemo(
    () => (workspaceId ? buildQueryOptions(workspaceId, filters) : null),
    [filters, workspaceId],
  );
  const comparisonOptions = useMemo(
    () => buildComparisonOptions(queryOptions, filters),
    [filters, queryOptions],
  );
  const series = useAnalyticsHistoricalSeries(workspaceId, queryOptions);
  const comparison = useAnalyticsPreviousPeriodComparison(workspaceId, comparisonOptions);
  const goals = useCampaignGoals(
    workspaceId,
    filters.targetType === "campaign_object" ? filters.campaignId || null : null,
  );
  const milestones = useCampaignMilestones(
    workspaceId,
    filters.targetType === "campaign_object" ? filters.campaignId || null : null,
  );
  const canView = workspaceProfile.subject
    ? can(workspaceProfile.subject, null, capabilities.analyticsView)
    : false;
  const canCreate = workspaceProfile.subject
    ? can(workspaceProfile.subject, null, capabilities.analyticsCreate)
    : false;
  const campaignObjectOptions = useMemo(
    () => [
      ...(goals.data?.goals ?? []).map((goal) => ({
        id: goal.id,
        label: goal.title,
        type: "goal" as const,
      })),
      ...(milestones.data?.milestones ?? []).map((milestone) => ({
        id: milestone.id,
        label: milestone.title,
        type: "milestone" as const,
      })),
    ],
    [goals.data, milestones.data],
  );

  const updateFilters = (updates: Partial<AnalyticsFilterState>) => {
    setFilters((current) => ({
      ...current,
      ...updates,
      ...(updates.targetType && updates.targetType !== current.targetType
        ? { artistProfileId: "", campaignObjectId: "", campaignId: "" }
        : {}),
    }));
  };

  if (!activeWorkspace) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900">
        Choose a workspace to view analytics.
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
      <PageHeader
        description={`${activeWorkspace.name} observations, historical series, and period comparisons.`}
        eyebrow="Analytics Workspace"
        title="Analytics"
      />

      {!canView && !workspaceProfile.isLoading ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          You need analytics view access to open this workspace.
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

      {metrics.isLoading && !metrics.data ? (
        <Card className="grid gap-3">
          <LoadingState label="Loading analytics" />
          <div className="h-24 rounded-md bg-slate-100 auth-shimmer" />
          <div className="h-64 rounded-md bg-slate-100 auth-shimmer" />
        </Card>
      ) : metricDefinitions.length === 0 ? (
        <>
          <AnalyticsWriterPanel
            canCreate={canCreate}
            filters={filters}
            metric={selectedMetric}
            onMetricCreated={(metricId) => {
              setFilters((current) => ({ ...current, metricDefinitionId: metricId }));
              void metrics.reload().catch(() => undefined);
            }}
            onObservationCreated={() => undefined}
            workspaceId={activeWorkspace.id}
          />
          <EmptyState
            description="Analytics observations appear here after metric definitions are connected."
            title="No analytics metrics yet"
          />
        </>
      ) : (
        <>
          <AnalyticsWriterPanel
            canCreate={canCreate}
            filters={filters}
            metric={selectedMetric}
            onMetricCreated={(metricId) => {
              setFilters((current) => ({ ...current, metricDefinitionId: metricId }));
              void metrics.reload().catch(() => undefined);
            }}
            onObservationCreated={() => {
              void series.reload().catch(() => undefined);
              void comparison.reload().catch(() => undefined);
            }}
            workspaceId={activeWorkspace.id}
          />

          <AnalyticsFilters
            campaignObjectOptions={campaignObjectOptions}
            campaigns={campaigns.data?.campaigns ?? []}
            filters={filters}
            metrics={metricDefinitions}
            onChange={updateFilters}
            people={people.data?.people ?? []}
          />

          <MetricSummary
            comparison={comparison.data}
            metric={selectedMetric}
            series={series.data}
          />

          {series.error ? (
            <div
              className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
              role="alert"
            >
              {series.error.message}
            </div>
          ) : null}

          <Card className={cn("grid gap-4", series.isLoading ? "opacity-80" : "")}>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-950">Historical series</h2>
                <p className="mt-1 text-sm text-slate-500">
                  {selectedMetric?.display_name ?? "Selected metric"} by observed date.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="neutral">{formatLabel(filters.aggregation)}</Badge>
                {series.data?.unit ? <Badge variant="neutral">{series.data.unit}</Badge> : null}
              </div>
            </div>

            {series.isLoading && !series.data ? (
              <LoadingState label="Loading series" />
            ) : series.data && series.data.points.length > 0 ? (
              <>
                <AnalyticsSeriesChart points={series.data.points} />
                <AnalyticsSeriesTable points={series.data.points} />
              </>
            ) : (
              <div className="rounded-md border border-slate-200 bg-slate-50 p-5 text-sm text-slate-600">
                No observations match the selected filters.
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
