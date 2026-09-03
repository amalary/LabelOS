"use client";

import { Badge, Button, Card, EmptyState, LoadingState, PageHeader, cn } from "@label-os/ui";
import Link from "next/link";
import { useMemo, useState } from "react";

import {
  AnalyticsReadSurface,
  type AnalyticsSelectedChildResource,
} from "../../../components/analytics/analytics-read-surface";
import { can, capabilities } from "../../../lib/authorization";
import {
  type Campaign,
  type CampaignGoal,
  type CampaignMilestone,
  useCampaign,
  useCampaignGoals,
  useCampaignMilestones,
} from "../../../lib/campaigns";
import {
  type MarketingContentItem,
  type MarketingContentItemStatus,
  useCampaignMarketingContent,
} from "../../../lib/marketing-content";
import { useOrganizationRealtimeContext } from "../../../lib/realtime/use-organization-realtime";
import { useActiveWorkspace, useActiveWorkspaceProfile } from "../../../lib/workspace-context";
import { mapActivityEvents } from "../../dashboard/_components/activity-event-map";

const futureSections = ["Assets", "Legal", "Budget", "Agents"];
const marketingSummaryStatuses: MarketingContentItemStatus[] = [
  "draft",
  "in_review",
  "approved",
  "scheduled",
  "published",
];

function humanize(value: string | null | undefined): string {
  if (!value) {
    return "Not set";
  }
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string | null): string {
  if (!value) {
    return "Not set";
  }
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric" }).format(
    new Date(`${value}T00:00:00`),
  );
}

function statusVariant(status: string) {
  if (status === "active" || status === "completed") {
    return "success" as const;
  }
  if (status === "planning" || status === "draft" || status === "open") {
    return "warning" as const;
  }
  return "neutral" as const;
}

function FieldValue({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">{label}</p>
      <p className="mt-1 text-sm font-medium text-slate-900">{value}</p>
    </div>
  );
}

function SectionHeader({ action, title }: { action?: React.ReactNode; title: string }) {
  return (
    <div className="flex flex-col gap-2 border-b border-slate-200 pb-3 sm:flex-row sm:items-center sm:justify-between">
      <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
      {action ? <div className="flex items-center gap-2">{action}</div> : null}
    </div>
  );
}

function OverviewSection({ campaign }: { campaign: Campaign }) {
  return (
    <Card>
      <SectionHeader title="Overview" />
      <div className="mt-4 grid gap-4 md:grid-cols-4">
        <FieldValue label="Type" value={humanize(campaign.campaign_type)} />
        <FieldValue label="Status" value={humanize(campaign.status)} />
        <FieldValue label="Start" value={formatDate(campaign.start_date)} />
        <FieldValue label="Target" value={formatDate(campaign.target_end_date)} />
      </div>
      <p className="mt-5 max-w-3xl whitespace-pre-line text-sm leading-6 text-slate-600">
        {campaign.description || "No overview notes have been added yet."}
      </p>
    </Card>
  );
}

function TeamSection({ campaign, canEdit }: { campaign: Campaign; canEdit: boolean }) {
  const members = campaign.members;

  return (
    <Card>
      <SectionHeader
        action={
          <Button disabled={!canEdit} size="sm" variant="secondary">
            Manage team
          </Button>
        }
        title="Team"
      />
      {!canEdit ? (
        <p className="mt-3 text-sm leading-6 text-slate-500">
          You can view this campaign, but changing team assignments requires campaign edit access.
        </p>
      ) : null}
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {members.length ? (
          members.map((member) => (
            <div
              className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3"
              key={member.workspace_membership_id}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-slate-950">
                    {member.display_name ?? "Unnamed teammate"}
                  </p>
                  <p className="mt-1 text-sm text-slate-500">
                    {member.responsibility_label ?? "No responsibility set"}
                  </p>
                </div>
                {member.is_owner ? <Badge>Owner</Badge> : null}
              </div>
              <p className="mt-3 text-xs font-medium uppercase tracking-normal text-slate-500">
                {humanize(member.participation_status)}
              </p>
            </div>
          ))
        ) : (
          <p className="text-sm leading-6 text-slate-500">No campaign team members are assigned.</p>
        )}
      </div>
    </Card>
  );
}

function GoalsSection({
  canEdit,
  goals,
  isLoading,
  milestones,
  onInspectAnalytics,
  selectedAnalyticsChild,
}: {
  canEdit: boolean;
  goals: CampaignGoal[];
  isLoading: boolean;
  milestones: CampaignMilestone[];
  onInspectAnalytics: (child: AnalyticsSelectedChildResource) => void;
  selectedAnalyticsChild: AnalyticsSelectedChildResource;
}) {
  const activeGoalCount = goals.filter((goal) => goal.status !== "archived").length;
  const completedMilestoneCount = milestones.filter(
    (milestone) => milestone.status === "completed",
  ).length;

  return (
    <Card>
      <SectionHeader
        action={
          <Button disabled={!canEdit} size="sm" variant="secondary">
            Add milestone
          </Button>
        }
        title="Goals / Milestones"
      />
      {isLoading && goals.length === 0 && milestones.length === 0 ? (
        <LoadingState className="mt-4" label="Loading planning data" />
      ) : null}
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3">
          <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">
            Active goals
          </p>
          <p className="mt-2 text-2xl font-semibold text-slate-950">{activeGoalCount}</p>
        </div>
        <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3">
          <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">
            Milestones
          </p>
          <p className="mt-2 text-2xl font-semibold text-slate-950">{milestones.length}</p>
        </div>
        <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3">
          <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">
            Completed
          </p>
          <p className="mt-2 text-2xl font-semibold text-slate-950">{completedMilestoneCount}</p>
        </div>
      </div>
      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="text-sm font-semibold text-slate-950">Goals</h3>
          <div className="mt-3 grid gap-2">
            {goals.length ? (
              goals.map((goal) => (
                <div
                  className="rounded-md border border-slate-200 bg-white px-3 py-3"
                  key={goal.id}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-slate-950">{goal.title}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <Badge variant={statusVariant(goal.status)}>{humanize(goal.status)}</Badge>
                        {selectedAnalyticsChild?.id === goal.id ? (
                          <Badge variant="neutral">Inspecting analytics</Badge>
                        ) : null}
                      </div>
                    </div>
                    <Button
                      onClick={() =>
                        onInspectAnalytics(
                          selectedAnalyticsChild?.id === goal.id
                            ? null
                            : { id: goal.id, label: goal.title, type: "goal" },
                        )
                      }
                      size="sm"
                      type="button"
                      variant="secondary"
                    >
                      Analytics
                    </Button>
                  </div>
                  {goal.target_value ? (
                    <p className="mt-1 text-sm text-slate-500">{goal.target_value}</p>
                  ) : null}
                </div>
              ))
            ) : (
              <p className="text-sm leading-6 text-slate-500">No goals have been defined yet.</p>
            )}
          </div>
        </div>
        <div>
          <h3 className="text-sm font-semibold text-slate-950">Milestones</h3>
          <div className="mt-3 grid gap-2">
            {milestones.length ? (
              milestones.map((milestone) => (
                <div
                  className="rounded-md border border-slate-200 bg-white px-3 py-3"
                  key={milestone.id}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-slate-950">{milestone.title}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <Badge variant={statusVariant(milestone.status)}>
                          {humanize(milestone.status)}
                        </Badge>
                        {selectedAnalyticsChild?.id === milestone.id ? (
                          <Badge variant="neutral">Inspecting analytics</Badge>
                        ) : null}
                      </div>
                    </div>
                    <Button
                      onClick={() =>
                        onInspectAnalytics(
                          selectedAnalyticsChild?.id === milestone.id
                            ? null
                            : {
                                id: milestone.id,
                                label: milestone.title,
                                type: "milestone",
                              },
                        )
                      }
                      size="sm"
                      type="button"
                      variant="secondary"
                    >
                      Analytics
                    </Button>
                  </div>
                  <p className="mt-1 text-sm text-slate-500">
                    Target: {formatDate(milestone.target_date)}
                  </p>
                </div>
              ))
            ) : (
              <p className="text-sm leading-6 text-slate-500">No milestones have been added yet.</p>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}

function ReleasesSection({ campaign }: { campaign: Campaign }) {
  const releaseLinks = campaign.releases;
  const primaryRelease = campaign.release;

  return (
    <Card>
      <SectionHeader title="Releases" />
      <div className="mt-4 grid gap-3">
        {primaryRelease ? (
          <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3">
            <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">
              Primary release
            </p>
            <p className="mt-1 text-sm font-semibold text-slate-950">{primaryRelease.title}</p>
          </div>
        ) : null}
        {releaseLinks.length ? (
          releaseLinks.map((link) => (
            <div
              className="flex flex-col gap-2 rounded-md border border-slate-200 bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
              key={`${link.release.id}-${link.relationship_kind}`}
            >
              <p className="text-sm font-semibold text-slate-950">{link.release.title}</p>
              <Badge>{humanize(link.relationship_kind)}</Badge>
            </div>
          ))
        ) : !primaryRelease ? (
          <p className="text-sm leading-6 text-slate-500">No releases are linked yet.</p>
        ) : null}
      </div>
    </Card>
  );
}

function ActivitySection({ campaign }: { campaign: Campaign }) {
  const realtime = useOrganizationRealtimeContext();
  const liveEvents = useMemo(
    () =>
      mapActivityEvents(
        (realtime?.recentActivityEvents ?? []).filter(
          (event) =>
            event.type.startsWith("campaign.") &&
            (event.entityId === campaign.id || event.payload?.campaignId === campaign.id),
        ),
      ),
    [campaign.id, realtime?.recentActivityEvents],
  );

  return (
    <Card>
      <SectionHeader title="Activity" />
      <div className="mt-4 grid gap-3">
        {liveEvents.map((event) => (
          <div className="rounded-md border border-slate-200 bg-white px-4 py-3" key={event.id}>
            <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <p className="text-sm font-semibold text-slate-950">{event.title}</p>
                <p className="mt-1 text-sm text-slate-500">{event.description}</p>
              </div>
              <p className="text-xs font-medium text-slate-500">{event.timestamp}</p>
            </div>
          </div>
        ))}
        <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3">
          <p className="text-sm font-semibold text-slate-950">Campaign updated</p>
          <p className="mt-1 text-sm text-slate-500">
            Last workspace update:{" "}
            {new Intl.DateTimeFormat("en", {
              month: "short",
              day: "numeric",
              year: "numeric",
            }).format(new Date(campaign.updated_at))}
          </p>
        </div>
        {liveEvents.length === 0 ? (
          <p className="text-sm leading-6 text-slate-500">No live campaign activity yet.</p>
        ) : null}
      </div>
    </Card>
  );
}

function marketingStatusCounts(items: MarketingContentItem[]) {
  return marketingSummaryStatuses.map((status) => ({
    count: items.filter((item) => item.status === status).length,
    status,
  }));
}

function MarketingSection({
  campaignId,
  items,
  isLoading,
  total,
}: {
  campaignId: string;
  items: MarketingContentItem[];
  isLoading: boolean;
  total: number | null;
}) {
  const counts = marketingStatusCounts(items);

  return (
    <Card>
      <SectionHeader
        action={
          <Link
            className="inline-flex h-9 items-center justify-center rounded-md border border-slate-300 bg-white px-3 text-sm font-medium text-slate-950 transition-colors hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-700"
            href={`/marketing?campaignId=${encodeURIComponent(campaignId)}`}
          >
            Open Marketing
          </Link>
        }
        title="Marketing"
      />
      {isLoading && total === null ? (
        <LoadingState className="mt-4" label="Loading marketing content" />
      ) : (
        <div className="mt-4 grid gap-3">
          <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3">
            <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">
              Content items
            </p>
            <p className="mt-2 text-2xl font-semibold text-slate-950">{total ?? items.length}</p>
          </div>
          {items.length ? (
            <div className="grid grid-cols-2 gap-2">
              {counts.map(({ count, status }) => (
                <div className="rounded-md border border-slate-200 bg-white px-3 py-2" key={status}>
                  <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">
                    {humanize(status)}
                  </p>
                  <p className="mt-1 text-lg font-semibold text-slate-950">{count}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm leading-6 text-slate-500">
              No marketing content is linked to this campaign yet.
            </p>
          )}
        </div>
      )}
    </Card>
  );
}

function FutureAttachmentPoints() {
  return (
    <Card>
      <SectionHeader title="Future Sections" />
      <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {futureSections.map((section) => (
          <button
            aria-disabled="true"
            className="flex h-12 items-center justify-between rounded-md border border-dashed border-slate-300 bg-slate-50 px-3 text-left text-sm font-medium text-slate-500"
            disabled
            key={section}
            type="button"
          >
            <span>{section}</span>
            <span className="text-xs uppercase tracking-normal">Later</span>
          </button>
        ))}
      </div>
    </Card>
  );
}

export function CampaignDetailWorkspace({ campaignId }: { campaignId: string }) {
  const { activeWorkspace } = useActiveWorkspace();
  const workspaceProfile = useActiveWorkspaceProfile();
  const campaign = useCampaign(activeWorkspace?.id ?? null, campaignId);
  const goals = useCampaignGoals(activeWorkspace?.id ?? null, campaignId);
  const milestones = useCampaignMilestones(activeWorkspace?.id ?? null, campaignId);
  const marketingContent = useCampaignMarketingContent(activeWorkspace?.id ?? null, campaignId, {
    limit: 500,
    offset: 0,
  });
  const canEdit = workspaceProfile.subject
    ? can(workspaceProfile.subject, null, capabilities.marketingCampaignEdit)
    : false;
  const canView = workspaceProfile.subject
    ? can(workspaceProfile.subject, null, capabilities.marketingCampaignView)
    : false;
  const planningError = goals.error || milestones.error;
  const planningIsLoading = goals.isLoading || milestones.isLoading;
  const [selectedAnalyticsChild, setSelectedAnalyticsChild] =
    useState<AnalyticsSelectedChildResource>(null);
  const planningData = useMemo(
    () => ({
      goals: goals.data?.goals ?? [],
      milestones: milestones.data?.milestones ?? [],
    }),
    [goals.data, milestones.data],
  );
  const analyticsChildResources = useMemo(
    () => [
      ...planningData.goals.map((goal) => ({
        id: goal.id,
        label: goal.title,
        type: "goal" as const,
      })),
      ...planningData.milestones.map((milestone) => ({
        id: milestone.id,
        label: milestone.title,
        type: "milestone" as const,
      })),
    ],
    [planningData.goals, planningData.milestones],
  );

  if (!activeWorkspace) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900">
        Choose a workspace to view this campaign.
      </div>
    );
  }

  if (campaign.isLoading && !campaign.data) {
    return (
      <div className="mx-auto grid w-full max-w-7xl gap-4">
        <div className="h-28 rounded-md border border-slate-200 bg-white auth-shimmer" />
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="h-72 rounded-md border border-slate-200 bg-white auth-shimmer" />
          <div className="h-72 rounded-md border border-slate-200 bg-white auth-shimmer" />
        </div>
      </div>
    );
  }

  if (!canView && !workspaceProfile.isLoading) {
    return (
      <EmptyState
        action={
          <Link
            className="inline-flex h-9 items-center justify-center rounded-md border border-slate-300 bg-white px-3 text-sm font-medium text-slate-950"
            href="/campaigns"
          >
            Back to campaigns
          </Link>
        }
        description="Campaign view access is required for this workspace."
        title="Campaign unavailable"
      />
    );
  }

  if (campaign.error || !campaign.data) {
    return (
      <div className="mx-auto max-w-3xl rounded-md border border-red-200 bg-red-50 p-5 text-sm leading-6 text-red-900">
        Campaign data could not be loaded.
      </div>
    );
  }

  const detail = campaign.data;

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
      <PageHeader
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Link
              className="inline-flex h-9 items-center justify-center rounded-md border border-slate-300 bg-white px-3 text-sm font-medium text-slate-950 transition-colors hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-700"
              href="/campaigns"
            >
              Back
            </Link>
            <Button disabled={!canEdit} size="sm" variant="secondary">
              Edit campaign
            </Button>
          </div>
        }
        description={detail.primary_artist?.name ?? activeWorkspace.name}
        eyebrow="Campaign"
        title={detail.name}
      />

      {!canEdit ? (
        <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
          View-only mode. Editing this campaign requires campaign edit access.
        </div>
      ) : null}
      {planningError ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Planning data could not be loaded. Core campaign details are still available.
        </div>
      ) : null}

      <div className={cn("grid gap-5", campaign.isLoading ? "opacity-80" : "")}>
        <OverviewSection campaign={detail} />
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="grid gap-5">
            <GoalsSection
              canEdit={canEdit}
              goals={planningData.goals}
              isLoading={planningIsLoading}
              milestones={planningData.milestones}
              onInspectAnalytics={setSelectedAnalyticsChild}
              selectedAnalyticsChild={selectedAnalyticsChild}
            />
            <AnalyticsReadSurface
              campaignId={detail.id}
              childResources={analyticsChildResources}
              selectedChild={selectedAnalyticsChild}
              title="Campaign analytics"
              workspaceId={activeWorkspace.id}
            />
            <ReleasesSection campaign={detail} />
            <ActivitySection campaign={detail} />
          </div>
          <div className="grid content-start gap-5">
            <TeamSection campaign={detail} canEdit={canEdit} />
            <MarketingSection
              campaignId={detail.id}
              isLoading={marketingContent.isLoading}
              items={marketingContent.data?.marketing_content ?? []}
              total={marketingContent.data?.total ?? null}
            />
            <FutureAttachmentPoints />
          </div>
        </div>
      </div>
    </div>
  );
}
