"use client";

import type {
  ChannelSchedulingEligibilityResponse,
  ScheduleActivationRequest,
  SchedulingJobListResponse,
  SchedulingJobResponse,
} from "./generated/scheduling-api";

export const schedulingRecovery: Record<string, string> = {
  stale_content_revision:
    "Content changed. Refresh, save your edits, and obtain approval for the current revision.",
  stale_approval: "Submit the current revision for approval and complete review before activation.",
  ineligible_parent_state: "Submit this content for approval and complete review first.",
  changed_schedule_generation:
    "The channel schedule changed. Obtain fresh approval and activate a replacement.",
  missing_schedule_intent:
    "Set a channel date, time, and IANA timezone, then save and submit for approval.",
  destination_mismatch:
    "Choose an account compatible with this channel and artist, save, and request reapproval.",
  connection_unavailable:
    "Open Accounts and restore the destination connection, or select another account and request reapproval.",
  reconnect_required:
    "Reconnect this destination in Accounts, then revalidate unchanged blocked work.",
  capability_unavailable:
    "The account lacks publishing capability. Restore access in Accounts or change destination and request reapproval.",
  manual_delivery_required:
    "This account requires manual delivery in a separate workflow. Activation cannot automatically publish it or confirm publication.",
  execution_disabled:
    "Automatic execution is disabled. Ask a workspace administrator to enable execution. Planning and approval do not start delivery.",
  authoring_disabled:
    "Schedule activation is disabled by the deployment administrator. Inspection and cancellation remain available.",
  missing_durable_delivery_receiver:
    "Delivery is not configured. Ask an administrator to configure a durable delivery receiver before activation.",
  missed_schedule_window:
    "The delivery window has passed. Set a new time, save the material edit, obtain fresh approval, and activate a replacement.",
  handoff_contract_violation:
    "Delivery acceptance could not be verified. Ask an administrator to investigate before creating another publication.",
  active_job_conflict:
    "This channel already has active work. Inspect it and cancel while mutable before rescheduling.",
  replacement_required:
    "Activate a replacement using the approved channel revision to preserve schedule history.",
  replacement_requires_reapproval:
    "Change the channel time or content, save, and complete a new approval before replacing this job.",
  already_handed_off:
    "Delivery already accepted this intent. A new publication requires a material edit, fresh approval, and new activation.",
  invalid_state_transition:
    "The job changed and may already be handed off. Refresh its state; handed-off work cannot be cancelled.",
  idempotency_conflict:
    "This operation conflicts with an earlier request. Refresh and inspect the current job before trying again.",
};

export function reasonMessage(code: string): string {
  return (
    schedulingRecovery[code] ??
    `${code.replaceAll("_", " ")}. Refresh scheduling state; contact an administrator if it persists.`
  );
}

export class SchedulingApiError extends Error {
  constructor(
    readonly status: number,
    readonly reasons: string[],
    message: string,
  ) {
    super(message);
    this.name = "SchedulingApiError";
  }
}

async function schedulingJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new SchedulingApiError(
      0,
      [],
      "Unable to reach scheduling. Refresh or retry the same action safely.",
    );
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const reasons: string[] = Array.isArray(payload.detail?.reason_codes)
      ? payload.detail.reason_codes.filter((value: unknown) => typeof value === "string")
      : [];
    const message =
      response.status === 401
        ? "Sign in again to access scheduling."
        : response.status === 403
          ? "You do not have permission to perform this scheduling action."
          : response.status === 404
            ? "This channel or schedule no longer exists. Refresh marketing content."
            : response.status === 422
              ? "The schedule request is invalid. Check the channel time, timezone, and revision, then refresh."
              : reasons.length
                ? reasons.map(reasonMessage).join(" ")
                : "Scheduling could not be completed. Refresh state and retry the same action safely.";
    throw new SchedulingApiError(response.status, reasons, message);
  }
  return response.json() as Promise<T>;
}

export const schedulingPaths = {
  channel: (workspaceId: string, itemId: string, channelId: string) =>
    `/api/workspaces/${encodeURIComponent(workspaceId)}/marketing-content/${encodeURIComponent(itemId)}/channels/${encodeURIComponent(channelId)}/scheduling`,
  jobs: (workspaceId: string) =>
    `/api/workspaces/${encodeURIComponent(workspaceId)}/scheduling/jobs`,
};

export function getChannelEligibility(
  workspaceId: string,
  itemId: string,
  channelId: string,
  signal?: AbortSignal,
) {
  return schedulingJson<ChannelSchedulingEligibilityResponse>(
    `${schedulingPaths.channel(workspaceId, itemId, channelId)}/eligibility`,
    { signal },
  );
}

export function listChannelJobs(
  workspaceId: string,
  itemId: string,
  channelId: string,
  signal?: AbortSignal,
  cursor?: string,
) {
  const query = new URLSearchParams({
    content_item_id: itemId,
    channel_id: channelId,
    limit: "100",
  });
  if (cursor) query.set("cursor", cursor);
  return schedulingJson<SchedulingJobListResponse>(
    `${schedulingPaths.jobs(workspaceId)}?${query}`,
    { signal },
  );
}

export function scheduleCommand(
  path: string,
  payload: ScheduleActivationRequest | Record<string, never>,
  operationId: string,
) {
  return schedulingJson<SchedulingJobResponse>(path, {
    method: "POST",
    body: JSON.stringify(payload),
    headers: { "Idempotency-Key": operationId },
  });
}

// Mounted inspectors can retain their item while calendar caches refresh.
type SchedulingListener = (workspaceId: string, contentItemId: string | null) => void;
const schedulingListeners = new Set<SchedulingListener>();
export function subscribeSchedulingUpdates(listener: SchedulingListener) {
  schedulingListeners.add(listener);
  return () => {
    schedulingListeners.delete(listener);
  };
}
export function notifySchedulingUpdate(workspaceId: string, contentItemId: string | null) {
  for (const listener of schedulingListeners) listener(workspaceId, contentItemId);
}
