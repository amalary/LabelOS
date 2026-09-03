"use client";

import { Badge, Button, Card, EmptyState, LoadingState, PageHeader, cn } from "@label-os/ui";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { can, capabilities } from "../../lib/authorization";
import { type Campaign, useCampaigns } from "../../lib/campaigns";
import {
  type MarketingContentChannelCreate,
  type MarketingContentItem,
  type MarketingContentItemCreate,
  type MarketingContentItemStatus,
  type MarketingContentItemUpdate,
  type MarketingContentListOptions,
  useCreateMarketingContentItem,
  useTransitionMarketingContentStatus,
  useUpdateMarketingContentItem,
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

const channelOptions = [
  "instagram",
  "tiktok",
  "youtube",
  "facebook",
  "x",
  "threads",
  "spotify",
  "email",
];
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

type ContentEditorMode = "create" | "edit";

type ChannelFormRow = {
  id: string;
  channel: string;
  placement: string;
  scheduledAt: string;
  copyTextOverride: string;
  assetRefsJson: string;
};

type ContentFormState = {
  campaignId: string;
  artistId: string;
  releaseId: string;
  title: string;
  contentType: string;
  copyText: string;
  assetRefsJson: string;
  ownerProfileId: string;
  scheduledAt: string;
  channels: ChannelFormRow[];
};

const contentTypeOptions = ["social_post", "video", "email", "ad", "press", "playlist_pitch"];

function formatDateTimeInput(value: string | null): string {
  return value ? value.slice(0, 16) : "";
}

function selectedDateInput(dateKey: string | null): string {
  return dateKey ? `${dateKey}T09:00` : "";
}

function dateTimeInputToIso(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}

function parseAssetRefs(value: string, fieldName: string): unknown[] {
  const trimmed = value.trim();
  if (!trimmed) {
    return [];
  }
  const parsed = JSON.parse(trimmed) as unknown;
  if (!Array.isArray(parsed)) {
    throw new Error(`${fieldName} must be a JSON array.`);
  }
  return parsed;
}

function assetRefsInput(value: unknown[] | null | undefined): string {
  return value && value.length ? JSON.stringify(value, null, 2) : "";
}

function channelTargetKey(row: Pick<ChannelFormRow, "channel" | "placement">): string {
  return `${row.channel.trim().toLowerCase()}::${(row.placement.trim() || "default").toLowerCase()}`;
}

function duplicateChannelTargets(channels: ChannelFormRow[]): boolean {
  const seen = new Set<string>();
  for (const row of channels) {
    if (!row.channel.trim()) {
      continue;
    }
    const key = channelTargetKey(row);
    if (seen.has(key)) {
      return true;
    }
    seen.add(key);
  }
  return false;
}

function emptyChannelRow(index: number): ChannelFormRow {
  return {
    assetRefsJson: "",
    channel: index === 0 ? "instagram" : "",
    copyTextOverride: "",
    id: `channel_${Date.now()}_${index}`,
    placement: index === 0 ? "feed" : "",
    scheduledAt: "",
  };
}

function initialFormState({
  campaigns,
  createDate,
  filters,
  item,
}: {
  campaigns: Campaign[];
  createDate: string | null;
  filters: CalendarFilters;
  item?: MarketingContentItem | null;
}): ContentFormState {
  if (item) {
    return {
      assetRefsJson: assetRefsInput(item.asset_refs),
      artistId: item.artist_id ?? "",
      campaignId: item.campaign_id,
      channels: item.channels.map((channel, index) => ({
        assetRefsJson: assetRefsInput(channel.asset_refs),
        channel: channel.channel,
        copyTextOverride: channel.copy_text_override ?? "",
        id: channel.id || `channel_${index}`,
        placement: channel.placement ?? "",
        scheduledAt: formatDateTimeInput(channel.scheduled_at),
      })),
      contentType: item.content_type,
      copyText: item.copy_text ?? "",
      ownerProfileId: item.owner_profile_id ?? "",
      releaseId: item.release_id ?? "",
      scheduledAt: formatDateTimeInput(item.scheduled_at),
      title: item.title,
    };
  }
  const campaignId = filters.campaignId || campaigns[0]?.id || "";
  const campaign = campaigns.find((entry) => entry.id === campaignId);
  return {
    assetRefsJson: "",
    artistId: campaign?.primary_artist?.id ?? "",
    campaignId,
    channels: [emptyChannelRow(0)],
    contentType: "social_post",
    copyText: "",
    ownerProfileId: campaign?.owner_profile_id ?? "",
    releaseId: campaign?.release?.id ?? "",
    scheduledAt: selectedDateInput(createDate),
    title: "",
  };
}

function formToPayload(form: ContentFormState): MarketingContentItemCreate {
  return {
    artist_id: form.artistId || null,
    asset_refs: parseAssetRefs(form.assetRefsJson, "Asset references"),
    channels: form.channels.map<MarketingContentChannelCreate>((channel) => ({
      asset_refs: parseAssetRefs(channel.assetRefsJson, "Channel asset references"),
      channel: channel.channel,
      copy_text_override: channel.copyTextOverride || null,
      placement: channel.placement || null,
      scheduled_at: dateTimeInputToIso(channel.scheduledAt),
    })),
    content_type: form.contentType,
    copy_text: form.copyText || null,
    owner_profile_id: form.ownerProfileId || null,
    release_id: form.releaseId || null,
    scheduled_at: dateTimeInputToIso(form.scheduledAt),
    title: form.title,
  };
}

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
    (release, index, releases) =>
      releases.findIndex((entry) => entry.id === release.id) === index,
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

function ContentEditor({
  campaigns,
  canApprove,
  canEdit,
  canSubmitForReview,
  createDate,
  filters,
  item,
  mode,
  onCancel,
  onSaved,
  timeZone,
}: {
  campaigns: Campaign[];
  canApprove: boolean;
  canEdit: boolean;
  canSubmitForReview: boolean;
  createDate: string | null;
  filters: CalendarFilters;
  item: MarketingContentItem | null;
  mode: ContentEditorMode;
  onCancel: () => void;
  onSaved: () => void;
  timeZone: string;
}) {
  const [form, setForm] = useState(() =>
    initialFormState({ campaigns, createDate, filters, item }),
  );
  const [clientError, setClientError] = useState<string | null>(null);
  const selectedCampaign = campaigns.find((campaign) => campaign.id === form.campaignId) ?? null;
  const create = useCreateMarketingContentItem(
    selectedCampaign?.workspace_id ?? item?.workspace_id ?? null,
    mode === "create" ? form.campaignId || null : null,
  );
  const update = useUpdateMarketingContentItem(
    item?.workspace_id ?? selectedCampaign?.workspace_id ?? null,
    item?.campaign_id ?? null,
    item?.id ?? null,
  );
  const transition = useTransitionMarketingContentStatus(
    item?.workspace_id ?? selectedCampaign?.workspace_id ?? null,
    item?.campaign_id ?? null,
    item?.id ?? null,
  );
  const isEditable = mode === "create" || canEdit;
  const artistOptions = selectedCampaign
    ? [
        ...(selectedCampaign.primary_artist ? [selectedCampaign.primary_artist] : []),
        ...selectedCampaign.artists.map((entry) => entry.artist),
      ].filter(
        (artist, index, artists) => artists.findIndex((entry) => entry.id === artist.id) === index,
      )
    : [];
  const releaseOptions = (selectedCampaign
    ? [
        ...(selectedCampaign.release ? [selectedCampaign.release] : []),
        ...selectedCampaign.releases.map((entry) => entry.release),
      ].filter(
        (release, index, releases) =>
          releases.findIndex((entry) => entry.id === release.id) === index,
      )
    : []
  ).filter((release) => !form.artistId || !release.artist_id || release.artist_id === form.artistId);
  const ownerOptions = selectedCampaign?.members ?? [];
  const duplicateChannels = duplicateChannelTargets(form.channels);
  const mutationError = create.error ?? update.error ?? transition.error;
  const isMutating = create.isMutating || update.isMutating || transition.isMutating;

  const setField = (next: Partial<ContentFormState>) => {
    setClientError(null);
    setForm((current) => ({ ...current, ...next }));
  };
  const setChannel = (id: string, next: Partial<ChannelFormRow>) => {
    setClientError(null);
    setForm((current) => ({
      ...current,
      channels: current.channels.map((channel) =>
        channel.id === id ? { ...channel, ...next } : channel,
      ),
    }));
  };

  async function saveDraft() {
    setClientError(null);
    if (!form.campaignId) {
      setClientError("Campaign is required.");
      return;
    }
    if (!form.title.trim()) {
      setClientError("Title is required.");
      return;
    }
    if (!form.contentType.trim()) {
      setClientError("Content type is required.");
      return;
    }
    if (form.channels.length < 1 || form.channels.some((channel) => !channel.channel.trim())) {
      setClientError("At least one channel is required.");
      return;
    }
    if (duplicateChannels) {
      setClientError("Each channel and placement target can only be selected once.");
      return;
    }
    if (form.artistId && !artistOptions.some((artist) => artist.id === form.artistId)) {
      setClientError("Choose an artist linked to this workspace campaign.");
      return;
    }
    if (form.releaseId && !releaseOptions.some((release) => release.id === form.releaseId)) {
      setClientError("Choose a release linked to this workspace campaign.");
      return;
    }
    try {
      const payload = formToPayload(form);
      if (mode === "create") {
        await create.mutate(payload);
      } else {
        await update.mutate(payload as MarketingContentItemUpdate);
      }
      onSaved();
    } catch (error) {
      if (error instanceof SyntaxError || error instanceof Error) {
        setClientError(error.message);
      }
    }
  }

  async function submitForReview() {
    setClientError(null);
    if (!item) {
      return;
    }
    try {
      await transition.mutate({ status: "in_review" });
      onSaved();
    } catch {
      // The mutation state renders API denial and invalid transition messages.
    }
  }

  async function approveForAdminTest() {
    setClientError(null);
    if (!item) {
      return;
    }
    try {
      await transition.mutate({ status: "approved" });
      onSaved();
    } catch {
      // The mutation state renders API denial and invalid transition messages.
    }
  }

  return (
    <Card className="grid gap-4 p-4" role="region" aria-label="Marketing content editor">
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">
            {mode === "create" ? "Create content draft" : "Edit content"}
          </h2>
          <p className="text-sm text-slate-500">
            Schedule for calendar by setting a planned publish time. LabelOS will not automatically
            publish posts yet.
          </p>
          {item ? (
            <p className="mt-1 text-xs font-medium text-slate-500">
              Current status: {humanize(item.status)}
            </p>
          ) : null}
        </div>
        <Button onClick={onCancel} size="sm" type="button" variant="secondary">
          Close
        </Button>
      </div>

      {clientError || mutationError ? (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900" role="alert">
          {clientError ?? mutationError?.message}
        </div>
      ) : null}

      <div className="grid gap-3 md:grid-cols-2">
        <label className="grid gap-1 text-sm font-medium text-slate-700">
          <span>Campaign</span>
          <select
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            disabled={!isEditable || mode === "edit"}
            onChange={(event) => {
              const campaign = campaigns.find((entry) => entry.id === event.target.value);
              setField({
                artistId: campaign?.primary_artist?.id ?? "",
                campaignId: event.target.value,
                ownerProfileId: campaign?.owner_profile_id ?? "",
                releaseId: campaign?.release?.id ?? "",
              });
            }}
            value={form.campaignId}
          >
            <option value="">Choose campaign</option>
            {campaigns.map((campaign) => (
              <option key={campaign.id} value={campaign.id}>
                {campaign.name}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700">
          <span>Title</span>
          <input
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            disabled={!isEditable}
            onChange={(event) => setField({ title: event.target.value })}
            value={form.title}
          />
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700">
          <span>Artist</span>
          <select
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            disabled={!isEditable || !selectedCampaign}
            onChange={(event) => setField({ artistId: event.target.value })}
            value={form.artistId}
          >
            <option value="">No artist</option>
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
            disabled={!isEditable || !selectedCampaign}
            onChange={(event) => setField({ releaseId: event.target.value })}
            value={form.releaseId}
          >
            <option value="">No release</option>
            {releaseOptions.map((release) => (
              <option key={release.id} value={release.id}>
                {release.title}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700">
          <span>Content Type</span>
          <select
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            disabled={!isEditable}
            onChange={(event) => setField({ contentType: event.target.value })}
            value={form.contentType}
          >
            {contentTypeOptions.map((contentType) => (
              <option key={contentType} value={contentType}>
                {humanize(contentType)}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700">
          <span>Owner</span>
          <select
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            disabled={!isEditable || !selectedCampaign}
            onChange={(event) => setField({ ownerProfileId: event.target.value })}
            value={form.ownerProfileId}
          >
            <option value="">No owner</option>
            {ownerOptions.map((member) => (
              <option key={member.profile_id} value={member.profile_id}>
                {member.display_name ?? member.profile_id}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700 md:col-span-2">
          <span>Planned publish time</span>
          <input
            aria-label="Planned publish time"
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            disabled={!isEditable}
            onChange={(event) => setField({ scheduledAt: event.target.value })}
            type="datetime-local"
            value={form.scheduledAt}
          />
          <span className="text-xs font-normal text-slate-500">Calendar timezone: {timeZone}</span>
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700 md:col-span-2">
          <span>Core Copy / Caption</span>
          <textarea
            className="min-h-24 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950"
            disabled={!isEditable}
            onChange={(event) => setField({ copyText: event.target.value })}
            value={form.copyText}
          />
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700 md:col-span-2">
          <span>Asset references</span>
          <textarea
            className="min-h-20 rounded-md border border-slate-300 bg-white px-3 py-2 font-mono text-xs text-slate-950"
            disabled={!isEditable}
            onChange={(event) => setField({ assetRefsJson: event.target.value })}
            placeholder='[{"id":"asset_01","type":"image"}]'
            value={form.assetRefsJson}
          />
        </label>
      </div>

      <div className="grid gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-base font-semibold text-slate-950">Channel targets</h3>
          <Button
            disabled={!isEditable}
            onClick={() =>
              setForm((current) => ({
                ...current,
                channels: [...current.channels, emptyChannelRow(current.channels.length)],
              }))
            }
            size="sm"
            type="button"
            variant="secondary"
          >
            Add channel
          </Button>
        </div>
        {duplicateChannels ? (
          <p className="text-sm font-medium text-red-700">
            Duplicate channel and placement targets are not allowed.
          </p>
        ) : null}
        {form.channels.map((channel, index) => (
          <div className="grid gap-3 rounded-md border border-slate-200 p-3" key={channel.id}>
            <div className="grid gap-3 md:grid-cols-[1fr_1fr_1fr_auto]">
              <label className="grid gap-1 text-sm font-medium text-slate-700">
                <span>Channel</span>
                <select
                  className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                  disabled={!isEditable}
                  onChange={(event) => setChannel(channel.id, { channel: event.target.value })}
                  value={channel.channel}
                >
                  <option value="">Choose channel</option>
                  {channelOptions.map((option) => (
                    <option key={option} value={option}>
                      {humanize(option)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="grid gap-1 text-sm font-medium text-slate-700">
                <span>Placement</span>
                <input
                  className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                  disabled={!isEditable}
                  onChange={(event) => setChannel(channel.id, { placement: event.target.value })}
                  placeholder="default"
                  value={channel.placement}
                />
              </label>
              <label className="grid gap-1 text-sm font-medium text-slate-700">
                <span>Channel planned publish time</span>
                <input
                  aria-label="Channel planned publish time"
                  className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                  disabled={!isEditable}
                  onChange={(event) => setChannel(channel.id, { scheduledAt: event.target.value })}
                  type="datetime-local"
                  value={channel.scheduledAt}
                />
              </label>
              <Button
                className="self-end"
                disabled={!isEditable || form.channels.length === 1}
                onClick={() =>
                  setForm((current) => ({
                    ...current,
                    channels: current.channels.filter((entry) => entry.id !== channel.id),
                  }))
                }
                size="sm"
                type="button"
                variant="secondary"
              >
                Remove
              </Button>
            </div>
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              <span>Channel copy override</span>
              <textarea
                className="min-h-16 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950"
                disabled={!isEditable}
                onChange={(event) =>
                  setChannel(channel.id, { copyTextOverride: event.target.value })
                }
                value={channel.copyTextOverride}
              />
            </label>
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              <span>Channel asset references</span>
              <textarea
                className="min-h-16 rounded-md border border-slate-300 bg-white px-3 py-2 font-mono text-xs text-slate-950"
                disabled={!isEditable}
                onChange={(event) => setChannel(channel.id, { assetRefsJson: event.target.value })}
                placeholder="[]"
                value={channel.assetRefsJson}
              />
            </label>
            <p className="text-xs text-slate-500">Target {index + 1}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button disabled={!isEditable || isMutating} onClick={saveDraft} type="button">
          {mode === "create" ? "Save draft" : "Save changes"}
        </Button>
        {item?.status === "draft" && canSubmitForReview ? (
          <Button disabled={isMutating} onClick={submitForReview} type="button" variant="secondary">
            Submit for Review
          </Button>
        ) : null}
        {item?.status === "in_review" && canApprove ? (
          <Button disabled={isMutating} onClick={approveForAdminTest} type="button" variant="secondary">
            Approve
          </Button>
        ) : null}
        {!isEditable ? (
          <span className="text-sm text-slate-500">You need edit access to change this content.</span>
        ) : null}
      </div>
    </Card>
  );
}

function MonthCalendar({
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
                    key={instance.item.id}
                    onClick={() => onItemClick(instance.item)}
                    type="button"
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

function CalendarList({
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
          Planned date uses the parent schedule first, then the earliest relevant channel schedule.
        </p>
      </div>
      <div className="divide-y divide-slate-100">
        {instances.map((instance) => (
          <button
            className="grid gap-3 px-4 py-4 text-left transition hover:bg-slate-50 md:grid-cols-[190px_minmax(0,1fr)_170px_170px]"
            key={instance.item.id}
            onClick={() => onItemClick(instance.item)}
            type="button"
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
          </button>
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
  const createDate = searchParams.get("createDate");
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
  const [editor, setEditor] = useState<
    | { key: string; mode: "create"; item: null; createDate: string | null }
    | { key: string; mode: "edit"; item: MarketingContentItem; createDate: null }
    | null
  >(() => (createDate ? { createDate, item: null, key: `create:${createDate}`, mode: "create" } : null));
  const range = useMemo(() => calendarVisibleRange(monthDate, timeZone), [monthDate, timeZone]);
  const campaigns = useCampaigns(activeWorkspace?.id ?? null, { limit: 500, offset: 0 });
  const canView =
    workspaceProfile.subject && activeWorkspace
      ? can(workspaceProfile.subject, null, capabilities.marketingContentView)
      : false;
  const canCreate =
    workspaceProfile.subject && activeWorkspace
      ? can(workspaceProfile.subject, null, capabilities.marketingContentCreate)
      : false;
  const canEdit =
    workspaceProfile.subject && activeWorkspace
      ? can(workspaceProfile.subject, null, capabilities.marketingContentEdit)
      : false;
  const canSubmitForReview =
    workspaceProfile.subject && activeWorkspace
      ? can(workspaceProfile.subject, null, capabilities.marketingContentSubmitForReview)
      : false;
  const canApprove =
    workspaceProfile.subject && activeWorkspace
      ? can(workspaceProfile.subject, null, capabilities.marketingContentApprove)
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

  const openCreateEditor = useCallback(
    (dateKey: string | null = null) => {
      setEditor({
        createDate: dateKey,
        item: null,
        key: `create:${dateKey ?? "blank"}:${Date.now()}`,
        mode: "create",
      });
      updateUrl(filters, dateKey ?? undefined);
    },
    [filters, updateUrl],
  );

  const closeEditor = useCallback(() => {
    setEditor(null);
    updateUrl(filters);
  }, [filters, updateUrl]);

  const handleSaved = useCallback(() => {
    setEditor(null);
    updateUrl(filters);
    void calendarContent.reload().catch(() => undefined);
  }, [calendarContent, filters, updateUrl]);

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
              {canCreate ? (
                <Button onClick={() => openCreateEditor()} size="sm" type="button">
                  Create Content
                </Button>
              ) : null}
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

          {editor ? (
            <ContentEditor
              campaigns={campaignList}
              canApprove={canApprove}
              canEdit={canEdit}
              canSubmitForReview={canSubmitForReview}
              createDate={editor.createDate}
              filters={filters}
              item={editor.item}
              key={editor.key}
              mode={editor.mode}
              onCancel={closeEditor}
              onSaved={handleSaved}
              timeZone={timeZone}
            />
          ) : null}

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
              onEmptyDayClick={(dateKey) => {
                if (canCreate) {
                  openCreateEditor(dateKey);
                } else {
                  updateUrl(filters, dateKey);
                }
              }}
              onItemClick={(selectedItem) =>
                setEditor({
                  createDate: null,
                  item: selectedItem,
                  key: `edit:${selectedItem.id}:${selectedItem.updated_at}`,
                  mode: "edit",
                })
              }
              timeZone={timeZone}
            />
          ) : (
            <CalendarList
              campaigns={campaignList}
              instances={scheduleInstances}
              onItemClick={(selectedItem) =>
                setEditor({
                  createDate: null,
                  item: selectedItem,
                  key: `edit:${selectedItem.id}:${selectedItem.updated_at}`,
                  mode: "edit",
                })
              }
              timeZone={timeZone}
            />
          )}
        </section>
      ) : null}

      {activeTab !== "calendar" ? (
        <UpcomingTab label={tabs.find((tab) => tab.id === activeTab)?.label ?? "Section"} />
      ) : null}
    </div>
  );
}
