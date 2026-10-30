import {
  type MarketingContentItemStatus,
  type MarketingContentItem,
} from "../../lib/marketing-content";
import { calendarFallbackTimeZone } from "../../lib/calendar-dates";
import { type Campaign } from "../../lib/campaigns";

export const statuses: MarketingContentItemStatus[] = [
  "draft",
  "in_review",
  "approved",
  "scheduled",
  "published",
  "cancelled",
  "archived",
];

export const channelOptions = [
  "instagram",
  "tiktok",
  "youtube",
  "facebook",
  "x",
  "threads",
  "spotify",
  "email",
];

export const planningFallbackTimeZone = calendarFallbackTimeZone;

export function humanize(value: string | null | undefined): string {
  if (!value) {
    return "Not set";
  }
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

export function approvalStateVariant(item: MarketingContentItem) {
  const state = item.approval_state?.state ?? item.status;
  if (state === "approved" || state === "scheduled" || state === "published") {
    return "success" as const;
  }
  if (state === "in_review" || state === "changes_requested" || state === "reapproval_required") {
    return "warning" as const;
  }
  return statusVariant(item.status);
}

export function approvalStateLabel(item: MarketingContentItem): string {
  if (
    item.approval_state?.state === "scheduled" ||
    (!item.approval_state && item.status === "scheduled")
  )
    return "Planned";
  return item.approval_state?.label ?? humanize(item.status);
}

export function approvedRevisionIsCurrent(item: MarketingContentItem): boolean {
  return Boolean(
    item.approval_state?.approved_revision_is_current ??
    (item.approved_revision !== null &&
      item.approved_revision !== undefined &&
      item.approved_revision === item.content_revision),
  );
}

function channelNames(item: MarketingContentItem): string[] {
  return [...new Set(item.channels.map((channel) => channel.channel))].sort();
}

export function channelSummary(item: MarketingContentItem): string {
  const channels = channelNames(item);
  return channels.length ? channels.map(humanize).join(" / ") : "No channel";
}

export function destinationAccountLabel(
  account: NonNullable<
    NonNullable<MarketingContentItem["channels"][number]["destination_readiness"]>["account"]
  >,
): string {
  return account.handle ?? account.display_name ?? account.id;
}

export function channelDestinationSummaries(item: MarketingContentItem): string[] {
  if (!item.channels.length) {
    return ["No channel"];
  }
  return item.channels.map((channel) => {
    const readiness = channel.destination_readiness;
    const account = readiness?.account ? ` ${destinationAccountLabel(readiness.account)}` : "";
    return `${humanize(channel.channel)}${account} ${readiness?.label ?? "No Account Selected"}`;
  });
}

export function destinationReadinessVariant(
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

export function channelPlacementSummary(item: MarketingContentItem): string {
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

export function campaignName(campaigns: Campaign[], campaignId: string): string {
  return campaigns.find((campaign) => campaign.id === campaignId)?.name ?? campaignId;
}

export function relationshipLabel(value: string | null): string {
  return value ? value : "Not linked";
}

export function copyPreview(item: MarketingContentItem): string {
  const copy = item.copy_text?.trim();
  if (copy) {
    return copy;
  }
  const channelCopy = item.channels
    .map((channel) => channel.copy_text_override?.trim())
    .find((value): value is string => Boolean(value));
  return channelCopy ?? "No caption yet";
}

export function ownerCreatorLabel(item: MarketingContentItem): string {
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

export function revisionLabel(item: MarketingContentItem): string {
  return item.approved_revision === null || item.approved_revision === undefined
    ? `Revision ${item.content_revision}`
    : `Revision ${item.content_revision} / approved ${item.approved_revision}`;
}

export function filtersActive(filters: CalendarFilters | DraftFilters): boolean {
  return Object.values(filters).some((value) => value.trim().length > 0);
}

export type CalendarFilters = {
  artistId: string;
  campaignId: string;
  channel: string;
  releaseId: string;
  status: string;
};

export type DraftUpdatedFilter = "" | "7" | "30";

export type DraftFilters = {
  artistId: string;
  campaignId: string;
  channel: string;
  contentType: string;
  ownerProfileId: string;
  releaseId: string;
  search: string;
  updatedWithinDays: DraftUpdatedFilter;
};

export const contentTypeOptions = [
  "social_post",
  "video",
  "email",
  "ad",
  "press",
  "playlist_pitch",
];
