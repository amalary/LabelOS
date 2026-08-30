import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AnalyticsWorkspace } from "./analytics-workspace";

vi.mock("../../lib/workspace-context", () => ({
  useActiveWorkspace: vi.fn(),
  useActiveWorkspaceProfile: vi.fn(),
}));

vi.mock("../../lib/analytics", async () => {
  const actual = await vi.importActual<typeof import("../../lib/analytics")>("../../lib/analytics");
  return {
    ...actual,
    createAnalyticsMetricDefinition: vi.fn(),
    createAnalyticsObservation: vi.fn(),
    useAnalyticsHistoricalSeries: vi.fn(),
    useAnalyticsMetricDefinitions: vi.fn(),
    useAnalyticsPreviousPeriodComparison: vi.fn(),
  };
});

vi.mock("../../lib/campaigns", () => ({
  useCampaignGoals: vi.fn(),
  useCampaignMilestones: vi.fn(),
  useCampaigns: vi.fn(),
}));

vi.mock("../../lib/profiles", () => ({
  useWorkspacePeopleDirectory: vi.fn(),
}));

const workspaceContext = await import("../../lib/workspace-context");
const analytics = await import("../../lib/analytics");
const campaigns = await import("../../lib/campaigns");
const profiles = await import("../../lib/profiles");

const metric = {
  id: "metric_01",
  workspace_id: "workspace_01",
  provider: {
    id: "provider_01",
    workspace_id: "workspace_01",
    key: "internal",
    display_name: "Internal Analytics",
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
} as const;

describe("AnalyticsWorkspace", () => {
  const reloadMetrics = vi.fn();
  const reloadSeries = vi.fn();
  const reloadComparison = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    reloadMetrics.mockResolvedValue({ metric_definitions: [metric] });
    reloadSeries.mockResolvedValue({
      aggregation: "sum",
      metric_definition_id: "metric_01",
      observation_count: 2,
      points: [
        { bucket_date: "2026-08-29", observation_count: 1, value: "100.000000" },
        { bucket_date: "2026-08-30", observation_count: 1, value: "125.000000" },
      ],
      provider_id: "provider_01",
      unit: "count",
      value_type: "integer",
    });
    reloadComparison.mockResolvedValue({
      absolute_change: "75.000000",
      aggregation: "sum",
      current_end: "2026-09-01T00:00:00Z",
      current_observation_count: 2,
      current_start: "2026-08-01T00:00:00Z",
      current_value: "225.000000",
      percentage_change: "0.500000",
      previous_end: "2026-08-01T00:00:00Z",
      previous_observation_count: 1,
      previous_start: "2026-07-01T00:00:00Z",
      previous_value: "150.000000",
      status: "compared",
    });
    vi.mocked(workspaceContext.useActiveWorkspace).mockReturnValue({
      activeWorkspace: {
        id: "workspace_01",
        name: "Alpha Label",
        slug: "alpha",
        role: "owner",
        workspace_permission: "owner",
        department_access: ["analytics"],
        capability_permissions: ["analytics.view", "analytics.create"],
        can_switch: true,
      },
      hasActiveWorkspace: true,
      workspaces: [],
    });
    vi.mocked(workspaceContext.useActiveWorkspaceProfile).mockReturnValue({
      capabilities: ["analytics.view", "analytics.create"],
      canEditProfile: false,
      departmentAccess: ["analytics"],
      isLoading: false,
      membership: null,
      responsibilities: [],
      roles: ["owner"],
      subject: {
        capabilities: ["analytics.view", "analytics.create"],
        departmentAccess: ["analytics"],
        role: "owner",
        workspacePermission: "owner",
      },
    });
    vi.mocked(analytics.useAnalyticsMetricDefinitions).mockReturnValue({
      data: { metric_definitions: [metric] },
      error: null,
      isLoading: false,
      reload: reloadMetrics,
    });
    vi.mocked(analytics.useAnalyticsHistoricalSeries).mockReturnValue({
      data: {
        aggregation: "sum",
        metric_definition_id: "metric_01",
        observation_count: 2,
        points: [
          { bucket_date: "2026-08-29", observation_count: 1, value: "100.000000" },
          { bucket_date: "2026-08-30", observation_count: 1, value: "125.000000" },
        ],
        provider_id: "provider_01",
        unit: "count",
        value_type: "integer",
      },
      error: null,
      isLoading: false,
      reload: reloadSeries,
    });
    vi.mocked(analytics.useAnalyticsPreviousPeriodComparison).mockReturnValue({
      data: {
        absolute_change: "75.000000",
        aggregation: "sum",
        current_end: "2026-09-01T00:00:00Z",
        current_observation_count: 2,
        current_start: "2026-08-01T00:00:00Z",
        current_value: "225.000000",
        percentage_change: "0.500000",
        previous_end: "2026-08-01T00:00:00Z",
        previous_observation_count: 1,
        previous_start: "2026-07-01T00:00:00Z",
        previous_value: "150.000000",
        status: "compared",
      },
      error: null,
      isLoading: false,
      reload: reloadComparison,
    });
    vi.mocked(campaigns.useCampaigns).mockReturnValue({
      data: {
        campaigns: [
          {
            id: "campaign_01",
            name: "Launch Campaign",
            workspace_id: "workspace_01",
            description: null,
            campaign_type: "marketing",
            status: "active",
            start_date: null,
            target_end_date: null,
            created_by_user_id: null,
            created_by_profile_id: null,
            owner_profile_id: null,
            owner: null,
            primary_artist: null,
            release: null,
            members: [],
            artists: [],
            releases: [],
            created_at: "2026-08-29T12:00:00Z",
            updated_at: "2026-08-29T12:00:00Z",
          },
        ],
        limit: 100,
        offset: 0,
        total: 1,
      },
      error: null,
      isLoading: false,
      isMutating: false,
      reload: vi.fn(),
    });
    vi.mocked(campaigns.useCampaignGoals).mockReturnValue({
      data: {
        goals: [
          {
            id: "goal_01",
            campaign_id: "campaign_01",
            created_at: "2026-08-29T12:00:00Z",
            description: null,
            status: "active",
            success_criteria: null,
            target_value: null,
            title: "Pre-save goal",
            updated_at: "2026-08-29T12:00:00Z",
          },
        ],
      },
      error: null,
      isLoading: false,
      isMutating: false,
      reload: vi.fn(),
    });
    vi.mocked(campaigns.useCampaignMilestones).mockReturnValue({
      data: { milestones: [] },
      error: null,
      isLoading: false,
      isMutating: false,
      reload: vi.fn(),
    });
    vi.mocked(profiles.useWorkspacePeopleDirectory).mockReturnValue({
      data: {
        limit: 100,
        offset: 0,
        people: [
          {
            artist_profile_id: "artist_profile_01",
            avatar_url: null,
            departments: ["analytics"],
            display_name: "Mira Stone",
            headline: null,
            id: "membership_01",
            membership_status: "active",
            profile_id: "profile_01",
            profile_modules: ["artist"],
            roles: ["Artist"],
            workspace_id: "workspace_01",
          },
        ],
        query: null,
        total: 1,
      },
      error: null,
      isLoading: false,
      isMutating: false,
      reload: vi.fn(),
    });
    vi.mocked(analytics.createAnalyticsMetricDefinition).mockResolvedValue({
      ...metric,
      id: "metric_created",
      key: "followers",
      display_name: "Followers",
    });
    vi.mocked(analytics.createAnalyticsObservation).mockResolvedValue({
      id: "observation_created",
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
      value_numeric: "175.000000",
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
    });
  });

  it("renders reporting controls, summary, chart, and data table", async () => {
    render(<AnalyticsWorkspace />);

    expect(screen.getByRole("heading", { name: "Analytics" })).toBeInTheDocument();
    expect(screen.getByLabelText("Metric")).toHaveValue("metric_01");
    expect(screen.getAllByText("125")).toHaveLength(2);
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.getByRole("figure", { name: "Analytics series chart" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Analytics series data" })).toBeInTheDocument();
    expect(screen.getAllByText("2026-08-30")).toHaveLength(2);
  });

  it("exposes campaign child target controls", () => {
    render(<AnalyticsWorkspace />);

    fireEvent.change(screen.getByLabelText("Target"), {
      target: { value: "campaign_object" },
    });
    fireEvent.change(screen.getByLabelText("Campaign"), {
      target: { value: "campaign_01" },
    });

    expect(screen.getByLabelText("Item type")).toHaveValue("goal");
    expect(screen.getByLabelText("Item")).toHaveTextContent("Pre-save goal");
  });

  it("creates a metric definition from the analytics page", async () => {
    render(<AnalyticsWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Add metric" }));
    fireEvent.change(screen.getByLabelText("Metric name"), {
      target: { value: "Followers" },
    });
    fireEvent.change(screen.getByLabelText("Metric key"), {
      target: { value: "followers" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create metric" }));

    await waitFor(() =>
      expect(analytics.createAnalyticsMetricDefinition).toHaveBeenCalledWith(
        "workspace_01",
        expect.objectContaining({
          display_name: "Followers",
          key: "followers",
          value_type: "integer",
        }),
      ),
    );
    await waitFor(() => expect(reloadMetrics).toHaveBeenCalled());
    expect(screen.getByText("Metric definition created.")).toBeInTheDocument();
  });

  it("records an observation for the current report target", async () => {
    render(<AnalyticsWorkspace />);

    fireEvent.change(screen.getByLabelText("Value"), {
      target: { value: "175" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Record observation" }).at(-1)!);

    await waitFor(() =>
      expect(analytics.createAnalyticsObservation).toHaveBeenCalledWith(
        "workspace_01",
        expect.objectContaining({
          metric_definition_id: "metric_01",
          target_id: "workspace_01",
          target_type: "workspace",
          value_numeric: "175",
        }),
      ),
    );
    await waitFor(() => expect(reloadSeries).toHaveBeenCalled());
    await waitFor(() => expect(reloadComparison).toHaveBeenCalled());
  });
});
