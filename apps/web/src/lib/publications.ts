"use client";

export type PublicationStatus =
  | "pending"
  | "processing"
  | "published"
  | "retryable_failure"
  | "retrying"
  | "permanent_failure"
  | "manual_action_required"
  | "cancelled";

export type PublicationAttempt = {
  id: string;
  number: number;
  started_at: string;
  completed_at: string | null;
  outcome: string | null;
  failure_reason: string | null;
  external_post_id: string | null;
  observations: {
    version: number;
    observed_at: string;
    outcome: string;
    source: string;
    failure_reason: string | null;
  }[];
};

/** Explicit public projection; provider diagnostics and credentials are never part of this contract. */
export type Publication = {
  transition_version?: number;
  action_version?: number;
  can_authorize_retry?: boolean;
  can_begin_manual?: boolean;
  can_complete_manual?: boolean;
  can_manage_recovery?: boolean;
  can_manage_account?: boolean;
  destination_connection_method?: string | null;
  destination_connection_status?: string | null;
  id: string;
  workspace_id: string;
  content_item_id: string;
  channel_id: string;
  artist_profile_id: string | null;
  scheduling_job_id: string;
  schedule_generation: number;
  origin: string;
  delivery_status: PublicationStatus;
  resolution: string;
  completion_source: "human" | "provider" | null;
  external_post_id: string | null;
  provider_url: string | null;
  provider: string;
  destination_id: string;
  destination_identity_matches: boolean;
  destination_account: {
    external_account_id: string;
    username: string | null;
    display_name: string | null;
  } | null;
  caption: string | null;
  hashtags: string[];
  asset_refs: { sha256: string; size_bytes: number; media_type: string }[];
  channel: string;
  placement: string | null;
  content_revision: number;
  scheduled_for: string;
  authoring_timezone: string;
  created_at: string;
  started_at: string | null;
  published_at: string | null;
  cancelled_at?: string | null;
  cancellation_reason?: string | null;
  last_failed_at: string | null;
  manual_completed_at: string | null;
  next_retry_at: string | null;
  latest_failure_reason: string | null;
  attempt_count: number;
  attempts: PublicationAttempt[];
  actions: {
    version: number;
    operation: string;
    occurred_at: string;
  }[];
};

/** Polling contract: rich content, assets and journals are fetched on expansion. */
export type PublicationSummary = Pick<
  Publication,
  | "id"
  | "workspace_id"
  | "content_item_id"
  | "provider"
  | "destination_id"
  | "delivery_status"
  | "published_at"
  | "channel"
  | "placement"
  | "content_revision"
  | "scheduled_for"
  | "authoring_timezone"
  | "attempt_count"
  | "started_at"
  | "latest_failure_reason"
  | "last_failed_at"
  | "transition_version"
  | "next_retry_at"
  | "resolution"
  | "destination_identity_matches"
  | "destination_account"
  | "completion_source"
  | "external_post_id"
  | "provider_url"
  | "manual_completed_at"
  | "action_version"
  | "can_manage_recovery"
  | "can_authorize_retry"
  | "can_begin_manual"
  | "can_complete_manual"
> & { failure_category: string | null };

export type PublicationPage = { publications: PublicationSummary[]; next_after_id: string | null };

export const publicationStatusLabels: Record<PublicationStatus, string> = {
  pending: "Pending delivery",
  processing: "Delivering",
  published: "Published",
  retryable_failure: "Delivery failed · recoverable",
  retrying: "Retrying delivery",
  permanent_failure: "Delivery failed · permanent",
  manual_action_required: "Outcome unknown",
  cancelled: "Cancelled",
};

const failureMessages: Record<string, string> = {
  temporary_unavailability: "The provider was temporarily unavailable.",
  rate_limited: "The provider rate limit was reached.",
  invalid_content: "The provider could not accept the approved content or media.",
  destination_unavailable: "The destination account was unavailable.",
  authorization_required: "The destination requires renewed publishing access.",
  outcome_unknown: "Delivery could not be confirmed. Check the provider before publishing again.",
};

const cancellationMessages: Record<string, string> = {
  scheduling_cancelled: "The scheduled delivery was cancelled.",
  stale_approval:
    "Approval is no longer valid. Approve and schedule a new content revision to publish.",
  stale_content_revision:
    "The approved content revision was replaced. Schedule the newly approved revision to publish.",
  ineligible_parent_state: "The content is no longer approved for delivery.",
  changed_schedule_generation: "This delivery intent was superseded by a schedule change.",
  missing_schedule_intent: "The schedule for this delivery was removed.",
};

export function publicationCancellationMessage(code: string | null | undefined): string {
  return code && Object.hasOwn(cancellationMessages, code)
    ? cancellationMessages[code]!
    : "This publication was cancelled.";
}

export function publicationFailureMessage(code: string | null): string {
  return code
    ? Object.hasOwn(failureMessages, code)
      ? failureMessages[code]!
      : "Delivery failed. Ask a workspace administrator to investigate."
    : "No recorded failure.";
}

export const publicationResolution: Record<string, { label: string; instruction: string }> = {
  pending: { label: "Waiting for delivery", instruction: "Delivery has not started." },
  processing: { label: "Delivery in progress", instruction: "Waiting for provider confirmation." },
  retrying: { label: "Retry in progress", instruction: "Waiting for provider confirmation." },
  published: { label: "No action required", instruction: "The provider confirmed publication." },
  cancelled: { label: "No delivery planned", instruction: "This publication was cancelled." },
  retry_scheduled: {
    label: "Automatic retry scheduled",
    instruction: "The worker will retry. Reserve manual delivery before publishing it yourself.",
  },
  retry_authorized: {
    label: "Recovery authorized",
    instruction: "The worker will revalidate the destination and retry delivery.",
  },
  reconnect_required: {
    label: "Reconnect required",
    instruction:
      "Reconnect the destination in Accounts, then request recovery from an authorized operator.",
  },
  reconciliation_required: {
    label: "Reconciliation required",
    instruction:
      "The provider may have published. Investigate the outcome before any new delivery.",
  },
  human_intervention_required: {
    label: "Manual action required",
    instruction:
      "An authorized operator must investigate and resolve the failure before requesting recovery.",
  },
  terminal_failure: {
    label: "Manual delivery required",
    instruction:
      "Automatic delivery has stopped. Review the rejection with an authorized operator before reserving manual delivery.",
  },
  retry_exhausted: {
    label: "Retry budget exhausted",
    instruction:
      "Automatic retries have ended. Ask an authorized operator to reserve manual delivery.",
  },
  manual_publishing: {
    label: "Manual delivery reserved",
    instruction:
      "Automatic delivery is paused. The operator must publish the prepared content and record completion.",
  },
  manually_completed: {
    label: "Manually completed",
    instruction: "A human recorded delivery. This is separate from provider-confirmed publication.",
  },
};

// Public resource links only. Do not turn credential-bearing or arbitrary schemes into links.
export function publicProviderUrl(value: string | null): string | null {
  if (
    !value ||
    /[\s\\?#@]/.test(value) ||
    [...value].some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)
  )
    return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password && !url.port
      ? url.href
      : null;
  } catch {
    return null;
  }
}

export function publicationReadError(status = 0): string {
  if (status === 401) return "Sign in again to view publication history.";
  if (status === 403) return "You do not have permission to view this publication history.";
  if (status === 404) return "Publication history is unavailable or no longer exists.";
  return "Unable to load publication history. Refresh to try again.";
}

class PublicationReadError extends Error {
  constructor(status = 0) {
    super(publicationReadError(status));
  }
}

export function publicationErrorMessage(error: unknown): string {
  return error instanceof PublicationReadError ? error.message : publicationReadError();
}

async function read<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new PublicationReadError();
  }
  // Never reflect HTTP error bodies, exception messages, or provider diagnostics.
  if (!response.ok) throw new PublicationReadError(response.status);
  try {
    return (await response.json()) as T;
  } catch {
    throw new PublicationReadError();
  }
}

const basePath = (workspaceId: string) =>
  `/api/workspaces/${encodeURIComponent(workspaceId)}/publications`;

export async function listPublications(
  workspaceId: string,
  contentId: string,
  signal?: AbortSignal,
  afterId?: string,
) {
  const query = new URLSearchParams({ content_item_id: contentId, limit: "25" });
  if (afterId) query.set("after_id", afterId);
  const page = await read<PublicationPage>(`${basePath(workspaceId)}?${query}`, signal);
  if (
    !page ||
    !Array.isArray(page.publications) ||
    (page.next_after_id !== null && typeof page.next_after_id !== "string")
  ) {
    throw new PublicationReadError();
  }
  return page;
}

export function getPublication(workspaceId: string, publicationId: string, signal?: AbortSignal) {
  return read<Publication>(`${basePath(workspaceId)}/${encodeURIComponent(publicationId)}`, signal);
}

export type PublicationCommand = "recover" | "manual/start" | "manual/complete";
export class PublicationCommandError extends Error {
  constructor(readonly status = 0) {
    super(
      status === 409
        ? "Publication state changed or recovery is no longer allowed. Review the refreshed state before trying again."
        : status === 401
          ? "Sign in again to recover this publication."
          : status === 403
            ? "You do not have permission to recover this publication."
            : status === 404
              ? "This publication is no longer available."
              : status === 422
                ? "Check the completion information and refresh before trying again."
                : "Recovery could not be confirmed. Refresh or retry the same action safely.",
    );
  }
}

export function preparedAssetPath(publication: Publication, digest: string) {
  return `${basePath(publication.workspace_id)}/${encodeURIComponent(publication.id)}/assets/${encodeURIComponent(digest)}`;
}

export async function publicationCommand(
  publication: Publication,
  command: PublicationCommand,
  operationId: string,
  evidence: { delivery_confirmed?: boolean; external_post_id?: string; provider_url?: string } = {},
): Promise<Publication> {
  let response: Response;
  try {
    response = await fetch(
      `${basePath(publication.workspace_id)}/${encodeURIComponent(publication.id)}/${command}`,
      {
        method: "POST",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "Idempotency-Key": operationId,
        },
        body: JSON.stringify({
          expected_version: publication.transition_version,
          expected_action_version: publication.action_version,
          ...evidence,
        }),
      },
    );
  } catch {
    throw new PublicationCommandError();
  }
  if (!response.ok) throw new PublicationCommandError(response.status);
  try {
    return (await response.json()) as Publication;
  } catch {
    throw new PublicationCommandError();
  }
}
