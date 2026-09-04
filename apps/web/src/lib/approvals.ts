"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

import {
  invalidateMarketingContentCache,
  marketingContentQueryKeys,
  shouldInvalidateMarketingContentRealtimeCacheKey,
} from "./marketing-content";

export type ApprovalApiErrorCode =
  | "unauthorized"
  | "forbidden"
  | "not_found"
  | "conflict"
  | "stale_revision"
  | "validation"
  | "network_failure";

export class ApprovalApiError extends Error {
  constructor(
    readonly code: ApprovalApiErrorCode,
    message: string,
    readonly status?: number,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "ApprovalApiError";
  }
}

export type ApprovalRequestStatus =
  | "requested"
  | "in_review"
  | "approved"
  | "rejected"
  | "changes_requested"
  | "cancelled"
  | "invalidated";

export type ApprovalAction = "approved" | "rejected" | "changes_requested" | "cancelled";

export type ApprovalActor = {
  user_id: string | null;
  profile_id: string | null;
  actor_kind?: string | null;
  actor_key?: string | null;
  display_name?: string | null;
};

export type ApprovalStage = {
  id: string;
  stage_order: number;
  required_capability: string;
  status: string;
  assigned_profile_id: string | null;
  started_at: string | null;
  completed_at: string | null;
};

export type ApprovalDecision = {
  id: string;
  stage_id: string | null;
  decision: ApprovalAction | "submitted" | "assigned" | "resubmitted" | "invalidated";
  decided_by_user_id: string | null;
  decided_by_profile_id: string | null;
  actor_kind: string;
  actor_key: string | null;
  reason: string | null;
  payload: Record<string, unknown>;
  created_at: string;
};

export type ApprovalContext = {
  id: string | null;
  name: string | null;
};

export type MarketingContentApprovalPreview = {
  id: string;
  title: string;
  content_type: string;
  copy_text: string | null;
  asset_refs: unknown[];
  status: string;
  current_revision: number;
  approved_revision: number | null;
};

export type ApprovalChannelPlacement = {
  channel: string;
  placement: string;
};

export type ApprovalRequestSummary = {
  id: string;
  workspace_id: string;
  resource_type: string;
  resource_id: string;
  submitted_revision: number;
  status: ApprovalRequestStatus;
  current_stage: ApprovalStage | null;
  stage_assignment: ApprovalActor | null;
  submitter: ApprovalActor;
  title: string;
  summary: string | null;
  submitted_at: string;
  resolved_at: string | null;
  campaign: ApprovalContext | null;
  artist: ApprovalContext | null;
};

export type ApprovalRequestDetail = ApprovalRequestSummary & {
  current_resource_revision: number | null;
  is_stale: boolean;
  decision_history: ApprovalDecision[];
  marketing_content_preview: MarketingContentApprovalPreview | null;
  release: ApprovalContext | null;
  channels: ApprovalChannelPlacement[];
  available_actions: ApprovalAction[];
};

export type ApprovalRequestList = {
  approvals: ApprovalRequestSummary[];
  total: number;
  limit: number;
  offset: number;
};

export type ApprovalListOptions = {
  status?: ApprovalRequestStatus | null;
  resource_type?: string | null;
  campaign_id?: string | null;
  artist_id?: string | null;
  submitter_user_id?: string | null;
  submitter_profile_id?: string | null;
  assigned_reviewer_profile_id?: string | null;
  assigned_to_me?: boolean | null;
  submitted_by_me?: boolean | null;
  submitted_start?: string | null;
  submitted_end?: string | null;
  limit?: number;
  offset?: number;
};

export type ApprovalSubmitRequest = {
  summary?: string | null;
  metadata?: Record<string, unknown> | null;
};

export type ApprovalDecisionRequest = {
  reason?: string | null;
  idempotency_key?: string | null;
};

export type ApprovalAssignRequest = {
  assigned_profile_id?: string | null;
};

export type ApprovalResourceState<T> = {
  data: T | null;
  error: ApprovalApiError | null;
  isLoading: boolean;
  isMutating: boolean;
  reload: () => Promise<T>;
};

export type ApprovalMutationState<TData, TVariables> = {
  data: TData | null;
  error: ApprovalApiError | null;
  isMutating: boolean;
  mutate: (variables: TVariables) => Promise<TData>;
  reset: () => void;
};

type CacheEntry<T> = {
  data: T | null;
  error: ApprovalApiError | null;
  fetcher: (() => Promise<T>) | null;
  isLoading: boolean;
  listeners: Set<() => void>;
  promise: Promise<T> | null;
  version: number;
};

const cache = new Map<string, CacheEntry<unknown>>();
const mutationListeners = new Set<() => void>();
let mutationVersion = 0;
let activeMutationCount = 0;

export const approvalQueryKeys = {
  all: "approvals",
  workspaceList: (workspaceId: string, options?: ApprovalListOptions) =>
    `approvals:workspace-list:${workspaceId}:${stableQueryKey(options)}`,
  detail: (workspaceId: string, approvalRequestId: string) =>
    `approvals:detail:${workspaceId}:${approvalRequestId}`,
  decisions: (workspaceId: string, approvalRequestId: string) =>
    `approvals:decisions:${workspaceId}:${approvalRequestId}`,
};

function stableQueryKey(options?: Record<string, unknown> | null): string {
  if (!options) {
    return "default";
  }
  const key = Object.entries(options)
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}:${String(value)}`)
    .join("|");
  return key || "default";
}

function entryFor<T>(key: string): CacheEntry<T> {
  let entry = cache.get(key) as CacheEntry<T> | undefined;
  if (!entry) {
    entry = {
      data: null,
      error: null,
      fetcher: null,
      isLoading: false,
      listeners: new Set(),
      promise: null,
      version: 0,
    };
    cache.set(key, entry as CacheEntry<unknown>);
  }
  return entry;
}

function emit(entry: CacheEntry<unknown>) {
  entry.version += 1;
  for (const listener of entry.listeners) {
    listener();
  }
}

function emitMutationChange() {
  mutationVersion += 1;
  for (const listener of mutationListeners) {
    listener();
  }
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

function toApprovalApiError(status: number, detail?: string | null): ApprovalApiError {
  if (status === 401) {
    return new ApprovalApiError("unauthorized", "Sign in again to load approvals.", status);
  }
  if (status === 403) {
    return new ApprovalApiError("forbidden", "You do not have access to approvals.", status);
  }
  if (status === 404) {
    return new ApprovalApiError("not_found", "Approval request was not found.", status);
  }
  if (status === 422) {
    return new ApprovalApiError(
      "validation",
      detail || "Approval request has validation errors.",
      status,
    );
  }
  if (status === 409) {
    const stale =
      detail?.toLowerCase().includes("stale") || detail?.toLowerCase().includes("revision");
    return new ApprovalApiError(
      stale ? "stale_revision" : "conflict",
      detail || "Approval request could not be changed.",
      status,
    );
  }
  if (status === 400) {
    return new ApprovalApiError(
      "conflict",
      detail || "Approval request could not be changed.",
      status,
    );
  }
  return new ApprovalApiError("network_failure", "Approvals could not be loaded.", status);
}

async function approvalJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(path, { ...init, cache: "no-store", headers });
  } catch (error) {
    throw new ApprovalApiError("network_failure", "Unable to reach the approvals API.", undefined, {
      cause: error,
    });
  }

  if (!response.ok) {
    throw toApprovalApiError(response.status, await responseErrorDetail(response));
  }
  return (await response.json()) as T;
}

function approvalQuery(options?: ApprovalListOptions): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(options ?? {})) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

function normalizeApprovalList(payload: ApprovalRequestList): ApprovalRequestList {
  return {
    approvals: payload.approvals.map(normalizeApprovalSummary),
    total: payload.total,
    limit: payload.limit,
    offset: payload.offset,
  };
}

function normalizeApprovalSummary(payload: ApprovalRequestSummary): ApprovalRequestSummary {
  return {
    ...payload,
    campaign: payload.campaign ?? null,
    artist: payload.artist ?? null,
    current_stage: payload.current_stage ?? null,
    stage_assignment: payload.stage_assignment ?? null,
    summary: payload.summary ?? null,
    resolved_at: payload.resolved_at ?? null,
  };
}

function normalizeApprovalDetail(payload: ApprovalRequestDetail): ApprovalRequestDetail {
  return {
    ...normalizeApprovalSummary(payload),
    current_resource_revision: payload.current_resource_revision ?? null,
    is_stale: Boolean(payload.is_stale),
    decision_history: payload.decision_history ?? [],
    marketing_content_preview: payload.marketing_content_preview ?? null,
    release: payload.release ?? null,
    channels: payload.channels ?? [],
    available_actions: payload.available_actions ?? [],
  };
}

async function loadResource<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
  const entry = entryFor<T>(key);
  entry.fetcher = fetcher;
  if (entry.promise) {
    return entry.promise;
  }

  entry.error = null;
  entry.isLoading = true;
  emit(entry);

  entry.promise = fetcher()
    .then((data) => {
      entry.data = data;
      entry.error = null;
      return data;
    })
    .catch((error) => {
      entry.error =
        error instanceof ApprovalApiError
          ? error
          : new ApprovalApiError("network_failure", "Approvals could not be loaded.", undefined, {
              cause: error,
            });
      throw entry.error;
    })
    .finally(() => {
      entry.isLoading = false;
      entry.promise = null;
      emit(entry);
    });

  emit(entry);
  return entry.promise;
}

function useApprovalResource<T>(
  key: string | null,
  fetcher: (() => Promise<T>) | null,
): ApprovalResourceState<T> {
  const subscribe = useCallback(
    (listener: () => void) => {
      if (!key) {
        return () => undefined;
      }
      const entry = entryFor<T>(key);
      entry.listeners.add(listener);
      return () => {
        entry.listeners.delete(listener);
      };
    },
    [key],
  );

  const getSnapshot = useCallback(() => (key ? entryFor<T>(key).version : 0), [key]);
  useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  useEffect(() => {
    if (!key || !fetcher) {
      return;
    }
    const entry = entryFor<T>(key);
    entry.fetcher = fetcher;
    if (entry.data === null && !entry.isLoading) {
      void loadResource(key, fetcher).catch(() => undefined);
    }
  }, [fetcher, key]);

  const reload = useCallback(async () => {
    if (!key || !fetcher) {
      throw new ApprovalApiError("not_found", "An approval resource key is required.");
    }
    return loadResource(key, fetcher);
  }, [fetcher, key]);

  const entry = key ? entryFor<T>(key) : null;
  return {
    data: entry?.data ?? null,
    error: entry?.error ?? null,
    isLoading: entry?.isLoading ?? false,
    isMutating: activeMutationCount > 0,
    reload,
  };
}

function useApprovalMutation<TData, TVariables>(
  key: string,
  mutation: (variables: TVariables) => Promise<TData>,
): ApprovalMutationState<TData, TVariables> {
  const getVersion = useCallback(() => mutationVersion, []);
  const subscribe = useCallback((listener: () => void) => {
    mutationListeners.add(listener);
    return () => {
      mutationListeners.delete(listener);
    };
  }, []);
  useSyncExternalStore(subscribe, getVersion, getVersion);

  const entry = entryFor<TData>(key);
  const mutate = useCallback(
    async (variables: TVariables) => {
      if (entry.isLoading) {
        throw new ApprovalApiError("conflict", "Approval mutation is already pending.");
      }
      activeMutationCount += 1;
      entry.isLoading = true;
      entry.error = null;
      emitMutationChange();
      try {
        const data = await mutation(variables);
        entry.data = data;
        entry.error = null;
        return data;
      } catch (error) {
        entry.error =
          error instanceof ApprovalApiError
            ? error
            : new ApprovalApiError("network_failure", "Approval mutation failed.", undefined, {
                cause: error,
              });
        throw entry.error;
      } finally {
        activeMutationCount = Math.max(0, activeMutationCount - 1);
        entry.isLoading = false;
        emitMutationChange();
      }
    },
    [entry, mutation],
  );

  const reset = useCallback(() => {
    entry.data = null;
    entry.error = null;
    entry.isLoading = false;
    emitMutationChange();
  }, [entry]);

  return {
    data: entry.data,
    error: entry.error,
    isMutating: entry.isLoading || activeMutationCount > 0,
    mutate,
    reset,
  };
}

export function invalidateApprovalCache(predicate?: (key: string) => boolean) {
  for (const [key, entry] of cache.entries()) {
    if (predicate && !predicate(key)) {
      continue;
    }
    entry.data = null;
    entry.error = null;
    if (entry.fetcher) {
      void loadResource(key, entry.fetcher).catch(() => undefined);
    } else {
      emit(entry);
    }
  }
}

export function clearApprovalCache() {
  cache.clear();
  activeMutationCount = 0;
  mutationVersion = 0;
}

export function shouldInvalidateApprovalRealtimeCacheKey({
  approvalRequestId,
  key,
  workspaceId,
}: {
  approvalRequestId: string | null;
  key: string;
  workspaceId: string;
}) {
  if (key.startsWith(`approvals:workspace-list:${workspaceId}:`)) {
    return true;
  }
  if (approvalRequestId) {
    return (
      key === approvalQueryKeys.detail(workspaceId, approvalRequestId) ||
      key === approvalQueryKeys.decisions(workspaceId, approvalRequestId)
    );
  }
  return false;
}

function invalidateApprovalRequestCaches(workspaceId: string, approvalRequestId?: string | null) {
  invalidateApprovalCache((key) =>
    shouldInvalidateApprovalRealtimeCacheKey({
      approvalRequestId: approvalRequestId ?? null,
      key,
      workspaceId,
    }),
  );
}

function marketingContentIdsFromApproval(detail: ApprovalRequestDetail): {
  campaignId: string | null;
  contentItemId: string | null;
} {
  if (detail.resource_type === "marketing_content_item") {
    return {
      campaignId: detail.campaign?.id ?? null,
      contentItemId: detail.marketing_content_preview?.id ?? detail.resource_id,
    };
  }
  return { campaignId: null, contentItemId: null };
}

function invalidateMarketingContentForApproval(workspaceId: string, detail: ApprovalRequestDetail) {
  const { campaignId, contentItemId } = marketingContentIdsFromApproval(detail);
  if (!campaignId && !contentItemId) {
    return;
  }
  invalidateMarketingContentCache((key) =>
    shouldInvalidateMarketingContentRealtimeCacheKey({
      campaignId,
      contentItemId,
      key,
      workspaceId,
    }),
  );
}

export function handleApprovalRealtimeInvalidation({
  approvalRequestId,
  campaignId,
  contentItemId,
  workspaceId,
}: {
  approvalRequestId: string | null;
  campaignId: string | null;
  contentItemId: string | null;
  workspaceId: string;
}) {
  invalidateApprovalRequestCaches(workspaceId, approvalRequestId);
  if (campaignId || contentItemId) {
    invalidateMarketingContentCache((key) =>
      shouldInvalidateMarketingContentRealtimeCacheKey({
        campaignId,
        contentItemId,
        key,
        workspaceId,
      }),
    );
  }
}

export function listApprovals(
  workspaceId: string,
  options?: ApprovalListOptions,
): Promise<ApprovalRequestList> {
  return approvalJson<ApprovalRequestList>(
    `/api/workspaces/${workspaceId}/approvals${approvalQuery(options)}`,
  ).then(normalizeApprovalList);
}

export function getApprovalRequest(
  workspaceId: string,
  approvalRequestId: string,
): Promise<ApprovalRequestDetail> {
  return approvalJson<ApprovalRequestDetail>(
    `/api/workspaces/${workspaceId}/approvals/${approvalRequestId}`,
  ).then(normalizeApprovalDetail);
}

export function listApprovalDecisionHistory(
  workspaceId: string,
  approvalRequestId: string,
): Promise<ApprovalDecision[]> {
  return approvalJson<ApprovalRequestDetail>(
    `/api/workspaces/${workspaceId}/approvals/${approvalRequestId}/decisions`,
  ).then((detail) => normalizeApprovalDetail(detail).decision_history);
}

export async function submitMarketingContentForApproval(
  workspaceId: string,
  campaignId: string,
  contentItemId: string,
  payload: ApprovalSubmitRequest,
): Promise<ApprovalRequestDetail> {
  const detail = normalizeApprovalDetail(
    await approvalJson<ApprovalRequestDetail>(
      `/api/workspaces/${workspaceId}/campaigns/${campaignId}/marketing-content/${contentItemId}/approval-requests`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),
  );
  invalidateApprovalRequestCaches(workspaceId, detail.id);
  invalidateMarketingContentCache((key) =>
    shouldInvalidateMarketingContentRealtimeCacheKey({
      campaignId,
      contentItemId,
      key,
      workspaceId,
    }),
  );
  return detail;
}

export async function assignApprovalReviewer(
  workspaceId: string,
  approvalRequestId: string,
  payload: ApprovalAssignRequest,
): Promise<ApprovalRequestDetail> {
  const detail = normalizeApprovalDetail(
    await approvalJson<ApprovalRequestDetail>(
      `/api/workspaces/${workspaceId}/approvals/${approvalRequestId}/assign`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),
  );
  invalidateApprovalRequestCaches(workspaceId, approvalRequestId);
  invalidateMarketingContentForApproval(workspaceId, detail);
  return detail;
}

export async function submitApprovalDecision(
  workspaceId: string,
  approvalRequestId: string,
  action: ApprovalAction,
  payload: ApprovalDecisionRequest = {},
): Promise<ApprovalRequestDetail> {
  const detail = normalizeApprovalDetail(
    await approvalJson<ApprovalRequestDetail>(
      `/api/workspaces/${workspaceId}/approvals/${approvalRequestId}/decisions`,
      {
        method: "POST",
        body: JSON.stringify({ ...payload, action }),
      },
    ),
  );
  invalidateApprovalRequestCaches(workspaceId, approvalRequestId);
  invalidateMarketingContentForApproval(workspaceId, detail);
  return detail;
}

export function approveApprovalRequest(
  workspaceId: string,
  approvalRequestId: string,
  payload?: ApprovalDecisionRequest,
) {
  return submitApprovalDecision(workspaceId, approvalRequestId, "approved", payload);
}

export function rejectApprovalRequest(
  workspaceId: string,
  approvalRequestId: string,
  payload: ApprovalDecisionRequest,
) {
  return submitApprovalDecision(workspaceId, approvalRequestId, "rejected", payload);
}

export function requestApprovalChanges(
  workspaceId: string,
  approvalRequestId: string,
  payload: ApprovalDecisionRequest,
) {
  return submitApprovalDecision(workspaceId, approvalRequestId, "changes_requested", payload);
}

export function cancelApprovalRequest(
  workspaceId: string,
  approvalRequestId: string,
  payload: ApprovalDecisionRequest = {},
) {
  return submitApprovalDecision(workspaceId, approvalRequestId, "cancelled", payload);
}

export function useApprovalQueue(
  workspaceId: string | null,
  options?: ApprovalListOptions,
): ApprovalResourceState<ApprovalRequestList> {
  const key = workspaceId ? approvalQueryKeys.workspaceList(workspaceId, options) : null;
  const fetcher = useCallback(
    () => listApprovals(workspaceId ?? "", options),
    [options, workspaceId],
  );
  return useApprovalResource(key, workspaceId ? fetcher : null);
}

export function useApprovalRequest(
  workspaceId: string | null,
  approvalRequestId: string | null,
): ApprovalResourceState<ApprovalRequestDetail> {
  const key =
    workspaceId && approvalRequestId
      ? approvalQueryKeys.detail(workspaceId, approvalRequestId)
      : null;
  const fetcher = useCallback(
    () => getApprovalRequest(workspaceId ?? "", approvalRequestId ?? ""),
    [approvalRequestId, workspaceId],
  );
  return useApprovalResource(key, workspaceId && approvalRequestId ? fetcher : null);
}

export function useApprovalDecisionHistory(
  workspaceId: string | null,
  approvalRequestId: string | null,
): ApprovalResourceState<ApprovalDecision[]> {
  const key =
    workspaceId && approvalRequestId
      ? approvalQueryKeys.decisions(workspaceId, approvalRequestId)
      : null;
  const fetcher = useCallback(
    () => listApprovalDecisionHistory(workspaceId ?? "", approvalRequestId ?? ""),
    [approvalRequestId, workspaceId],
  );
  return useApprovalResource(key, workspaceId && approvalRequestId ? fetcher : null);
}

export function useSubmitMarketingContentForApproval(
  workspaceId: string | null,
  campaignId: string | null,
  contentItemId: string | null,
): ApprovalMutationState<ApprovalRequestDetail, ApprovalSubmitRequest> {
  const mutation = useCallback(
    (payload: ApprovalSubmitRequest) => {
      if (!workspaceId || !campaignId || !contentItemId) {
        throw new ApprovalApiError("not_found", "A marketing content approval key is required.");
      }
      return submitMarketingContentForApproval(workspaceId, campaignId, contentItemId, payload);
    },
    [campaignId, contentItemId, workspaceId],
  );
  return useApprovalMutation(
    `approvals:mutation:submit-marketing-content:${workspaceId ?? "none"}:${
      campaignId ?? "none"
    }:${contentItemId ?? "none"}`,
    mutation,
  );
}

export function useAssignApprovalReviewer(
  workspaceId: string | null,
  approvalRequestId: string | null,
): ApprovalMutationState<ApprovalRequestDetail, ApprovalAssignRequest> {
  const mutation = useCallback(
    (payload: ApprovalAssignRequest) => {
      if (!workspaceId || !approvalRequestId) {
        throw new ApprovalApiError("not_found", "An approval request key is required.");
      }
      return assignApprovalReviewer(workspaceId, approvalRequestId, payload);
    },
    [approvalRequestId, workspaceId],
  );
  return useApprovalMutation(
    `approvals:mutation:assign:${workspaceId ?? "none"}:${approvalRequestId ?? "none"}`,
    mutation,
  );
}

export function useApprovalDecision(
  workspaceId: string | null,
  approvalRequestId: string | null,
  action: ApprovalAction,
): ApprovalMutationState<ApprovalRequestDetail, ApprovalDecisionRequest | undefined> {
  const mutation = useCallback(
    (payload: ApprovalDecisionRequest | undefined) => {
      if (!workspaceId || !approvalRequestId) {
        throw new ApprovalApiError("not_found", "An approval request key is required.");
      }
      return submitApprovalDecision(workspaceId, approvalRequestId, action, payload);
    },
    [action, approvalRequestId, workspaceId],
  );
  return useApprovalMutation(
    `approvals:mutation:decision:${workspaceId ?? "none"}:${approvalRequestId ?? "none"}:${action}`,
    mutation,
  );
}

export const useApproveApprovalRequest = (
  workspaceId: string | null,
  approvalRequestId: string | null,
) => useApprovalDecision(workspaceId, approvalRequestId, "approved");

export const useRejectApprovalRequest = (
  workspaceId: string | null,
  approvalRequestId: string | null,
) => useApprovalDecision(workspaceId, approvalRequestId, "rejected");

export const useRequestApprovalChanges = (
  workspaceId: string | null,
  approvalRequestId: string | null,
) => useApprovalDecision(workspaceId, approvalRequestId, "changes_requested");

export const useCancelApprovalRequest = (
  workspaceId: string | null,
  approvalRequestId: string | null,
) => useApprovalDecision(workspaceId, approvalRequestId, "cancelled");

export function approvalMarketingContentDetailKey(
  workspaceId: string,
  campaignId: string,
  contentItemId: string,
) {
  return marketingContentQueryKeys.detail(workspaceId, campaignId, contentItemId);
}
