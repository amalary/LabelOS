import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AnalyticsWorkspace } from "./analytics-workspace";

vi.mock("../../components/analytics/analytics-read-surface", () => ({
  AnalyticsReadSurface: vi.fn(
    (props: { artistProfileId?: string; campaignId?: string; title?: string }) => (
      <section data-testid="analytics-read-surface">
        <h2>{props.title}</h2>
        <span>{props.artistProfileId ?? props.campaignId ?? "workspace"}</span>
      </section>
    ),
  ),
}));

vi.mock("../../lib/workspace-context", () => ({
  useActiveWorkspace: vi.fn(),
  useActiveWorkspaceProfile: vi.fn(),
}));

vi.mock("../../lib/analytics", async () => {
  const actual = await vi.importActual<typeof import("../../lib/analytics")>("../../lib/analytics");
  return {
    ...actual,
    useAnalyticsMetricDefinitions: vi.fn(),
    useAnalyticsObservations: vi.fn(),
  };
});

vi.mock("../../lib/campaigns", () => ({
  useCampaigns: vi.fn(),
}));

vi.mock("../../lib/profiles", () => ({
  useWorkspacePeopleDirectory: vi.fn(),
}));

const workspaceContext = await import("../../lib/workspace-context");
const analytics = await import("../../lib/analytics");
const campaigns = await import("../../lib/campaigns");
const profiles = await import("../../lib/profiles");
const readSurface = await import("../../components/analytics/analytics-read-surface");

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

const metric = {
  id: "metric_01",
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

const observation = {
  id: "observation_01",
  workspace_id: "workspace_01",
  metric_definition_id: "metric_01",
  metric_key: "streams",
  provider_id: "provider_01",
  provider_key: "spotify",
  target_type: "campaign",
  target_id: "campaign_01",
  artist_profile_id: "artist_profile_01",
  campaign_id: "campaign_01",
  campaign_name: "Launch Campaign",
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

describe("AnalyticsWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(workspaceContext.useActiveWorkspace).mockReturnValue({
      activeWorkspace: {
        id: "workspace_01",
        name: "Alpha Label",
        slug: "alpha",
        role: "owner",
        workspace_permission: "owner",
        department_access: ["analytics"],
        capability_permissions: ["analytics.view"],
        can_switch: true,
      },
      hasActiveWorkspace: true,
      workspaces: [],
    });
    vi.mocked(workspaceContext.useActiveWorkspaceProfile).mockReturnValue({
      capabilities: ["analytics.view"],
      canEditProfile: false,
      departmentAccess: ["analytics"],
      isLoading: false,
      membership: null,
      responsibilities: [],
      roles: ["owner"],
      subject: {
        capabilities: ["analytics.view"],
        departmentAccess: ["analytics"],
        role: "owner",
        workspacePermission: "owner",
      },
    });
    vi.mocked(analytics.useAnalyticsMetricDefinitions).mockReturnValue({
      data: { metric_definitions: [metric] },
      error: null,
      isLoading: false,
      reload: vi.fn(),
    });
    vi.mocked(analytics.useAnalyticsObservations).mockReturnValue({
      data: { observations: [observation], total: 1, limit: 100, offset: 0 },
      error: null,
      isLoading: false,
      reload: vi.fn(),
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
  });

  it("renders workspace analytics using the shared read surface and comparison tables", () => {
    render(<AnalyticsWorkspace />);

    expect(screen.getByRole("heading", { name: "Analytics" })).toBeInTheDocument();
    expect(screen.getByTestId("analytics-read-surface")).toHaveTextContent("Workspace analytics");
    expect(screen.getByRole("heading", { name: "Workspace comparisons" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Artist comparison" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Campaign comparison" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Provider breakdown" })).toBeInTheDocument();
    expect(screen.getByText("All value types")).toBeInTheDocument();
    expect(screen.getAllByText("Launch Campaign")).not.toHaveLength(0);
  });

  it("filters the reusable read surface by artist and campaign", () => {
    render(<AnalyticsWorkspace />);

    fireEvent.change(screen.getByLabelText("Explore"), { target: { value: "artist" } });
    fireEvent.change(screen.getByLabelText("Artist"), {
      target: { value: "artist_profile_01" },
    });

    expect(readSurface.AnalyticsReadSurface).toHaveBeenLastCalledWith(
      expect.objectContaining({
        artistProfileId: "artist_profile_01",
        title: "Mira Stone",
      }),
      undefined,
    );

    fireEvent.change(screen.getByLabelText("Explore"), { target: { value: "campaign" } });
    fireEvent.change(screen.getByLabelText("Campaign"), {
      target: { value: "campaign_01" },
    });

    expect(readSurface.AnalyticsReadSurface).toHaveBeenLastCalledWith(
      expect.objectContaining({
        campaignId: "campaign_01",
        title: "Launch Campaign",
      }),
      undefined,
    );
  });

  it("applies metric, provider, and date filters to workspace comparisons", () => {
    render(<AnalyticsWorkspace />);

    fireEvent.change(screen.getByLabelText("Metric"), { target: { value: "metric_01" } });
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "provider_01" } });
    fireEvent.change(screen.getByLabelText("Start"), { target: { value: "2026-08-01" } });
    fireEvent.change(screen.getByLabelText("End"), { target: { value: "2026-08-31" } });

    expect(analytics.useAnalyticsObservations).toHaveBeenLastCalledWith(
      "workspace_01",
      expect.objectContaining({
        metric_definition_id: "metric_01",
        observed_end: "2026-08-31T23:59:59Z",
        observed_start: "2026-08-01T00:00:00Z",
        provider_id: "provider_01",
      }),
    );
    expect(screen.getByText("Numeric metrics chart and aggregate.")).toBeInTheDocument();
  });
});
