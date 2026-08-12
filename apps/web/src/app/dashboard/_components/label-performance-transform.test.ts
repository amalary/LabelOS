import { describe, expect, it } from "vitest";

import type { LabelPerformanceApiSeries } from "./dashboard.types";
import {
  labelPerformanceMetrics,
  normalizeLabelPerformanceApiData,
} from "./label-performance-data";
import { getLabelPerformanceViewModel } from "./label-performance-transform";

describe("label performance contract transforms", () => {
  it("maps backend normalized series into dashboard range data", () => {
    const apiSeries: LabelPerformanceApiSeries[] = [
      {
        metric: "streams",
        period: "30d",
        total: 125,
        changePercent: 25,
        source: "development_mock",
        isMock: true,
        series: [
          { date: "2026-07-13", value: 100 },
          { date: "2026-07-14", value: 125 },
        ],
      },
      {
        metric: "revenue",
        period: "30d",
        total: 25,
        changePercent: 25,
        source: "development_mock",
        isMock: true,
        series: [
          { date: "2026-07-13", value: 20 },
          { date: "2026-07-14", value: 25 },
        ],
      },
    ];

    const data = normalizeLabelPerformanceApiData(apiSeries);

    expect(data.source).toBe("development_mock");
    expect(data.isMock).toBe(true);
    expect(data.ranges).toHaveLength(1);
    expect(data.ranges[0]).toMatchObject({
      range: "30D",
      points: [
        {
          date: "2026-07-13",
          label: "Jul 13",
          values: {
            streams: 100,
            revenue: 20,
          },
        },
        {
          date: "2026-07-14",
          label: "Jul 14",
          values: {
            streams: 125,
            revenue: 25,
          },
        },
      ],
    });
  });

  it("keeps the dashboard view model independent from provider-specific payloads", () => {
    const data = normalizeLabelPerformanceApiData([
      {
        metric: "streams",
        period: "30d",
        total: 125,
        changePercent: 25,
        source: "spotify",
        isMock: false,
        series: [
          { date: "2026-07-13", value: 100 },
          { date: "2026-07-14", value: 125 },
        ],
      },
    ]);

    const viewModel = getLabelPerformanceViewModel(data, "streams", "30D");

    expect(viewModel?.metric).toEqual(labelPerformanceMetrics[0]);
    expect(viewModel?.totalLabel).toBe("125");
    expect(viewModel?.changeLabel).toBe("+25.0%");
    expect(viewModel?.chartPoints).toEqual([
      { date: "2026-07-13", label: "Jul 13", value: 100 },
      { date: "2026-07-14", label: "Jul 14", value: 125 },
    ]);
  });
});
