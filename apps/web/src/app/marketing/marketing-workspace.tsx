"use client";

import { Badge, Button, Card, EmptyState, LoadingState, PageHeader, cn } from "@label-os/ui";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { can, capabilities } from "../../lib/authorization";
import {
  type ApprovalAction,
  type ApprovalActor,
  type ApprovalDecision,
  type ApprovalListOptions,
  type ApprovalRequestStatus,
  type ApprovalRequestSummary,
  useApprovalDecision,
  useApprovalQueue,
  useApprovalRequest,
  useSubmitMarketingContentForApproval,
} from "../../lib/approvals";
import { type Campaign, useCampaigns } from "../../lib/campaigns";
import {
  addCalendarMonths,
  calendarFallbackTimeZone,
  calendarVisibleRange,
  currentCalendarMonthDate,
  dateKeyInTimeZone,
  formatCalendarDateTime,
  formatCalendarListDate,
  formatCalendarMonthTitle,
  monthDays,
  type CalendarDay,
} from "../../lib/calendar-dates";
import {
  type MarketingContentChannelCreate,
  type MarketingContentItem,
  type MarketingContentItemCreate,
  type MarketingContentItemStatus,
  type MarketingContentItemUpdate,
  type MarketingContentListOptions,
  useArchiveMarketingContentItem,
  useCreateMarketingContentItem,
  useMarketingContentItem,
  useTransitionMarketingContentStatus,
  useUpdateMarketingContentItem,
  useWorkspaceMarketingContent,
  useWorkspaceCalendarContent,
} from "../../lib/marketing-content";
import { useOrganizationRealtimeContext } from "../../lib/realtime/use-organization-realtime";
import {
  type AssistedSocialAccountConnectionCreate,
  type SocialAccountCapability,
  type SocialAccountConnection,
  type SocialAccountConnectionStatus,
  type SocialAccountProvider,
  useCreateAssistedSocialAccountConnection,
  useDisconnectSocialAccountConnection,
  navigateToSocialAccountAuthorization,
  useSocialAccountConnections,
  useStartSocialAccountOAuthConnection,
  useUpdateSocialAccountConnection,
} from "../../lib/social-account-connections";
import { useActiveWorkspace, useActiveWorkspaceProfile } from "../../lib/workspace-context";

type MarketingTab = "calendar" | "drafts" | "approvals" | "accounts";
type CalendarView = "month" | "list";

export type MarketingScheduleInstance = {
  item: MarketingContentItem;
  scheduledAt: string | null;
  dateKey: string | null;
  hasMultipleChannelTimes: boolean;
};

const tabs: Array<{ id: MarketingTab; label: string; enabled: boolean }> = [
  { id: "calendar", label: "Calendar", enabled: true },
  { id: "drafts", label: "Drafts", enabled: true },
  { id: "approvals", label: "Approvals", enabled: true },
  { id: "accounts", label: "Accounts", enabled: true },
];

type ApprovalQueueView =
  "awaiting_review" | "submitted_by_me" | "changes_requested" | "approved" | "rejected" | "all";

const approvalQueueResourceType = "marketing_content_item";
const approvalQueueViews: Array<{ id: ApprovalQueueView; label: string }> = [
  { id: "awaiting_review", label: "Awaiting my review" },
  { id: "submitted_by_me", label: "Submitted by me" },
  { id: "changes_requested", label: "Changes requested" },
  { id: "approved", label: "Approved" },
  { id: "rejected", label: "Rejected" },
  { id: "all", label: "All" },
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
const socialAccountProviders = [
  "instagram",
  "facebook",
  "tiktok",
  "youtube",
  "spotify",
  "x",
] as const;
const assistedCapabilityOptions: SocialAccountCapability[] = [
  "manual_publish",
  "manual_metrics",
  "account_analytics_read",
  "post_analytics_read",
];
const weekdayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const planningFallbackTimeZone = calendarFallbackTimeZone;

function humanize(value: string | null | undefined): string {
  if (!value) {
    return "Not set";
  }
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
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

function statusVariant(status: MarketingContentItemStatus) {
  if (status === "approved" || status === "scheduled" || status === "published") {
    return "success" as const;
  }
  if (status === "draft" || status === "in_review") {
    return "warning" as const;
  }
  return "neutral" as const;
}

function approvalStateVariant(item: MarketingContentItem) {
  const state = item.approval_state?.state ?? item.status;
  if (state === "approved" || state === "scheduled" || state === "published") {
    return "success" as const;
  }
  if (state === "in_review" || state === "changes_requested" || state === "reapproval_required") {
    return "warning" as const;
  }
  return statusVariant(item.status);
}

function approvalStateLabel(item: MarketingContentItem): string {
  return item.approval_state?.label ?? humanize(item.status);
}

function approvedRevisionIsCurrent(item: MarketingContentItem): boolean {
  return Boolean(
    item.approval_state?.approved_revision_is_current ??
    (item.approved_revision !== null &&
      item.approved_revision !== undefined &&
      item.approved_revision === item.content_revision),
  );
}

function canScheduleApprovedRevision(item: MarketingContentItem): boolean {
  return Boolean(
    item.approval_state?.can_schedule ??
    (item.status === "approved" && approvedRevisionIsCurrent(item)),
  );
}

function channelNames(item: MarketingContentItem): string[] {
  return [...new Set(item.channels.map((channel) => channel.channel))].sort();
}

function channelSummary(item: MarketingContentItem): string {
  const channels = channelNames(item);
  return channels.length ? channels.map(humanize).join(" / ") : "No channel";
}

function destinationAccountLabel(
  account: NonNullable<
    NonNullable<MarketingContentItem["channels"][number]["destination_readiness"]>["account"]
  >,
): string {
  return account.handle ?? account.display_name ?? account.id;
}

function channelDestinationSummaries(item: MarketingContentItem): string[] {
  if (!item.channels.length) {
    return ["No channel"];
  }
  return item.channels.map((channel) => {
    const readiness = channel.destination_readiness;
    const account = readiness?.account ? ` ${destinationAccountLabel(readiness.account)}` : "";
    return `${humanize(channel.channel)}${account} ${readiness?.label ?? "No Account Selected"}`;
  });
}

function destinationReadinessVariant(
  readiness: MarketingContentItem["channels"][number]["destination_readiness"] | undefined,
) {
  if (readiness?.status === "ready") {
    return "success" as const;
  }
  if (readiness?.status === "assisted" || readiness?.status === "missing_account") {
    return "warning" as const;
  }
  return "neutral" as const;
}

function channelPlacementSummary(item: MarketingContentItem): string {
  const placements = [
    ...new Set(
      item.channels.map((channel) =>
        channel.placement
          ? `${humanize(channel.channel)} / ${humanize(channel.placement)}`
          : humanize(channel.channel),
      ),
    ),
  ].sort();
  return placements.length ? placements.join(", ") : "No placements";
}

function campaignName(campaigns: Campaign[], campaignId: string): string {
  return campaigns.find((campaign) => campaign.id === campaignId)?.name ?? campaignId;
}

function relationshipLabel(value: string | null): string {
  return value ? value : "Not linked";
}

function copyPreview(item: MarketingContentItem): string {
  const copy = item.copy_text?.trim();
  if (copy) {
    return copy;
  }
  const channelCopy = item.channels
    .map((channel) => channel.copy_text_override?.trim())
    .find((value): value is string => Boolean(value));
  return channelCopy ?? "No caption yet";
}

function ownerCreatorLabel(item: MarketingContentItem): string {
  if (item.owner_profile_id) {
    return `Owner ${item.owner_profile_id}`;
  }
  if (item.created_by_profile_id) {
    return `Creator ${item.created_by_profile_id}`;
  }
  if (item.created_by_user_id) {
    return `Creator ${item.created_by_user_id}`;
  }
  return "Unassigned";
}

function revisionLabel(item: MarketingContentItem): string {
  return item.approved_revision === null || item.approved_revision === undefined
    ? `Revision ${item.content_revision}`
    : `Revision ${item.content_revision} / approved ${item.approved_revision}`;
}

function filtersActive(filters: CalendarFilters | DraftFilters): boolean {
  return Object.values(filters).some((value) => value.trim().length > 0);
}

type CalendarFilters = {
  artistId: string;
  campaignId: string;
  channel: string;
  releaseId: string;
  status: string;
};

type DraftUpdatedFilter = "" | "7" | "30";

type DraftFilters = {
  artistId: string;
  campaignId: string;
  channel: string;
  contentType: string;
  ownerProfileId: string;
  releaseId: string;
  search: string;
  updatedWithinDays: DraftUpdatedFilter;
};

const emptyDraftFilters: DraftFilters = {
  artistId: "",
  campaignId: "",
  channel: "",
  contentType: "",
  ownerProfileId: "",
  releaseId: "",
  search: "",
  updatedWithinDays: "",
};

type ContentEditorMode = "create" | "edit";
type ContentEditorSurface = "calendar" | "drafts";

type ChannelFormRow = {
  id: string;
  persistedId?: string;
  channel: string;
  placement: string;
  socialAccountConnectionId: string;
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

function accountConnectionLabel(connection: SocialAccountConnection): string {
  const handle =
    connection.handle ?? connection.display_name ?? connection.external_account_id ?? connection.id;
  const mode = connection.capabilities.includes("content_publish")
    ? "Automatic Publishing"
    : "Assisted Publishing";
  return `${handle} - ${mode}`;
}

function accountConnectionWarning(connection: SocialAccountConnection): string | null {
  if (connection.status === "disconnected") {
    return "Disconnected";
  }
  if (connection.status === "reconnect_required") {
    return "Reconnect required";
  }
  if (
    !connection.capabilities.includes("content_publish") &&
    !connection.capabilities.includes("manual_publish")
  ) {
    return "Missing publishing capability";
  }
  return null;
}

function emptyChannelRow(index: number): ChannelFormRow {
  return {
    assetRefsJson: "",
    channel: index === 0 ? "instagram" : "",
    copyTextOverride: "",
    id: `channel_${Date.now()}_${index}`,
    placement: index === 0 ? "feed" : "",
    socialAccountConnectionId: "",
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
        persistedId: channel.id,
        placement: channel.placement ?? "",
        socialAccountConnectionId: channel.social_account_connection_id ?? "",
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
      ...(channel.persistedId ? { id: channel.persistedId } : {}),
      asset_refs: parseAssetRefs(channel.assetRefsJson, "Channel asset references"),
      channel: channel.channel,
      copy_text_override: channel.copyTextOverride || null,
      placement: channel.placement || null,
      social_account_connection_id: channel.socialAccountConnectionId || null,
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
  canEdit,
  canArchive,
  canSubmitForReview,
  createDate,
  filters,
  item,
  mode,
  onCancel,
  onArchived,
  onOpenApprovalReview,
  onSaved,
  surface,
  timeZone,
}: {
  campaigns: Campaign[];
  canEdit: boolean;
  canArchive: boolean;
  canSubmitForReview: boolean;
  createDate: string | null;
  filters: CalendarFilters;
  item: MarketingContentItem | null;
  mode: ContentEditorMode;
  onCancel: () => void;
  onArchived: (item: MarketingContentItem) => void;
  onOpenApprovalReview: (approvalRequestId: string | null) => void;
  onSaved: (item: MarketingContentItem | null) => void;
  surface: ContentEditorSurface;
  timeZone: string;
}) {
  const [form, setForm] = useState(() =>
    initialFormState({ campaigns, createDate, filters, item }),
  );
  const [clientError, setClientError] = useState<string | null>(null);
  const selectedCampaign = campaigns.find((campaign) => campaign.id === form.campaignId) ?? null;
  const workspaceId = selectedCampaign?.workspace_id ?? item?.workspace_id ?? null;
  const socialAccounts = useSocialAccountConnections(workspaceId, {
    include_disconnected: true,
    limit: 100,
    offset: 0,
  });
  const create = useCreateMarketingContentItem(
    workspaceId,
    mode === "create" ? form.campaignId || null : null,
  );
  const update = useUpdateMarketingContentItem(
    workspaceId,
    item?.campaign_id ?? null,
    item?.id ?? null,
  );
  const submitApproval = useSubmitMarketingContentForApproval(
    workspaceId,
    item?.campaign_id ?? null,
    item?.id ?? null,
  );
  const archive = useArchiveMarketingContentItem(
    workspaceId,
    item?.campaign_id ?? null,
    item?.id ?? null,
  );
  const transitionStatus = useTransitionMarketingContentStatus(
    workspaceId,
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
  const releaseOptions = (
    selectedCampaign
      ? [
          ...(selectedCampaign.release ? [selectedCampaign.release] : []),
          ...selectedCampaign.releases.map((entry) => entry.release),
        ].filter(
          (release, index, releases) =>
            releases.findIndex((entry) => entry.id === release.id) === index,
        )
      : []
  ).filter(
    (release) => !form.artistId || !release.artist_id || release.artist_id === form.artistId,
  );
  const ownerOptions = selectedCampaign?.members ?? [];
  const duplicateChannels = duplicateChannelTargets(form.channels);
  const mutationError =
    create.error ?? update.error ?? submitApproval.error ?? archive.error ?? transitionStatus.error;
  const isMutating =
    create.isMutating ||
    update.isMutating ||
    submitApproval.isMutating ||
    archive.isMutating ||
    transitionStatus.isMutating;
  const approvalState = item?.approval_state?.state ?? item?.status;
  const isCurrentlyApproved = item ? approvedRevisionIsCurrent(item) : false;
  const scheduleEligible = item ? canScheduleApprovedRevision(item) : false;
  const isDraftSurface = surface === "drafts";
  const accountConnections = socialAccounts.data?.social_account_connections ?? [];

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
        const saved = await create.mutate(payload);
        onSaved(saved);
      } else {
        if (
          isCurrentlyApproved &&
          !window.confirm(
            "This content is currently approved. Saving material edits will require reapproval before scheduling.",
          )
        ) {
          return;
        }
        const saved = await update.mutate(payload as MarketingContentItemUpdate);
        onSaved(saved);
      }
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
      await submitApproval.mutate({ expected_resource_revision: item.content_revision });
      onSaved(null);
    } catch {
      // The mutation state renders API denial and invalid transition messages.
    }
  }

  async function scheduleApproved() {
    setClientError(null);
    if (!item) {
      return;
    }
    try {
      const saved = await transitionStatus.mutate({ status: "scheduled" });
      onSaved(saved);
    } catch {
      // The mutation state renders exact-revision approval failures.
    }
  }

  async function archiveContent() {
    setClientError(null);
    if (!item) {
      return;
    }
    if (
      !window.confirm(
        `Archive "${item.title}"? It will be hidden from active Draft Posts and retained in Marketing Content history.`,
      )
    ) {
      return;
    }
    try {
      const archived = await archive.mutate();
      onArchived(archived);
    } catch {
      // The mutation state renders API authorization and lifecycle failures.
    }
  }

  return (
    <Card className="grid gap-4 p-4" role="region" aria-label="Marketing content editor">
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">
            {mode === "create"
              ? surface === "drafts"
                ? "Create draft post"
                : "Create content draft"
              : "Edit content"}
          </h2>
          <p className="text-sm text-slate-500">
            {isDraftSurface
              ? "Author channel-specific draft copy, assets, placements, and optional planned times before approval."
              : "Schedule for calendar by setting a planned publish time. LabelOS will not automatically publish posts yet."}
          </p>
          {item ? (
            <p className="mt-1 text-xs font-medium text-slate-500">
              Current status: {humanize(item.status)} - Approval: {approvalStateLabel(item)} -
              Revision {item.content_revision}
            </p>
          ) : null}
        </div>
        <Button onClick={onCancel} size="sm" type="button" variant="secondary">
          Close
        </Button>
      </div>

      {clientError || mutationError ? (
        <div
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
          role="alert"
        >
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
            {(() => {
              const providerAccounts = accountConnections.filter(
                (connection) => connection.provider === channel.channel,
              );
              const selectedAccount =
                accountConnections.find(
                  (connection) => connection.id === channel.socialAccountConnectionId,
                ) ?? null;
              const accountWarning = selectedAccount
                ? accountConnectionWarning(selectedAccount)
                : null;
              return (
                <>
                  <div className="grid gap-3 md:grid-cols-[1fr_1fr_1fr_auto]">
                    <label className="grid gap-1 text-sm font-medium text-slate-700">
                      <span>Channel</span>
                      <select
                        className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                        disabled={!isEditable}
                        onChange={(event) =>
                          setChannel(channel.id, {
                            channel: event.target.value,
                            socialAccountConnectionId: "",
                          })
                        }
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
                        onChange={(event) =>
                          setChannel(channel.id, { placement: event.target.value })
                        }
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
                        onChange={(event) =>
                          setChannel(channel.id, { scheduledAt: event.target.value })
                        }
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
                    <span>Destination account</span>
                    <select
                      className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                      disabled={!isEditable || !channel.channel}
                      onChange={(event) =>
                        setChannel(channel.id, { socialAccountConnectionId: event.target.value })
                      }
                      value={channel.socialAccountConnectionId}
                    >
                      <option value="">{humanize(channel.channel)} - No account selected</option>
                      {providerAccounts.map((connection) => (
                        <option key={connection.id} value={connection.id}>
                          {accountConnectionLabel(connection)}
                        </option>
                      ))}
                    </select>
                    {socialAccounts.error ? (
                      <span className="text-xs font-normal text-amber-700">
                        Account destinations could not be loaded.
                      </span>
                    ) : null}
                    {accountWarning ? (
                      <span className="text-xs font-medium text-amber-700">{accountWarning}</span>
                    ) : null}
                  </label>
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
                      onChange={(event) =>
                        setChannel(channel.id, { assetRefsJson: event.target.value })
                      }
                      placeholder="[]"
                      value={channel.assetRefsJson}
                    />
                  </label>
                  <p className="text-xs text-slate-500">Target {index + 1}</p>
                </>
              );
            })()}
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button disabled={!isEditable || isMutating} onClick={saveDraft} type="button">
          {mode === "create" ? "Save draft" : "Save changes"}
        </Button>
        {item?.status === "draft" && approvalState !== "changes_requested" && canSubmitForReview ? (
          <Button disabled={isMutating} onClick={submitForReview} type="button" variant="secondary">
            Submit for approval
          </Button>
        ) : null}
        {item?.status === "draft" && approvalState === "changes_requested" && canSubmitForReview ? (
          <Button disabled={isMutating} onClick={submitForReview} type="button" variant="secondary">
            Resubmit for approval
          </Button>
        ) : null}
        {item?.approval_request_id ? (
          <Button
            disabled={isMutating}
            onClick={() => onOpenApprovalReview(item.approval_request_id)}
            type="button"
            variant="secondary"
          >
            Open Approval Review
          </Button>
        ) : null}
        {item?.status === "approved" && canEdit ? (
          <Button
            disabled={isMutating || !scheduleEligible}
            onClick={scheduleApproved}
            type="button"
          >
            Schedule
          </Button>
        ) : null}
        {item?.status === "approved" && canEdit && !scheduleEligible ? (
          <span className="text-sm text-amber-700">
            Scheduling is blocked until approval matches the current revision.
          </span>
        ) : null}
        {item && isDraftSurface && canArchive && item.status === "draft" ? (
          <Button disabled={isMutating} onClick={archiveContent} type="button" variant="secondary">
            {archive.isMutating ? "Archiving..." : "Archive"}
          </Button>
        ) : null}
        {!isEditable ? (
          <span className="text-sm text-slate-500">
            You need edit access to change this content.
          </span>
        ) : null}
      </div>
    </Card>
  );
}

function contentDetailErrorMessage(code: string | undefined): string {
  if (code === "unauthorized") {
    return "Sign in again to open this marketing content.";
  }
  if (code === "forbidden") {
    return "You do not have access to this marketing content.";
  }
  if (code === "not_found") {
    return "This marketing content is missing or was deleted.";
  }
  return "Marketing content detail could not be loaded.";
}

function ContentEditorDetail({
  campaigns,
  canEdit,
  canArchive,
  canSubmitForReview,
  createDate,
  filters,
  item,
  mode,
  onCancel,
  onArchived,
  onOpenApprovalReview,
  onSaved,
  surface,
  timeZone,
}: {
  campaigns: Campaign[];
  canEdit: boolean;
  canArchive: boolean;
  canSubmitForReview: boolean;
  createDate: string | null;
  filters: CalendarFilters;
  item: MarketingContentItem | null;
  mode: ContentEditorMode;
  onCancel: () => void;
  onArchived: (item: MarketingContentItem) => void;
  onOpenApprovalReview: (approvalRequestId: string | null) => void;
  onSaved: (item: MarketingContentItem | null) => void;
  surface: ContentEditorSurface;
  timeZone: string;
}) {
  const detail = useMarketingContentItem(
    mode === "edit" ? (item?.workspace_id ?? null) : null,
    mode === "edit" ? (item?.campaign_id ?? null) : null,
    mode === "edit" ? (item?.id ?? null) : null,
  );

  if (mode === "edit") {
    if (detail.isLoading && !detail.data) {
      return (
        <Card className="grid gap-3 p-4" role="region" aria-label="Marketing content editor">
          <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-950">Edit content</h2>
              <p className="text-sm text-slate-500">Loading the latest marketing content.</p>
            </div>
            <Button onClick={onCancel} size="sm" type="button" variant="secondary">
              Close
            </Button>
          </div>
          <LoadingState label="Loading marketing content detail" />
        </Card>
      );
    }

    if (detail.error || !detail.data) {
      return (
        <Card className="grid gap-4 p-4" role="region" aria-label="Marketing content editor">
          <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-950">Edit content</h2>
              <p className="text-sm text-slate-500">{item?.title ?? "Marketing content detail"}</p>
            </div>
            <Button onClick={onCancel} size="sm" type="button" variant="secondary">
              Close
            </Button>
          </div>
          <div
            className={cn(
              "rounded-md border px-4 py-3 text-sm",
              detail.error?.code === "unauthorized" || detail.error?.code === "forbidden"
                ? "border-amber-200 bg-amber-50 text-amber-900"
                : "border-red-200 bg-red-50 text-red-900",
            )}
            role={
              detail.error?.code === "unauthorized" || detail.error?.code === "forbidden"
                ? "status"
                : "alert"
            }
          >
            {contentDetailErrorMessage(detail.error?.code)}
          </div>
          {detail.error?.code !== "not_found" ? (
            <Button
              disabled={detail.isLoading}
              onClick={() => void detail.reload().catch(() => undefined)}
              size="sm"
              type="button"
              variant="secondary"
            >
              Retry
            </Button>
          ) : null}
        </Card>
      );
    }
  }

  const canonicalItem = mode === "edit" ? detail.data : item;

  return (
    <ContentEditor
      campaigns={campaigns}
      canEdit={canEdit}
      canArchive={canArchive}
      canSubmitForReview={canSubmitForReview}
      createDate={createDate}
      filters={filters}
      item={canonicalItem}
      key={canonicalItem ? `${canonicalItem.id}:${canonicalItem.updated_at}` : undefined}
      mode={mode}
      onCancel={onCancel}
      onArchived={onArchived}
      onOpenApprovalReview={onOpenApprovalReview}
      onSaved={onSaved}
      surface={surface}
      timeZone={timeZone}
    />
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
                    <span className="grid gap-0.5">
                      {channelDestinationSummaries(instance.item).map((summary, index) => (
                        <span className="truncate text-xs text-slate-600" key={index}>
                          {summary}
                        </span>
                      ))}
                    </span>
                    <span className="flex flex-wrap items-center gap-1">
                      <Badge
                        className="max-w-full truncate"
                        variant={approvalStateVariant(instance.item)}
                      >
                        {approvalStateLabel(instance.item)}
                      </Badge>
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
                <Badge variant={approvalStateVariant(instance.item)}>
                  {approvalStateLabel(instance.item)}
                </Badge>
              </div>
              <p className="mt-1 text-sm text-slate-500">
                {humanize(instance.item.content_type)} - {channelSummary(instance.item)}
              </p>
              <div className="mt-2 flex flex-wrap gap-1">
                {instance.item.channels.length ? (
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

function draftOwnerOptions(campaigns: Campaign[]) {
  return [
    ...campaigns.flatMap((campaign) => [
      ...(campaign.owner ? [campaign.owner] : []),
      ...campaign.members.map((member) => ({
        display_name: member.display_name,
        profile_id: member.profile_id,
      })),
    ]),
  ].filter(
    (owner, index, owners) =>
      owners.findIndex((entry) => entry.profile_id === owner.profile_id) === index,
  );
}

function draftSearchText(item: MarketingContentItem): string {
  return [item.title, item.copy_text, ...item.channels.map((channel) => channel.copy_text_override)]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function draftMatchesSearch(item: MarketingContentItem, search: string): boolean {
  const query = search.trim().toLowerCase();
  return !query || draftSearchText(item).includes(query);
}

function draftRecentlyUpdated(item: MarketingContentItem, updatedWithinDays: DraftUpdatedFilter) {
  if (!updatedWithinDays) {
    return true;
  }
  const updatedAt = new Date(item.updated_at).getTime();
  if (Number.isNaN(updatedAt)) {
    return false;
  }
  const days = Number(updatedWithinDays);
  return updatedAt >= Date.now() - days * 24 * 60 * 60 * 1000;
}

function DraftsTab({
  canCreate,
  canArchive,
  canSubmitForReview,
  campaigns,
  onCreate,
  onArchived,
  onItemClick,
  savedRevision,
  workspaceId,
}: {
  canCreate: boolean;
  canArchive: boolean;
  canSubmitForReview: boolean;
  campaigns: Campaign[];
  onCreate: () => void;
  onArchived: (item: MarketingContentItem) => void;
  onItemClick: (item: MarketingContentItem) => void;
  savedRevision: number;
  workspaceId: string;
}) {
  const [filters, setFilters] = useState<DraftFilters>(emptyDraftFilters);
  const [archivedDraftIds, setArchivedDraftIds] = useState<Set<string>>(() => new Set());
  const updateFilter = useCallback((next: Partial<DraftFilters>) => {
    setFilters((current) => ({ ...current, ...next }));
  }, []);
  const resetFilters = useCallback(() => setFilters(emptyDraftFilters), []);
  const draftOptions = useMemo<MarketingContentListOptions>(
    () => ({
      artist_id: filters.artistId.trim() || null,
      campaign_id: filters.campaignId || null,
      channel: filters.channel || null,
      content_type: filters.contentType || null,
      limit: 500,
      offset: 0,
      owner_profile_id: filters.ownerProfileId || null,
      release_id: filters.releaseId.trim() || null,
      status: "draft",
    }),
    [
      filters.artistId,
      filters.campaignId,
      filters.channel,
      filters.contentType,
      filters.ownerProfileId,
      filters.releaseId,
    ],
  );
  const drafts = useWorkspaceMarketingContent(workspaceId, draftOptions);
  const markArchived = useCallback(
    (archived: MarketingContentItem) => {
      setArchivedDraftIds((current) => new Set(current).add(archived.id));
      onArchived(archived);
      void Promise.resolve(drafts.reload()).catch(() => undefined);
    },
    [drafts.reload, onArchived],
  );
  useEffect(() => {
    if (savedRevision > 0) {
      void Promise.resolve(drafts.reload()).catch(() => undefined);
    }
  }, [drafts.reload, savedRevision]);
  useEffect(() => {
    if (!drafts.data) {
      return;
    }
    const activeIds = new Set(
      drafts.data.marketing_content
        .filter((draft) => draft.status === "draft")
        .map((draft) => draft.id),
    );
    setArchivedDraftIds((current) => {
      const next = new Set([...current].filter((id) => activeIds.has(id)));
      const unchanged = next.size === current.size && [...next].every((id) => current.has(id));
      return unchanged ? current : next;
    });
  }, [drafts.data]);
  const serverDraftItems = (drafts.data?.marketing_content ?? []).filter(
    (draft) => draft.status === "draft" && !archivedDraftIds.has(draft.id),
  );
  const draftItems = useMemo(
    () =>
      serverDraftItems
        .filter(
          (draft) =>
            draftMatchesSearch(draft, filters.search) &&
            draftRecentlyUpdated(draft, filters.updatedWithinDays),
        )
        .sort(
          (left, right) =>
            new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime() ||
            left.title.localeCompare(right.title),
        ),
    [filters.search, filters.updatedWithinDays, serverDraftItems],
  );
  const activeFilters = filtersActive(filters);
  const ownerOptions = draftOwnerOptions(campaigns);
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
    <section className="grid gap-4" aria-label="Draft posts">
      <Card className="grid gap-1">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">Draft Posts</h2>
            <p className="text-sm text-slate-500">
              Unsubmitted marketing content where status is draft.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge>
              {draftItems.length}
              {activeFilters ? ` of ${serverDraftItems.length}` : ""} drafts
            </Badge>
            {canCreate ? (
              <Button onClick={onCreate} size="sm" type="button">
                Create Draft
              </Button>
            ) : null}
          </div>
        </div>
      </Card>

      <Card className="grid gap-3 p-4">
        <div className="grid gap-3 lg:grid-cols-[minmax(220px,1.5fr)_repeat(3,minmax(150px,1fr))]">
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            <span>Search title or copy</span>
            <input
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
              onChange={(event) => updateFilter({ search: event.target.value })}
              placeholder="Search drafts"
              type="search"
              value={filters.search}
            />
          </label>
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            <span>Campaign</span>
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
              onChange={(event) => updateFilter({ campaignId: event.target.value })}
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
            <span>Channel</span>
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
              onChange={(event) => updateFilter({ channel: event.target.value })}
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
            <span>Content type</span>
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
              onChange={(event) => updateFilter({ contentType: event.target.value })}
              value={filters.contentType}
            >
              <option value="">Any type</option>
              {contentTypeOptions.map((contentType) => (
                <option key={contentType} value={contentType}>
                  {humanize(contentType)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="grid gap-3 md:grid-cols-4">
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            <span>Artist</span>
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
              onChange={(event) => updateFilter({ artistId: event.target.value })}
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
              onChange={(event) => updateFilter({ releaseId: event.target.value })}
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
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            <span>Owner</span>
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
              onChange={(event) => updateFilter({ ownerProfileId: event.target.value })}
              value={filters.ownerProfileId}
            >
              <option value="">Any owner</option>
              {ownerOptions.map((owner) => (
                <option key={owner.profile_id} value={owner.profile_id}>
                  {owner.display_name ?? owner.profile_id}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            <span>Recently updated</span>
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
              onChange={(event) =>
                updateFilter({ updatedWithinDays: event.target.value as DraftUpdatedFilter })
              }
              value={filters.updatedWithinDays}
            >
              <option value="">Any time</option>
              <option value="7">Last 7 days</option>
              <option value="30">Last 30 days</option>
            </select>
          </label>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-slate-500">
            Draft status is fixed. Linked filters use the marketing content API; search and updated
            recency apply to the loaded draft set.
          </p>
          <Button
            disabled={!activeFilters}
            onClick={resetFilters}
            size="sm"
            type="button"
            variant="secondary"
          >
            Clear filters
          </Button>
        </div>
      </Card>

      {drafts.error ? (
        <div
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
          role="alert"
        >
          {drafts.error.code === "forbidden"
            ? "Marketing content access was denied for drafts."
            : "Draft posts could not be loaded."}
        </div>
      ) : null}

      {drafts.isLoading && !drafts.data ? (
        <Card className="grid gap-3">
          <LoadingState label="Loading draft posts" />
          {Array.from({ length: 3 }, (_, index) => (
            <div className="h-14 rounded-md bg-slate-100 auth-shimmer" key={index} />
          ))}
        </Card>
      ) : draftItems.length === 0 ? (
        <EmptyState
          description={
            activeFilters
              ? "Try clearing filters or broadening the search terms."
              : "Draft posts appear here before they are submitted for approval or scheduled."
          }
          action={
            activeFilters ? (
              <Button onClick={resetFilters} type="button" variant="secondary">
                Clear filters
              </Button>
            ) : null
          }
          title={activeFilters ? "No matching draft posts" : "No draft posts"}
        />
      ) : (
        <Card className="overflow-hidden p-0">
          <div className="divide-y divide-slate-100">
            {draftItems.map((draft) => (
              <DraftRow
                canArchive={canArchive}
                canSubmitForReview={canSubmitForReview}
                campaigns={campaigns}
                draft={draft}
                key={draft.id}
                onArchived={markArchived}
                onItemClick={onItemClick}
                onSubmitted={() => void Promise.resolve(drafts.reload()).catch(() => undefined)}
                workspaceId={workspaceId}
              />
            ))}
          </div>
        </Card>
      )}
    </section>
  );
}

function DraftRow({
  canArchive,
  canSubmitForReview,
  campaigns,
  draft,
  onArchived,
  onItemClick,
  onSubmitted,
  workspaceId,
}: {
  canArchive: boolean;
  canSubmitForReview: boolean;
  campaigns: Campaign[];
  draft: MarketingContentItem;
  onArchived: (item: MarketingContentItem) => void;
  onItemClick: (item: MarketingContentItem) => void;
  onSubmitted: () => void;
  workspaceId: string;
}) {
  const submitApproval = useSubmitMarketingContentForApproval(
    workspaceId,
    draft.campaign_id,
    draft.id,
  );
  const archive = useArchiveMarketingContentItem(workspaceId, draft.campaign_id, draft.id);
  const approvalState = draft.approval_state?.state ?? draft.status;
  const canSubmitDraft = canSubmitForReview && draft.status === "draft";
  const submitLabel =
    approvalState === "changes_requested" ? "Resubmit for approval" : "Submit for approval";

  async function submitForReview() {
    try {
      await submitApproval.mutate({ expected_resource_revision: draft.content_revision });
      onSubmitted();
    } catch {
      // Mutation state renders the existing approval eligibility/capability errors.
    }
  }

  async function archiveDraft() {
    if (
      !window.confirm(
        `Archive "${draft.title}"? It will be hidden from active Draft Posts and retained in Marketing Content history.`,
      )
    ) {
      return;
    }
    try {
      const archived = await archive.mutate();
      onArchived(archived);
    } catch {
      // Mutation state renders authorization and API failures inline.
    }
  }

  return (
    <article className="grid gap-4 px-4 py-4 transition hover:bg-slate-50 md:grid-cols-[minmax(0,1.4fr)_minmax(160px,0.8fr)_minmax(150px,0.7fr)_minmax(150px,0.7fr)_auto]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="truncate text-sm font-semibold text-slate-950">{draft.title}</h3>
          <Badge variant={approvalStateVariant(draft)}>{approvalStateLabel(draft)}</Badge>
          <Badge>{revisionLabel(draft)}</Badge>
        </div>
        <p className="mt-2 line-clamp-2 text-sm text-slate-600">{copyPreview(draft)}</p>
        <p className="mt-2 truncate text-xs text-slate-500">
          {humanize(draft.content_type)} - {channelSummary(draft)}
        </p>
      </div>
      <div>
        <p className="text-xs font-semibold uppercase text-slate-500">Campaign</p>
        <p className="mt-1 truncate text-sm font-medium text-slate-800">
          {campaignName(campaigns, draft.campaign_id)}
        </p>
        <p className="mt-1 truncate text-xs text-slate-500">
          Artist: {relationshipLabel(draft.artist_id)}
        </p>
        <p className="truncate text-xs text-slate-500">
          Release: {relationshipLabel(draft.release_id)}
        </p>
      </div>
      <div>
        <p className="text-xs font-semibold uppercase text-slate-500">Placements</p>
        <p className="mt-1 line-clamp-2 text-sm font-medium text-slate-800">
          {channelPlacementSummary(draft)}
        </p>
      </div>
      <div>
        <p className="text-xs font-semibold uppercase text-slate-500">Updated</p>
        <p className="mt-1 truncate text-sm font-medium text-slate-800">
          {draft.updated_at.slice(0, 10)}
        </p>
        <p className="mt-1 truncate text-xs text-slate-500">{ownerCreatorLabel(draft)}</p>
      </div>
      <div className="flex flex-wrap items-start gap-2 md:justify-end">
        <Button
          aria-label={`Open draft ${draft.title}`}
          onClick={() => onItemClick(draft)}
          size="sm"
          type="button"
          variant="secondary"
        >
          Open
        </Button>
        {canSubmitDraft ? (
          <Button
            aria-label={`${submitLabel} ${draft.title}`}
            disabled={submitApproval.isMutating}
            onClick={submitForReview}
            size="sm"
            type="button"
            variant="secondary"
          >
            {submitApproval.isMutating ? "Submitting..." : submitLabel}
          </Button>
        ) : null}
        {canArchive ? (
          <Button
            aria-label={`Archive draft ${draft.title}`}
            disabled={archive.isMutating}
            onClick={archiveDraft}
            size="sm"
            type="button"
            variant="secondary"
          >
            {archive.isMutating ? "Archiving..." : "Archive"}
          </Button>
        ) : null}
        {submitApproval.error || archive.error ? (
          <p className="basis-full text-xs font-medium text-red-700" role="alert">
            {submitApproval.error?.message ?? archive.error?.message}
          </p>
        ) : null}
      </div>
    </article>
  );
}

function actorName(actor: ApprovalActor | null | undefined): string {
  return actor?.display_name ?? actor?.profile_id ?? actor?.user_id ?? "Unassigned";
}

function approvalStatusVariant(status: ApprovalRequestStatus) {
  if (status === "approved") {
    return "success" as const;
  }
  if (status === "rejected" || status === "invalidated") {
    return "warning" as const;
  }
  if (status === "changes_requested" || status === "requested" || status === "in_review") {
    return "warning" as const;
  }
  return "neutral" as const;
}

function approvalQueueOptions(view: ApprovalQueueView): ApprovalListOptions {
  const base = {
    limit: 50,
    offset: 0,
    resource_type: approvalQueueResourceType,
  } satisfies ApprovalListOptions;
  if (view === "awaiting_review") {
    return { ...base, assigned_to_me: true, status: "in_review" };
  }
  if (view === "submitted_by_me") {
    return { ...base, submitted_by_me: true };
  }
  if (view === "changes_requested") {
    return { ...base, status: "changes_requested" };
  }
  if (view === "approved" || view === "rejected") {
    return { ...base, status: view };
  }
  return base;
}

function actionRequiredFor(
  approval: ApprovalRequestSummary,
  currentProfileId: string | null | undefined,
): boolean {
  return (
    Boolean(currentProfileId) &&
    (approval.status === "requested" || approval.status === "in_review") &&
    approval.stage_assignment?.profile_id === currentProfileId
  );
}

function hasStructuredFeedback(decision: ApprovalDecision): boolean {
  return Boolean(decision.payload && Object.keys(decision.payload).length > 0);
}

function ApprovalQueue({
  currentProfileId,
  focusedApprovalId,
  onOpenCalendarItem,
  timeZone,
  workspaceId,
}: {
  currentProfileId: string | null | undefined;
  focusedApprovalId: string | null;
  onOpenCalendarItem: (contentItemId: string, campaignId: string | null) => void;
  timeZone: string;
  workspaceId: string;
}) {
  const [view, setView] = useState<ApprovalQueueView>("awaiting_review");
  const [selectedApprovalId, setSelectedApprovalId] = useState<string | null>(focusedApprovalId);
  const options = useMemo(() => approvalQueueOptions(view), [view]);
  const queue = useApprovalQueue(workspaceId, options);
  const realtime = useOrganizationRealtimeContext();
  const latestApprovalEvent = realtime?.recentActivityEvents.find((event) =>
    event.type.startsWith("approval."),
  );
  const approvals = queue.data?.approvals ?? [];

  useEffect(() => {
    if (focusedApprovalId) {
      setSelectedApprovalId(focusedApprovalId);
    }
  }, [focusedApprovalId]);

  return (
    <section className="grid gap-4" aria-label="Marketing approval queue">
      <div className="flex flex-col gap-3 rounded-md border border-slate-200 bg-white p-4 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">Approval Queue</h2>
          <p className="text-sm text-slate-500">
            Marketing content requests filtered to {approvalQueueResourceType}.
          </p>
        </div>
        <Button
          disabled={queue.isLoading}
          onClick={() => void queue.reload().catch(() => undefined)}
          size="sm"
          type="button"
          variant="secondary"
        >
          Refresh
        </Button>
      </div>

      <Card className="grid gap-3 p-4">
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Approval queue views">
          {approvalQueueViews.map((entry) => (
            <button
              aria-selected={view === entry.id}
              className={cn(
                "rounded-md border px-3 py-2 text-sm font-medium transition",
                view === entry.id
                  ? "border-slate-950 bg-slate-950 text-white"
                  : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50",
              )}
              key={entry.id}
              onClick={() => {
                setView(entry.id);
                setSelectedApprovalId(null);
              }}
              role="tab"
              type="button"
            >
              {entry.label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
          <span>{queue.data ? `${queue.data.total} approvals` : "Loading approvals"}</span>
          {latestApprovalEvent ? (
            <span aria-live="polite">
              Realtime refresh: {latestApprovalEvent.type} at{" "}
              {formatCalendarDateTime(latestApprovalEvent.createdAt, timeZone)}
            </span>
          ) : null}
        </div>
      </Card>

      {queue.error ? (
        <div
          className={cn(
            "rounded-md border px-4 py-3 text-sm",
            queue.error.code === "unauthorized" || queue.error.code === "forbidden"
              ? "border-amber-200 bg-amber-50 text-amber-900"
              : "border-red-200 bg-red-50 text-red-900",
          )}
          role={
            queue.error.code === "unauthorized" || queue.error.code === "forbidden"
              ? "status"
              : "alert"
          }
        >
          {queue.error.message}
        </div>
      ) : null}

      {queue.isLoading && !queue.data ? (
        <Card className="grid gap-3">
          <LoadingState label="Loading approval queue" />
          {Array.from({ length: 3 }, (_, index) => (
            <div className="h-20 rounded-md bg-slate-100 auth-shimmer" key={index} />
          ))}
        </Card>
      ) : null}

      {!queue.isLoading && !queue.error && approvals.length === 0 ? (
        <EmptyState
          description={
            view === "awaiting_review"
              ? "No marketing content approvals require your review."
              : "No marketing content approvals match this queue view."
          }
          title="No approvals in this queue"
        />
      ) : null}

      {approvals.length > 0 ? (
        <Card className="overflow-hidden p-0">
          <div className="divide-y divide-slate-100">
            {approvals.map((approval) => {
              const actionRequired = actionRequiredFor(approval, currentProfileId);
              return (
                <button
                  aria-pressed={selectedApprovalId === approval.id}
                  className="grid w-full gap-3 px-4 py-4 text-left transition hover:bg-slate-50 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_170px_160px]"
                  key={approval.id}
                  onClick={() => setSelectedApprovalId(approval.id)}
                  type="button"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="truncate text-sm font-semibold text-slate-950">
                        {approval.title}
                      </h3>
                      <Badge variant={approvalStatusVariant(approval.status)}>
                        {humanize(approval.status)}
                      </Badge>
                      {actionRequired ? <Badge variant="warning">Action required</Badge> : null}
                    </div>
                    <p className="mt-1 line-clamp-2 text-sm text-slate-600">
                      {approval.summary ?? "No content preview provided."}
                    </p>
                    <p className="mt-2 text-xs text-slate-500">
                      Submitted revision {approval.submitted_revision}
                    </p>
                  </div>
                  <div className="min-w-0">
                    <p className="text-xs font-semibold uppercase text-slate-500">Context</p>
                    <p className="mt-1 truncate text-sm font-medium text-slate-800">
                      {approval.campaign?.name ?? "Campaign not linked"}
                    </p>
                    <p className="truncate text-xs text-slate-500">
                      {approval.artist?.name ?? "Artist not linked"}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs font-semibold uppercase text-slate-500">People</p>
                    <p className="mt-1 truncate text-sm text-slate-800">
                      Submitter: {actorName(approval.submitter)}
                    </p>
                    <p className="truncate text-xs text-slate-500">
                      Reviewer: {actorName(approval.stage_assignment)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs font-semibold uppercase text-slate-500">Submitted</p>
                    <p className="mt-1 text-sm font-medium text-slate-800">
                      {formatCalendarDateTime(approval.submitted_at, timeZone)}
                    </p>
                    {approval.resolved_at ? (
                      <p className="text-xs text-slate-500">
                        Resolved {formatCalendarDateTime(approval.resolved_at, timeZone)}
                      </p>
                    ) : null}
                  </div>
                </button>
              );
            })}
          </div>
        </Card>
      ) : null}

      {selectedApprovalId ? (
        <ApprovalReviewDetail
          currentProfileId={currentProfileId}
          onClose={() => setSelectedApprovalId(null)}
          onOpenCalendarItem={onOpenCalendarItem}
          timeZone={timeZone}
          workspaceId={workspaceId}
          approvalRequestId={selectedApprovalId}
        />
      ) : null}
    </section>
  );
}

function ApprovalReviewDetail({
  approvalRequestId,
  currentProfileId,
  onClose,
  onOpenCalendarItem,
  timeZone,
  workspaceId,
}: {
  approvalRequestId: string;
  currentProfileId: string | null | undefined;
  onClose: () => void;
  onOpenCalendarItem: (contentItemId: string, campaignId: string | null) => void;
  timeZone: string;
  workspaceId: string;
}) {
  const detail = useApprovalRequest(workspaceId, approvalRequestId);
  const approve = useApprovalDecision(workspaceId, approvalRequestId, "approved");
  const requestChanges = useApprovalDecision(workspaceId, approvalRequestId, "changes_requested");
  const reject = useApprovalDecision(workspaceId, approvalRequestId, "rejected");
  const cancel = useApprovalDecision(workspaceId, approvalRequestId, "cancelled");
  const [reason, setReason] = useState("");
  const [clientError, setClientError] = useState<string | null>(null);
  const selected = detail.data;
  const decisionError = approve.error ?? requestChanges.error ?? reject.error ?? cancel.error;
  const isMutating =
    approve.isMutating || requestChanges.isMutating || reject.isMutating || cancel.isMutating;
  const availableActions = new Set<ApprovalAction>(selected?.available_actions ?? []);
  const actionRequired = selected ? actionRequiredFor(selected, currentProfileId) : false;
  const currentRevision =
    selected?.current_resource_revision ??
    selected?.marketing_content_preview?.current_revision ??
    null;
  const isStale =
    Boolean(selected?.is_stale) ||
    (currentRevision !== null && selected
      ? currentRevision !== selected.submitted_revision
      : false);
  const resolved =
    Boolean(selected?.resolved_at) ||
    ["approved", "rejected", "cancelled", "invalidated"].includes(selected?.status ?? "");

  async function decide(action: ApprovalAction) {
    setClientError(null);
    const trimmedReason = reason.trim();
    if ((action === "rejected" || action === "changes_requested") && !trimmedReason) {
      setClientError("A reason is required for rejection and requested changes.");
      return;
    }
    const mutation =
      action === "approved"
        ? approve
        : action === "changes_requested"
          ? requestChanges
          : action === "rejected"
            ? reject
            : cancel;
    try {
      await mutation.mutate({
        idempotency_key: `${approvalRequestId}:${action}:${Date.now()}`,
        reason: trimmedReason || null,
      });
      setReason("");
      await detail.reload().catch(() => undefined);
    } catch {
      // The mutation state renders the API error.
    }
  }

  return (
    <Card className="grid gap-4 p-4" role="region" aria-label="Approval review detail">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">Review detail</p>
          <h2 className="text-lg font-semibold text-slate-950">
            {selected?.title ?? "Approval request"}
          </h2>
          <p className="text-sm text-slate-500">Request {approvalRequestId}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {selected?.marketing_content_preview ? (
            <Button
              onClick={() =>
                onOpenCalendarItem(
                  selected.marketing_content_preview?.id ?? selected.resource_id,
                  selected.campaign?.id ?? null,
                )
              }
              size="sm"
              type="button"
              variant="secondary"
            >
              Open calendar item
            </Button>
          ) : null}
          <Button onClick={onClose} size="sm" type="button" variant="secondary">
            Close
          </Button>
        </div>
      </div>

      {detail.isLoading && !selected ? <LoadingState label="Loading approval detail" /> : null}

      {detail.error ? (
        <div
          className={cn(
            "rounded-md border px-4 py-3 text-sm",
            detail.error.code === "unauthorized" || detail.error.code === "forbidden"
              ? "border-amber-200 bg-amber-50 text-amber-900"
              : "border-red-200 bg-red-50 text-red-900",
          )}
          role={
            detail.error.code === "unauthorized" || detail.error.code === "forbidden"
              ? "status"
              : "alert"
          }
        >
          {detail.error.message}
        </div>
      ) : null}

      {selected ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={approvalStatusVariant(selected.status)}>
              {humanize(selected.status)}
            </Badge>
            <Badge variant={actionRequired ? "warning" : "neutral"}>
              {actionRequired ? "Action required from you" : "No action required"}
            </Badge>
            {isStale ? <Badge variant="warning">Stale approval</Badge> : null}
            {resolved ? <Badge variant="neutral">Resolved</Badge> : null}
          </div>

          {isStale ? (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              This request was submitted for revision {selected.submitted_revision}, but the current
              content revision is {currentRevision ?? "unknown"}. Review the latest calendar item
              before making a decision.
            </div>
          ) : null}

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
            <div className="grid gap-4">
              <section
                className="grid gap-2 rounded-md border border-slate-200 p-4"
                aria-label="Content preview"
              >
                <h3 className="text-base font-semibold text-slate-950">Content preview</h3>
                <p className="text-sm font-medium text-slate-800">
                  {selected.marketing_content_preview?.title ?? selected.title}
                </p>
                <p className="whitespace-pre-wrap text-sm leading-6 text-slate-600">
                  {selected.marketing_content_preview?.copy_text ??
                    selected.summary ??
                    "No preview copy was provided."}
                </p>
                <p className="text-xs text-slate-500">
                  Type: {humanize(selected.marketing_content_preview?.content_type)}
                </p>
              </section>

              <section
                className="grid gap-2 rounded-md border border-slate-200 p-4"
                aria-label="Decision history"
              >
                <h3 className="text-base font-semibold text-slate-950">Decision history</h3>
                {selected.decision_history.length === 0 ? (
                  <p className="text-sm text-slate-500">No decisions have been recorded yet.</p>
                ) : (
                  <ol className="grid gap-3">
                    {selected.decision_history.map((decision) => (
                      <li
                        className="rounded-md border border-slate-100 bg-slate-50 p-3"
                        key={decision.id}
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-sm font-semibold text-slate-900">
                            {humanize(decision.decision)}
                          </p>
                          <p className="text-xs text-slate-500">
                            {formatCalendarDateTime(decision.created_at, timeZone)}
                          </p>
                        </div>
                        <p className="mt-1 text-xs text-slate-500">
                          By{" "}
                          {decision.decided_by_profile_id ??
                            decision.decided_by_user_id ??
                            decision.actor_key ??
                            decision.actor_kind}
                        </p>
                        {decision.reason ? (
                          <p className="mt-2 text-sm text-slate-700">{decision.reason}</p>
                        ) : null}
                        {hasStructuredFeedback(decision) ? (
                          <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-white p-2 text-xs text-slate-700">
                            {JSON.stringify(decision.payload, null, 2)}
                          </pre>
                        ) : null}
                      </li>
                    ))}
                  </ol>
                )}
              </section>
            </div>

            <aside className="grid content-start gap-4">
              <section
                className="grid gap-3 rounded-md border border-slate-200 p-4"
                aria-label="Approval context"
              >
                <h3 className="text-base font-semibold text-slate-950">Context</h3>
                <dl className="grid gap-2 text-sm">
                  <div>
                    <dt className="text-xs font-semibold uppercase text-slate-500">Campaign</dt>
                    <dd className="text-slate-800">{selected.campaign?.name ?? "Not linked"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase text-slate-500">Artist</dt>
                    <dd className="text-slate-800">{selected.artist?.name ?? "Not linked"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase text-slate-500">Release</dt>
                    <dd className="text-slate-800">{selected.release?.name ?? "Not linked"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase text-slate-500">
                      Channels and placements
                    </dt>
                    <dd className="text-slate-800">
                      {selected.channels.length
                        ? selected.channels
                            .map(
                              (channel) =>
                                `${humanize(channel.channel)} / ${humanize(channel.placement)}`,
                            )
                            .join(", ")
                        : "Not provided"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase text-slate-500">
                      Submission note
                    </dt>
                    <dd className="text-slate-800">{selected.summary ?? "No note provided"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase text-slate-500">
                      Current stage
                    </dt>
                    <dd className="text-slate-800">
                      {selected.current_stage
                        ? `${humanize(selected.current_stage.status)} stage ${selected.current_stage.stage_order}`
                        : "No active stage"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase text-slate-500">
                      Reviewer assignment
                    </dt>
                    <dd className="text-slate-800">{actorName(selected.stage_assignment)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase text-slate-500">Revisions</dt>
                    <dd className="text-slate-800">
                      Submitted {selected.submitted_revision}; current{" "}
                      {currentRevision ?? "unknown"}
                    </dd>
                  </div>
                </dl>
              </section>

              <section
                className="grid gap-3 rounded-md border border-slate-200 p-4"
                aria-label="Approval decision"
              >
                <h3 className="text-base font-semibold text-slate-950">Decision</h3>
                {clientError || decisionError ? (
                  <div
                    className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900"
                    role="alert"
                  >
                    {clientError ?? decisionError?.message}
                  </div>
                ) : null}
                <label className="grid gap-1 text-sm font-medium text-slate-700">
                  <span>Reason or feedback</span>
                  <textarea
                    className="min-h-24 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950"
                    disabled={isMutating || resolved}
                    onChange={(event) => {
                      setClientError(null);
                      setReason(event.target.value);
                    }}
                    value={reason}
                  />
                </label>
                <div className="flex flex-wrap gap-2">
                  {availableActions.has("approved") ? (
                    <Button
                      disabled={isMutating || resolved}
                      onClick={() => void decide("approved")}
                      type="button"
                    >
                      {approve.isMutating ? "Approving..." : "Approve"}
                    </Button>
                  ) : null}
                  {availableActions.has("changes_requested") ? (
                    <Button
                      disabled={isMutating || resolved}
                      onClick={() => void decide("changes_requested")}
                      type="button"
                      variant="secondary"
                    >
                      {requestChanges.isMutating ? "Requesting..." : "Request changes"}
                    </Button>
                  ) : null}
                  {availableActions.has("rejected") ? (
                    <Button
                      disabled={isMutating || resolved}
                      onClick={() => void decide("rejected")}
                      type="button"
                      variant="secondary"
                    >
                      {reject.isMutating ? "Rejecting..." : "Reject"}
                    </Button>
                  ) : null}
                  {availableActions.has("cancelled") ? (
                    <Button
                      disabled={isMutating || resolved}
                      onClick={() => void decide("cancelled")}
                      type="button"
                      variant="secondary"
                    >
                      {cancel.isMutating ? "Cancelling..." : "Cancel request"}
                    </Button>
                  ) : null}
                </div>
                {!availableActions.size || resolved ? (
                  <p className="text-sm text-slate-500">
                    No approval actions are currently available.
                  </p>
                ) : null}
              </section>
            </aside>
          </div>
        </>
      ) : null}
    </Card>
  );
}

type SocialAccountFormState = {
  provider: SocialAccountProvider;
  artistProfileId: string;
  handle: string;
  displayName: string;
  profileUrl: string;
  capabilities: SocialAccountCapability[];
  providerMetadataJson: string;
};

function emptySocialAccountForm(): SocialAccountFormState {
  return {
    artistProfileId: "",
    capabilities: ["manual_publish"],
    displayName: "",
    handle: "",
    profileUrl: "",
    provider: "instagram",
    providerMetadataJson: "",
  };
}

function socialAccountFormFromConnection(
  connection: SocialAccountConnection,
): SocialAccountFormState {
  return {
    artistProfileId: connection.artist_association?.artist_profile_id ?? "",
    capabilities: connection.capabilities.length ? connection.capabilities : ["manual_publish"],
    displayName: connection.display_name ?? "",
    handle: connection.handle ?? "",
    profileUrl: connection.profile_url ?? "",
    provider: connection.provider,
    providerMetadataJson: Object.keys(connection.provider_metadata).length
      ? JSON.stringify(connection.provider_metadata, null, 2)
      : "",
  };
}

function parseMetadataJson(value: string): Record<string, unknown> {
  const trimmed = value.trim();
  if (!trimmed) {
    return {};
  }
  const parsed = JSON.parse(trimmed) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Provider metadata must be a JSON object.");
  }
  return parsed as Record<string, unknown>;
}

function providerLabel(provider: SocialAccountProvider): string {
  if (provider === "x") {
    return "X";
  }
  if (provider === "tiktok") {
    return "TikTok";
  }
  if (provider === "youtube") {
    return "YouTube";
  }
  return humanize(provider);
}

function connectionModeLabel(
  connection: Pick<SocialAccountConnection, "connection_method">,
): string {
  if (connection.connection_method === "assisted") {
    return "Assisted Publishing";
  }
  if (connection.connection_method === "direct_api") {
    return "Direct API";
  }
  return "Third-party";
}

function socialStatusVariant(status: SocialAccountConnectionStatus) {
  if (status === "connected") {
    return "success" as const;
  }
  if (status === "limited" || status === "reconnect_required" || status === "error") {
    return "warning" as const;
  }
  return "neutral" as const;
}

function socialAttentionLabel(connection: SocialAccountConnection): string {
  if (connection.status === "connected") {
    return "Active";
  }
  if (connection.status === "limited") {
    return "Limited access";
  }
  if (connection.status === "reconnect_required") {
    return "Needs reconnect";
  }
  if (connection.status === "error") {
    return connection.last_error_message ?? "Needs attention";
  }
  if (connection.status === "disconnected") {
    return "Disconnected";
  }
  return "Pending setup";
}

function capabilityLabel(capability: SocialAccountCapability): string {
  if (capability === "content_publish") {
    return "Auto-publish content";
  }
  if (capability === "manual_publish") {
    return "Assisted publishing checklist";
  }
  if (capability === "manual_metrics") {
    return "Manual metrics entry";
  }
  if (capability === "account_analytics_read") {
    return "Account analytics reference";
  }
  if (capability === "post_analytics_read") {
    return "Post analytics reference";
  }
  return humanize(capability);
}

function accountDisplayName(connection: SocialAccountConnection): string {
  return (
    connection.handle ||
    connection.display_name ||
    connection.external_account_id ||
    "Unnamed account"
  );
}

function providerAccountCount(
  accounts: SocialAccountConnection[],
  provider: (typeof socialAccountProviders)[number],
): number {
  return accounts.filter((account) => account.provider.toLowerCase() === provider).length;
}

function campaignArtistOptions(campaigns: Campaign[]) {
  return [
    ...campaigns.flatMap((campaign) => [
      ...(campaign.primary_artist ? [campaign.primary_artist] : []),
      ...campaign.artists.map((entry) => entry.artist),
    ]),
  ].filter(
    (artist, index, artists) => artists.findIndex((entry) => entry.id === artist.id) === index,
  );
}

function capabilityText(connection: SocialAccountConnection): string {
  const labels = connection.capabilities.map(capabilityLabel);
  if (connection.resolved_capabilities.requires_manual_publish && !labels.length) {
    labels.push("Assisted publishing checklist");
  }
  return labels.length ? labels.join(", ") : "No capabilities configured";
}

function isYouTubeDirectOAuthEnabled(): boolean {
  return process.env.NEXT_PUBLIC_YOUTUBE_DIRECT_OAUTH_ENABLED === "true";
}

function SocialAccountsTab({
  campaigns,
  canManage,
  workspaceId,
}: {
  campaigns: Campaign[];
  canManage: boolean;
  workspaceId: string;
}) {
  const accounts = useSocialAccountConnections(workspaceId, {
    include_disconnected: true,
    limit: 100,
    offset: 0,
  });
  const create = useCreateAssistedSocialAccountConnection(workspaceId);
  const youtubeOAuth = useStartSocialAccountOAuthConnection(workspaceId);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<SocialAccountFormState>(() => emptySocialAccountForm());
  const [clientError, setClientError] = useState<string | null>(null);
  const accountItems = accounts.data?.social_account_connections ?? [];
  const artistOptions = campaignArtistOptions(campaigns);
  const youtubeDirectOAuthEnabled = isYouTubeDirectOAuthEnabled();

  function updateCapability(capability: SocialAccountCapability, checked: boolean) {
    setForm((current) => ({
      ...current,
      capabilities: checked
        ? [...new Set([...current.capabilities, capability])]
        : current.capabilities.filter((entry) => entry !== capability),
    }));
  }

  async function registerAccount() {
    setClientError(null);
    try {
      await create.mutate({
        artist_profile_id: form.artistProfileId.trim() || null,
        capabilities: form.capabilities,
        display_name: form.displayName.trim() || null,
        handle: form.handle.trim() || null,
        profile_url: form.profileUrl.trim() || null,
        provider: form.provider,
        provider_metadata: parseMetadataJson(form.providerMetadataJson),
      } satisfies AssistedSocialAccountConnectionCreate);
      setForm(emptySocialAccountForm());
      setShowForm(false);
      void accounts.reload().catch(() => undefined);
    } catch (error) {
      setClientError(
        error instanceof SyntaxError
          ? "Provider metadata must be valid JSON."
          : (error as Error).message,
      );
    }
  }

  async function connectYouTube() {
    setClientError(null);
    try {
      const redirectUri = `${window.location.origin}/api/social-account-connections/oauth/youtube/callback`;
      const result = await youtubeOAuth.mutate({
        provider: "youtube",
        redirect_uri: redirectUri,
        safe_redirect_path: "/marketing?tab=accounts",
      });
      navigateToSocialAccountAuthorization(result.authorization_url);
    } catch (error) {
      setClientError((error as Error).message);
    }
  }

  return (
    <section className="grid gap-4" aria-label="Social account connections">
      <Card className="grid gap-1">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">Social Account Connections</h2>
            <p className="text-sm text-slate-500">
              Registered destinations for assisted and direct provider workflows.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge>{accountItems.length} accounts</Badge>
            {canManage && youtubeDirectOAuthEnabled ? (
              <Button
                disabled={youtubeOAuth.isMutating}
                onClick={connectYouTube}
                size="sm"
                type="button"
                variant="secondary"
              >
                {youtubeOAuth.isMutating ? "Connecting..." : "Connect YouTube"}
              </Button>
            ) : null}
            {canManage ? (
              <Button onClick={() => setShowForm((current) => !current)} size="sm" type="button">
                {showForm ? "Close" : "Register Account"}
              </Button>
            ) : null}
          </div>
        </div>
      </Card>

      {!canManage ? (
        <div
          className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
          role="status"
        >
          You can view social accounts, but need marketing account manage access to register, edit,
          or disconnect them.
        </div>
      ) : null}

      <Card className="grid gap-3 p-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
          {socialAccountProviders.map((provider) => {
            const count = providerAccountCount(accountItems, provider);
            return (
              <div className="rounded-md border border-slate-200 p-3" key={provider}>
                <p className="text-sm font-semibold text-slate-950">{providerLabel(provider)}</p>
                <p className="mt-1 text-xs text-slate-500">
                  {count
                    ? `${count} registered`
                    : provider === "youtube" && youtubeDirectOAuthEnabled
                      ? "Ready for direct connection"
                      : "Direct connection not yet available"}
                </p>
                <p className="mt-2 text-xs font-medium text-slate-700">
                  {provider === "youtube" && youtubeDirectOAuthEnabled
                    ? "Direct API supported"
                    : "Assisted Mode supported"}
                </p>
              </div>
            );
          })}
        </div>
      </Card>

      {showForm && canManage ? (
        <Card className="grid gap-4 p-4" role="region" aria-label="Assisted account registration">
          <div>
            <h3 className="text-base font-semibold text-slate-950">Register Assisted Account</h3>
            <p className="text-sm text-slate-500">
              This records the account and supported manual workflows. It does not create a direct
              provider login.
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              <span>Provider</span>
              <select
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    provider: event.target.value as SocialAccountProvider,
                  }))
                }
                value={form.provider}
              >
                {socialAccountProviders.map((provider) => (
                  <option key={provider} value={provider}>
                    {providerLabel(provider)}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              <span>Handle</span>
              <input
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                onChange={(event) =>
                  setForm((current) => ({ ...current, handle: event.target.value }))
                }
                placeholder="@artist"
                value={form.handle}
              />
            </label>
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              <span>Display name</span>
              <input
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                onChange={(event) =>
                  setForm((current) => ({ ...current, displayName: event.target.value }))
                }
                value={form.displayName}
              />
            </label>
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              <span>Artist profile ID</span>
              <input
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                list="social-account-artist-options"
                onChange={(event) =>
                  setForm((current) => ({ ...current, artistProfileId: event.target.value }))
                }
                placeholder="artist_profile_..."
                value={form.artistProfileId}
              />
              <datalist id="social-account-artist-options">
                {artistOptions.map((artist) => (
                  <option key={artist.id} value={artist.id}>
                    {artist.name}
                  </option>
                ))}
              </datalist>
            </label>
            <label className="grid gap-1 text-sm font-medium text-slate-700 md:col-span-2">
              <span>Profile URL</span>
              <input
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                onChange={(event) =>
                  setForm((current) => ({ ...current, profileUrl: event.target.value }))
                }
                placeholder="https://..."
                type="url"
                value={form.profileUrl}
              />
            </label>
          </div>
          <fieldset className="grid gap-2">
            <legend className="text-sm font-medium text-slate-700">LabelOS can</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {assistedCapabilityOptions.map((capability) => (
                <label className="flex items-center gap-2 text-sm text-slate-700" key={capability}>
                  <input
                    checked={form.capabilities.includes(capability)}
                    onChange={(event) => updateCapability(capability, event.target.checked)}
                    type="checkbox"
                  />
                  <span>{capabilityLabel(capability)}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            <span>Provider metadata JSON</span>
            <textarea
              className="min-h-24 rounded-md border border-slate-300 bg-white px-3 py-2 font-mono text-sm text-slate-950"
              onChange={(event) =>
                setForm((current) => ({ ...current, providerMetadataJson: event.target.value }))
              }
              placeholder='{"source":"artist-submitted"}'
              value={form.providerMetadataJson}
            />
          </label>
          {clientError || create.error ? (
            <p className="text-sm font-medium text-red-700" role="alert">
              {clientError ?? create.error?.message}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button disabled={create.isMutating} onClick={registerAccount} type="button">
              {create.isMutating ? "Registering..." : "Register Assisted Account"}
            </Button>
            <Button
              onClick={() => {
                setShowForm(false);
                setClientError(null);
              }}
              type="button"
              variant="secondary"
            >
              Cancel
            </Button>
          </div>
        </Card>
      ) : null}

      {accounts.error ? (
        <div
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
          role="alert"
        >
          {accounts.error.code === "forbidden"
            ? "Social account access was denied for this workspace."
            : "Social account connections could not be loaded."}
        </div>
      ) : null}

      {accounts.isLoading && !accounts.data ? (
        <Card className="grid gap-3">
          <LoadingState label="Loading social account connections" />
          {Array.from({ length: 3 }, (_, index) => (
            <div className="h-20 rounded-md bg-slate-100 auth-shimmer" key={index} />
          ))}
        </Card>
      ) : accountItems.length === 0 ? (
        <EmptyState
          action={
            canManage ? (
              <Button onClick={() => setShowForm(true)} type="button">
                Register Account
              </Button>
            ) : null
          }
          description="Register assisted social accounts to track provider, artist, publishing mode, capabilities, and attention states before OAuth is available."
          title="No social accounts registered"
        />
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {accountItems.map((connection) => (
            <SocialAccountCard
              canManage={canManage}
              connection={connection}
              key={connection.id}
              onChanged={() => void accounts.reload().catch(() => undefined)}
              workspaceId={workspaceId}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function SocialAccountCard({
  canManage,
  connection,
  onChanged,
  workspaceId,
}: {
  canManage: boolean;
  connection: SocialAccountConnection;
  onChanged: () => void;
  workspaceId: string;
}) {
  const update = useUpdateSocialAccountConnection(workspaceId, connection.id);
  const disconnect = useDisconnectSocialAccountConnection(workspaceId, connection.id);
  const [isEditing, setIsEditing] = useState(false);
  const [localConnection, setLocalConnection] = useState(connection);
  const [form, setForm] = useState(() => socialAccountFormFromConnection(connection));
  const [clientError, setClientError] = useState<string | null>(null);

  useEffect(() => {
    setLocalConnection(connection);
    setForm(socialAccountFormFromConnection(connection));
  }, [connection]);

  function updateCapability(capability: SocialAccountCapability, checked: boolean) {
    setForm((current) => ({
      ...current,
      capabilities: checked
        ? [...new Set([...current.capabilities, capability])]
        : current.capabilities.filter((entry) => entry !== capability),
    }));
  }

  async function saveAccount() {
    setClientError(null);
    try {
      const saved = await update.mutate({
        artist_profile_id: form.artistProfileId.trim() || null,
        capabilities: form.capabilities,
        display_name: form.displayName.trim() || null,
        handle: form.handle.trim() || null,
        profile_url: form.profileUrl.trim() || null,
        provider_metadata: parseMetadataJson(form.providerMetadataJson),
      });
      setLocalConnection(saved);
      setIsEditing(false);
      onChanged();
    } catch (error) {
      setClientError(
        error instanceof SyntaxError
          ? "Provider metadata must be valid JSON."
          : (error as Error).message,
      );
    }
  }

  async function disconnectAccount() {
    if (
      !window.confirm(
        `Disconnect ${providerLabel(localConnection.provider)} ${accountDisplayName(
          localConnection,
        )}? It will remain visible in social account history.`,
      )
    ) {
      return;
    }
    try {
      const disconnected = await disconnect.mutate();
      setLocalConnection(disconnected);
      onChanged();
    } catch {
      // Mutation state renders API failures inline.
    }
  }

  return (
    <Card className="grid gap-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-base font-semibold text-slate-950">
              {providerLabel(localConnection.provider)}
            </h3>
            <Badge variant={socialStatusVariant(localConnection.status)}>
              {humanize(localConnection.status)}
            </Badge>
            <Badge>{connectionModeLabel(localConnection)}</Badge>
          </div>
          <p className="mt-1 truncate text-sm font-medium text-slate-800">
            {accountDisplayName(localConnection)}
          </p>
          <p className="mt-1 text-xs text-slate-500">Direct connection not yet available</p>
        </div>
        {canManage ? (
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => {
                setIsEditing((current) => !current);
                setClientError(null);
              }}
              size="sm"
              type="button"
              variant="secondary"
            >
              {isEditing ? "Close" : "Edit"}
            </Button>
            {localConnection.status !== "disconnected" ? (
              <Button
                disabled={disconnect.isMutating}
                onClick={disconnectAccount}
                size="sm"
                type="button"
                variant="secondary"
              >
                {disconnect.isMutating ? "Disconnecting..." : "Disconnect"}
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>

      <dl className="grid gap-3 sm:grid-cols-2">
        <div>
          <dt className="text-xs font-semibold uppercase text-slate-500">Artist</dt>
          <dd className="mt-1 text-sm font-medium text-slate-800">
            {localConnection.artist_association?.stage_name ??
              localConnection.artist_association?.artist_name ??
              "Unassigned"}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase text-slate-500">Attention</dt>
          <dd className="mt-1 text-sm font-medium text-slate-800">
            {socialAttentionLabel(localConnection)}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase text-slate-500">LabelOS can</dt>
          <dd className="mt-1 text-sm font-medium text-slate-800">
            {capabilityText(localConnection)}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase text-slate-500">Last checked</dt>
          <dd className="mt-1 text-sm font-medium text-slate-800">
            {localConnection.last_health_checked_at?.slice(0, 10) ?? "Not checked"}
          </dd>
        </div>
      </dl>

      {isEditing ? (
        <div className="grid gap-3 border-t border-slate-100 pt-4">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              <span>Handle</span>
              <input
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                onChange={(event) =>
                  setForm((current) => ({ ...current, handle: event.target.value }))
                }
                value={form.handle}
              />
            </label>
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              <span>Display name</span>
              <input
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                onChange={(event) =>
                  setForm((current) => ({ ...current, displayName: event.target.value }))
                }
                value={form.displayName}
              />
            </label>
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              <span>Artist profile ID</span>
              <input
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                onChange={(event) =>
                  setForm((current) => ({ ...current, artistProfileId: event.target.value }))
                }
                value={form.artistProfileId}
              />
            </label>
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              <span>Profile URL</span>
              <input
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                onChange={(event) =>
                  setForm((current) => ({ ...current, profileUrl: event.target.value }))
                }
                type="url"
                value={form.profileUrl}
              />
            </label>
          </div>
          <fieldset className="grid gap-2">
            <legend className="text-sm font-medium text-slate-700">Capabilities</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {assistedCapabilityOptions.map((capability) => (
                <label className="flex items-center gap-2 text-sm text-slate-700" key={capability}>
                  <input
                    checked={form.capabilities.includes(capability)}
                    onChange={(event) => updateCapability(capability, event.target.checked)}
                    type="checkbox"
                  />
                  <span>{capabilityLabel(capability)}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            <span>Provider metadata JSON</span>
            <textarea
              className="min-h-24 rounded-md border border-slate-300 bg-white px-3 py-2 font-mono text-sm text-slate-950"
              onChange={(event) =>
                setForm((current) => ({ ...current, providerMetadataJson: event.target.value }))
              }
              value={form.providerMetadataJson}
            />
          </label>
          {clientError || update.error || disconnect.error ? (
            <p className="text-sm font-medium text-red-700" role="alert">
              {clientError ?? update.error?.message ?? disconnect.error?.message}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button disabled={update.isMutating} onClick={saveAccount} size="sm" type="button">
              {update.isMutating ? "Saving..." : "Save changes"}
            </Button>
            <Button
              onClick={() => {
                setForm(socialAccountFormFromConnection(localConnection));
                setIsEditing(false);
                setClientError(null);
              }}
              size="sm"
              type="button"
              variant="secondary"
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : null}

      {!isEditing && disconnect.error ? (
        <p className="text-sm font-medium text-red-700" role="alert">
          {disconnect.error.message}
        </p>
      ) : null}
    </Card>
  );
}

export function MarketingWorkspace() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { activeWorkspace } = useActiveWorkspace();
  const workspaceProfile = useActiveWorkspaceProfile();
  const tabParam = searchParams.get("tab");
  const initialTab: MarketingTab =
    tabParam === "accounts" || tabParam === "approvals" || tabParam === "drafts"
      ? tabParam
      : "calendar";
  const [activeTab, setActiveTab] = useState<MarketingTab>(initialTab);
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
  const [monthDate, setMonthDate] = useState(() => currentCalendarMonthDate(timeZone));
  const [editor, setEditor] = useState<
    | {
        key: string;
        mode: "create";
        item: null;
        createDate: string | null;
        surface: ContentEditorSurface;
      }
    | {
        key: string;
        mode: "edit";
        item: MarketingContentItem;
        createDate: null;
        surface: ContentEditorSurface;
      }
    | null
  >(() =>
    createDate
      ? {
          createDate,
          item: null,
          key: `create:${createDate}`,
          mode: "create",
          surface: "calendar",
        }
      : null,
  );
  const [savedRevision, setSavedRevision] = useState(0);
  const [saveNotice, setSaveNotice] = useState<string | null>(null);
  const [focusedApprovalId, setFocusedApprovalId] = useState<string | null>(
    searchParams.get("approvalRequestId"),
  );
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
  const canArchive =
    workspaceProfile.subject && activeWorkspace
      ? can(workspaceProfile.subject, null, capabilities.marketingContentArchive)
      : false;
  const canSubmitForReview =
    workspaceProfile.subject && activeWorkspace
      ? can(workspaceProfile.subject, null, capabilities.marketingContentSubmitForReview)
      : false;
  const canViewAccounts =
    workspaceProfile.subject && activeWorkspace
      ? can(workspaceProfile.subject, null, capabilities.marketingAccountView)
      : false;
  const canManageAccounts =
    workspaceProfile.subject && activeWorkspace
      ? can(workspaceProfile.subject, null, capabilities.marketingAccountManage)
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
    [
      filters.artistId,
      filters.campaignId,
      filters.channel,
      filters.releaseId,
      filters.status,
      range,
    ],
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
    (dateKey: string | null = null, surface: ContentEditorSurface = "calendar") => {
      setSaveNotice(null);
      setEditor({
        createDate: dateKey,
        item: null,
        key: `create:${surface}:${dateKey ?? "blank"}:${Date.now()}`,
        mode: "create",
        surface,
      });
      updateUrl(filters, dateKey ?? undefined);
    },
    [filters, updateUrl],
  );

  const openEditEditor = useCallback(
    (selectedItem: MarketingContentItem, surface: ContentEditorSurface) => {
      setSaveNotice(null);
      setEditor({
        createDate: null,
        item: selectedItem,
        key: `edit:${surface}:${selectedItem.id}:${selectedItem.updated_at}`,
        mode: "edit",
        surface,
      });
    },
    [],
  );

  const closeEditor = useCallback(() => {
    setEditor(null);
    setSaveNotice(null);
    updateUrl(filters);
  }, [filters, updateUrl]);

  const handleSaved = useCallback(
    (savedItem: MarketingContentItem | null) => {
      setEditor(null);
      updateUrl(filters);
      setSaveNotice(
        savedItem
          ? `Saved ${savedItem.title}. Revision ${savedItem.content_revision}.`
          : "Marketing content updated.",
      );
      setSavedRevision((current) => current + 1);
      void calendarContent.reload().catch(() => undefined);
    },
    [calendarContent, filters, updateUrl],
  );
  const handleArchived = useCallback(
    (archivedItem: MarketingContentItem) => {
      setEditor(null);
      updateUrl(filters);
      setSaveNotice(`Archived ${archivedItem.title}.`);
      setSavedRevision((current) => current + 1);
      void calendarContent.reload().catch(() => undefined);
    },
    [calendarContent, filters, updateUrl],
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
    setMonthDate((current) => addCalendarMonths(current, amount));
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

      {!canView && activeTab !== "accounts" && !workspaceProfile.isLoading ? (
        <div
          className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
          role="status"
        >
          You need marketing content view access to open the Marketing Hub.
        </div>
      ) : null}

      {activeTab === "accounts" && !canViewAccounts && !workspaceProfile.isLoading ? (
        <div
          className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
          role="status"
        >
          You need marketing account view access to open Social Account Connections.
        </div>
      ) : null}

      {saveNotice ? (
        <div
          className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900"
          role="status"
        >
          {saveNotice}
        </div>
      ) : null}

      {activeTab === "calendar" && canView ? (
        <section className="grid gap-4" aria-label="Marketing content calendar">
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
                onClick={() => {
                  setMonthDate(currentCalendarMonthDate(timeZone));
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
            <ContentEditorDetail
              campaigns={campaignList}
              canEdit={canEdit}
              canArchive={canArchive}
              canSubmitForReview={canSubmitForReview}
              createDate={editor.createDate}
              filters={filters}
              item={editor.item}
              key={editor.key}
              mode={editor.mode}
              onCancel={closeEditor}
              onArchived={handleArchived}
              onOpenApprovalReview={(approvalRequestId) => {
                setFocusedApprovalId(approvalRequestId);
                setActiveTab("approvals");
                setEditor(null);
              }}
              onSaved={handleSaved}
              surface={editor.surface}
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
              onItemClick={(selectedItem) => openEditEditor(selectedItem, "calendar")}
              timeZone={timeZone}
            />
          ) : (
            <CalendarList
              campaigns={campaignList}
              instances={scheduleInstances}
              onItemClick={(selectedItem) => openEditEditor(selectedItem, "calendar")}
              timeZone={timeZone}
            />
          )}
        </section>
      ) : null}

      {activeTab === "approvals" && canView ? (
        <ApprovalQueue
          currentProfileId={workspaceProfile.membership?.profile.id}
          focusedApprovalId={focusedApprovalId}
          onOpenCalendarItem={(contentItemId, campaignId) => {
            const nextFilters = {
              ...filters,
              campaignId: campaignId ?? filters.campaignId,
            };
            setFocusedApprovalId(null);
            setFilters(nextFilters);
            updateUrl(nextFilters);
            setActiveTab("calendar");
            const selectedItem = items.find((entry) => entry.id === contentItemId);
            if (selectedItem) {
              openEditEditor(selectedItem, "calendar");
            }
          }}
          timeZone={timeZone}
          workspaceId={activeWorkspace.id}
        />
      ) : null}

      {activeTab === "drafts" && canView ? (
        <>
          <DraftsTab
            canCreate={canCreate}
            canArchive={canArchive}
            canSubmitForReview={canSubmitForReview}
            campaigns={campaignList}
            onCreate={() => openCreateEditor(null, "drafts")}
            onArchived={handleArchived}
            onItemClick={(selectedItem) => openEditEditor(selectedItem, "drafts")}
            savedRevision={savedRevision}
            workspaceId={activeWorkspace.id}
          />
          {editor ? (
            <ContentEditorDetail
              campaigns={campaignList}
              canEdit={canEdit}
              canArchive={canArchive}
              canSubmitForReview={canSubmitForReview}
              createDate={editor.createDate}
              filters={filters}
              item={editor.item}
              key={editor.key}
              mode={editor.mode}
              onCancel={closeEditor}
              onArchived={handleArchived}
              onOpenApprovalReview={(approvalRequestId) => {
                setFocusedApprovalId(approvalRequestId);
                setActiveTab("approvals");
                setEditor(null);
              }}
              onSaved={handleSaved}
              surface={editor.surface}
              timeZone={timeZone}
            />
          ) : null}
        </>
      ) : null}

      {activeTab === "accounts" && canViewAccounts ? (
        <SocialAccountsTab
          campaigns={campaignList}
          canManage={canManageAccounts}
          workspaceId={activeWorkspace.id}
        />
      ) : null}
    </div>
  );
}
