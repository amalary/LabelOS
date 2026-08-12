import type {
  LabelPerformanceApiSeries,
  LabelPerformanceData,
  LabelPerformanceMetricConfig,
  LabelPerformanceMetricId,
  LabelPerformanceRangeSeries,
  LabelPerformanceTimeRange,
} from "./dashboard.types";
import { toLabelPerformanceData } from "./label-performance-transform";

export const labelPerformanceMetrics: LabelPerformanceMetricConfig[] = [
  { id: "streams", label: "Streams", unit: "count" },
  { id: "listeners", label: "Listeners", unit: "count" },
  { id: "followers", label: "Followers", unit: "count" },
  { id: "revenue", label: "Revenue", unit: "currency" },
  { id: "engagement", label: "Engagement", unit: "percent" },
];

type SeriesSeed = {
  range: LabelPerformanceTimeRange;
  labels: string[];
  streams: number[];
  listeners: number[];
  followers: number[];
  revenue: number[];
  engagement: number[];
};

const seeds: SeriesSeed[] = [
  {
    range: "7D",
    labels: ["Thu", "Fri", "Sat", "Sun", "Mon", "Tue", "Wed"],
    streams: [980000, 1050000, 1110000, 1160000, 1200000, 1290000, 1420000],
    listeners: [430000, 452000, 468000, 491000, 506000, 529000, 557000],
    followers: [18200, 19100, 20400, 21900, 22600, 23900, 25100],
    revenue: [58500, 61200, 64800, 69000, 71400, 76200, 81500],
    engagement: [6.8, 7.0, 7.1, 7.4, 7.5, 7.7, 7.9],
  },
  {
    range: "30D",
    labels: [
      "Jul 14",
      "Jul 17",
      "Jul 20",
      "Jul 23",
      "Jul 26",
      "Jul 29",
      "Aug 1",
      "Aug 4",
      "Aug 7",
      "Aug 10",
    ],
    streams: [
      7355000, 7460000, 7580000, 7710000, 7830000, 7950000, 8080000, 8200000, 8310000, 8400000,
    ],
    listeners: [
      2210000, 2290000, 2360000, 2440000, 2510000, 2580000, 2660000, 2740000, 2810000, 2890000,
    ],
    followers: [312000, 319000, 326000, 334000, 342000, 351000, 359000, 368000, 376000, 385000],
    revenue: [312000, 326000, 339000, 353000, 367000, 381000, 398000, 414000, 431000, 448000],
    engagement: [5.9, 6.0, 6.1, 6.2, 6.4, 6.5, 6.7, 6.8, 6.9, 7.1],
  },
  {
    range: "90D",
    labels: [
      "May 15",
      "May 25",
      "Jun 4",
      "Jun 14",
      "Jun 24",
      "Jul 4",
      "Jul 14",
      "Jul 24",
      "Aug 3",
      "Aug 12",
    ],
    streams: [
      15200000, 15800000, 16400000, 17300000, 18100000, 19000000, 20100000, 21300000, 22400000,
      23800000,
    ],
    listeners: [
      5200000, 5390000, 5610000, 5860000, 6120000, 6380000, 6690000, 7010000, 7290000, 7640000,
    ],
    followers: [710000, 731000, 755000, 782000, 811000, 838000, 871000, 904000, 936000, 971000],
    revenue: [810000, 839000, 873000, 918000, 962000, 1009000, 1063000, 1118000, 1172000, 1248000],
    engagement: [5.2, 5.3, 5.4, 5.5, 5.7, 5.9, 6.0, 6.2, 6.4, 6.6],
  },
  {
    range: "1Y",
    labels: ["Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug"],
    streams: [
      41200000, 43100000, 45500000, 48900000, 50700000, 53200000, 55800000, 59100000, 62700000,
      66300000, 70400000, 75200000,
    ],
    listeners: [
      12100000, 12600000, 13200000, 13900000, 14300000, 14900000, 15600000, 16400000, 17300000,
      18200000, 19100000, 20200000,
    ],
    followers: [
      1840000, 1900000, 1980000, 2070000, 2150000, 2240000, 2340000, 2460000, 2580000, 2710000,
      2850000, 3010000,
    ],
    revenue: [
      2180000, 2270000, 2390000, 2540000, 2660000, 2790000, 2930000, 3090000, 3270000, 3460000,
      3670000, 3910000,
    ],
    engagement: [4.8, 4.9, 5.0, 5.1, 5.1, 5.3, 5.4, 5.6, 5.7, 5.9, 6.1, 6.3],
  },
];

const dateByRange: Record<LabelPerformanceTimeRange, string> = {
  "7D": "2026-08",
  "30D": "2026",
  "90D": "2026",
  "1Y": "2026",
};

function toRangeSeries(seed: SeriesSeed): LabelPerformanceRangeSeries {
  return {
    range: seed.range,
    points: seed.labels.map((label, index) => ({
      label,
      date: `${dateByRange[seed.range]}-${String(index + 1).padStart(2, "0")}`,
      values: labelPerformanceMetrics.reduce(
        (values, metric) => ({
          ...values,
          [metric.id]: seed[metric.id][index],
        }),
        {} as Record<LabelPerformanceMetricId, number>,
      ),
    })),
  };
}

export async function getMockLabelPerformanceData(): Promise<LabelPerformanceData> {
  return {
    metrics: labelPerformanceMetrics,
    ranges: seeds.map(toRangeSeries),
    source: "development_mock",
    isMock: true,
  };
}

export function getLabelPerformanceMetrics() {
  return labelPerformanceMetrics;
}

export function normalizeLabelPerformanceApiData(
  apiSeries: LabelPerformanceApiSeries[],
): LabelPerformanceData {
  return toLabelPerformanceData(labelPerformanceMetrics, apiSeries);
}
