import Link from "next/link";

import { DashboardPanel } from "./dashboard-panel";
import { mapActivityEvents, type ActivityEventTone } from "./activity-event-map";
import type { RecentActivityData } from "./dashboard.types";

type RecentActivityProps = {
  activity: RecentActivityData;
  now?: Date;
};

const toneClassNames: Record<ActivityEventTone, string> = {
  organization: "bg-sky-300 shadow-[0_0_16px_rgba(125,211,252,0.28)]",
  team: "bg-emerald-300 shadow-[0_0_16px_rgba(110,231,183,0.24)]",
  artist: "bg-cyan-300 shadow-[0_0_16px_rgba(34,211,238,0.28)]",
  release: "bg-violet-300 shadow-[0_0_16px_rgba(196,181,253,0.24)]",
  campaign: "bg-amber-300 shadow-[0_0_16px_rgba(252,211,77,0.22)]",
  approval: "bg-rose-300 shadow-[0_0_16px_rgba(253,164,175,0.22)]",
  agent: "bg-indigo-300 shadow-[0_0_16px_rgba(165,180,252,0.24)]",
  default: "bg-slate-300 shadow-[0_0_16px_rgba(203,213,225,0.18)]",
};

function RecentActivityLoading() {
  return (
    <ol className="flex flex-col gap-4" aria-label="Recent activity loading">
      {["activity-loading-1", "activity-loading-2", "activity-loading-3"].map((id) => (
        <li className="grid grid-cols-[auto_1fr] gap-3" key={id}>
          <span className="mt-1 h-2.5 w-2.5 rounded-full bg-slate-700" aria-hidden="true" />
          <div className="min-w-0 animate-pulse">
            <div className="h-4 w-32 rounded bg-slate-700/80" />
            <div className="mt-2 h-4 w-full max-w-64 rounded bg-slate-800" />
            <div className="mt-2 h-3 w-20 rounded bg-slate-800" />
          </div>
        </li>
      ))}
    </ol>
  );
}

export function RecentActivity({ activity, now }: RecentActivityProps) {
  const items = mapActivityEvents(activity.events, now);

  return (
    <DashboardPanel>
      <div className="flex flex-col gap-5">
        <div>
          <h2 className="text-lg font-semibold text-slate-50">Recent Activity</h2>
          <p className="mt-1 text-sm text-slate-400">Latest workspace updates.</p>
        </div>
        {activity.loading ? <RecentActivityLoading /> : null}
        {!activity.loading && activity.error ? (
          <div className="rounded-lg border border-rose-400/30 bg-rose-950/30 px-3 py-3" role="alert">
            <p className="text-sm font-medium text-rose-100">Activity could not be loaded.</p>
            <p className="mt-1 text-sm text-rose-200/80">{activity.error}</p>
          </div>
        ) : null}
        {!activity.loading && !activity.error && items.length === 0 ? (
          <div className="rounded-lg border border-slate-700/80 bg-slate-950/30 px-3 py-4">
            <p className="text-sm font-medium text-slate-200">No recent activity yet.</p>
            <p className="mt-1 text-sm text-slate-500">
              Workspace changes will appear here after artists, releases, campaigns, or approvals
              are created.
            </p>
            <Link
              className="mt-3 inline-flex text-sm font-semibold text-cyan-100 hover:text-cyan-50"
              href="/dashboard/artists/new"
            >
              Add your first artist -&gt;
            </Link>
          </div>
        ) : null}
        {!activity.loading && !activity.error && items.length > 0 ? (
          <ol className="flex flex-col gap-4">
            {items.map((item) => (
              <li className="grid grid-cols-[auto_1fr] gap-3" key={item.id}>
                <span
                  className={`mt-1 h-2.5 w-2.5 rounded-full ${toneClassNames[item.tone]}`}
                  aria-hidden="true"
                />
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-semibold text-slate-100">{item.title}</p>
                    <span className="text-xs font-medium text-slate-500">{item.rawType}</span>
                  </div>
                  <p className="mt-1 text-sm leading-6 text-slate-400">{item.description}</p>
                  <p className="mt-1 text-xs text-slate-500">{item.timestamp}</p>
                </div>
              </li>
            ))}
          </ol>
        ) : null}
      </div>
    </DashboardPanel>
  );
}
