"use client";

import { Badge, Button, Card, EmptyState, LoadingState, PageHeader, cn } from "@label-os/ui";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { can, capabilities } from "../../lib/authorization";
import {
  type CampaignCalendarEvent,
  type CampaignCalendarEventType,
  type CampaignCalendarQueryOptions,
  useCampaignCalendar,
} from "../../lib/campaign-calendar";
import { type Campaign, useCampaigns } from "../../lib/campaigns";
import {
  addCalendarMonths,
  calendarVisibleRange,
  currentCalendarMonthDate,
  dateKeyInTimeZone,
  formatCalendarDateTime,
  formatCalendarListDate,
  formatCalendarMonthTitle,
  monthDays,
  type CalendarDay,
} from "../../lib/calendar-dates";
import { useActiveWorkspace, useActiveWorkspaceProfile } from "../../lib/workspace-context";

type CalendarView = "month" | "list";

type CalendarFilters = {
  artistId: string;
  campaignId: string;
  eventType: string;
  includeArchived: boolean;
  includePublished: boolean;
  releaseId: string;
  status: string;
};

const weekdayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const maxVisibleDayEvents = 4;

const eventTypeOptions: Array<{ label: string; value: CampaignCalendarEventType }> = [
  { label: "Campaign start", value: "campaign.start" },
  { label: "Campaign target end", value: "campaign.target_end" },
  { label: "Milestone target", value: "campaign.milestone.target" },
  { label: "Scheduled content", value: "marketing.content.scheduled" },
  { label: "Channel schedule", value: "marketing.content.channel_scheduled" },
  { label: "Published content", value: "marketing.content.published" },
  { label: "Channel published", value: "marketing.content.channel_published" },
  { label: "Approval requested", value: "marketing.content.approval_requested" },
  { label: "Approval completed", value: "marketing.content.approved" },
];

const statusOptions = [
  "active",
  "planning",
  "completed",
  "draft",
  "in_review",
  "approved",
  "scheduled",
  "published",
  "changes_requested",
  "cancelled",
  "rejected",
  "archived",
];

function humanize(value: string | null | undefined): string {
  if (!value) {
    return "Not set";
  }
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function filtersActive(filters: CalendarFilters): boolean {
  return (
    Boolean(filters.artistId || filters.campaignId || filters.eventType || filters.releaseId) ||
    Boolean(filters.status) ||
    filters.includeArchived ||
    filters.includePublished
  );
}

function eventTypeLabel(eventType: string): string {
  return (
    eventTypeOptions.find((option) => option.value === eventType)?.label ?? humanize(eventType)
  );
}

function eventTypeToken(eventType: string): string {
  if (eventType.startsWith("campaign.")) {
    return eventType.includes("milestone") ? "MILE" : "CAMP";
  }
  if (eventType === "marketing.content.channel_published") {
    return "CPUB";
  }
  if (eventType.includes("channel")) {
    return "CHAN";
  }
  if (eventType.includes("approval") || eventType === "marketing.content.approved") {
    return "APPR";
  }
  if (eventType.includes("published")) {
    return "PUB";
  }
  return "CONT";
}

function eventVariant(event: CampaignCalendarEvent) {
  if (event.event_type.startsWith("campaign.")) {
    return "neutral" as const;
  }
  if (event.event_type === "marketing.content.approved") {
    return "success" as const;
  }
  if (event.event_type.includes("approval")) {
    return "warning" as const;
  }
  if (event.event_type.includes("published")) {
    return "success" as const;
  }
  if (event.status === "cancelled" || event.status === "archived" || event.status === "rejected") {
    return "neutral" as const;
  }
  return "success" as const;
}

function eventDateKey(event: CampaignCalendarEvent, timeZone: string): string {
  return event.all_day && event.date ? event.date : dateKeyInTimeZone(event.starts_at, timeZone);
}

function eventTimeLabel(event: CampaignCalendarEvent, timeZone: string): string {
  return event.all_day ? "All day" : formatCalendarDateTime(event.starts_at, timeZone);
}

function eventContext(event: CampaignCalendarEvent): string {
  const parts = [
    event.campaign?.name,
    event.artist?.name,
    event.release?.title,
    event.channel
      ? `${humanize(event.channel.channel)}${event.channel.placement ? ` / ${humanize(event.channel.placement)}` : ""}`
      : null,
  ].filter(Boolean);
  return parts.join(" - ") || "Workspace event";
}

export function campaignCalendarEventHref(event: CampaignCalendarEvent): string {
  if (event.url) {
    return event.url;
  }

  const campaignId =
    event.campaign?.id ??
    (event.source_type === "campaign" ? event.source_id : null) ??
    event.source_parent_id;
  if (event.event_type.startsWith("campaign.") && campaignId) {
    return `/campaigns/${campaignId}`;
  }

  const approvalRequestId =
    event.approval?.request_id ??
    (event.source_type === "approval_request" ? event.source_id : null);
  const params = new URLSearchParams();
  if (approvalRequestId) {
    params.set("tab", "approvals");
    params.set("approvalRequestId", approvalRequestId);
  }
  if (campaignId) {
    params.set("campaignId", campaignId);
  }
  return params.size ? `/marketing?${params.toString()}` : "/marketing";
}

function sortEvents(left: CampaignCalendarEvent, right: CampaignCalendarEvent): number {
  return (
    left.sort_key.localeCompare(right.sort_key) ||
    Number(right.all_day) - Number(left.all_day) ||
    left.title.localeCompare(right.title)
  );
}

function eventArtistOptions(events: CampaignCalendarEvent[]) {
  return events
    .map((event) => event.artist)
    .filter((entry): entry is NonNullable<CampaignCalendarEvent["artist"]> => Boolean(entry))
    .filter((entry, index, entries) => entries.findIndex((item) => item.id === entry.id) === index)
    .sort((left, right) => left.name.localeCompare(right.name));
}

function eventReleaseOptions(events: CampaignCalendarEvent[]) {
  return events
    .map((event) => event.release)
    .filter((entry): entry is NonNullable<CampaignCalendarEvent["release"]> => Boolean(entry))
    .filter((entry, index, entries) => entries.findIndex((item) => item.id === entry.id) === index)
    .sort((left, right) => left.title.localeCompare(right.title));
}

function campaignArtistOptions(campaigns: Campaign[]) {
  return [
    ...campaigns.flatMap((campaign) => [
      ...(campaign.primary_artist ? [campaign.primary_artist] : []),
      ...campaign.artists.map((entry) => entry.artist),
    ]),
  ]
    .filter(
      (artist, index, artists) => artists.findIndex((entry) => entry.id === artist.id) === index,
    )
    .sort((left, right) => left.name.localeCompare(right.name));
}

function campaignReleaseOptions(campaigns: Campaign[]) {
  return [
    ...campaigns.flatMap((campaign) => [
      ...(campaign.release ? [campaign.release] : []),
      ...campaign.releases.map((entry) => entry.release),
    ]),
  ]
    .filter(
      (release, index, releases) =>
        releases.findIndex((entry) => entry.id === release.id) === index,
    )
    .sort((left, right) => left.title.localeCompare(right.title));
}

function Filters({
  campaigns,
  events,
  filters,
  isLoadingCampaigns,
  onChange,
  onReset,
}: {
  campaigns: Campaign[];
  events: CampaignCalendarEvent[];
  filters: CalendarFilters;
  isLoadingCampaigns: boolean;
  onChange: (next: Partial<CalendarFilters>) => void;
  onReset: () => void;
}) {
  const artistOptions = campaignArtistOptions(campaigns);
  const releaseOptions = campaignReleaseOptions(campaigns);
  const eventArtists = eventArtistOptions(events);
  const eventReleases = eventReleaseOptions(events);
  const mergedArtists = [...artistOptions, ...eventArtists].filter(
    (artist, index, artists) => artists.findIndex((entry) => entry.id === artist.id) === index,
  );
  const mergedReleases = [...releaseOptions, ...eventReleases].filter(
    (release, index, releases) => releases.findIndex((entry) => entry.id === release.id) === index,
  );

  return (
    <Card className="grid gap-3 p-4">
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
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
          <span>Artist</span>
          <select
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            onChange={(event) => onChange({ artistId: event.target.value })}
            value={filters.artistId}
          >
            <option value="">Any artist</option>
            {mergedArtists.map((artist) => (
              <option key={artist.id} value={artist.id}>
                {artist.name}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700">
          <span>Release</span>
          <select
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            onChange={(event) => onChange({ releaseId: event.target.value })}
            value={filters.releaseId}
          >
            <option value="">Any release</option>
            {mergedReleases.map((release) => (
              <option key={release.id} value={release.id}>
                {release.title}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700">
          <span>Event type</span>
          <select
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            onChange={(event) => onChange({ eventType: event.target.value })}
            value={filters.eventType}
          >
            <option value="">All event types</option>
            {eventTypeOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
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
            {statusOptions.map((status) => (
              <option key={status} value={status}>
                {humanize(status)}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-end">
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
      </div>
      <div className="flex flex-wrap gap-4">
        <label className="inline-flex items-center gap-2 text-sm font-medium text-slate-700">
          <input
            checked={filters.includePublished}
            className="h-4 w-4 rounded border-slate-300"
            onChange={(event) => onChange({ includePublished: event.target.checked })}
            type="checkbox"
          />
          <span>Include published</span>
        </label>
        <label className="inline-flex items-center gap-2 text-sm font-medium text-slate-700">
          <input
            checked={filters.includeArchived}
            className="h-4 w-4 rounded border-slate-300"
            onChange={(event) => onChange({ includeArchived: event.target.checked })}
            type="checkbox"
          />
          <span>Include archived</span>
        </label>
      </div>
    </Card>
  );
}

function EventCard({
  event,
  onOpen,
  timeZone,
}: {
  event: CampaignCalendarEvent;
  onOpen: (event: CampaignCalendarEvent) => void;
  timeZone: string;
}) {
  const label = eventTypeLabel(event.event_type);
  return (
    <button
      aria-label={`${label}: ${event.title}`}
      className="grid min-w-0 gap-1 rounded-md border border-slate-200 bg-white px-2 py-1.5 text-left transition hover:border-slate-400 hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-950"
      onClick={() => onOpen(event)}
      type="button"
    >
      <span className="flex min-w-0 items-center gap-1.5">
        <Badge className="shrink-0" variant={eventVariant(event)}>
          {eventTypeToken(event.event_type)}
        </Badge>
        <span className="truncate text-xs font-semibold text-slate-950">{event.title}</span>
      </span>
      <span className="truncate text-xs text-slate-500">{eventTimeLabel(event, timeZone)}</span>
      <span className="truncate text-xs text-slate-500">{eventContext(event)}</span>
      {event.status ? (
        <span className="truncate text-xs text-slate-600">{humanize(event.status)}</span>
      ) : null}
    </button>
  );
}

function MonthCalendar({
  days,
  eventsByDay,
  onOpenEvent,
  timeZone,
}: {
  days: CalendarDay[];
  eventsByDay: Map<string, CampaignCalendarEvent[]>;
  onOpenEvent: (event: CampaignCalendarEvent) => void;
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
      <div className="grid grid-cols-1 sm:grid-cols-7">
        {days.map((day) => {
          const dayEvents = eventsByDay.get(day.dateKey) ?? [];
          return (
            <section
              aria-label={`${day.dateKey} events`}
              className={cn(
                "min-h-36 border-b border-r border-slate-200 bg-white p-2",
                !day.inMonth && "bg-slate-50 text-slate-400",
              )}
              key={day.dateKey}
            >
              <div className="mb-2 flex items-center justify-between text-xs font-medium text-slate-500">
                <span
                  className={cn(
                    "inline-flex h-6 w-6 items-center justify-center rounded-full",
                    day.isToday && "bg-slate-950 text-white",
                  )}
                >
                  {day.day}
                </span>
                {day.isToday ? <span>Today</span> : null}
              </div>
              <div className="grid gap-1">
                {dayEvents.slice(0, maxVisibleDayEvents).map((event) => (
                  <EventCard
                    event={event}
                    key={event.id}
                    onOpen={onOpenEvent}
                    timeZone={timeZone}
                  />
                ))}
                {dayEvents.length > maxVisibleDayEvents ? (
                  <span className="text-xs font-medium text-slate-500">
                    +{dayEvents.length - maxVisibleDayEvents} more
                  </span>
                ) : null}
              </div>
            </section>
          );
        })}
      </div>
    </Card>
  );
}

function CalendarList({
  events,
  onOpenEvent,
  timeZone,
}: {
  events: CampaignCalendarEvent[];
  onOpenEvent: (event: CampaignCalendarEvent) => void;
  timeZone: string;
}) {
  const grouped = useMemo(() => {
    const groups = new Map<string, CampaignCalendarEvent[]>();
    for (const event of events) {
      const key = eventDateKey(event, timeZone);
      groups.set(key, [...(groups.get(key) ?? []), event]);
    }
    return [...groups.entries()].sort(([left], [right]) => left.localeCompare(right));
  }, [events, timeZone]);

  return (
    <Card className="overflow-hidden p-0">
      <div className="grid gap-1 border-b border-slate-200 bg-slate-50 px-4 py-3">
        <h2 className="text-base font-semibold text-slate-950">Calendar list</h2>
        <p className="text-sm text-slate-500">
          Grouped by workspace date; timed rows retain their configured timezone.
        </p>
      </div>
      <div className="divide-y divide-slate-100">
        {grouped.map(([dateKey, dateEvents]) => (
          <section className="grid gap-2 px-4 py-4" key={dateKey}>
            <h3 className="text-sm font-semibold text-slate-950">
              {formatCalendarListDate(`${dateKey}T12:00:00Z`, "UTC").replace(", 12:00 PM", "")}
            </h3>
            <div className="grid gap-2">
              {dateEvents.map((event) => (
                <button
                  aria-label={`${eventTypeLabel(event.event_type)}: ${event.title}`}
                  className="grid gap-3 rounded-md border border-slate-200 px-3 py-3 text-left transition hover:border-slate-400 hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 md:grid-cols-[180px_minmax(0,1fr)_180px_160px]"
                  key={event.id}
                  onClick={() => onOpenEvent(event)}
                  type="button"
                >
                  <div>
                    <p className="text-xs font-semibold uppercase text-slate-500">
                      {event.all_day ? "All-day event" : "Timed event"}
                    </p>
                    <p className="mt-1 text-sm font-medium text-slate-900">
                      {eventTimeLabel(event, timeZone)}
                    </p>
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={eventVariant(event)}>
                        {eventTypeToken(event.event_type)}
                      </Badge>
                      <h4 className="truncate text-sm font-semibold text-slate-950">
                        {event.title}
                      </h4>
                      <Badge>{eventTypeLabel(event.event_type)}</Badge>
                    </div>
                    <p className="mt-1 text-sm text-slate-500">
                      {event.description ?? eventContext(event)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs font-semibold uppercase text-slate-500">Campaign</p>
                    <p className="mt-1 truncate text-sm font-medium text-slate-800">
                      {event.campaign?.name ?? "Not linked"}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs font-semibold uppercase text-slate-500">Status</p>
                    <p className="mt-1 truncate text-sm font-medium text-slate-800">
                      {humanize(event.status)}
                    </p>
                  </div>
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>
    </Card>
  );
}

export function CampaignCalendarWorkspace() {
  const router = useRouter();
  const { activeWorkspace } = useActiveWorkspace();
  const workspaceProfile = useActiveWorkspaceProfile();
  const timeZone =
    workspaceProfile.membership?.profile.preferences.timezone ??
    workspaceProfile.membership?.profile.timezone ??
    "UTC";
  const [view, setView] = useState<CalendarView>("month");
  const [monthDate, setMonthDate] = useState(() => currentCalendarMonthDate(timeZone));
  const [filters, setFilters] = useState<CalendarFilters>({
    artistId: "",
    campaignId: "",
    eventType: "",
    includeArchived: false,
    includePublished: false,
    releaseId: "",
    status: "",
  });

  const range = useMemo(() => calendarVisibleRange(monthDate, timeZone), [monthDate, timeZone]);
  const queryOptions = useMemo<CampaignCalendarQueryOptions>(
    () => ({
      artist_id: filters.artistId || null,
      campaign_id: filters.campaignId || null,
      end: range.end,
      event_types: filters.eventType || null,
      include_archived: filters.includeArchived,
      include_published: filters.includePublished,
      limit: 1000,
      offset: 0,
      release_id: filters.releaseId || null,
      start: range.start,
      status: filters.status || null,
      timezone: timeZone,
    }),
    [filters, range.end, range.start, timeZone],
  );
  const campaigns = useCampaigns(activeWorkspace?.id ?? null, { limit: 500, offset: 0 });
  const calendar = useCampaignCalendar(activeWorkspace?.id ?? null, queryOptions);
  const events = useMemo(
    () => [...(calendar.data?.events ?? [])].sort(sortEvents),
    [calendar.data?.events],
  );
  const currentMonthDays = useMemo(() => monthDays(monthDate, timeZone), [monthDate, timeZone]);
  const eventsByDay = useMemo(() => {
    const grouped = new Map<string, CampaignCalendarEvent[]>();
    for (const event of events) {
      const key = eventDateKey(event, timeZone);
      grouped.set(key, [...(grouped.get(key) ?? []), event]);
    }
    return grouped;
  }, [events, timeZone]);
  const canView =
    workspaceProfile.subject && activeWorkspace
      ? can(workspaceProfile.subject, null, capabilities.marketingCampaignView) &&
        can(workspaceProfile.subject, null, capabilities.marketingContentView)
      : false;
  const isCurrentMonth = monthDate.getTime() === currentCalendarMonthDate(timeZone).getTime();
  const showNoEventsInRange = events.length === 0 && (!isCurrentMonth || filtersActive(filters));

  const updateFilters = useCallback((next: Partial<CalendarFilters>) => {
    setFilters((current) => ({ ...current, ...next }));
  }, []);
  const resetFilters = useCallback(() => {
    setFilters({
      artistId: "",
      campaignId: "",
      eventType: "",
      includeArchived: false,
      includePublished: false,
      releaseId: "",
      status: "",
    });
  }, []);
  const moveMonth = useCallback((amount: number) => {
    setMonthDate((current) => addCalendarMonths(current, amount));
  }, []);
  const openEvent = useCallback(
    (event: CampaignCalendarEvent) => {
      router.push(campaignCalendarEventHref(event));
    },
    [router],
  );

  if (!activeWorkspace) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900">
        Choose a workspace to view the Campaign Calendar.
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
      <PageHeader
        description={`${activeWorkspace.name} campaign starts, milestones, schedules, approvals, and publishing history.`}
        eyebrow="Campaign Operations"
        title="Campaign Calendar"
      />

      {!canView && !workspaceProfile.isLoading ? (
        <div
          className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
          role="status"
        >
          You need campaign and marketing content view access to open the Campaign Calendar.
        </div>
      ) : null}

      {canView ? (
        <section className="grid gap-4" aria-label="Campaign calendar">
          <div className="flex flex-col gap-3 rounded-md border border-slate-200 bg-white p-4 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-950">
                {formatCalendarMonthTitle(monthDate)}
              </h2>
              <p className="text-sm text-slate-500">
                Showing {formatCalendarDateTime(range.start, timeZone)} through{" "}
                {formatCalendarDateTime(range.end, timeZone)}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={() => moveMonth(-1)} size="sm" type="button" variant="secondary">
                Previous
              </Button>
              <Button
                onClick={() => setMonthDate(currentCalendarMonthDate(timeZone))}
                size="sm"
                type="button"
                variant="secondary"
              >
                Today
              </Button>
              <Button onClick={() => moveMonth(1)} size="sm" type="button" variant="secondary">
                Next
              </Button>
              <div className="flex rounded-md border border-slate-300 p-0.5">
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
            campaigns={campaigns.data?.campaigns ?? []}
            events={events}
            filters={filters}
            isLoadingCampaigns={campaigns.isLoading}
            onChange={updateFilters}
            onReset={resetFilters}
          />

          {calendar.error ? (
            <div
              className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
              role="alert"
            >
              {calendar.error.message}
            </div>
          ) : null}

          {calendar.isLoading && !calendar.data ? (
            <Card className="grid gap-3">
              <LoadingState label="Loading campaign calendar" />
              {Array.from({ length: 3 }, (_, index) => (
                <div className="h-16 rounded-md bg-slate-100 auth-shimmer" key={index} />
              ))}
            </Card>
          ) : events.length === 0 ? (
            <EmptyState
              description={
                showNoEventsInRange
                  ? "Try another month or change the campaign, artist, release, event type, status, published, or archived filters."
                  : "Campaign starts, milestones, content schedules, approvals, and publish history will appear here after they are planned."
              }
              title={
                showNoEventsInRange ? "No events in this range" : "No campaign calendar events yet"
              }
            />
          ) : view === "month" ? (
            <MonthCalendar
              days={currentMonthDays}
              eventsByDay={eventsByDay}
              onOpenEvent={openEvent}
              timeZone={timeZone}
            />
          ) : (
            <CalendarList events={events} onOpenEvent={openEvent} timeZone={timeZone} />
          )}
        </section>
      ) : null}
    </div>
  );
}
