import type { DashboardData } from "./dashboard.types";
import { KpiCard } from "./kpi-card";
import { LabelPerformance } from "./label-performance";
import { RecentActivity } from "./recent-activity";
import { ReleasePipeline } from "./release-pipeline";

type DashboardGridProps = {
  data: DashboardData;
};

export function DashboardGrid({ data }: DashboardGridProps) {
  return (
    <div className="flex flex-col gap-5">
      <section aria-label="Dashboard KPIs" className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-4">
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
      <section className="grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(22rem,0.82fr)]">
        <div className="min-w-0" aria-label="Primary dashboard column">
          <LabelPerformance performance={data.labelPerformance} />
        </div>
        <aside className="flex min-w-0 flex-col gap-5" aria-label="Secondary dashboard column">
          <ReleasePipeline pipeline={data.releasePipeline} />
          <RecentActivity activity={data.recentActivity} />
        </aside>
      </section>
    </div>
  );
}
