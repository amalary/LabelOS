"use client";

import { type Campaign } from "../../lib/campaigns";
import {
  type CalendarFilters,
  statuses,
  humanize,
  channelOptions,
  filtersActive,
  channelSummary,
  channelDestinationSummaries,
  approvalStateVariant,
  approvalStateLabel,
  campaignName,
  destinationReadinessVariant,
  destinationAccountLabel,
  relationshipLabel,
} from "./marketing-presentation";
import { Card, Button, cn, Badge } from "@label-os/ui";
import {
  type CalendarDay,
  formatCalendarDateTime,
  formatCalendarListDate,
} from "../../lib/calendar-dates";
import { type MarketingScheduleInstance } from "./marketing-schedule";
import { type MarketingContentItem } from "../../lib/marketing-content";
import { SchedulingJobState } from "../../components/scheduling-job-state";

export type CalendarView = "month" | "list";

const weekdayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function Filters({
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
  const artistOptions = [
    ...campaigns.flatMap((campaign) => [
      ...(campaign.primary_artist ? [campaign.primary_artist] : []),
      ...campaign.artists.map((entry) => entry.artist),
    ]),
  ].filter(
    (artist, index, artists) => artists.findIndex((entry) => entry.id === artist.id) === index,
  );
  const releaseOptions = [
    ...campaigns.flatMap((campaign) => [
      ...(campaign.release ? [campaign.release] : []),
      ...campaign.releases.map((entry) => entry.release),
    ]),
  ].filter(
    (release, index, releases) => releases.findIndex((entry) => entry.id === release.id) === index,
  );
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
                {status === "scheduled" ? "Planned" : humanize(status)}
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
          <select
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            onChange={(event) => onChange({ artistId: event.target.value })}
            value={filters.artistId}
          >
            <option value="">Any artist</option>
            {artistOptions.map((artist) => (
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
            {releaseOptions.map((release) => (
              <option key={release.id} value={release.id}>
                {release.title}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-slate-500">
          Filters are sent to the marketing content API using campaigns and linked catalog
          relationships in this workspace.
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

export function MonthCalendar({
  campaigns,
  days,
  instancesByDay,
  onEmptyDayClick,
  onItemClick,
  timeZone,
}: {
  campaigns: Campaign[];
  days: CalendarDay[];
  instancesByDay: Map<string, MarketingScheduleInstance[]>;
  onEmptyDayClick: (dateKey: string) => void;
  onItemClick: (item: MarketingContentItem) => void;
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
                  <button
                    className="grid gap-1 rounded-md border border-slate-200 bg-slate-50 px-2 py-1.5 text-left transition hover:border-slate-400 hover:bg-white"
                    key={instance.eventId ?? instance.item.id}
                    onClick={() => onItemClick(instance.item)}
                    type="button"
                  >
                    <span className="truncate text-xs font-semibold text-slate-950">
                      {instance.item.title}
                    </span>
                    <span className="truncate text-xs text-slate-500">
                      {instance.publication
                        ? humanize(instance.publication.provider)
                        : channelSummary(instance.item)}
                    </span>
                    <span className="grid gap-0.5">
                      {(instance.publication
                        ? [humanize(instance.publication.placement)]
                        : channelDestinationSummaries(instance.item)
                      ).map((summary, index) => (
                        <span className="truncate text-xs text-slate-600" key={index}>
                          {summary}
                        </span>
                      ))}
                    </span>
                    <span className="flex flex-wrap items-center gap-1">
                      <Badge
                        className="max-w-full truncate"
                        variant={
                          instance.publication ? "success" : approvalStateVariant(instance.item)
                        }
                      >
                        {instance.publication ? "Published" : approvalStateLabel(instance.item)}
                      </Badge>
                      {(instance.publication ? [] : instance.item.channels).map((channel) => (
                        <SchedulingJobState key={channel.id} job={channel.scheduling_job} />
                      ))}
                      {instance.hasMultipleChannelTimes ? (
                        <Badge title={formatCalendarDateTime(instance.scheduledAt, timeZone)}>
                          Multi-time
                        </Badge>
                      ) : null}
                    </span>
                    <span className="truncate text-xs text-slate-500">
                      {campaignName(campaigns, instance.item.campaign_id)}
                    </span>
                  </button>
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

export function CalendarList({
  campaigns,
  instances,
  onItemClick,
  timeZone,
}: {
  campaigns: Campaign[];
  instances: MarketingScheduleInstance[];
  onItemClick: (item: MarketingContentItem) => void;
  timeZone: string;
}) {
  return (
    <Card className="overflow-hidden p-0">
      <div className="grid gap-1 border-b border-slate-200 bg-slate-50 px-4 py-3">
        <h2 className="text-base font-semibold text-slate-950">Chronological content</h2>
        <p className="text-sm text-slate-500">
          Planned dates follow content schedules. Published dates reflect confirmed external
          publication.
        </p>
      </div>
      <div className="divide-y divide-slate-100">
        {instances.map((instance) => (
          <button
            className="grid gap-3 px-4 py-4 text-left transition hover:bg-slate-50 md:grid-cols-[190px_minmax(0,1fr)_170px_170px]"
            key={instance.eventId ?? instance.item.id}
            onClick={() => onItemClick(instance.item)}
            type="button"
          >
            <div>
              <p className="text-xs font-semibold uppercase text-slate-500">
                {instance.publication ? "Published" : "Planned"}
              </p>
              <p className="mt-1 text-sm font-medium text-slate-900">
                {formatCalendarListDate(instance.scheduledAt, timeZone)}
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
                <Badge
                  variant={instance.publication ? "success" : approvalStateVariant(instance.item)}
                >
                  {instance.publication ? "Published" : approvalStateLabel(instance.item)}
                </Badge>
              </div>
              <p className="mt-1 text-sm text-slate-500">
                {humanize(instance.item.content_type)} -{" "}
                {instance.publication
                  ? humanize(instance.publication.provider)
                  : channelSummary(instance.item)}
              </p>
              {(instance.publication ? [] : instance.item.channels).map((channel) => (
                <SchedulingJobState key={channel.id} job={channel.scheduling_job} />
              ))}
              <div className="mt-2 flex flex-wrap gap-1">
                {instance.publication ? (
                  <Badge variant="success">{humanize(instance.publication.placement)}</Badge>
                ) : instance.item.channels.length ? (
                  instance.item.channels.map((channel) => {
                    const readiness = channel.destination_readiness;
                    return (
                      <Badge key={channel.id} variant={destinationReadinessVariant(readiness)}>
                        {`${humanize(channel.channel)} ${
                          readiness?.account ? destinationAccountLabel(readiness.account) : ""
                        } ${readiness?.label ?? "No Account Selected"}`.replace(/\s+/g, " ")}
                      </Badge>
                    );
                  })
                ) : (
                  <Badge variant="warning">No Account Selected</Badge>
                )}
              </div>
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
          </button>
        ))}
      </div>
    </Card>
  );
}
