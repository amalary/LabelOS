"use client";

import { Badge, Card, EmptyState, LoadingState, PageHeader, cn } from "@label-os/ui";
import { useMemo, useState } from "react";

import { can, capabilities } from "../../lib/authorization";
import {
  type MarketingContentItem,
  type MarketingContentListOptions,
  type MarketingContentItemStatus,
  useWorkspaceCalendarContent,
} from "../../lib/marketing-content";
import { useActiveWorkspace, useActiveWorkspaceProfile } from "../../lib/workspace-context";

type MarketingTab = "calendar" | "drafts" | "approvals" | "accounts";

const tabs: Array<{ id: MarketingTab; label: string; enabled: boolean }> = [
  { id: "calendar", label: "Calendar", enabled: true },
  { id: "drafts", label: "Drafts", enabled: false },
  { id: "approvals", label: "Approvals", enabled: false },
  { id: "accounts", label: "Accounts", enabled: false },
];

function monthRange(date: Date): { start: string; end: string } {
  const start = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1, 0, 0, 0));
  const end = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0, 23, 59, 59));
  return {
    start: start.toISOString(),
    end: end.toISOString(),
  };
}

function formatDateTime(value: string | null): string {
  if (!value) {
    return "Unscheduled";
  }
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function humanize(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function statusVariant(status: MarketingContentItemStatus) {
  if (status === "approved" || status === "scheduled" || status === "published") {
    return "success" as const;
  }
  if (status === "draft" || status === "in_review") {
    return "warning" as const;
  }
  return "neutral" as const;
}

function channelSummary(item: MarketingContentItem): string {
  if (item.channels.length === 0) {
    return "No channel";
  }
  return item.channels
    .map((channel) => [channel.channel, channel.placement].filter(Boolean).join(" / "))
    .join(", ");
}

function CalendarContentList({ items }: { items: MarketingContentItem[] }) {
  return (
    <Card className="overflow-hidden p-0">
      <div className="grid gap-1 border-b border-slate-200 bg-slate-50 px-4 py-3">
        <h2 className="text-base font-semibold text-slate-950">Calendar content</h2>
        <p className="text-sm text-slate-500">Scheduled content records for the selected range.</p>
      </div>
      <div className="divide-y divide-slate-100">
        {items.map((item) => (
          <article
            className="grid gap-3 px-4 py-4 md:grid-cols-[minmax(0,1fr)_180px_180px]"
            key={item.id}
          >
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="truncate text-sm font-semibold text-slate-950">{item.title}</h3>
                <Badge variant={statusVariant(item.status)}>{humanize(item.status)}</Badge>
              </div>
              <p className="mt-1 text-sm text-slate-500">
                {humanize(item.content_type)} - {channelSummary(item)}
              </p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">
                Scheduled
              </p>
              <p className="mt-1 text-sm font-medium text-slate-800">
                {formatDateTime(item.scheduled_at)}
              </p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">
                Campaign
              </p>
              <p className="mt-1 truncate text-sm font-medium text-slate-800">
                {item.campaign_id}
              </p>
            </div>
          </article>
        ))}
      </div>
    </Card>
  );
}

function UpcomingTab({ label }: { label: string }) {
  return (
    <EmptyState
      description={`${label} will be connected after the Marketing Hub calendar foundation is in place.`}
      title={`${label} upcoming`}
    />
  );
}

export function MarketingWorkspace() {
  const { activeWorkspace } = useActiveWorkspace();
  const workspaceProfile = useActiveWorkspaceProfile();
  const [activeTab, setActiveTab] = useState<MarketingTab>("calendar");
  const range = useMemo(() => monthRange(new Date()), []);
  const calendarOptions = useMemo<MarketingContentListOptions>(
    () => ({
      start: range.start,
      end: range.end,
      limit: 100,
      offset: 0,
    }),
    [range.end, range.start],
  );
  const calendarContent = useWorkspaceCalendarContent(activeWorkspace?.id ?? null, calendarOptions);
  const canView =
    workspaceProfile.subject && activeWorkspace
      ? can(workspaceProfile.subject, null, capabilities.marketingContentView)
      : false;
  const items = calendarContent.data?.marketing_content ?? [];

  if (!activeWorkspace) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900">
        Choose a workspace to view the Marketing Hub.
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
      <PageHeader
        description={`${activeWorkspace.name} content planning, approvals, and channel coordination.`}
        eyebrow="Phase 2 Marketing Hub"
        title="Marketing"
      />

      <nav aria-label="Marketing Hub sections" className="flex flex-wrap gap-2">
        {tabs.map((tab) => (
          <button
            aria-current={activeTab === tab.id ? "page" : undefined}
            className={cn(
              "rounded-md border px-3 py-2 text-sm font-medium transition",
              activeTab === tab.id
                ? "border-slate-950 bg-slate-950 text-white"
                : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50",
            )}
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            type="button"
          >
            <span>{tab.label}</span>
            {!tab.enabled ? (
              <>
                {" "}
                <span className="ml-2 text-xs font-normal opacity-75">Upcoming</span>
              </>
            ) : null}
          </button>
        ))}
      </nav>

      {!canView && !workspaceProfile.isLoading ? (
        <div
          className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
          role="status"
        >
          You need marketing content view access to open the Marketing Hub.
        </div>
      ) : null}

      {activeTab === "calendar" && canView ? (
        <section className="grid gap-4" aria-label="Marketing content calendar">
          {calendarContent.error ? (
            <div
              className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
              role="alert"
            >
              Marketing content could not be loaded.
            </div>
          ) : null}

          {calendarContent.isLoading && !calendarContent.data ? (
            <Card className="grid gap-3">
              <LoadingState label="Loading marketing calendar" />
              {Array.from({ length: 3 }, (_, index) => (
                <div className="h-16 rounded-md bg-slate-100 auth-shimmer" key={index} />
              ))}
            </Card>
          ) : items.length === 0 ? (
            <EmptyState
              description="Calendar content appears here after campaign content is scheduled."
              title="No scheduled content"
            />
          ) : (
            <CalendarContentList items={items} />
          )}
        </section>
      ) : null}

      {activeTab !== "calendar" ? (
        <UpcomingTab label={tabs.find((tab) => tab.id === activeTab)?.label ?? "Section"} />
      ) : null}
    </div>
  );
}
