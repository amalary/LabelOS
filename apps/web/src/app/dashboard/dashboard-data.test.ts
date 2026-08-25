import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClient = vi.hoisted(() => ({
  ApiClientError: class ApiClientError extends Error {
    constructor(
      readonly code: string,
      message: string,
      readonly status?: number,
    ) {
      super(message);
      this.name = "ApiClientError";
    }
  },
  apiFetch: vi.fn(),
}));

vi.mock("server-only", () => ({}));
vi.mock("../../lib/api-client", () => apiClient);

describe("getDashboardData", () => {
  beforeEach(() => {
    vi.resetModules();
    apiClient.apiFetch.mockReset();
  });

  it("maps organization-scoped summary counts into KPI and release pipeline view data", async () => {
    apiClient.apiFetch.mockResolvedValue(
      new Response(
        JSON.stringify({
          active_artists: 12,
          upcoming_releases: 7,
          active_campaigns: 3,
          pending_approvals: 2,
          releasePipeline: {
            planning: 4,
            production: 1,
            distribution: 1,
            scheduled: 1,
            released: 9,
          },
          availableCards: [
            "active-artists",
            "upcoming-releases",
            "active-campaigns",
            "tasks-approvals",
          ],
          availableSections: ["release-pipeline", "label-performance", "member-activity"],
        }),
        { status: 200 },
      ),
    );

    const { getDashboardData } = await import("./dashboard-data");
    const data = await getDashboardData();

    expect(apiClient.apiFetch).toHaveBeenCalledWith("/api/v1/dashboard/summary", {
      headers: {
        Accept: "application/json",
      },
    });
    expect(data.kpis.map((kpi) => [kpi.id, kpi.primaryValue])).toEqual([
      ["active-artists", "12"],
      ["upcoming-releases", "7"],
      ["active-campaigns", "3"],
      ["tasks-approvals", "2"],
    ]);
    expect(data.releasePipeline.stages).toEqual([
      { status: "planning", label: "Planning", count: 4, href: "/releases?status=planning" },
      {
        status: "production",
        label: "Production",
        count: 1,
        href: "/releases?status=production",
      },
      {
        status: "distribution",
        label: "Distribution",
        count: 1,
        href: "/releases?status=distribution",
      },
      { status: "scheduled", label: "Scheduled", count: 1, href: "/releases?status=scheduled" },
      { status: "released", label: "Released", count: 9, href: "/releases?status=released" },
    ]);
    expect(data.labelPerformance.ranges).toEqual([]);
    expect(data.labelPerformance.unavailable).toBe(false);
    expect(data.releasePipeline.unavailable).toBe(false);
    expect(data.recentActivity.unavailable).toBe(false);
  });

  it("omits dashboard cards and sections marked unavailable by the backend", async () => {
    apiClient.apiFetch.mockResolvedValue(
      new Response(
        JSON.stringify({
          active_artists: 12,
          upcoming_releases: 7,
          releasePipeline: {
            planning: 4,
            production: 1,
            distribution: 1,
            scheduled: 1,
            released: 9,
          },
          availableCards: ["active-artists", "upcoming-releases"],
          availableSections: ["release-pipeline"],
        }),
        { status: 200 },
      ),
    );

    const { getDashboardData } = await import("./dashboard-data");
    const data = await getDashboardData();

    expect(data.kpis.map((kpi) => kpi.id)).toEqual(["active-artists", "upcoming-releases"]);
    expect(data.releasePipeline.stages).toHaveLength(5);
    expect(data.releasePipeline.unavailable).toBe(false);
    expect(data.labelPerformance.unavailable).toBe(true);
    expect(data.recentActivity.unavailable).toBe(true);
    expect(data.recentActivity.events).toEqual([]);
  });

  it("returns actionable empty states for a brand-new organization with zero data", async () => {
    apiClient.apiFetch.mockResolvedValue(
      new Response(
        JSON.stringify({
          active_artists: 0,
          upcoming_releases: 0,
          active_campaigns: 0,
          pending_approvals: 0,
          releasePipeline: {
            planning: 0,
            production: 0,
            distribution: 0,
            scheduled: 0,
            released: 0,
          },
        }),
        { status: 200 },
      ),
    );

    const { getDashboardData } = await import("./dashboard-data");
    const data = await getDashboardData();

    expect(data.kpis).toMatchObject([
      {
        id: "active-artists",
        primaryValue: "0",
        empty: true,
        description: "No artists yet.",
        actionLabel: "Add your first artist ->",
      },
      {
        id: "upcoming-releases",
        primaryValue: "0",
        empty: true,
        description: "No upcoming releases.",
        actionLabel: "Create a release ->",
      },
      {
        id: "active-campaigns",
        primaryValue: "0",
        empty: true,
        description: "No active campaigns yet.",
        actionLabel: "Create a campaign ->",
      },
      {
        id: "tasks-approvals",
        primaryValue: "0",
        empty: true,
        description: "No approvals are waiting on your team.",
        actionLabel: "Review approval workflows ->",
      },
    ]);
    expect(data.releasePipeline.stages.every((stage) => stage.count === 0)).toBe(true);
    expect(data.labelPerformance).toMatchObject({ ranges: [] });
    expect(data.recentActivity).toEqual({ events: [], unavailable: false });
  });

  it("returns component-level error states when the dashboard summary fails", async () => {
    apiClient.apiFetch.mockResolvedValue(new Response("Service unavailable", { status: 503 }));

    const { getDashboardData } = await import("./dashboard-data");
    const data = await getDashboardData();

    expect(data.kpis).toHaveLength(4);
    expect(data.kpis.every((kpi) => kpi.error)).toBe(true);
    expect(data.releasePipeline).toMatchObject({
      stages: [],
      error: "Dashboard summary could not be loaded. Refresh the page or try again later.",
    });
    expect(data.labelPerformance.ranges).toEqual([]);
    expect(data.recentActivity.events).toEqual([]);
  });
});
