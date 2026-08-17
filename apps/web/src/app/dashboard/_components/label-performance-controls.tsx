import { cn } from "@label-os/ui";

import type {
  LabelPerformanceMetricConfig,
  LabelPerformanceMetricId,
  LabelPerformanceTimeRange,
} from "./dashboard.types";

type LabelPerformanceControlsProps = {
  metrics: LabelPerformanceMetricConfig[];
  selectedMetric: LabelPerformanceMetricId;
  selectedRange: LabelPerformanceTimeRange;
  onMetricChange: (metric: LabelPerformanceMetricId) => void;
  onRangeChange: (range: LabelPerformanceTimeRange) => void;
};

const timeRanges: LabelPerformanceTimeRange[] = ["7D", "30D", "90D", "1Y"];

const buttonBaseClasses =
  "rounded-md border px-3 py-2 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-200";

export function LabelPerformanceControls({
  metrics,
  selectedMetric,
  selectedRange,
  onMetricChange,
  onRangeChange,
}: LabelPerformanceControlsProps) {
  return (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
      <div aria-label="Performance metric" className="flex flex-wrap gap-2">
        {metrics.map((metric) => (
          <button
            aria-pressed={metric.id === selectedMetric}
            className={cn(
              buttonBaseClasses,
              metric.id === selectedMetric
                ? "border-cyan-300/60 bg-cyan-300/15 text-cyan-50"
                : "border-slate-700/80 bg-slate-950/30 text-slate-300 hover:border-slate-500 hover:text-slate-50",
            )}
            key={metric.id}
            onClick={() => onMetricChange(metric.id)}
            type="button"
          >
            {metric.label}
          </button>
        ))}
      </div>
      <div aria-label="Performance time range" className="grid grid-cols-4 gap-2 sm:flex">
        {timeRanges.map((range) => (
          <button
            aria-pressed={range === selectedRange}
            className={cn(
              buttonBaseClasses,
              "min-w-14",
              range === selectedRange
                ? "border-emerald-300/60 bg-emerald-300/15 text-emerald-50"
                : "border-slate-700/80 bg-slate-950/30 text-slate-300 hover:border-slate-500 hover:text-slate-50",
            )}
            key={range}
            onClick={() => onRangeChange(range)}
            type="button"
          >
            {range}
          </button>
        ))}
      </div>
    </div>
  );
}
