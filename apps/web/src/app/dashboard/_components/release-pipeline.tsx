import Link from "next/link";
import { cn } from "@label-os/ui";

import { DashboardPanel } from "./dashboard-panel";
import type { ReleaseLifecycleStatus, ReleasePipelineData } from "./dashboard.types";

type ReleasePipelineProps = {
  pipeline: ReleasePipelineData;
};

const stageToneClasses: Record<ReleaseLifecycleStatus, string> = {
  planning: "border-sky-300/20 bg-sky-300/10 text-sky-100",
  production: "border-violet-300/20 bg-violet-300/10 text-violet-100",
  distribution: "border-teal-300/20 bg-teal-300/10 text-teal-100",
  scheduled: "border-amber-300/20 bg-amber-300/10 text-amber-100",
  released: "border-emerald-300/20 bg-emerald-300/10 text-emerald-100",
};

const emptyMessage = "No releases are in the pipeline yet.";
const emptyOrganizationMessage = "Select or create an organization to view release stages.";

function formatReleaseCount(count: number) {
  return new Intl.NumberFormat("en-US").format(count);
}

export function ReleasePipeline({ pipeline }: ReleasePipelineProps) {
  const totalReleases = pipeline.stages.reduce((total, stage) => total + stage.count, 0);

  return (
    <DashboardPanel aria-labelledby="release-pipeline-title">
      <div className="flex flex-col gap-4">
        <div>
          <h2 id="release-pipeline-title" className="text-lg font-semibold text-slate-50">
            Release Pipeline
          </h2>
          <p className="mt-1 text-sm text-slate-400">
            Lifecycle position across planning, production, distribution, scheduling, and release.
          </p>
        </div>

        {pipeline.loading ? (
          <div
            role="status"
            aria-label="Release pipeline loading"
            className="grid animate-pulse gap-3 motion-reduce:animate-none sm:grid-cols-5"
          >
            {Array.from({ length: 5 }).map((_, index) => (
              <div
                className="h-24 rounded-md border border-slate-700/60 bg-slate-800/45"
                key={index}
              />
            ))}
          </div>
        ) : null}

        {pipeline.error ? (
          <div role="alert" className="rounded-md border border-rose-300/20 bg-rose-300/10 p-4">
            <p className="text-sm leading-6 text-rose-100">{pipeline.error}</p>
          </div>
        ) : null}

        {!pipeline.loading && !pipeline.error ? (
          <>
            <div className="flex flex-wrap items-end justify-between gap-4">
              <p className="text-sm text-slate-400">
                <span className="font-semibold text-slate-100">
                  {formatReleaseCount(totalReleases)}
                </span>{" "}
                total releases
              </p>
              {totalReleases === 0 || pipeline.emptyOrganization ? (
                <span className="rounded-full border border-slate-500/20 bg-slate-500/10 px-2 py-1 text-xs font-semibold text-slate-300">
                  Empty
                </span>
              ) : null}
            </div>

            {pipeline.emptyOrganization ? (
              <p className="rounded-md border border-slate-700/70 bg-slate-900/60 p-4 text-sm leading-6 text-slate-300">
                {emptyOrganizationMessage}
              </p>
            ) : (
              <ol
                className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,8rem),1fr))] gap-3 xl:grid-cols-5"
                aria-label="Release lifecycle stages"
              >
                {pipeline.stages.map((stage, index) => (
                  <li className="relative min-w-0" key={stage.status}>
                    <Link
                      aria-label={`${stage.label}: ${formatReleaseCount(stage.count)} releases`}
                      className={cn(
                        "group flex min-h-28 touch-manipulation flex-col justify-between rounded-md border p-3 transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950",
                        stageToneClasses[stage.status],
                        "hover:border-cyan-300/45 hover:bg-slate-800/70",
                      )}
                      href={stage.href}
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-semibold">{stage.label}</span>
                        {index < pipeline.stages.length - 1 ? (
                          <span
                            className="hidden text-slate-400 group-hover:text-cyan-100 sm:inline"
                            aria-hidden="true"
                          >
                            v
                          </span>
                        ) : null}
                      </span>
                      <span className="text-[2rem] font-semibold leading-none text-slate-50">
                        {formatReleaseCount(stage.count)}
                      </span>
                      <span className="text-xs font-medium text-slate-400">
                        {stage.count === 1 ? "release" : "releases"}
                      </span>
                    </Link>
                  </li>
                ))}
              </ol>
            )}

            {totalReleases === 0 && !pipeline.emptyOrganization ? (
              <div className="rounded-md border border-slate-700/70 bg-slate-950/30 p-4">
                <p className="text-sm font-medium text-slate-200">{emptyMessage}</p>
                <Link
                  className="mt-2 inline-flex rounded-sm text-sm font-semibold text-cyan-100 hover:text-cyan-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
                  href="/releases/new"
                >
                  Create a release -&gt;
                </Link>
              </div>
            ) : null}
          </>
        ) : null}
      </div>
    </DashboardPanel>
  );
}
