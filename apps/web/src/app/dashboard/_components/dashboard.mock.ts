import type { DashboardData } from "./dashboard.types";
import { getMockLabelPerformanceData } from "./label-performance-data";

const baseDashboardMockData: Omit<DashboardData, "labelPerformance"> = {
  kpis: [
    {
      id: "active-artists",
      title: "Active Artists",
      primaryValue: "12",
      icon: "AR",
      trendValue: "9.1%",
      trendDirection: "positive",
      comparisonLabel: "from last month",
      description: "Roster with recent activity",
      href: "/dashboard/artists",
    },
    {
      id: "upcoming-releases",
      title: "Upcoming Releases",
      primaryValue: "14",
      icon: "UR",
      trendValue: "3",
      trendDirection: "positive",
      comparisonLabel: "added this week",
      description: "Scheduled in the next 90 days",
      href: "/releases",
    },
    {
      id: "active-campaigns",
      title: "Active Campaigns",
      primaryValue: "8",
      icon: "AC",
      trendValue: "0%",
      trendDirection: "neutral",
      comparisonLabel: "from last week",
      description: "Marketing campaigns currently in flight",
      href: "/dashboard/campaigns",
    },
    {
      id: "tasks-approvals",
      title: "Tasks / Approvals",
      primaryValue: "6",
      icon: "TA",
      trendValue: "2",
      trendDirection: "negative",
      comparisonLabel: "more awaiting review",
      description: "Open tasks requiring team approval",
      href: "/dashboard/tasks",
    },
  ],
  releasePipeline: {
    stages: [
      {
        status: "planning",
        label: "Planning",
        count: 6,
        href: "/releases?status=planning",
      },
      {
        status: "production",
        label: "Production",
        count: 4,
        href: "/releases?status=production",
      },
      {
        status: "distribution",
        label: "Distribution",
        count: 3,
        href: "/releases?status=distribution",
      },
      {
        status: "scheduled",
        label: "Scheduled",
        count: 1,
        href: "/releases?status=scheduled",
      },
      {
        status: "released",
        label: "Released",
        count: 18,
        href: "/releases?status=released",
      },
    ],
  },
  recentActivity: {
    events: [],
  },
};

export async function getDashboardMockData(): Promise<DashboardData> {
  const now = Date.now();

  return {
    ...baseDashboardMockData,
    labelPerformance: await getMockLabelPerformanceData(),
    recentActivity: {
      events: [
        {
          id: "activity-01",
          type: "artist.created",
          entityType: "artist",
          entityId: "artist_nova",
          payload: { name: "NOVA" },
          createdAt: new Date(now - 4 * 60000).toISOString(),
        },
        {
          id: "activity-02",
          type: "member.joined",
          entityType: "member",
          entityId: "member_sarah",
          actor: { displayName: "Sarah" },
          payload: { displayName: "Sarah" },
          createdAt: new Date(now - 32 * 60000).toISOString(),
        },
        {
          id: "activity-03",
          type: "organization.updated",
          entityType: "organization",
          entityId: "org_northstar",
          actor: { displayName: "Mara Chen" },
          payload: { organizationName: "Northstar Audio" },
          createdAt: new Date(now - 3 * 60 * 60000).toISOString(),
        },
        {
          id: "activity-04",
          type: "agent.completed",
          entityType: "ai_agent",
          entityId: "agent_release_brief",
          payload: { name: "Release brief agent" },
          createdAt: new Date(now - 26 * 60 * 60000).toISOString(),
        },
      ],
    },
  };
}
