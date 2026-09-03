"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

export type MarketingContentApiErrorCode =
  "unauthorized" | "forbidden" | "not_found" | "conflict" | "validation" | "network_failure";

export class MarketingContentApiError extends Error {
  constructor(
    readonly code: MarketingContentApiErrorCode,
    message: string,
    readonly status?: number,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "MarketingContentApiError";
  }
}

export type MarketingContentItemStatus =
  | "draft"
  | "in_review"
  | "approved"
  | "scheduled"
  | "published"
  | "cancelled"
  | "archived";

export type MarketingContentItemChannel = {
  id: string;
  marketing_content_item_id: string;
  channel: string;
  placement: string | null;
  scheduled_at: string | null;
  published_at: string | null;
  external_post_id: string | null;
  external_url: string | null;
  copy_text_override: string | null;
  asset_refs: unknown[];
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type MarketingContentItem = {
  id: string;
  workspace_id: string;
  campaign_id: string;
  title: string;
  content_type: string;
  copy_text: string | null;
  asset_refs: unknown[];
  metadata: Record<string, unknown>;
  status: MarketingContentItemStatus;
  artist_id: string | null;
  release_id: string | null;
  owner_profile_id: string | null;
  created_by_user_id: string | null;
  created_by_profile_id: string | null;
  scheduled_at: string | null;
  published_at: string | null;
  approval_requested_at: string | null;
  approved_at: string | null;
  approved_by_profile_id: string | null;
  channels: MarketingContentItemChannel[];
  created_at: string;
  updated_at: string;
};

export type MarketingContentList = {
  marketing_content: MarketingContentItem[];
  total: number;
  limit: number;
  offset: number;
};

export type MarketingContentListOptions = {
  campaign?: string | null;
  campaign_id?: string | null;
  artist?: string | null;
  artist_id?: string | null;
  release?: string | null;
  release_id?: string | null;
  start?: string | null;
  end?: string | null;
  status?: MarketingContentItemStatus | null;
  channel?: string | null;
  content_type?: string | null;
  limit?: number;
  offset?: number;
};

export type MarketingContentCampaignListOptions = {
  limit?: number;
  offset?: number;
};

export type MarketingContentChannelCreate = {
  channel: string;
  placement?: string | null;
  scheduled_at?: string | null;
  copy_text_override?: string | null;
  asset_refs?: unknown[] | null;
};

export type MarketingContentItemCreate = {
  title: string;
  content_type: string;
  copy_text?: string | null;
  asset_refs?: unknown[] | null;
  artist_id?: string | null;
  release_id?: string | null;
  owner_profile_id?: string | null;
  scheduled_at?: string | null;
  channels?: MarketingContentChannelCreate[];
};

export type MarketingContentItemUpdate = Partial<MarketingContentItemCreate> & {
  channels?: MarketingContentChannelCreate[] | null;
};

export type MarketingContentStatusTransition = {
  status: MarketingContentItemStatus;
  approved_by_profile_id?: string | null;
};

export type MarketingContentResourceState<T> = {
  data: T | null;
  error: MarketingContentApiError | null;
  isLoading: boolean;
  isMutating: boolean;
  reload: () => Promise<T>;
};

export type MarketingContentMutationState<TData, TVariables> = {
  data: TData | null;
  error: MarketingContentApiError | null;
  isMutating: boolean;
  mutate: (variables: TVariables) => Promise<TData>;
  reset: () => void;
};

type CacheEntry<T> = {
  data: T | null;
  error: MarketingContentApiError | null;
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

export const marketingContentQueryKeys = {
  all: "marketing-content",
  workspaceList: (workspaceId: string, options?: MarketingContentListOptions) =>
    `marketing-content:workspace-list:${workspaceId}:${stableQueryKey(
      normalizeMarketingContentListOptions(options),
    )}`,
  campaignList: (
    workspaceId: string,
    campaignId: string,
    options?: MarketingContentCampaignListOptions,
  ) =>
    `marketing-content:campaign-list:${workspaceId}:${campaignId}:${stableQueryKey(options)}`,
  detail: (workspaceId: string, campaignId: string, contentItemId: string) =>
    `marketing-content:detail:${workspaceId}:${campaignId}:${contentItemId}`,
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

function normalizeMarketingContentListOptions(
  options?: MarketingContentListOptions,
): Record<string, string | number | null | undefined> {
  if (!options) {
    return {};
  }
  const normalized: Record<string, string | number | null | undefined> = { ...options };
  if (normalized.campaign_id === undefined && options.campaign !== undefined) {
    normalized.campaign_id = options.campaign;
  }
  if (normalized.artist_id === undefined && options.artist !== undefined) {
    normalized.artist_id = options.artist;
  }
  if (normalized.release_id === undefined && options.release !== undefined) {
    normalized.release_id = options.release;
  }
  delete normalized.campaign;
  delete normalized.artist;
  delete normalized.release;
  return normalized;
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

function toMarketingContentApiError(status: number, detail?: string | null): MarketingContentApiError {
  if (status === 401) {
    return new MarketingContentApiError(
      "unauthorized",
      "Sign in again to load marketing content.",
      status,
    );
  }
  if (status === 403) {
    return new MarketingContentApiError(
      "forbidden",
      "You do not have access to marketing content.",
      status,
    );
  }
  if (status === 404) {
    return new MarketingContentApiError("not_found", "Marketing content was not found.", status);
  }
  if (status === 400 || status === 409 || status === 422) {
    if (status === 422) {
      return new MarketingContentApiError(
        "validation",
        detail || "Marketing content has validation errors.",
        status,
      );
    }
    return new MarketingContentApiError(
      "conflict",
      detail || "Marketing content could not be changed.",
      status,
    );
  }
  return new MarketingContentApiError(
    "network_failure",
    "Marketing content could not be loaded.",
    status,
  );
}

async function marketingContentJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(path, { ...init, cache: "no-store", headers });
  } catch (error) {
    throw new MarketingContentApiError(
      "network_failure",
      "Unable to reach the marketing content API.",
      undefined,
      { cause: error },
    );
  }

  if (!response.ok) {
    throw toMarketingContentApiError(response.status, await responseErrorDetail(response));
  }
  return (await response.json()) as T;
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
        error instanceof MarketingContentApiError
          ? error
          : new MarketingContentApiError(
              "network_failure",
              "Marketing content could not be loaded.",
              undefined,
              { cause: error },
            );
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

function marketingContentQuery(
  options?: MarketingContentListOptions | MarketingContentCampaignListOptions,
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(normalizeMarketingContentListOptions(options))) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

function useMarketingContentResource<T>(
  key: string | null,
  fetcher: (() => Promise<T>) | null,
): MarketingContentResourceState<T> {
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
      throw new MarketingContentApiError(
        "not_found",
        "A marketing content resource key is required.",
      );
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

function useMarketingContentMutation<TData, TVariables>(
  key: string,
  mutation: (variables: TVariables) => Promise<TData>,
): MarketingContentMutationState<TData, TVariables> {
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
          error instanceof MarketingContentApiError
            ? error
            : new MarketingContentApiError(
                "network_failure",
                "Marketing content mutation failed.",
                undefined,
                { cause: error },
              );
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

export function invalidateMarketingContentCache(predicate?: (key: string) => boolean) {
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

export function shouldInvalidateMarketingContentRealtimeCacheKey({
  campaignId,
  contentItemId,
  key,
  workspaceId,
}: {
  campaignId: string | null;
  contentItemId: string | null;
  key: string;
  workspaceId: string;
}) {
  if (key.startsWith(`marketing-content:workspace-list:${workspaceId}:`)) {
    return true;
  }
  if (
    campaignId &&
    (key === `marketing-content:campaign-list:${workspaceId}:${campaignId}` ||
      key.startsWith(`marketing-content:campaign-list:${workspaceId}:${campaignId}:`))
  ) {
    return true;
  }
  if (campaignId && contentItemId) {
    return key === marketingContentQueryKeys.detail(workspaceId, campaignId, contentItemId);
  }
  return false;
}

export function invalidateMarketingContentWorkspaceCache(workspaceId: string) {
  invalidateMarketingContentCache((key) =>
    shouldInvalidateMarketingContentRealtimeCacheKey({
      campaignId: null,
      contentItemId: null,
      key,
      workspaceId,
    }),
  );
}

function invalidateItemCaches(workspaceId: string, campaignId: string, contentItemId?: string) {
  invalidateMarketingContentCache((key) => {
    if (key.startsWith(`marketing-content:workspace-list:${workspaceId}:`)) {
      return true;
    }
    if (key.startsWith(`marketing-content:campaign-list:${workspaceId}:${campaignId}:`)) {
      return true;
    }
    return contentItemId
      ? key === marketingContentQueryKeys.detail(workspaceId, campaignId, contentItemId)
      : false;
  });
}

export function clearMarketingContentCache() {
  cache.clear();
  activeMutationCount = 0;
  mutationVersion = 0;
}

export function listWorkspaceMarketingContent(
  workspaceId: string,
  options?: MarketingContentListOptions,
): Promise<MarketingContentList> {
  return marketingContentJson<MarketingContentList>(
    `/api/workspaces/${workspaceId}/marketing-content${marketingContentQuery(options)}`,
  );
}

export const listWorkspaceCalendarContent = listWorkspaceMarketingContent;

export function listCampaignMarketingContent(
  workspaceId: string,
  campaignId: string,
  options?: MarketingContentCampaignListOptions,
): Promise<MarketingContentList> {
  return marketingContentJson<MarketingContentList>(
    `/api/workspaces/${workspaceId}/campaigns/${campaignId}/marketing-content${marketingContentQuery(
      options,
    )}`,
  );
}

export const listCampaignContent = listCampaignMarketingContent;

export function getMarketingContentItem(
  workspaceId: string,
  campaignId: string,
  contentItemId: string,
): Promise<MarketingContentItem> {
  return marketingContentJson<MarketingContentItem>(
    `/api/workspaces/${workspaceId}/campaigns/${campaignId}/marketing-content/${contentItemId}`,
  );
}

export const getMarketingContent = getMarketingContentItem;

export async function createMarketingContentItem(
  workspaceId: string,
  campaignId: string,
  payload: MarketingContentItemCreate,
): Promise<MarketingContentItem> {
  const item = await marketingContentJson<MarketingContentItem>(
    `/api/workspaces/${workspaceId}/campaigns/${campaignId}/marketing-content`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
  invalidateItemCaches(workspaceId, campaignId, item.id);
  return item;
}

export async function updateMarketingContentItem(
  workspaceId: string,
  campaignId: string,
  contentItemId: string,
  payload: MarketingContentItemUpdate,
): Promise<MarketingContentItem> {
  const item = await marketingContentJson<MarketingContentItem>(
    `/api/workspaces/${workspaceId}/campaigns/${campaignId}/marketing-content/${contentItemId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
  invalidateItemCaches(workspaceId, campaignId, contentItemId);
  return item;
}

export async function archiveMarketingContentItem(
  workspaceId: string,
  campaignId: string,
  contentItemId: string,
): Promise<MarketingContentItem> {
  const item = await marketingContentJson<MarketingContentItem>(
    `/api/workspaces/${workspaceId}/campaigns/${campaignId}/marketing-content/${contentItemId}/archive`,
    {
      method: "POST",
    },
  );
  invalidateItemCaches(workspaceId, campaignId, contentItemId);
  return item;
}

export async function transitionMarketingContentStatus(
  workspaceId: string,
  campaignId: string,
  contentItemId: string,
  payload: MarketingContentStatusTransition,
): Promise<MarketingContentItem> {
  const item = await marketingContentJson<MarketingContentItem>(
    `/api/workspaces/${workspaceId}/campaigns/${campaignId}/marketing-content/${contentItemId}/status`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
  invalidateItemCaches(workspaceId, campaignId, contentItemId);
  return item;
}

export function useWorkspaceMarketingContent(
  workspaceId: string | null,
  options?: MarketingContentListOptions,
): MarketingContentResourceState<MarketingContentList> {
  const key = workspaceId ? marketingContentQueryKeys.workspaceList(workspaceId, options) : null;
  const fetcher = useCallback(
    () => listWorkspaceMarketingContent(workspaceId ?? "", options),
    [options, workspaceId],
  );
  return useMarketingContentResource(key, workspaceId ? fetcher : null);
}

export const useWorkspaceCalendarContent = useWorkspaceMarketingContent;

export function useCampaignMarketingContent(
  workspaceId: string | null,
  campaignId: string | null,
  options?: MarketingContentCampaignListOptions,
): MarketingContentResourceState<MarketingContentList> {
  const key =
    workspaceId && campaignId
      ? marketingContentQueryKeys.campaignList(workspaceId, campaignId, options)
      : null;
  const fetcher = useCallback(
    () => listCampaignMarketingContent(workspaceId ?? "", campaignId ?? "", options),
    [campaignId, options, workspaceId],
  );
  return useMarketingContentResource(key, workspaceId && campaignId ? fetcher : null);
}

export function useMarketingContentItem(
  workspaceId: string | null,
  campaignId: string | null,
  contentItemId: string | null,
): MarketingContentResourceState<MarketingContentItem> {
  const key =
    workspaceId && campaignId && contentItemId
      ? marketingContentQueryKeys.detail(workspaceId, campaignId, contentItemId)
      : null;
  const fetcher = useCallback(
    () => getMarketingContentItem(workspaceId ?? "", campaignId ?? "", contentItemId ?? ""),
    [campaignId, contentItemId, workspaceId],
  );
  return useMarketingContentResource(
    key,
    workspaceId && campaignId && contentItemId ? fetcher : null,
  );
}

export function useCreateMarketingContentItem(
  workspaceId: string | null,
  campaignId: string | null,
): MarketingContentMutationState<MarketingContentItem, MarketingContentItemCreate> {
  const mutation = useCallback(
    (payload: MarketingContentItemCreate) => {
      if (!workspaceId || !campaignId) {
        throw new MarketingContentApiError("not_found", "A campaign resource key is required.");
      }
      return createMarketingContentItem(workspaceId, campaignId, payload);
    },
    [campaignId, workspaceId],
  );
  return useMarketingContentMutation(
    `marketing-content:mutation:create:${workspaceId ?? "none"}:${campaignId ?? "none"}`,
    mutation,
  );
}

export function useUpdateMarketingContentItem(
  workspaceId: string | null,
  campaignId: string | null,
  contentItemId: string | null,
): MarketingContentMutationState<MarketingContentItem, MarketingContentItemUpdate> {
  const mutation = useCallback(
    (payload: MarketingContentItemUpdate) => {
      if (!workspaceId || !campaignId || !contentItemId) {
        throw new MarketingContentApiError("not_found", "A marketing content key is required.");
      }
      return updateMarketingContentItem(workspaceId, campaignId, contentItemId, payload);
    },
    [campaignId, contentItemId, workspaceId],
  );
  return useMarketingContentMutation(
    `marketing-content:mutation:update:${workspaceId ?? "none"}:${campaignId ?? "none"}:${
      contentItemId ?? "none"
    }`,
    mutation,
  );
}

export function useArchiveMarketingContentItem(
  workspaceId: string | null,
  campaignId: string | null,
  contentItemId: string | null,
): MarketingContentMutationState<MarketingContentItem, void> {
  const mutation = useCallback(() => {
    if (!workspaceId || !campaignId || !contentItemId) {
      throw new MarketingContentApiError("not_found", "A marketing content key is required.");
    }
    return archiveMarketingContentItem(workspaceId, campaignId, contentItemId);
  }, [campaignId, contentItemId, workspaceId]);
  return useMarketingContentMutation(
    `marketing-content:mutation:archive:${workspaceId ?? "none"}:${campaignId ?? "none"}:${
      contentItemId ?? "none"
    }`,
    mutation,
  );
}

export function useTransitionMarketingContentStatus(
  workspaceId: string | null,
  campaignId: string | null,
  contentItemId: string | null,
): MarketingContentMutationState<MarketingContentItem, MarketingContentStatusTransition> {
  const mutation = useCallback(
    (payload: MarketingContentStatusTransition) => {
      if (!workspaceId || !campaignId || !contentItemId) {
        throw new MarketingContentApiError("not_found", "A marketing content key is required.");
      }
      return transitionMarketingContentStatus(workspaceId, campaignId, contentItemId, payload);
    },
    [campaignId, contentItemId, workspaceId],
  );
  return useMarketingContentMutation(
    `marketing-content:mutation:status:${workspaceId ?? "none"}:${campaignId ?? "none"}:${
      contentItemId ?? "none"
    }`,
    mutation,
  );
}
