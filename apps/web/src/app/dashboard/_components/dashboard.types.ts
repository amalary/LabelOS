import type { ReactNode } from "react";

export type DashboardKpiTrendDirection = "positive" | "negative" | "neutral";

export type DashboardKpi = {
  id: string;
  title: string;
  primaryValue: string;
  icon: ReactNode;
  trendValue?: string;
  trendDirection?: DashboardKpiTrendDirection;
  comparisonLabel?: string;
  description?: string;
  href?: string;
  actionLabel?: string;
  loading?: boolean;
  empty?: boolean;
  error?: string;
};

export type LabelPerformanceMetricId =
  "streams" | "listeners" | "followers" | "revenue" | "engagement";

export type LabelPerformanceTimeRange = "7D" | "30D" | "90D" | "1Y";
export type LabelPerformanceApiPeriod = "7d" | "30d" | "90d" | "1y";

export type LabelPerformanceMetricConfig = {
  id: LabelPerformanceMetricId;
  label: string;
  unit: "count" | "currency" | "percent";
};

export type LabelPerformancePoint = {
  label: string;
  date: string;
  value: number;
};

export type LabelPerformanceSeriesPoint = {
  label: string;
  date: string;
  values: Record<LabelPerformanceMetricId, number>;
};

export type LabelPerformanceRangeSeries = {
  range: LabelPerformanceTimeRange;
  points: LabelPerformanceSeriesPoint[];
};

export type LabelPerformanceData = {
  metrics: LabelPerformanceMetricConfig[];
  ranges: LabelPerformanceRangeSeries[];
  source?: string;
  isMock?: boolean;
  loading?: boolean;
  error?: string;
};

export type LabelPerformanceApiPoint = {
  date: string;
  value: number;
};

export type LabelPerformanceApiSeries = {
  metric: LabelPerformanceMetricId;
  period: LabelPerformanceApiPeriod;
  total: number;
  changePercent: number;
  series: LabelPerformanceApiPoint[];
  source: string;
  isMock: boolean;
};

export type ReleaseLifecycleStatus =
  "planning" | "production" | "distribution" | "scheduled" | "released";

export type ReleasePipelineStage = {
  status: ReleaseLifecycleStatus;
  label: string;
  count: number;
  href: string;
};

export type ReleasePipelineData = {
  stages: ReleasePipelineStage[];
  loading?: boolean;
  error?: string;
  emptyOrganization?: boolean;
};

export type ActivityEventType =
  | "organization.created"
  | "organization.updated"
  | "organization.switched"
  | "member.invited"
  | "member.joined"
  | "member.role_changed"
  | "member.removed"
  | "artist.created"
  | "artist.updated"
  | "artist.status_changed"
  | "release.updated"
  | "campaign.updated"
  | "approval.updated"
  | "agent.started"
  | "agent.completed"
  | "agent.failed"
  | (string & {});

export type ActivityEventActor = {
  userId?: string;
  displayName?: string | null;
};

export type ActivityEventPayload = Record<string, string | number | boolean | null | undefined>;

export type ActivityEvent = {
  id: string;
  type: ActivityEventType;
  createdAt: string;
  actor?: ActivityEventActor | null;
  entityType?: string | null;
  entityId?: string | null;
  payload?: ActivityEventPayload;
};

export type RecentActivityData = {
  events: ActivityEvent[];
  loading?: boolean;
  error?: string;
};

export type DashboardData = {
  kpis: DashboardKpi[];
  labelPerformance: LabelPerformanceData;
  releasePipeline: ReleasePipelineData;
  recentActivity: RecentActivityData;
};
