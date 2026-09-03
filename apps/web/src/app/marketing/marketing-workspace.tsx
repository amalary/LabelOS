"use client";

import { Badge, Button, Card, EmptyState, LoadingState, PageHeader, cn } from "@label-os/ui";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { can, capabilities } from "../../lib/authorization";
import { type Campaign, useCampaigns } from "../../lib/campaigns";
import {
  type MarketingContentItem,
  type MarketingContentItemStatus,
  type MarketingContentListOptions,
  useWorkspaceCalendarContent,
} from "../../lib/marketing-content";
import { useActiveWorkspace, useActiveWorkspaceProfile } from "../../lib/workspace-context";

type MarketingTab = "calendar" | "drafts" | "approvals" | "accounts";
type CalendarView = "month" | "list";

type CalendarDay = {
  dateKey: string;
  day: number;
  inMonth: boolean;
  isToday: boolean;
  rangeDate: Date;
};

export type MarketingScheduleInstance = {
  item: MarketingContentItem;
  scheduledAt: string | null;
  dateKey: string | null;
  hasMultipleChannelTimes: boolean;
};

const tabs: Array<{ id: MarketingTab; label: string; enabled: boolean }> = [
  { id: "calendar", label: "Calendar", enabled: true },
  { id: "drafts", label: "Drafts", enabled: false },
  { id: "approvals", label: "Approvals", enabled: false },
  { id: "accounts", label: "Accounts", enabled: false },
];

const statuses: MarketingContentItemStatus[] = [
  "draft",
  "in_review",
  "approved",
  "scheduled",
  "published",
  "cancelled",
  "archived",
];

const channelOptions = ["instagram", "tiktok", "youtube", "spotify", "email", "x", "facebook"];
const weekdayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const planningFallbackTimeZone = "UTC";

function humanize(value: string | null | undefined): string {
  if (!value) {
    return "Not set";
  }
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function datePartsInTimeZone(value: Date, timeZone: string) {
  const parts = new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    hour: "2-digit",
    hour12: false,
    minute: "2-digit",
    month: "2-digit",
    second: "2-digit",
    timeZone,
    year: "numeric",
  }).formatToParts(value);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((entry) => entry.type === type)?.value ?? 0);
  const hour = part("hour");
  return {
    year: part("year"),
    month: part("month"),
    day: part("day"),
    hour: hour === 24 ? 0 : hour,
    minute: part("minute"),
    second: part("second"),
  };
}

function zonedDateTimeToUtc(
  year: number,
  monthIndex: number,
  day: number,
  hour: number,
  minute: number,
  second: number,
  timeZone: string,
): Date {
  const utcGuess = new Date(Date.UTC(year, monthIndex, day, hour, minute, second));
  const actualParts = datePartsInTimeZone(utcGuess, timeZone);
  const desiredAsUtc = Date.UTC(year, monthIndex, day, hour, minute, second);
  const actualAsUtc = Date.UTC(
    actualParts.year,
    actualParts.month - 1,
    actualParts.day,
    actualParts.hour,
    actualParts.minute,
    actualParts.second,
  );
  return new Date(utcGuess.getTime() + desiredAsUtc - actualAsUtc);
}

export function calendarVisibleRange(monthDate: Date, timeZone = planningFallbackTimeZone) {
  const year = monthDate.getUTCFullYear();
  const month = monthDate.getUTCMonth();
  const firstOfMonth = new Date(Date.UTC(year, month, 1));
  const lastOfMonth = new Date(Date.UTC(year, month + 1, 0));
  const gridStart = new Date(firstOfMonth);
  gridStart.setUTCDate(firstOfMonth.getUTCDate() - firstOfMonth.getUTCDay());
  const gridEnd = new Date(lastOfMonth);
  gridEnd.setUTCDate(lastOfMonth.getUTCDate() + (6 - lastOfMonth.getUTCDay()));
  return {
    end: zonedDateTimeToUtc(
      gridEnd.getUTCFullYear(),
      gridEnd.getUTCMonth(),
      gridEnd.getUTCDate(),
      23,
      59,
      59,
      timeZone,
    ).toISOString(),
    gridEnd,
    gridStart,
    start: zonedDateTimeToUtc(
      gridStart.getUTCFullYear(),
      gridStart.getUTCMonth(),
      gridStart.getUTCDate(),
      0,
      0,
      0,
      timeZone,
    ).toISOString(),
  };
}

function dateKeyFromDate(value: Date): string {
  return value.toISOString().slice(0, 10);
}

function dateKeyInTimeZone(value: string, timeZone: string): string {
  const parts = datePartsInTimeZone(new Date(value), timeZone);
  return `${parts.year}-${String(parts.month).padStart(2, "0")}-${String(parts.day).padStart(
    2,
    "0",
  )}`;
}

function isWithinRange(value: string, rangeStart: string, rangeEnd: string): boolean {
  const time = new Date(value).getTime();
  return time >= new Date(rangeStart).getTime() && time <= new Date(rangeEnd).getTime();
}

function uniqueScheduledValues(item: MarketingContentItem): string[] {
  return [
    ...new Set(
      item.channels
        .map((channel) => channel.scheduled_at)
        .filter((scheduledAt): scheduledAt is string => Boolean(scheduledAt)),
    ),
  ].sort();
}

export function toScheduleInstance(
  item: MarketingContentItem,
  rangeStart: string,
  rangeEnd: string,
  timeZone = planningFallbackTimeZone,
): MarketingScheduleInstance {
  // Canonical display date: parent scheduled_at first; otherwise earliest channel date relevant
  // to the visible range, falling back to the earliest channel date overall.
  const channelDates = uniqueScheduledValues(item);
  const relevantChannelDate =
    channelDates.find((scheduledAt) => isWithinRange(scheduledAt, rangeStart, rangeEnd)) ?? null;
  const scheduledAt = item.scheduled_at ?? relevantChannelDate ?? channelDates[0] ?? null;
  return {
    dateKey: scheduledAt ? dateKeyInTimeZone(scheduledAt, timeZone) : null,
    hasMultipleChannelTimes: channelDates.length > 1,
    item,
    scheduledAt,
  };
}

export function toScheduleInstances(
  items: MarketingContentItem[],
  rangeStart: string,
  rangeEnd: string,
  timeZone = planningFallbackTimeZone,
): MarketingScheduleInstance[] {
  return items
    .map((item) => toScheduleInstance(item, rangeStart, rangeEnd, timeZone))
    .sort((left, right) => {
      const leftTime = left.scheduledAt ? new Date(left.scheduledAt).getTime() : Infinity;
      const rightTime = right.scheduledAt ? new Date(right.scheduledAt).getTime() : Infinity;
      return leftTime - rightTime || left.item.title.localeCompare(right.item.title);
    });
}

function monthDays(monthDate: Date, timeZone: string): CalendarDay[] {
  const range = calendarVisibleRange(monthDate, timeZone);
  const days: CalendarDay[] = [];
  const todayKey = dateKeyInTimeZone(new Date().toISOString(), timeZone);
  const cursor = new Date(range.gridStart);
  while (cursor <= range.gridEnd) {
    const rangeDate = new Date(cursor);
    const dateKey = dateKeyFromDate(rangeDate);
    days.push({
      dateKey,
      day: rangeDate.getUTCDate(),
      inMonth: rangeDate.getUTCMonth() === monthDate.getUTCMonth(),
      isToday: dateKey === todayKey,
      rangeDate,
    });
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return days;
}

function formatMonthTitle(value: Date): string {
  return new Intl.DateTimeFormat("en", { month: "long", timeZone: "UTC", year: "numeric" }).format(
    value,
  );
}

function currentMonthDate(timeZone: string): Date {
  const nowParts = datePartsInTimeZone(new Date(), timeZone);
  return new Date(Date.UTC(nowParts.year, nowParts.month - 1, 1));
}

function formatDateTime(value: string | null, timeZone: string): string {
  if (!value) {
    return "Unscheduled";
  }
  return new Intl.DateTimeFormat("en", {
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    month: "short",
    timeZone,
    timeZoneName: "short",
  }).format(new Date(value));
}

function formatListDate(value: string | null, timeZone: string): string {
  if (!value) {
    return "Unscheduled";
  }
  return new Intl.DateTimeFormat("en", {
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    month: "short",
    timeZone,
    weekday: "short",
    year: "numeric",
  }).format(new Date(value));
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

function channelNames(item: MarketingContentItem): string[] {
  return [...new Set(item.channels.map((channel) => channel.channel))].sort();
}

function channelSummary(item: MarketingContentItem): string {
  const channels = channelNames(item);
  return channels.length ? channels.map(humanize).join(" • ") : "No channel";
}

function campaignName(campaigns: Campaign[], campaignId: string): string {
  return campaigns.find((campaign) => campaign.id === campaignId)?.name ?? campaignId;
}

function relationshipLabel(value: string | null): string {
  return value ? value : "Not linked";
}

function filtersActive(filters: CalendarFilters): boolean {
  return Object.values(filters).some((value) => value.trim().length > 0);
}

type CalendarFilters = {
  artistId: string;
  campaignId: string;
  channel: string;
  releaseId: string;
  status: string;
};

function Filters({
  campaigns,
  filters,
  isLoadingCampaigns,
  onChange,
  onReset,
}: {
  campaigns: Campaign[];
  filters: CalendarFilters;
  isLoadingCampaigns: boolean;
  onChange: (next: Partial<CalendarFilters>) => void;
  onReset: () => void;
}) {
  return (
    <Card className="grid gap-3 p-4">
      <div className="grid gap-3 md:grid-cols-5">
        <label className="grid gap-1 text-sm font-medium text-slate-700">
          <span>Campaign</span>
          <select
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            onChange={(event) => onChange({ campaignId: event.target.value })}
            value={filters.campaignId}
          >
            <option value="">All campaigns</option>
            {campaigns.map((campaign) => (
              <option key={campaign.id} value={campaign.id}>
                {campaign.name}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700">
          <span>Status</span>
          <select
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            onChange={(event) => onChange({ status: event.target.value })}
            value={filters.status}
          >
            <option value="">Any status</option>
            {statuses.map((status) => (
              <option key={status} value={status}>
                {humanize(status)}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700">
          <span>Channel</span>
          <select
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            onChange={(event) => onChange({ channel: event.target.value })}
            value={filters.channel}
          >
            <option value="">Any channel</option>
            {channelOptions.map((channel) => (
              <option key={channel} value={channel}>
                {humanize(channel)}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700">
          <span>Artist</span>
          <input
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            onChange={(event) => onChange({ artistId: event.target.value })}
            placeholder="Artist ID"
            value={filters.artistId}
          />
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700">
          <span>Release</span>
          <input
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            onChange={(event) => onChange({ releaseId: event.target.value })}
            placeholder="Release ID"
            value={filters.releaseId}
          />
        </label>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-slate-500">
          Filters are sent to the marketing content API. Artist and release selectors use IDs until
          relationship lookup endpoints are exposed here.
        </p>
        <Button
          disabled={!filtersActive(filters) || isLoadingCampaigns}
          onClick={onReset}
          size="sm"
          type="button"
          variant="secondary"
        >
          Reset filters
        </Button>
      </div>
    </Card>
  );
}

function MonthCalendar({
  campaigns,
  days,
  instancesByDay,
  onEmptyDayClick,
  timeZone,
}: {
  campaigns: Campaign[];
  days: CalendarDay[];
  instancesByDay: Map<string, MarketingScheduleInstance[]>;
  onEmptyDayClick: (dateKey: string) => void;
  timeZone: string;
}) {
  return (
    <Card className="overflow-hidden p-0">
      <div className="grid grid-cols-7 border-b border-slate-200 bg-slate-50">
        {weekdayLabels.map((weekday) => (
          <div className="px-2 py-2 text-xs font-semibold uppercase text-slate-500" key={weekday}>
            {weekday}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7">
        {days.map((day) => {
          const dayItems = instancesByDay.get(day.dateKey) ?? [];
          return (
            <div
              className={cn(
                "min-h-32 border-b border-r border-slate-200 bg-white p-2",
                !day.inMonth && "bg-slate-50 text-slate-400",
              )}
              key={day.dateKey}
            >
              <button
                aria-label={`Create content on ${day.dateKey}`}
                className="mb-2 flex w-full items-center justify-between rounded-md px-1 py-0.5 text-left text-xs font-medium text-slate-500 hover:bg-slate-100"
                onClick={() => onEmptyDayClick(day.dateKey)}
                type="button"
              >
                <span
                  className={cn(
                    "inline-flex h-6 w-6 items-center justify-center rounded-full",
                    day.isToday && "bg-slate-950 text-white",
                  )}
                >
                  {day.day}
                </span>
                {day.isToday ? <span>Today</span> : null}
              </button>
              <div className="grid gap-1">
                {dayItems.slice(0, 3).map((instance) => (
                  <Link
                    className="grid gap-1 rounded-md border border-slate-200 bg-slate-50 px-2 py-1.5 text-left transition hover:border-slate-400 hover:bg-white"
                    href={`/campaigns/${instance.item.campaign_id}?contentId=${instance.item.id}`}
                    key={instance.item.id}
                  >
                    <span className="truncate text-xs font-semibold text-slate-950">
                      {instance.item.title}
                    </span>
                    <span className="truncate text-xs text-slate-500">
                      {channelSummary(instance.item)}
                    </span>
                    <span className="flex flex-wrap items-center gap-1">
                      <Badge className="max-w-full truncate" variant={statusVariant(instance.item.status)}>
                        {humanize(instance.item.status)}
                      </Badge>
                      {instance.hasMultipleChannelTimes ? (
                        <Badge title={formatDateTime(instance.scheduledAt, timeZone)}>
                          Multi-time
                        </Badge>
                      ) : null}
                    </span>
                    <span className="truncate text-xs text-slate-500">
                      {campaignName(campaigns, instance.item.campaign_id)}
                    </span>
                  </Link>
                ))}
                {dayItems.length > 3 ? (
                  <span className="text-xs font-medium text-slate-500">
                    +{dayItems.length - 3} more
                  </span>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function CalendarList({
  campaigns,
  instances,
  timeZone,
}: {
  campaigns: Campaign[];
  instances: MarketingScheduleInstance[];
  timeZone: string;
}) {
  return (
    <Card className="overflow-hidden p-0">
      <div className="grid gap-1 border-b border-slate-200 bg-slate-50 px-4 py-3">
        <h2 className="text-base font-semibold text-slate-950">Chronological content</h2>
        <p className="text-sm text-slate-500">
          Planned date uses the parent schedule first, then the earliest relevant channel schedule.
        </p>
      </div>
      <div className="divide-y divide-slate-100">
        {instances.map((instance) => (
          <Link
            className="grid gap-3 px-4 py-4 transition hover:bg-slate-50 md:grid-cols-[190px_minmax(0,1fr)_170px_170px]"
            href={`/campaigns/${instance.item.campaign_id}?contentId=${instance.item.id}`}
            key={instance.item.id}
          >
            <div>
              <p className="text-xs font-semibold uppercase text-slate-500">Planned</p>
              <p className="mt-1 text-sm font-medium text-slate-900">
                {formatListDate(instance.scheduledAt, timeZone)}
              </p>
              {instance.hasMultipleChannelTimes ? (
                <p className="mt-1 text-xs text-slate-500">Multiple channel times</p>
              ) : null}
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="truncate text-sm font-semibold text-slate-950">
                  {instance.item.title}
                </h3>
                <Badge variant={statusVariant(instance.item.status)}>
                  {humanize(instance.item.status)}
                </Badge>
              </div>
              <p className="mt-1 text-sm text-slate-500">
                {humanize(instance.item.content_type)} - {channelSummary(instance.item)}
              </p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase text-slate-500">Campaign</p>
              <p className="mt-1 truncate text-sm font-medium text-slate-800">
                {campaignName(campaigns, instance.item.campaign_id)}
              </p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase text-slate-500">Artist / Release</p>
              <p className="mt-1 truncate text-sm font-medium text-slate-800">
                {relationshipLabel(instance.item.artist_id)}
              </p>
              <p className="truncate text-xs text-slate-500">
                {relationshipLabel(instance.item.release_id)}
              </p>
            </div>
          </Link>
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
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { activeWorkspace } = useActiveWorkspace();
  const workspaceProfile = useActiveWorkspaceProfile();
  const [activeTab, setActiveTab] = useState<MarketingTab>("calendar");
  const [view, setView] = useState<CalendarView>("month");
  const initialCampaignId = searchParams.get("campaignId") ?? "";
  const timeZone =
    workspaceProfile.membership?.profile.preferences.timezone ??
    workspaceProfile.membership?.profile.timezone ??
    planningFallbackTimeZone;
  const [filters, setFilters] = useState<CalendarFilters>({
    artistId: "",
    campaignId: initialCampaignId,
    channel: "",
    releaseId: "",
    status: "",
  });
  const [monthDate, setMonthDate] = useState(() => currentMonthDate(timeZone));
  const range = useMemo(() => calendarVisibleRange(monthDate, timeZone), [monthDate, timeZone]);
  const campaigns = useCampaigns(activeWorkspace?.id ?? null, { limit: 500, offset: 0 });
  const canView =
    workspaceProfile.subject && activeWorkspace
      ? can(workspaceProfile.subject, null, capabilities.marketingContentView)
      : false;
  const calendarOptions = useMemo<MarketingContentListOptions>(
    () => ({
      artist_id: filters.artistId.trim() || null,
      campaign_id: filters.campaignId || null,
      channel: filters.channel || null,
      end: range.end,
      limit: 500,
      offset: 0,
      release_id: filters.releaseId.trim() || null,
      start: range.start,
      status: (filters.status || null) as MarketingContentItemStatus | null,
    }),
    [filters.artistId, filters.campaignId, filters.channel, filters.releaseId, filters.status, range],
  );
  const calendarContent = useWorkspaceCalendarContent(activeWorkspace?.id ?? null, calendarOptions);
  const items = calendarContent.data?.marketing_content ?? [];
  const scheduleInstances = useMemo(
    () => toScheduleInstances(items, range.start, range.end, timeZone),
    [items, range.end, range.start, timeZone],
  );
  const currentMonthDays = useMemo(() => monthDays(monthDate, timeZone), [monthDate, timeZone]);
  const instancesByDay = useMemo(() => {
    const grouped = new Map<string, MarketingScheduleInstance[]>();
    for (const instance of scheduleInstances) {
      if (!instance.dateKey) {
        continue;
      }
      grouped.set(instance.dateKey, [...(grouped.get(instance.dateKey) ?? []), instance]);
    }
    return grouped;
  }, [scheduleInstances]);

  const updateUrl = useCallback(
    (nextFilters: CalendarFilters, createDate?: string) => {
      const next = new URLSearchParams(searchParams.toString());
      if (nextFilters.campaignId) {
        next.set("campaignId", nextFilters.campaignId);
      } else {
        next.delete("campaignId");
      }
      if (createDate) {
        next.set("createDate", createDate);
      } else {
        next.delete("createDate");
      }
      const query = next.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  const updateFilters = useCallback(
    (next: Partial<CalendarFilters>) => {
      setFilters((current) => {
        const merged = { ...current, ...next };
        updateUrl(merged);
        return merged;
      });
    },
    [updateUrl],
  );

  const resetFilters = useCallback(() => {
    const next = { artistId: "", campaignId: "", channel: "", releaseId: "", status: "" };
    setFilters(next);
    updateUrl(next);
  }, [updateUrl]);

  const moveMonth = useCallback((amount: number) => {
    setMonthDate(
      (current) => new Date(Date.UTC(current.getUTCFullYear(), current.getUTCMonth() + amount, 1)),
    );
  }, []);

  const showNoResults = items.length === 0 && filtersActive(filters);
  const campaignList = campaigns.data?.campaigns ?? [];

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
          <div className="flex flex-col gap-3 rounded-md border border-slate-200 bg-white p-4 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-950">{formatMonthTitle(monthDate)}</h2>
              <p className="text-sm text-slate-500">
                Showing {formatDateTime(range.start, timeZone)} through{" "}
                {formatDateTime(range.end, timeZone)}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={() => moveMonth(-1)} size="sm" type="button" variant="secondary">
                Previous
              </Button>
              <Button
                onClick={() => {
                  setMonthDate(currentMonthDate(timeZone));
                }}
                size="sm"
                type="button"
                variant="secondary"
              >
                Today
              </Button>
              <Button onClick={() => moveMonth(1)} size="sm" type="button" variant="secondary">
                Next
              </Button>
              <div className="ml-0 flex rounded-md border border-slate-300 p-0.5 md:ml-2">
                <button
                  aria-pressed={view === "month"}
                  className={cn(
                    "h-8 rounded px-3 text-sm font-medium",
                    view === "month" ? "bg-slate-950 text-white" : "text-slate-700",
                  )}
                  onClick={() => setView("month")}
                  type="button"
                >
                  Month
                </button>
                <button
                  aria-pressed={view === "list"}
                  className={cn(
                    "h-8 rounded px-3 text-sm font-medium",
                    view === "list" ? "bg-slate-950 text-white" : "text-slate-700",
                  )}
                  onClick={() => setView("list")}
                  type="button"
                >
                  List
                </button>
              </div>
            </div>
          </div>

          <Filters
            campaigns={campaignList}
            filters={filters}
            isLoadingCampaigns={campaigns.isLoading}
            onChange={updateFilters}
            onReset={resetFilters}
          />

          {calendarContent.error ? (
            <div
              className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
              role="alert"
            >
              {calendarContent.error.code === "forbidden"
                ? "Marketing content access was denied for these filters."
                : "Marketing content could not be loaded."}
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
              description={
                showNoResults
                  ? "Try changing the campaign, status, channel, artist, release, or month."
                  : "Calendar content appears here after campaign content is scheduled."
              }
              title={showNoResults ? "No content matches these filters" : "No scheduled content"}
            />
          ) : view === "month" ? (
            <MonthCalendar
              campaigns={campaignList}
              days={currentMonthDays}
              instancesByDay={instancesByDay}
              onEmptyDayClick={(dateKey) => updateUrl(filters, dateKey)}
              timeZone={timeZone}
            />
          ) : (
            <CalendarList campaigns={campaignList} instances={scheduleInstances} timeZone={timeZone} />
          )}
        </section>
      ) : null}

      {activeTab !== "calendar" ? (
        <UpcomingTab label={tabs.find((tab) => tab.id === activeTab)?.label ?? "Section"} />
      ) : null}
    </div>
  );
}
