import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AnalyticsMetricDefinition,
  AnalyticsMetricDefinitionsList,
  AnalyticsProvidersList,
} from "../../../lib/analytics";

const mocks = vi.hoisted(() => ({
  can: vi.fn(),
  createMetric: vi.fn(),
  metricsReload: vi.fn(),
  providersReload: vi.fn(),
  metricDefinitions: null as AnalyticsMetricDefinitionsList | null,
  providers: null as AnalyticsProvidersList | null,
}));

vi.mock("../../../lib/authorization", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/authorization")>(
    "../../../lib/authorization",
  );
  return {
    ...actual,
    can: mocks.can,
  };
});

vi.mock("../../../lib/workspace-context", () => ({
  useActiveWorkspace: () => ({
    activeWorkspace: {
      id: "workspace_01",
      name: "Alpha Label",
    },
  }),
  useActiveWorkspaceProfile: () => ({
    isLoading: false,
    subject: {
      capabilities: ["analytics.view", "analytics.create"],
      departmentAccess: ["analytics"],
      role: "member",
      workspacePermission: "member",
    },
  }),
}));

vi.mock("../../../lib/analytics", async () => {
  const actual =
    await vi.importActual<typeof import("../../../lib/analytics")>("../../../lib/analytics");
  return {
    ...actual,
    useAnalyticsMetricDefinitions: () => ({
      data: mocks.metricDefinitions,
      error: null,
      isLoading: false,
      reload: mocks.metricsReload,
    }),
    useAnalyticsProviders: () => ({
      data: mocks.providers,
      error: null,
      isLoading: false,
      reload: mocks.providersReload,
    }),
    useCreateAnalyticsMetricDefinition: () => ({
      data: null,
      error: null,
      isMutating: false,
      mutate: mocks.createMetric,
      reset: vi.fn(),
    }),
  };
});

const metricDefinition: AnalyticsMetricDefinition = {
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
  key: "campaign.streams",
  display_name: "Campaign Streams",
  description: null,
  value_type: "integer",
  default_unit: "count",
  aggregation: "sum",
  metadata: {},
  created_at: "2026-08-29T12:00:00Z",
  updated_at: "2026-08-29T12:00:00Z",
};

describe("AnalyticsConfigurationPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.can.mockReturnValue(true);
    mocks.metricDefinitions = { metric_definitions: [metricDefinition] };
    mocks.providers = { providers: [metricDefinition.provider] };
    mocks.metricsReload.mockResolvedValue(mocks.metricDefinitions);
    mocks.providersReload.mockResolvedValue(mocks.providers);
    mocks.createMetric.mockResolvedValue({
      ...metricDefinition,
      id: "metric_02",
      key: "campaign.saves",
      display_name: "Campaign Saves",
    });
  });

  it("shows available metric definitions and provider source details", async () => {
    const { AnalyticsConfigurationPanel } = await import("./analytics-configuration-panel");

    render(<AnalyticsConfigurationPanel />);

    expect(screen.getByRole("heading", { name: "Analytics Configuration" })).toBeInTheDocument();
    expect(screen.getByText("campaign.streams")).toBeInTheDocument();
    expect(screen.getByText("Campaign Streams")).toBeInTheDocument();
    expect(screen.getAllByText("Integer").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Internal Analytics").length).toBeGreaterThan(0);
    expect(screen.getByText("Not tracked")).toBeInTheDocument();
  });

  it("creates a custom metric definition when analytics create is allowed", async () => {
    const user = userEvent.setup();
    const { AnalyticsConfigurationPanel } = await import("./analytics-configuration-panel");

    render(<AnalyticsConfigurationPanel />);

    await user.type(screen.getByLabelText("Canonical Name"), "campaign.saves");
    await user.type(screen.getByLabelText("Display Name"), "Campaign Saves");
    await user.selectOptions(screen.getByLabelText("Value Type"), "decimal");
    await user.clear(screen.getByLabelText("Unit"));
    await user.type(screen.getByLabelText("Unit"), "count");
    await user.click(screen.getByRole("button", { name: "Create metric definition" }));

    await waitFor(() =>
      expect(mocks.createMetric).toHaveBeenCalledWith({
        aggregation: "sum",
        default_unit: "count",
        description: null,
        display_name: "Campaign Saves",
        key: "campaign.saves",
        provider: {
          display_name: "Internal Analytics",
          key: "internal",
          provider_type: "internal",
        },
        value_type: "decimal",
      }),
    );
    expect(mocks.metricsReload).toHaveBeenCalled();
    expect(mocks.providersReload).toHaveBeenCalled();
  });

  it("keeps create controls disabled without analytics create capability", async () => {
    mocks.can.mockImplementation(
      (_subject, _workspace, capability) => capability === "analytics.view",
    );
    const { AnalyticsConfigurationPanel } = await import("./analytics-configuration-panel");

    render(<AnalyticsConfigurationPanel />);

    expect(screen.getByText("View only")).toBeInTheDocument();
    expect(screen.getByLabelText("Canonical Name")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Create metric definition" })).toBeDisabled();
  });

  it("validates canonical names before creating", async () => {
    const user = userEvent.setup();
    const { AnalyticsConfigurationPanel } = await import("./analytics-configuration-panel");

    render(<AnalyticsConfigurationPanel />);

    await user.type(screen.getByLabelText("Canonical Name"), "Campaign Saves");
    await user.type(screen.getByLabelText("Display Name"), "Campaign Saves");
    await user.click(screen.getByRole("button", { name: "Create metric definition" }));

    expect(
      screen.getByText(
        "Canonical name must use lowercase letters, numbers, underscores, and optional dot-separated segments.",
      ),
    ).toBeInTheDocument();
    expect(mocks.createMetric).not.toHaveBeenCalled();
  });
});
