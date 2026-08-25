import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { LabelPerformanceData } from "./dashboard.types";
import { LabelPerformance } from "./label-performance";
import { getMockLabelPerformanceData } from "./label-performance-data";

async function renderPanel(data?: Partial<LabelPerformanceData>) {
  const performance = {
    ...(await getMockLabelPerformanceData()),
    ...data,
  };

  render(<LabelPerformance performance={performance} />);
}

describe("LabelPerformance", () => {
  it("renders the default streams chart summary and accessible data table", async () => {
    await renderPanel();

    expect(screen.getByRole("heading", { name: "Label Performance" })).toBeInTheDocument();
    expect(screen.getByText("Total Streams")).toBeInTheDocument();
    expect(screen.getByText("8.4M")).toBeInTheDocument();
    expect(screen.getByText("Increase +14.2%")).toBeInTheDocument();
    expect(screen.getByText(/Streams for 30D: 8.4M, \+14.2%/i)).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Performance metric" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Performance time range" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Performance chart data" })).toBeInTheDocument();
  });

  it("changes metric and range through keyboard-accessible buttons", async () => {
    const user = userEvent.setup();
    await renderPanel();

    const revenueButton = screen.getByRole("button", { name: "Revenue" });
    const oneYearButton = screen.getByRole("button", { name: "1Y" });

    revenueButton.focus();
    await user.keyboard("{Enter}");
    oneYearButton.focus();
    await user.keyboard("{Enter}");

    expect(revenueButton).toHaveAttribute("aria-pressed", "true");
    expect(oneYearButton).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Total Revenue")).toBeInTheDocument();
    expect(screen.getByText("$3.9M")).toBeInTheDocument();
  });

  it("renders loading, empty, and error states", async () => {
    await renderPanel({ loading: true });
    expect(screen.getByRole("status", { name: "Label performance loading" })).toBeInTheDocument();

    await renderPanel({ metrics: [], ranges: [] });
    expect(screen.getByLabelText("Label performance empty")).toHaveTextContent(
      "No performance data yet",
    );
    expect(screen.getByRole("link", { name: "Connect analytics source ->" })).toHaveAttribute(
      "href",
      "/dashboard/integrations",
    );

    await renderPanel({ error: "Analytics could not be loaded." });
    expect(screen.getByRole("alert")).toHaveTextContent("Analytics could not be loaded.");
  });
});
