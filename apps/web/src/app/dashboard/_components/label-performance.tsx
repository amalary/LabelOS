"use client";

import { cn } from "@label-os/ui";
import Link from "next/link";
import { useMemo, useState } from "react";

import type {
  LabelPerformanceData,
  LabelPerformanceMetricId,
  LabelPerformanceTimeRange,
} from "./dashboard.types";
import { LabelPerformanceChart } from "./label-performance-chart";
import { LabelPerformanceControls } from "./label-performance-controls";
import { getLabelPerformanceViewModel } from "./label-performance-transform";
import { DashboardPanel } from "./dashboard-panel";

type LabelPerformanceProps = {
  performance: LabelPerformanceData;
};

const defaultMetric: LabelPerformanceMetricId = "streams";
const defaultRange: LabelPerformanceTimeRange = "30D";

const changeToneClasses = {
  negative: "text-rose-200",
  neutral: "text-slate-300",
  positive: "text-emerald-200",
};

const changeDirectionLabels = {
  negative: "Decrease",
  neutral: "No change",
  positive: "Increase",
};

export function LabelPerformance({ performance }: LabelPerformanceProps) {
  const [selectedMetric, setSelectedMetric] = useState<LabelPerformanceMetricId>(defaultMetric);
  const [selectedRange, setSelectedRange] = useState<LabelPerformanceTimeRange>(defaultRange);
  const viewModel = useMemo(
    () => getLabelPerformanceViewModel(performance, selectedMetric, selectedRange),
    [performance, selectedMetric, selectedRange],
  );
  const activeViewModel = performance.loading || performance.error ? null : viewModel;

  return (
    <DashboardPanel
      aria-labelledby="label-performance-title"
      className="min-h-[28rem] sm:min-h-[31rem] lg:min-h-[33rem]"
    >
      <div className="flex h-full min-w-0 flex-col gap-4 sm:gap-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <h2 className="text-xl font-semibold text-slate-50" id="label-performance-title">
              Label Performance
            </h2>
            <p className="mt-1 text-sm text-slate-400">
              Streaming, audience, commercial, and engagement trends.
            </p>
          </div>
          {activeViewModel ? (
            <div
              aria-live="polite"
              className="dashboard-panel-soft rounded-[14px] px-4 py-3 sm:min-w-56"
            >
              <p className="text-sm font-medium text-slate-400">
                Total {activeViewModel.metric.label}
              </p>
              <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <p className="text-2xl font-semibold text-slate-50 sm:text-3xl">
                  {activeViewModel.totalLabel}
                </p>
                <p
                  className={cn(
                    "text-sm font-semibold",
                    changeToneClasses[activeViewModel.changeDirection],
                  )}
                >
                  {changeDirectionLabels[activeViewModel.changeDirection]}{" "}
                  {activeViewModel.changeLabel}
                </p>
              </div>
            </div>
          ) : null}
        </div>

        {performance.loading ? (
          <div
            aria-label="Label performance loading"
            className="grid min-h-72 place-items-center rounded-[16px] border border-slate-700/70 bg-slate-950/30"
            role="status"
          >
            <div className="w-full max-w-md space-y-4 px-6">
              <div className="h-4 w-1/3 rounded bg-slate-700/80" />
              <div className="h-40 rounded bg-slate-800/80" />
              <div className="grid grid-cols-4 gap-2">
                <div className="h-8 rounded bg-slate-700/70" />
                <div className="h-8 rounded bg-slate-700/70" />
                <div className="h-8 rounded bg-slate-700/70" />
                <div className="h-8 rounded bg-slate-700/70" />
              </div>
            </div>
          </div>
        ) : performance.error ? (
          <div
            className="rounded-[16px] border border-rose-300/30 bg-rose-400/10 px-5 py-4 text-sm leading-6 text-rose-100"
            role="alert"
          >
            {performance.error}
          </div>
        ) : !activeViewModel ? (
          <div
            aria-label="Label performance empty"
            className="grid min-h-72 place-items-center rounded-[16px] border border-slate-700/70 bg-slate-950/30 px-5 text-center"
          >
            <div>
              <p className="text-base font-semibold text-slate-100">No performance data yet</p>
              <p className="mt-2 max-w-md text-sm leading-6 text-slate-400">
                Analytics will appear here after streams, audience, revenue, or engagement events
                are available for this workspace.
              </p>
              <Link
                className="mt-4 inline-flex rounded-sm text-sm font-semibold text-cyan-100 hover:text-cyan-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
                href="/dashboard/integrations"
              >
                Connect analytics source -&gt;
              </Link>
            </div>
          </div>
        ) : (
          <>
            <LabelPerformanceControls
              metrics={performance.metrics}
              onMetricChange={setSelectedMetric}
              onRangeChange={setSelectedRange}
              selectedMetric={selectedMetric}
              selectedRange={selectedRange}
            />
            <LabelPerformanceChart
              points={activeViewModel.chartPoints}
              summary={activeViewModel.summary}
            />
          </>
        )}
      </div>
    </DashboardPanel>
  );
}
