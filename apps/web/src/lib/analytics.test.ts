import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AnalyticsApiError,
  createAnalyticsMetricDefinition,
  createAnalyticsObservation,
  getAnalyticsHistoricalSeries,
  getAnalyticsMetricDefinitions,
  getAnalyticsObservations,
  getAnalyticsPreviousPeriodComparison,
  getAnalyticsProviders,
  getLatestAnalyticsObservation,
  queryAnalyticsSummary,
  queryMetricHistory,
  queryObservationsByArtist,
  queryObservationsByCampaign,
  queryObservationsByCampaignChildObject,
} from "./analytics";

const metricDefinition = {
  id: "metric_01",
  workspace_id: "workspace_01",
  provider: {
    id: "provider_01",
    workspace_id: "workspace_01",
    key: "internal",
    display_name: "Internal",
    provider_type: "internal",
    external_account_id: null,
    metadata: {},
    created_at: "2026-08-29T12:00:00Z",
    updated_at: "2026-08-29T12:00:00Z",
  },
  key: "streams",
  display_name: "Streams",
  description: null,
  value_type: "integer",
  default_unit: "count",
  aggregation: "sum",
  metadata: {},
  created_at: "2026-08-29T12:00:00Z",
  updated_at: "2026-08-29T12:00:00Z",
};

describe("analytics data layer", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("fetches metric definitions through the workspace analytics proxy", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ metric_definitions: [metricDefinition] }));

    await expect(getAnalyticsMetricDefinitions("workspace_01")).resolves.toEqual({
      metric_definitions: [metricDefinition],
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/workspaces/workspace_01/analytics/metric-definitions",
      expect.objectContaining({
        cache: "no-store",
        headers: expect.any(Headers),
      }),
    );
    const headers = vi.mocked(fetch).mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("Accept")).toBe("application/json");
  });

  it("fetches analytics providers through the workspace analytics proxy", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ providers: [metricDefinition.provider] }));

    await expect(getAnalyticsProviders("workspace_01")).resolves.toEqual({
      providers: [metricDefinition.provider],
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/workspaces/workspace_01/analytics/providers",
      expect.objectContaining({
        cache: "no-store",
        headers: expect.any(Headers),
      }),
    );
  });

  it("builds observation and latest query strings with target filters", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json({ observations: [], total: 0, limit: 50, offset: 0 }))
      .mockResolvedValueOnce(Response.json(null));

    await getAnalyticsObservations("workspace_01", {
      metric_definition_id: "metric_01",
      provider_id: "provider_01",
      target_type: "campaign_object",
      campaign_id: "campaign_01",
      campaign_object_type: "goal",
      campaign_object_id: "goal_01",
      observed_start: "2026-08-01T00:00:00Z",
      observed_end: "2026-08-31T23:59:59Z",
      limit: 50,
    });
    await getLatestAnalyticsObservation("workspace_01", {
      metric_definition_id: "metric_01",
      campaign_id: "campaign_01",
    });

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "/api/workspaces/workspace_01/analytics/observations?metric_definition_id=metric_01&provider_id=provider_01&target_type=campaign_object&campaign_id=campaign_01&campaign_object_type=goal&campaign_object_id=goal_01&observed_start=2026-08-01T00%3A00%3A00Z&observed_end=2026-08-31T23%3A59%3A59Z&limit=50",
      expect.any(Object),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/workspaces/workspace_01/analytics/observations/latest?metric_definition_id=metric_01&campaign_id=campaign_01",
      expect.any(Object),
    );
  });

  it("normalizes reusable analytics filter aliases", async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({ observations: [], total: 0, limit: 100, offset: 0 }),
    );

    await getAnalyticsObservations("workspace_01", {
      end_date: "2026-08-31T23:59:59Z",
      metric: "metric_01",
      provider: "provider_01",
      start_date: "2026-08-01T00:00:00Z",
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/workspaces/workspace_01/analytics/observations?metric_definition_id=metric_01&provider_id=provider_01&observed_start=2026-08-01T00%3A00%3A00Z&observed_end=2026-08-31T23%3A59%3A59Z",
      expect.any(Object),
    );
  });

  it("queries observations by analytics object scope", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json({ observations: [], total: 0, limit: 100, offset: 0 }))
      .mockResolvedValueOnce(Response.json({ observations: [], total: 0, limit: 100, offset: 0 }))
      .mockResolvedValueOnce(Response.json({ observations: [], total: 0, limit: 100, offset: 0 }));

    await queryObservationsByArtist("workspace_01", "artist_01", {
      metric_definition_id: "metric_01",
    });
    await queryObservationsByCampaign("workspace_01", "campaign_01", {
      include_child_objects: false,
      metric_definition_id: "metric_01",
    });
    await queryObservationsByCampaignChildObject("workspace_01", "campaign_01", "goal", "goal_01", {
      metric_definition_id: "metric_01",
    });

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "/api/workspaces/workspace_01/analytics/observations?metric_definition_id=metric_01&artist_profile_id=artist_01",
      expect.any(Object),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/workspaces/workspace_01/analytics/observations?metric_definition_id=metric_01&campaign_id=campaign_01&target_id=campaign_01&target_type=campaign",
      expect.any(Object),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      3,
      "/api/workspaces/workspace_01/analytics/observations?metric_definition_id=metric_01&campaign_id=campaign_01&campaign_object_id=goal_01&campaign_object_type=goal&target_id=goal_01&target_type=campaign_object",
      expect.any(Object),
    );
  });

  it("fetches historical series and previous-period comparison", async () => {
    const series = {
      aggregation: "sum",
      points: [{ bucket_date: "2026-08-29", value: "100.000000", observation_count: 1 }],
      value_type: "integer",
      unit: "count",
      provider_id: "provider_01",
      metric_definition_id: "metric_01",
      observation_count: 1,
    };
    const comparison = {
      aggregation: "sum",
      current_start: "2026-08-29T00:00:00Z",
      current_end: "2026-09-05T00:00:00Z",
      previous_start: "2026-08-22T00:00:00Z",
      previous_end: "2026-08-29T00:00:00Z",
      current_value: "100.000000",
      previous_value: "50.000000",
      current_observation_count: 1,
      previous_observation_count: 1,
      absolute_change: "50.000000",
      percentage_change: "1.000000",
      status: "compared",
    };
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json(series))
      .mockResolvedValueOnce(Response.json(comparison));

    await expect(
      getAnalyticsHistoricalSeries("workspace_01", {
        metric_definition_id: "metric_01",
        aggregation: "sum",
      }),
    ).resolves.toEqual(series);
    await expect(
      getAnalyticsPreviousPeriodComparison("workspace_01", {
        metric_definition_id: "metric_01",
        aggregation: "sum",
        current_start: "2026-08-29T00:00:00Z",
        current_end: "2026-09-05T00:00:00Z",
      }),
    ).resolves.toEqual(comparison);

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "/api/workspaces/workspace_01/analytics/series?metric_definition_id=metric_01&aggregation=sum",
      expect.any(Object),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/workspaces/workspace_01/analytics/comparison?metric_definition_id=metric_01&aggregation=sum&current_start=2026-08-29T00%3A00%3A00Z&current_end=2026-09-05T00%3A00%3A00Z",
      expect.any(Object),
    );
  });

  it("queries metric history and summary aggregation results", async () => {
    const series = {
      aggregation: "sum",
      points: [{ bucket_date: "2026-08-29", value: "100.000000", observation_count: 1 }],
      value_type: "integer",
      unit: "count",
      provider_id: "provider_01",
      metric_definition_id: "metric_01",
      observation_count: 1,
    };
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json(series))
      .mockResolvedValueOnce(Response.json(series));

    await expect(
      queryMetricHistory("workspace_01", {
        aggregation: "sum",
        metric: "metric_01",
      }),
    ).resolves.toEqual(series);
    await expect(
      queryAnalyticsSummary("workspace_01", {
        aggregation: "sum",
        campaign: "campaign_01",
        metric: "metric_01",
      }),
    ).resolves.toEqual(series);

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "/api/workspaces/workspace_01/analytics/series?aggregation=sum&metric_definition_id=metric_01",
      expect.any(Object),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/workspaces/workspace_01/analytics/summary?aggregation=sum&metric_definition_id=metric_01&campaign_id=campaign_01",
      expect.any(Object),
    );
  });

  it("creates metric definitions and observations through the proxy", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json(metricDefinition, { status: 201 }))
      .mockResolvedValueOnce(
        Response.json(
          {
            id: "observation_01",
            workspace_id: "workspace_01",
            metric_definition_id: "metric_01",
            metric_key: "streams",
            provider_id: "provider_01",
            provider_key: "internal",
            target_type: "workspace",
            target_id: "workspace_01",
            artist_profile_id: null,
            campaign_id: null,
            campaign_name: null,
            campaign_object_type: null,
            campaign_object_id: null,
            value_numeric: "125.000000",
            value_text: null,
            value_boolean: null,
            value_json: null,
            unit: "count",
            observed_at: "2026-08-30T00:00:00Z",
            source_record_id: null,
            idempotency_key: null,
            dimensions: {},
            metadata: {},
            created_at: "2026-08-30T00:00:00Z",
            updated_at: "2026-08-30T00:00:00Z",
          },
          { status: 201 },
        ),
      );

    await expect(
      createAnalyticsMetricDefinition("workspace_01", {
        aggregation: "sum",
        default_unit: "count",
        display_name: "Streams",
        key: "streams",
        provider: { display_name: "Internal", key: "internal", provider_type: "internal" },
        value_type: "integer",
      }),
    ).resolves.toEqual(metricDefinition);
    await expect(
      createAnalyticsObservation("workspace_01", {
        metric_definition_id: "metric_01",
        observed_at: "2026-08-30T00:00:00Z",
        target_id: "workspace_01",
        target_type: "workspace",
        unit: "count",
        value_numeric: "125",
      }),
    ).resolves.toMatchObject({ id: "observation_01" });

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "/api/workspaces/workspace_01/analytics/metric-definitions",
      expect.objectContaining({
        body: expect.stringContaining('"key":"streams"'),
        method: "POST",
      }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/workspaces/workspace_01/analytics/observations",
      expect.objectContaining({
        body: expect.stringContaining('"value_numeric":"125"'),
        method: "POST",
      }),
    );
  });

  it("maps failed analytics responses to typed errors", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ detail: "No access" }, { status: 403 }));

    await expect(getAnalyticsMetricDefinitions("workspace_01")).rejects.toBeInstanceOf(
      AnalyticsApiError,
    );
    await expect(getAnalyticsMetricDefinitions("workspace_01")).rejects.toMatchObject({
      code: "forbidden",
      status: 403,
    });
  });
});
