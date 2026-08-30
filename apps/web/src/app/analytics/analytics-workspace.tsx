"use client";

import { Badge, Card, EmptyState, Input, LoadingState, PageHeader } from "@label-os/ui";
import { useMemo, useState } from "react";

import { AnalyticsReadSurface } from "../../components/analytics/analytics-read-surface";
import {
  type AnalyticsMetricDefinition,
  type AnalyticsObservation,
  useAnalyticsMetricDefinitions,
  useAnalyticsObservations,
} from "../../lib/analytics";
import { can, capabilities } from "../../lib/authorization";
import { useCampaigns } from "../../lib/campaigns";
import { useWorkspacePeopleDirectory } from "../../lib/profiles";
import { useActiveWorkspace, useActiveWorkspaceProfile } from "../../lib/workspace-context";

type WorkspaceAnalyticsTarget = "workspace" | "artist" | "campaign";

type DateRange = {
  observedEnd: string;
  observedStart: string;
};

function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function defaultDateRange(): DateRange {
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

function metricValueTypeLabel(metric: AnalyticsMetricDefinition | null): string {
  if (!metric) {
    return "All value types";
  }
  if (metric.value_type === "integer" || metric.value_type === "decimal") {
    return "Numeric metrics chart and aggregate.";
  }
  if (metric.value_type === "boolean") {
    return "Boolean metrics show latest values and counts.";
  }
  if (metric.value_type === "json") {
    return "JSON metrics show as structured values and stay out of numeric charts.";
  }
  return "String metrics show latest values and stay out of numeric charts.";
}

function observationValue(observation: AnalyticsObservation): string | boolean | object | null {
  return (
    observation.value_numeric ??
    observation.value_text ??
    observation.value_boolean ??
    observation.value_json ??
    null
  );
}

function formatObservationValue(value: string | boolean | object | null): string {
  if (typeof value === "boolean") {
    return value ? "True" : "False";
  }
  if (value && typeof value === "object") {
    return JSON.stringify(value);
  }
  return value ?? "No data";
}

function hasChartableValue(observation: AnalyticsObservation): boolean {
  return observation.value_numeric !== null && Number.isFinite(Number(observation.value_numeric));
}

function comparisonRows(
  observations: AnalyticsObservation[],
  keyFor: (observation: AnalyticsObservation) => string | null,
  fallback: string,
) {
  return Array.from(
    observations.reduce((rows, observation) => {
      const key = keyFor(observation) ?? fallback;
      const current = rows.get(key) ?? { chartable: 0, count: 0, latest: null as string | null };
      current.count += 1;
      current.latest = formatObservationValue(observationValue(observation));
      if (hasChartableValue(observation)) {
        current.chartable += 1;
      }
      rows.set(key, current);
      return rows;
    }, new Map<string, { chartable: number; count: number; latest: string | null }>()),
  )
    .map(([label, row]) => ({ label, ...row }))
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label))
    .slice(0, 6);
}

function providerRows(observations: AnalyticsObservation[]) {
  return comparisonRows(
    observations,
    (observation) => formatLabel(observation.provider_key),
    "Unattributed provider",
  );
}

function WorkspaceComparisonTable({
  emptyLabel,
  rows,
  title,
}: {
  emptyLabel: string;
  rows: Array<{ chartable: number; count: number; label: string; latest: string | null }>;
  title: string;
}) {
  return (
    <Card className="grid gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-slate-950">{title}</h2>
        <Badge variant="neutral">{rows.length} groups</Badge>
      </div>
      {rows.length === 0 ? (
        <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
          {emptyLabel}
        </div>
      ) : (
        <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">{title}</caption>
            <thead className="bg-slate-50 text-xs uppercase tracking-normal text-slate-500">
              <tr>
                <th className="px-4 py-3" scope="col">
                  Group
                </th>
                <th className="px-4 py-3" scope="col">
                  Observations
                </th>
                <th className="px-4 py-3" scope="col">
                  Chartable
                </th>
                <th className="px-4 py-3" scope="col">
                  Latest value
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((row) => (
                <tr key={row.label}>
                  <td className="px-4 py-3 font-medium text-slate-900">{row.label}</td>
                  <td className="px-4 py-3 text-slate-700">{row.count}</td>
                  <td className="px-4 py-3 text-slate-700">{row.chartable}</td>
                  <td className="max-w-48 truncate px-4 py-3 text-slate-500">{row.latest}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
  const initialRange = useMemo(() => defaultDateRange(), []);
  const [target, setTarget] = useState<WorkspaceAnalyticsTarget>("workspace");
  const [artistProfileId, setArtistProfileId] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const [comparisonMetricId, setComparisonMetricId] = useState("all");
  const [comparisonProviderId, setComparisonProviderId] = useState("all");
  const [comparisonRange, setComparisonRange] = useState<DateRange>(initialRange);

  const metricDefinitions = metrics.data?.metric_definitions ?? [];
  const providerOptions = useMemo(
    () =>
      Array.from(
        new Map(metricDefinitions.map((metric) => [metric.provider.id, metric.provider])).values(),
      ),
    [metricDefinitions],
  );
  const selectedComparisonMetric =
    metricDefinitions.find((metric) => metric.id === comparisonMetricId) ?? null;
  const comparisonObservations = useAnalyticsObservations(
    workspaceId,
    workspaceId
      ? {
          limit: 100,
          metric_definition_id: comparisonMetricId === "all" ? null : comparisonMetricId,
          observed_end: toEndIso(comparisonRange.observedEnd),
          observed_start: toStartIso(comparisonRange.observedStart),
          provider_id: comparisonProviderId === "all" ? null : comparisonProviderId,
        }
      : null,
  );
  const observations = comparisonObservations.data?.observations ?? [];
  const artistNameById = useMemo(
    () =>
      new Map(
        (people.data?.people ?? [])
          .filter((person) => person.artist_profile_id)
          .map((person) => [
            person.artist_profile_id ?? "",
            person.display_name ?? "Unnamed artist",
          ]),
      ),
    [people.data],
  );
  const artistRows = comparisonRows(
    observations,
    (observation) =>
      observation.artist_profile_id
        ? (artistNameById.get(observation.artist_profile_id) ??
          `Artist ${observation.artist_profile_id.slice(0, 8)}`)
        : null,
    "Unattributed artist",
  );
  const campaignRows = comparisonRows(
    observations,
    (observation) => observation.campaign_name ?? observation.campaign_id,
    "Unattributed campaign",
  );
  const providers = providerRows(observations);
  const canView = workspaceProfile.subject
    ? can(workspaceProfile.subject, null, capabilities.analyticsView)
    : false;

  const selectedArtistName =
    people.data?.people.find((person) => person.artist_profile_id === artistProfileId)
      ?.display_name ?? "Artist analytics";
  const selectedCampaignName =
    campaigns.data?.campaigns.find((campaign) => campaign.id === campaignId)?.name ??
    "Campaign analytics";

  if (!activeWorkspace) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900">
        Choose a workspace to view analytics.
      </div>
    );
  }

  if (!canView && !workspaceProfile.isLoading) {
    return (
      <div className="mx-auto w-full max-w-7xl">
        <PageHeader
          description="Workspace analytics require analytics view access."
          eyebrow="Workspace Analytics"
          title="Analytics"
        />
        <div className="mt-5 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          You need analytics view access to open this workspace.
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
      <PageHeader
        description={`${activeWorkspace.name} metrics, trends, comparisons, and source breakdowns.`}
        eyebrow="Workspace Analytics"
        title="Analytics"
      />

      <Card className="grid gap-4">
        <div className="grid gap-4 lg:grid-cols-3">
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Explore
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200"
              onChange={(event) => setTarget(event.target.value as WorkspaceAnalyticsTarget)}
              value={target}
            >
              <option value="workspace">Workspace</option>
              <option value="artist">Artist</option>
              <option value="campaign">Campaign</option>
            </select>
          </label>
          {target === "artist" ? (
            <label className="grid gap-2 text-sm font-medium text-slate-700 lg:col-span-2">
              Artist
              <select
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200"
                onChange={(event) => setArtistProfileId(event.target.value)}
                value={artistProfileId}
              >
                <option value="">Select artist</option>
                {(people.data?.people ?? [])
                  .filter((person) => person.artist_profile_id)
                  .map((person) => (
                    <option key={person.artist_profile_id} value={person.artist_profile_id ?? ""}>
                      {person.display_name ?? "Unnamed artist"}
                    </option>
                  ))}
              </select>
            </label>
          ) : null}
          {target === "campaign" ? (
            <label className="grid gap-2 text-sm font-medium text-slate-700 lg:col-span-2">
              Campaign
              <select
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200"
                onChange={(event) => setCampaignId(event.target.value)}
                value={campaignId}
              >
                <option value="">Select campaign</option>
                {(campaigns.data?.campaigns ?? []).map((campaign) => (
                  <option key={campaign.id} value={campaign.id}>
                    {campaign.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
        {metrics.error || campaigns.error || people.error ? (
          <div
            className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
            role="alert"
          >
            Some workspace analytics filters could not be loaded.
          </div>
        ) : null}
        {(metrics.isLoading || campaigns.isLoading || people.isLoading) && !metrics.data ? (
          <LoadingState label="Loading workspace analytics filters" />
        ) : null}
      </Card>

      {target === "artist" && !artistProfileId ? (
        <EmptyState
          description="Choose an artist to inspect artist-level metrics, trends, and source values."
          title="Select an artist"
        />
      ) : target === "campaign" && !campaignId ? (
        <EmptyState
          description="Choose a campaign to inspect campaign-level metrics, trends, and source values."
          title="Select a campaign"
        />
      ) : (
        <AnalyticsReadSurface
          artistProfileId={target === "artist" ? artistProfileId : undefined}
          campaignId={target === "campaign" ? campaignId : undefined}
          title={
            target === "artist"
              ? selectedArtistName
              : target === "campaign"
                ? selectedCampaignName
                : "Workspace analytics"
          }
          workspaceId={activeWorkspace.id}
        />
      )}

      <Card className="grid gap-4">
        <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">Workspace comparisons</h2>
            <p className="mt-1 text-sm text-slate-500">
              Recent observations grouped by artist, campaign, and provider.
            </p>
          </div>
          <Badge variant="neutral">{metricValueTypeLabel(selectedComparisonMetric)}</Badge>
        </div>
        <div className="grid gap-4 lg:grid-cols-4">
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Metric
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200"
              onChange={(event) => setComparisonMetricId(event.target.value)}
              value={comparisonMetricId}
            >
              <option value="all">All metrics</option>
              {metricDefinitions.map((metric) => (
                <option key={metric.id} value={metric.id}>
                  {metric.display_name}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Provider
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200"
              onChange={(event) => setComparisonProviderId(event.target.value)}
              value={comparisonProviderId}
            >
              <option value="all">All providers</option>
              {providerOptions.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.display_name}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Start
            <Input
              onChange={(event) =>
                setComparisonRange((current) => ({
                  ...current,
                  observedStart: event.target.value,
                }))
              }
              type="date"
              value={comparisonRange.observedStart}
            />
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            End
            <Input
              onChange={(event) =>
                setComparisonRange((current) => ({ ...current, observedEnd: event.target.value }))
              }
              type="date"
              value={comparisonRange.observedEnd}
            />
          </label>
        </div>
      </Card>

      {comparisonObservations.error ? (
        <div
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
          role="alert"
        >
          Workspace comparisons could not be loaded.
        </div>
      ) : comparisonObservations.isLoading && !comparisonObservations.data ? (
        <Card className="grid gap-3">
          <LoadingState label="Loading workspace comparisons" />
          <div className="h-28 rounded-md bg-slate-100 auth-shimmer" />
        </Card>
      ) : observations.length === 0 ? (
        <EmptyState
          description="Comparison tables populate after observations match the selected metric, provider, and range."
          title="No comparison data"
        />
      ) : (
        <div className="grid gap-5 xl:grid-cols-3">
          <WorkspaceComparisonTable
            emptyLabel="No artist-attributed observations match this range."
            rows={artistRows}
            title="Artist comparison"
          />
          <WorkspaceComparisonTable
            emptyLabel="No campaign-attributed observations match this range."
            rows={campaignRows}
            title="Campaign comparison"
          />
          <WorkspaceComparisonTable
            emptyLabel="No provider observations match this range."
            rows={providers}
            title="Provider breakdown"
          />
        </div>
      )}
    </div>
  );
}
