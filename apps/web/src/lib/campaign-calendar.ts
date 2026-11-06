"use client";

import { createResourceCache, useCachedResource } from "./resource-cache";

import { useCallback } from "react";

import type {
  PublishedCalendarFact,
  SchedulingEligibility,
  SchedulingJobProjection,
} from "./marketing-content";

export type CampaignCalendarApiErrorCode =
  "unauthorized" | "forbidden" | "not_found" | "validation" | "network_failure";

export class CampaignCalendarApiError extends Error {
  constructor(
    readonly code: CampaignCalendarApiErrorCode,
    message: string,
    readonly status?: number,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "CampaignCalendarApiError";
  }
}

export type CampaignCalendarEventType =
  | "campaign.start"
  | "campaign.target_end"
  | "campaign.milestone.target"
  | "marketing.content.scheduled"
  | "marketing.content.channel_scheduled"
  | "marketing.content.published"
  | "marketing.content.channel_published"
  | "marketing.content.approval_requested"
  | "marketing.content.approved";

export type CampaignCalendarSourceType =
  | "campaign"
  | "campaign_milestone"
  | "marketing_content_item"
  | "marketing_content_channel"
  | "approval_request"
  | string;

export type CampaignCalendarCampaignContext = {
  id: string;
  name: string;
  status: string;
  campaign_type: string;
};

export type CampaignCalendarArtistContext = {
  id: string;
  name: string;
};

export type CampaignCalendarReleaseContext = {
  id: string;
  title: string;
  artist_id: string | null;
};

export type CampaignCalendarDestinationAccountContext = {
  id: string;
  provider: string;
  handle: string | null;
  display_name: string | null;
  connection_method: string;
  status: string;
};

export type CampaignCalendarDestinationReadinessContext = {
  planning_valid: boolean;
  delivery_ready: boolean;
  status: string;
  label: string;
  warning: string | null;
  account: CampaignCalendarDestinationAccountContext | null;
};

export type CampaignCalendarChannelContext = {
  scheduling_job?: SchedulingJobProjection | null;
  id: string;
  channel: string;
  placement: string;
  destination_readiness?: CampaignCalendarDestinationReadinessContext | null;
  scheduling_eligibility?: SchedulingEligibility | null;
};

export type CampaignCalendarApprovalContext = {
  request_id: string | null;
  state: string | null;
  label: string | null;
  approved_revision_is_current: boolean | null;
  can_schedule: boolean | null;
  available_actions: string[];
};

export type CampaignCalendarEvent = {
  publication?: PublishedCalendarFact | null;
  id: string;
  event_type: CampaignCalendarEventType | string;
  source_type: CampaignCalendarSourceType;
  source_id: string;
  source_parent_id: string | null;
  title: string;
  description: string | null;
  starts_at: string;
  ends_at: string | null;
  date: string | null;
  all_day: boolean;
  timezone: string;
  status: string | null;
  campaign: CampaignCalendarCampaignContext | null;
  artist: CampaignCalendarArtistContext | null;
  release: CampaignCalendarReleaseContext | null;
  channel: CampaignCalendarChannelContext | null;
  approval: CampaignCalendarApprovalContext | null;
  url: string | null;
  sort_key: string;
};

export type CampaignCalendarResponse = {
  workspace_id: string;
  start: string;
  end: string;
  timezone: string;
  events: CampaignCalendarEvent[];
  total: number;
  limit: number;
  offset: number;
};

export type CampaignCalendarQueryOptions = {
  start?: string | null;
  end?: string | null;
  timezone?: string | null;
  campaign_id?: string | null;
  artist_id?: string | null;
  release_id?: string | null;
  status?: string | null;
  event_types?: string | readonly string[] | null;
  include_archived?: boolean | null;
  include_published?: boolean | null;
  limit?: number | null;
  offset?: number | null;
};

export type CampaignCalendarResourceState<T> = {
  data: T | null;
  error: CampaignCalendarApiError | null;
  isLoading: boolean;
  isMutating: boolean;
  reload: () => Promise<T>;
};

const cache = createResourceCache({
  toError: (error: unknown) =>
    error instanceof CampaignCalendarApiError
      ? error
      : new CampaignCalendarApiError(
          "network_failure",
          "Campaign calendar could not be loaded.",
          undefined,
          { cause: error },
        ),
  missingKeyError: () =>
    new CampaignCalendarApiError("not_found", "A campaign calendar resource key is required."),
});

export const campaignCalendarQueryKeys = {
  all: "campaign-calendar",
  workspaceRange: (workspaceId: string, options?: CampaignCalendarQueryOptions) =>
    `campaign-calendar:workspace-range:${workspaceId}:${stableCampaignCalendarQueryKey(options)}`,
};

function definedQueryEntries(options?: CampaignCalendarQueryOptions) {
  return Object.entries(options ?? {}).filter(
    ([, value]) => value !== undefined && value !== null && value !== "",
  );
}

function normalizedEventTypes(value: string | readonly string[]): string[] {
  const values = typeof value === "string" ? value.split(",") : value;
  return values
    .map((item) => item.trim())
    .filter(Boolean)
    .sort();
}

export function stableCampaignCalendarQueryKey(
  options?: CampaignCalendarQueryOptions | null,
): string {
  if (!options) {
    return "default";
  }
  const key = definedQueryEntries(options)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => {
      if (key === "event_types" && (Array.isArray(value) || typeof value === "string")) {
        return `${key}:${normalizedEventTypes(value).join(",")}`;
      }
      return `${key}:${String(value)}`;
    })
    .join("|");
  return key || "default";
}

export function campaignCalendarQuery(options?: CampaignCalendarQueryOptions): string {
  const params = new URLSearchParams();
  for (const [key, value] of definedQueryEntries(options)) {
    if (key === "event_types" && (Array.isArray(value) || typeof value === "string")) {
      for (const item of normalizedEventTypes(value)) {
        params.append(key, item);
      }
      continue;
    }
    params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

function errorDetailMessage(detail: unknown): string | null {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((entry) => {
        if (entry && typeof entry === "object" && "msg" in entry) {
          return String(entry.msg);
        }
        return null;
      })
      .filter(Boolean)
      .join(" ");
  }
  return null;
}

async function responseErrorDetail(response: Response): Promise<string | null> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    return errorDetailMessage(payload.detail);
  } catch {
    return null;
  }
}

function toCampaignCalendarApiError(
  status: number,
  detail?: string | null,
): CampaignCalendarApiError {
  if (status === 401) {
    return new CampaignCalendarApiError(
      "unauthorized",
      "Sign in again to load the campaign calendar.",
      status,
    );
  }
  if (status === 403) {
    return new CampaignCalendarApiError(
      "forbidden",
      "You do not have access to the campaign calendar.",
      status,
    );
  }
  if (status === 404) {
    return new CampaignCalendarApiError("not_found", "Campaign calendar was not found.", status);
  }
  if (status === 400 || status === 422) {
    return new CampaignCalendarApiError(
      "validation",
      detail || "Campaign calendar filters have validation errors.",
      status,
    );
  }
  return new CampaignCalendarApiError(
    "network_failure",
    "Campaign calendar could not be loaded.",
    status,
  );
}

async function campaignCalendarJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");

  let response: Response;
  try {
    response = await fetch(path, { ...init, cache: "no-store", headers });
  } catch (error) {
    throw new CampaignCalendarApiError(
      "network_failure",
      "Unable to reach the campaign calendar API.",
      undefined,
      { cause: error },
    );
  }

  if (!response.ok) {
    throw toCampaignCalendarApiError(response.status, await responseErrorDetail(response));
  }
  return (await response.json()) as T;
}

function normalizeCampaignCalendarResponse(
  payload: CampaignCalendarResponse,
): CampaignCalendarResponse {
  return {
    ...payload,
    events: payload.events.map((event) => ({
      ...event,
      source_parent_id: event.source_parent_id ?? null,
      description: event.description ?? null,
      ends_at: event.ends_at ?? null,
      date: event.date ?? null,
      status: event.status ?? null,
      campaign: event.campaign ?? null,
      artist: event.artist ?? null,
      release: event.release ?? null,
      channel: event.channel
        ? {
            ...event.channel,
            destination_readiness: event.channel.destination_readiness ?? null,
          }
        : null,
      approval: event.approval
        ? {
            ...event.approval,
            available_actions: event.approval.available_actions ?? [],
          }
        : null,
      url: event.url ?? null,
    })),
  };
}

function useCampaignCalendarResource<T>(
  key: string | null,
  fetcher: (() => Promise<T>) | null,
): CampaignCalendarResourceState<T> {
  return { ...useCachedResource(cache, key, fetcher), isMutating: false };
}

export function invalidateCampaignCalendarCache(predicate?: (key: string) => boolean) {
  cache.invalidate(predicate);
}

export function invalidateCampaignCalendarWorkspaceCache(workspaceId: string) {
  invalidateCampaignCalendarCache((key) =>
    key.startsWith(`campaign-calendar:workspace-range:${workspaceId}:`),
  );
}

export function clearCampaignCalendarCache() {
  cache.clear();
}

export function listCampaignCalendarEvents(
  workspaceId: string,
  options: CampaignCalendarQueryOptions,
): Promise<CampaignCalendarResponse> {
  return campaignCalendarJson<CampaignCalendarResponse>(
    `/api/workspaces/${workspaceId}/campaign-calendar${campaignCalendarQuery(options)}`,
  ).then(normalizeCampaignCalendarResponse);
}

export function useCampaignCalendar(
  workspaceId: string | null,
  options?: CampaignCalendarQueryOptions,
): CampaignCalendarResourceState<CampaignCalendarResponse> {
  const key = workspaceId ? campaignCalendarQueryKeys.workspaceRange(workspaceId, options) : null;
  const fetcher = useCallback(
    () => listCampaignCalendarEvents(workspaceId ?? "", options ?? {}),
    [options, workspaceId],
  );
  return useCampaignCalendarResource(key, workspaceId ? fetcher : null);
}
