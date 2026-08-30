import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { AnalyticsReadSurface } from "./analytics-read-surface";

vi.mock("../../lib/analytics", async () => {
  const actual = await vi.importActual<typeof import("../../lib/analytics")>("../../lib/analytics");
  return {
    ...actual,
    useAnalyticsHistoricalSeries: vi.fn(),
    useAnalyticsMetricDefinitions: vi.fn(),
    useAnalyticsObservationsByCampaign: vi.fn(),
    useAnalyticsObservationsByCampaignChildObject: vi.fn(),
    useAnalyticsSummary: vi.fn(),
  };
});

const analytics = await import("../../lib/analytics");

const provider = {
  id: "provider_01",
  workspace_id: "workspace_01",
  key: "spotify",
  display_name: "Spotify",
  provider_type: "streaming",
  external_account_id: null,
  metadata: {},
  created_at: "2026-08-29T12:00:00Z",
  updated_at: "2026-08-29T12:00:00Z",
};

const streamMetric = {
  id: "metric_streams",
  workspace_id: "workspace_01",
  provider,
  key: "streams",
  display_name: "Streams",
  description: null,
  value_type: "integer",
  default_unit: "count",
  aggregation: "sum",
  metadata: {},
  created_at: "2026-08-29T12:00:00Z",
  updated_at: "2026-08-29T12:00:00Z",
} as const;

const sentimentMetric = {
  ...streamMetric,
  id: "metric_sentiment",
  key: "sentiment",
  display_name: "Sentiment",
  value_type: "string",
  default_unit: null,
  aggregation: "latest",
} as const;

const observation = {
  id: "observation_01",
  workspace_id: "workspace_01",
  metric_definition_id: "metric_streams",
  metric_key: "streams",
  provider_id: "provider_01",
  provider_key: "spotify",
  target_type: "campaign",
  target_id: "campaign_01",
  artist_profile_id: null,
  campaign_id: "campaign_01",
  campaign_object_type: null,
  campaign_object_id: null,
  value_numeric: "125.000000",
  value_text: null,
  value_boolean: null,
  value_json: null,
  unit: "count",
  observed_at: "2026-08-29T12:00:00Z",
  source_record_id: "spotify-row-1",
  idempotency_key: null,
  dimensions: {},
  metadata: {},
  created_at: "2026-08-29T12:00:00Z",
  updated_at: "2026-08-29T12:00:00Z",
};

describe("AnalyticsReadSurface", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(analytics.useAnalyticsMetricDefinitions).mockReturnValue({
      data: { metric_definitions: [streamMetric, sentimentMetric] },
      error: null,
      isLoading: false,
      reload: vi.fn(),
    });
    vi.mocked(analytics.useAnalyticsSummary).mockReturnValue({
      data: {
        aggregation: "sum",
        metric_definition_id: "metric_streams",
        observation_count: 2,
        points: [{ bucket_date: "2026-08-29", observation_count: 2, value: "125.000000" }],
        provider_id: "provider_01",
        unit: "count",
        value_type: "integer",
      },
      error: null,
      isLoading: false,
      reload: vi.fn(),
    });
    vi.mocked(analytics.useAnalyticsHistoricalSeries).mockReturnValue({
      data: {
        aggregation: "sum",
        metric_definition_id: "metric_streams",
        observation_count: 2,
        points: [
          { bucket_date: "2026-08-28", observation_count: 1, value: "100.000000" },
          { bucket_date: "2026-08-29", observation_count: 1, value: "125.000000" },
        ],
        provider_id: "provider_01",
        unit: "count",
        value_type: "integer",
      },
      error: null,
      isLoading: false,
      reload: vi.fn(),
    });
    vi.mocked(analytics.useAnalyticsObservationsByCampaign).mockReturnValue({
      data: { observations: [observation], total: 1, limit: 8, offset: 0 },
      error: null,
      isLoading: false,
      reload: vi.fn(),
    });
    vi.mocked(analytics.useAnalyticsObservationsByCampaignChildObject).mockReturnValue({
      data: { observations: [], total: 0, limit: 8, offset: 0 },
      error: null,
      isLoading: false,
      reload: vi.fn(),
    });
  });

  it("renders campaign headline metrics, trends, recent values, and provider details", () => {
    render(
      <AnalyticsReadSurface
        campaignId="campaign_01"
        title="Campaign analytics"
        workspaceId="workspace_01"
      />,
    );

    expect(screen.getByRole("heading", { name: "Campaign analytics" })).toBeInTheDocument();
    expect(screen.getAllByText("Streams")).not.toHaveLength(0);
    expect(screen.getAllByText("125")).not.toHaveLength(0);
    expect(screen.getByRole("figure", { name: "Campaign analytics trend" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Recent campaign metric values" })).toBeInTheDocument();
    expect(screen.getAllByText("Spotify")).not.toHaveLength(0);
    expect(screen.getByText("spotify-row-1")).toBeInTheDocument();
  });

  it("queries selected goal analytics with campaign object fields", () => {
    render(
      <AnalyticsReadSurface
        campaignId="campaign_01"
        selectedChild={{ id: "goal_01", label: "Pre-save goal", type: "goal" }}
        workspaceId="workspace_01"
      />,
    );

    expect(screen.getByText("Goal: Pre-save goal")).toBeInTheDocument();
    expect(analytics.useAnalyticsObservationsByCampaignChildObject).toHaveBeenCalledWith(
      "workspace_01",
      "campaign_01",
      "goal",
      "goal_01",
      expect.objectContaining({ limit: 8 }),
    );
    expect(analytics.useAnalyticsHistoricalSeries).toHaveBeenCalledWith(
      "workspace_01",
      expect.objectContaining({
        campaign_id: "campaign_01",
        campaign_object_id: "goal_01",
        campaign_object_type: "goal",
        target_id: "goal_01",
        target_type: "campaign_object",
      }),
    );
  });
});
