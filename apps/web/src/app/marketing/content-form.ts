import {
  type ScheduleDisambiguation,
  scheduleFromInstant,
  resolveSchedule,
} from "../../lib/schedule-timezones";
import { type Campaign } from "../../lib/campaigns";
import { type CalendarFilters } from "./marketing-presentation";
import {
  type MarketingContentItem,
  type MarketingContentItemCreate,
  type MarketingContentChannelCreate,
} from "../../lib/marketing-content";

export type ContentEditorMode = "create" | "edit";

export type ContentEditorSurface = "calendar" | "drafts";

export type ChannelFormRow = {
  id: string;
  legacyInstant?: string | null;
  legacyLocalTime?: string;
  persistedId?: string;
  channel: string;
  placement: string;
  socialAccountConnectionId: string;
  scheduledAt: string;
  scheduleTimezone: string;
  scheduleChoice: ScheduleDisambiguation;
  copyTextOverride: string;
  assetRefsJson: string;
};

export type ContentFormState = {
  campaignId: string;
  artistId: string;
  releaseId: string;
  title: string;
  contentType: string;
  copyText: string;
  assetRefsJson: string;
  ownerProfileId: string;
  scheduledAt: string;
  scheduleTimezone: string;
  scheduleChoice: ScheduleDisambiguation;
  channels: ChannelFormRow[];
};

function selectedDateInput(dateKey: string | null): string {
  return dateKey ? `${dateKey}T09:00` : "";
}

export function parseAssetRefs(value: string, fieldName: string): unknown[] {
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

export function duplicateChannelTargets(channels: ChannelFormRow[]): boolean {
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

export function emptyChannelRow(index: number, timeZone = "UTC"): ChannelFormRow {
  return {
    assetRefsJson: "",
    channel: index === 0 ? "instagram" : "",
    copyTextOverride: "",
    id: `channel_${Date.now()}_${index}`,
    placement: index === 0 ? "feed" : "",
    socialAccountConnectionId: "",
    scheduledAt: "",
    scheduleTimezone: timeZone,
    scheduleChoice: "",
  };
}

export function initialFormState({
  campaigns,
  createDate,
  filters,
  item,
  timeZone,
}: {
  timeZone: string;
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
        scheduledAt: scheduleFromInstant(
          channel.scheduled_at,
          channel.schedule_timezone || timeZone,
        ).localTime,
        scheduleTimezone: channel.schedule_timezone ?? (channel.scheduled_at ? "" : timeZone),
        scheduleChoice: channel.schedule_timezone
          ? scheduleFromInstant(channel.scheduled_at, channel.schedule_timezone).choice
          : "",
        legacyInstant: channel.schedule_timezone ? null : channel.scheduled_at,
        legacyLocalTime: scheduleFromInstant(
          channel.scheduled_at,
          channel.schedule_timezone || timeZone,
        ).localTime,
      })),
      contentType: item.content_type,
      copyText: item.copy_text ?? "",
      ownerProfileId: item.owner_profile_id ?? "",
      releaseId: item.release_id ?? "",
      scheduledAt: scheduleFromInstant(item.scheduled_at, timeZone).localTime,
      scheduleTimezone: timeZone,
      scheduleChoice: scheduleFromInstant(item.scheduled_at, timeZone).choice,
      title: item.title,
    };
  }
  const campaignId = filters.campaignId || campaigns[0]?.id || "";
  const campaign = campaigns.find((entry) => entry.id === campaignId);
  return {
    assetRefsJson: "",
    artistId: campaign?.primary_artist?.id ?? "",
    campaignId,
    channels: [emptyChannelRow(0, timeZone)],
    contentType: "social_post",
    copyText: "",
    ownerProfileId: campaign?.owner_profile_id ?? "",
    releaseId: campaign?.release?.id ?? "",
    scheduledAt: selectedDateInput(createDate),
    scheduleTimezone: timeZone,
    scheduleChoice: "",
    title: "",
  };
}

export function formToPayload(form: ContentFormState): MarketingContentItemCreate {
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
      ...(channel.scheduledAt
        ? !channel.scheduleTimezone &&
          channel.legacyInstant &&
          channel.scheduledAt === channel.legacyLocalTime
          ? { scheduled_at: channel.legacyInstant }
          : resolveSchedule(channel.scheduledAt, channel.scheduleTimezone, channel.scheduleChoice)
        : { scheduled_at: null }),
    })),
    content_type: form.contentType,
    copy_text: form.copyText || null,
    owner_profile_id: form.ownerProfileId || null,
    release_id: form.releaseId || null,
    scheduled_at: form.scheduledAt
      ? resolveSchedule(form.scheduledAt, form.scheduleTimezone, form.scheduleChoice).scheduled_at
      : null,
    title: form.title,
  };
}
