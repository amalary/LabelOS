import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LabelPerformanceControls } from "./label-performance-controls";
import type { LabelPerformanceMetricConfig } from "./dashboard.types";

const metrics: LabelPerformanceMetricConfig[] = [
  { id: "streams", label: "Streams", unit: "count" },
  { id: "listeners", label: "Listeners", unit: "count" },
  { id: "revenue", label: "Revenue", unit: "currency" },
];

describe("LabelPerformanceControls", () => {
  it("renders selected metric and period controls with accessible pressed states", () => {
    render(
      <LabelPerformanceControls
        metrics={metrics}
        onMetricChange={vi.fn()}
        onRangeChange={vi.fn()}
        selectedMetric="listeners"
        selectedRange="90D"
      />,
    );

    expect(screen.getByRole("group", { name: "Performance metric" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Performance time range" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Streams" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByRole("button", { name: "Listeners" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "90D" })).toHaveAttribute("aria-pressed", "true");
  });

  it("calls metric and period change handlers from the rendered controls", async () => {
    const user = userEvent.setup();
    const onMetricChange = vi.fn();
    const onRangeChange = vi.fn();

    render(
      <LabelPerformanceControls
        metrics={metrics}
        onMetricChange={onMetricChange}
        onRangeChange={onRangeChange}
        selectedMetric="streams"
        selectedRange="30D"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Revenue" }));
    await user.click(screen.getByRole("button", { name: "1Y" }));

    expect(onMetricChange).toHaveBeenCalledWith("revenue");
    expect(onRangeChange).toHaveBeenCalledWith("1Y");
  });
});
