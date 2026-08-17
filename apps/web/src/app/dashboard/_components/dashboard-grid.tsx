import type { DashboardData } from "./dashboard.types";
import { KpiCard } from "./kpi-card";
import { LabelPerformance } from "./label-performance";
import { RealtimeRecentActivity } from "./realtime-recent-activity";
import { ReleasePipeline } from "./release-pipeline";

type DashboardGridProps = {
  data: DashboardData;
};

export function DashboardGrid({ data }: DashboardGridProps) {
  const hasPrimaryColumn = !data.labelPerformance.unavailable;
  const secondaryPanels = [
    !data.releasePipeline.unavailable ? (
      <ReleasePipeline key="release-pipeline" pipeline={data.releasePipeline} />
    ) : null,
    !data.recentActivity.unavailable ? (
      <RealtimeRecentActivity key="recent-activity" activity={data.recentActivity} />
    ) : null,
  ].filter(Boolean);

  return (
    <div className="flex min-w-0 flex-col gap-4 sm:gap-5">
      {data.kpis.length > 0 ? (
        <section
          aria-label="Dashboard KPIs"
          className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,14.5rem),1fr))] gap-3 sm:gap-4 xl:grid-cols-4"
        >
          {data.kpis.map((kpi) => (
            <KpiCard
              key={kpi.id}
              title={kpi.title}
              primaryValue={kpi.primaryValue}
              icon={kpi.icon}
              trendValue={kpi.trendValue}
              trendDirection={kpi.trendDirection}
              comparisonLabel={kpi.comparisonLabel}
              description={kpi.description}
              href={kpi.href}
              actionLabel={kpi.actionLabel}
              loading={kpi.loading}
              empty={kpi.empty}
              error={kpi.error}
            />
          ))}
        </section>
      ) : null}
      {hasPrimaryColumn || secondaryPanels.length > 0 ? (
        <section className="grid min-w-0 gap-4 sm:gap-5 xl:grid-cols-[minmax(0,1.58fr)_minmax(21rem,0.82fr)]">
          {hasPrimaryColumn ? (
            <div className="min-w-0" aria-label="Primary dashboard column">
              <LabelPerformance performance={data.labelPerformance} />
            </div>
          ) : null}
          {secondaryPanels.length > 0 ? (
            <aside
              className="grid min-w-0 gap-5 md:grid-cols-2 xl:flex xl:flex-col"
              aria-label="Secondary dashboard column"
            >
              {secondaryPanels}
            </aside>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
