import "server-only";

import { ApiClientError, apiFetch } from "../../lib/api-client";
import type {
  DashboardData,
  DashboardKpi,
  ReleaseLifecycleStatus,
  ReleasePipelineStage,
} from "./_components/dashboard.types";
import { getLabelPerformanceMetrics } from "./_components/label-performance-data";

type DashboardSummaryResponse = {
  active_artists?: number;
  upcoming_releases?: number;
  active_campaigns?: number;
  pending_approvals?: number;
  releasePipeline?: Record<ReleaseLifecycleStatus, number>;
  availableCards?: string[];
  availableSections?: string[];
  authorization?: {
    role: string;
    permissions: string[];
  };
};

const releasePipelineStageConfig: Array<{
  status: ReleaseLifecycleStatus;
  label: string;
}> = [
  { status: "planning", label: "Planning" },
  { status: "production", label: "Production" },
  { status: "distribution", label: "Distribution" },
  { status: "scheduled", label: "Scheduled" },
  { status: "released", label: "Released" },
];

function formatCount(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

function toReleasePipelineStages(
  counts: Record<ReleaseLifecycleStatus, number>,
): ReleasePipelineStage[] {
  return releasePipelineStageConfig.map(({ status, label }) => ({
    status,
    label,
    count: counts[status] ?? 0,
    href: `/releases?status=${status}`,
  }));
}

const kpiConfig: Array<{
  id: string;
  title: string;
  icon: string;
  description: string;
  emptyDescription: string;
  href: string;
  actionLabel: string;
  valueKey: keyof Pick<
    DashboardSummaryResponse,
    "active_artists" | "upcoming_releases" | "active_campaigns" | "pending_approvals"
  >;
}> = [
  {
    id: "active-artists",
    title: "Active Artists",
    icon: "AR",
    description: "Roster records in this workspace",
    emptyDescription: "No artists yet.",
    href: "/dashboard/artists/new",
    actionLabel: "Add your first artist ->",
    valueKey: "active_artists",
  },
  {
    id: "upcoming-releases",
    title: "Upcoming Releases",
    icon: "UR",
    description: "Release records in this workspace",
    emptyDescription: "No upcoming releases.",
    href: "/releases/new",
    actionLabel: "Create a release ->",
    valueKey: "upcoming_releases",
  },
  {
    id: "active-campaigns",
    title: "Active Campaigns",
    icon: "AC",
    description: "Campaign records in this workspace",
    emptyDescription: "No active campaigns yet.",
    href: "/dashboard/campaigns/new",
    actionLabel: "Create a campaign ->",
    valueKey: "active_campaigns",
  },
  {
    id: "tasks-approvals",
    title: "Tasks / Approvals",
    icon: "TA",
    description: "Contract records awaiting workflow data",
    emptyDescription: "No approvals are waiting on your team.",
    href: "/dashboard/tasks",
    actionLabel: "Review approval workflows ->",
    valueKey: "pending_approvals",
  },
];

function toKpis(summary: DashboardSummaryResponse): DashboardKpi[] {
  const availableCards = new Set(summary.availableCards ?? kpiConfig.map((item) => item.id));

  return kpiConfig.flatMap((item) => {
    if (!availableCards.has(item.id)) {
      return [];
    }
    const count = summary[item.valueKey] ?? 0;

    return [
      {
        id: item.id,
        title: item.title,
        primaryValue: formatCount(count),
        icon: item.icon,
        description: count === 0 ? item.emptyDescription : item.description,
        href: item.href,
        actionLabel: item.actionLabel,
        empty: count === 0,
      },
    ];
  });
}

function emptyReleasePipelineStages(): ReleasePipelineStage[] {
  return toReleasePipelineStages({
    planning: 0,
    production: 0,
    distribution: 0,
    scheduled: 0,
    released: 0,
  });
}

export function getEmptyDashboardData(
  options: { emptyOrganization?: boolean; error?: string } = {},
): DashboardData {
  const summaryError = options.error;

  return {
    kpis: kpiConfig.map((item) => ({
      id: item.id,
      title: item.title,
      primaryValue: "0",
      icon: item.icon,
      description: summaryError ? undefined : item.emptyDescription,
      href: item.href,
      actionLabel: item.actionLabel,
      empty: !summaryError,
      error: summaryError,
    })),
    labelPerformance: {
      metrics: getLabelPerformanceMetrics(),
      ranges: [],
    },
    releasePipeline: {
      stages: summaryError ? [] : emptyReleasePipelineStages(),
      emptyOrganization: options.emptyOrganization,
      error: summaryError,
    },
    recentActivity: {
      events: [],
    },
  };
}

async function getDashboardSummary(): Promise<DashboardSummaryResponse> {
  const response = await apiFetch("/api/v1/dashboard/summary", {
    headers: {
      Accept: "application/json",
    },
  });

  if (!response.ok) {
    throw new ApiClientError(
      "network_failure",
      "The backend returned an unexpected dashboard response.",
      response.status,
    );
  }

  return (await response.json()) as DashboardSummaryResponse;
}

export async function getDashboardData(): Promise<DashboardData> {
  let summary: DashboardSummaryResponse;

  try {
    summary = await getDashboardSummary();
  } catch {
    return getEmptyDashboardData({
      error: "Dashboard summary could not be loaded. Refresh the page or try again later.",
    });
  }

  return {
    kpis: toKpis(summary),
    labelPerformance: {
      metrics: getLabelPerformanceMetrics(),
      ranges: [],
      unavailable: !(summary.availableSections ?? ["label-performance"]).includes(
        "label-performance",
      ),
    },
    releasePipeline: {
      stages:
        summary.releasePipeline &&
        (summary.availableSections ?? ["release-pipeline"]).includes("release-pipeline")
          ? toReleasePipelineStages(summary.releasePipeline)
          : [],
      unavailable: !(summary.availableSections ?? ["release-pipeline"]).includes(
        "release-pipeline",
      ),
    },
    recentActivity: {
      events: [],
      unavailable: !(summary.availableSections ?? ["member-activity"]).includes("member-activity"),
    },
  };
}
