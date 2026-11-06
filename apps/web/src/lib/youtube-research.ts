export type Provenance = {
  collected_at: string;
  expires_at: string;
  source_url: string;
  provider_fields: { key: string; value: string }[];
};
export type ChannelCandidate = { external_id: string; name: string; provenance: Provenance };
export type ChannelDisplay = {
  artist: ChannelCandidate;
  items: { metric_key: string; value: number; provenance: Provenance }[];
};

export const researchMessages: Record<string, string> = {
  quota_exceeded:
    "YouTube's daily request limit has been reached. Please try after the daily reset.",
  rate_limited: "YouTube requests are paused. Please wait before trying again.",
  timeout: "YouTube took too long to respond. You can try again.",
  data_unavailable: "This channel is deleted, private, or otherwise unavailable on YouTube.",
  authentication_failed: "YouTube access needs attention from a workspace administrator.",
  ineligible: "This research session is no longer eligible. Ask an administrator to review it.",
  error: "YouTube data is temporarily unavailable. You can try again.",
};

export function displayDeadline(provenance: Provenance): number {
  // Keep browser data only for this short research view, even if the provider's
  // absolute retention ceiling is longer. Invalid timestamps fail closed.
  return Math.min(
    Date.parse(provenance.expires_at),
    Date.parse(provenance.collected_at) + 15 * 60_000,
  );
}

export function isDisplayable(provenance: Provenance, now: number): boolean {
  return Number.isFinite(displayDeadline(provenance)) && now < displayDeadline(provenance);
}

export function counterText(data: ChannelDisplay, metric: string): string {
  const item = data.items.find((entry) => entry.metric_key === `youtube.channel.${metric}`);
  if (item === undefined) {
    const hidden =
      metric === "subscribers" &&
      data.artist.provenance.provider_fields.some(
        (field) => field.key === "subscriber_count_status" && field.value === "hidden",
      );
    return hidden ? "Hidden by channel" : "Unavailable";
  }
  return `${item.value.toLocaleString()}${metric === "subscribers" ? " (rounded by YouTube)" : ""}`;
}
