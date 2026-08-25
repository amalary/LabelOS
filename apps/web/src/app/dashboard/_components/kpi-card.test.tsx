import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { KpiCard } from "./kpi-card";

describe("KpiCard", () => {
  it("renders title, primary value, icon, description, and positive trend copy", () => {
    render(
      <KpiCard
        title="Active Artists"
        primaryValue="12"
        icon="AR"
        trendValue="9.1%"
        trendDirection="positive"
        comparisonLabel="from last month"
        description="Roster with recent activity"
      />,
    );

    expect(screen.getByRole("heading", { name: "Active Artists" })).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("Roster with recent activity")).toBeInTheDocument();
    expect(screen.getByLabelText("Increase 9.1%")).toHaveTextContent("\u2191 Increase 9.1%");
    expect(screen.getByText("from last month")).toBeInTheDocument();
  });

  it("uses non-color trend labels for negative and neutral trends", () => {
    const { rerender } = render(
      <KpiCard
        title="Tasks / Approvals"
        primaryValue="6"
        icon="TA"
        trendValue="2"
        trendDirection="negative"
      />,
    );

    expect(screen.getByLabelText("Decrease 2")).toHaveTextContent("\u2193 Decrease 2");

    rerender(
      <KpiCard
        title="Active Campaigns"
        primaryValue="8"
        icon="AC"
        trendValue="0%"
        trendDirection="neutral"
      />,
    );

    expect(screen.getByLabelText("No change 0%")).toHaveTextContent("\u2192 No change 0%");
  });

  it("handles missing trend data", () => {
    render(<KpiCard title="Upcoming Releases" primaryValue="14" icon="UR" />);

    expect(screen.getByLabelText("No trend data")).toHaveTextContent("No trend data");
  });

  it("renders navigation when a destination is provided", () => {
    render(
      <KpiCard title="Active Artists" primaryValue="12" icon="AR" href="/dashboard/artists" />,
    );

    expect(screen.getByRole("link", { name: "Active Artists details" })).toHaveAttribute(
      "href",
      "/dashboard/artists",
    );
  });

  it("renders loading, empty, and error states", () => {
    const { rerender } = render(
      <KpiCard title="Active Artists" primaryValue="12" icon="AR" loading />,
    );

    expect(screen.getByRole("status", { name: "Loading Active Artists" })).toBeInTheDocument();

    rerender(
      <KpiCard
        title="Upcoming Releases"
        primaryValue="0"
        icon="UR"
        empty
        description="No releases are scheduled yet."
        href="/releases/new"
        actionLabel="Create a release ->"
      />,
    );

    expect(screen.getByLabelText("Upcoming Releases empty")).toHaveTextContent(
      "No releases are scheduled yet.",
    );
    expect(screen.getByRole("link", { name: "Upcoming Releases details" })).toHaveAttribute(
      "href",
      "/releases/new",
    );
    expect(screen.getByText("Create a release ->")).toBeInTheDocument();

    rerender(
      <KpiCard
        title="Tasks / Approvals"
        primaryValue="0"
        icon="TA"
        error="Tasks could not be loaded."
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Tasks could not be loaded.");
  });

  it("keeps the legacy value prop as a compatibility fallback", () => {
    render(<KpiCard title="Active Artists" value="12" icon="AR" />);

    expect(screen.getByText("12")).toBeInTheDocument();
  });
});
