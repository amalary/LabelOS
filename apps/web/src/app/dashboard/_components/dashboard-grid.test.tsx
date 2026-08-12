import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DashboardGrid } from "./dashboard-grid";
import type { DashboardData } from "./dashboard.types";

const dashboardData: DashboardData = {
  kpis: [
    {
      id: "active-artists",
      title: "Active Artists",
      primaryValue: "12",
      icon: "AR",
      trendValue: "9.1%",
      trendDirection: "positive",
      comparisonLabel: "from last month",
      href: "/dashboard/artists",
    },
    {
      id: "upcoming-releases",
      title: "Upcoming Releases",
      primaryValue: "0",
      icon: "UR",
      empty: true,
      description: "No releases are scheduled yet.",
    },
    {
      id: "active-campaigns",
      title: "Active Campaigns",
      primaryValue: "8",
      icon: "AC",
      trendDirection: "neutral",
      trendValue: "0%",
    },
    {
      id: "tasks-approvals",
      title: "Tasks / Approvals",
      primaryValue: "0",
      icon: "TA",
      error: "Tasks could not be loaded.",
    },
  ],
  labelPerformance: {
    metrics: [],
    ranges: [],
  },
  releasePipeline: {
    stages: [],
  },
  recentActivity: {
    events: [],
  },
};

describe("DashboardGrid", () => {
  it("renders dashboard KPIs through the reusable KPI card API", () => {
    render(<DashboardGrid data={dashboardData} />);

    expect(screen.getByLabelText("Dashboard KPIs")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Active Artists details" })).toHaveAttribute(
      "href",
      "/dashboard/artists",
    );
    expect(screen.getByRole("heading", { name: "Active Artists" })).toBeInTheDocument();
    expect(screen.getByLabelText("Increase 9.1%")).toHaveTextContent("↑ Increase 9.1%");
    expect(screen.getByLabelText("Upcoming Releases empty")).toHaveTextContent(
      "No releases are scheduled yet.",
    );
    expect(screen.getByLabelText("No change 0%")).toHaveTextContent("→ No change 0%");
    expect(screen.getByRole("alert")).toHaveTextContent("Tasks could not be loaded.");
  });
});
