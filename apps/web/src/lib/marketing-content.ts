"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

export type MarketingContentApiErrorCode =
  "unauthorized" | "forbidden" | "not_found" | "conflict" | "network_failure";

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

export type MarketingContentItem = {
  id: string;
  workspace_id: string;
  campaign_id: string;
  title: string;
  content_type: string;
  status: string;
  scheduled_at: string | null;
  published_at: string | null;
};

export type MarketingContentList = {
  marketing_content: MarketingContentItem[];
  total: number;
  limit: number;
  offset: number;
};

export type MarketingContentListOptions = {
  campaign_id?: string | null;
  start?: string | null;
  end?: string | null;
  status?: string | null;
  channel?: string | null;
  content_type?: string | null;
  limit?: number;
  offset?: number;
};

export type MarketingContentResourceState<T> = {
  data: T | null;
  error: MarketingContentApiError | null;
  isLoading: boolean;
  reload: () => Promise<T>;
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

export const marketingContentQueryKeys = {
  all: "marketing-content",
  workspaceList: (workspaceId: string, options?: MarketingContentListOptions) =>
    `marketing-content:workspace-list:${workspaceId}:${stableQueryKey(options)}`,
  campaignList: (workspaceId: string, campaignId: string) =>
    `marketing-content:campaign-list:${workspaceId}:${campaignId}`,
  detail: (workspaceId: string, campaignId: string, contentItemId: string) =>
    `marketing-content:detail:${workspaceId}:${campaignId}:${contentItemId}`,
};

function stableQueryKey(options?: Record<string, unknown> | null): string {
  if (!options) {
    return "default";
  }
  return Object.entries(options)
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}:${String(value)}`)
    .join("|");
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

function toMarketingContentApiError(status: number): MarketingContentApiError {
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
    return new MarketingContentApiError(
      "conflict",
      "Marketing content could not be changed.",
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
    throw toMarketingContentApiError(response.status);
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

function marketingContentQuery(options?: MarketingContentListOptions): string {
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
    reload,
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
  if (campaignId && key === marketingContentQueryKeys.campaignList(workspaceId, campaignId)) {
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

export function clearMarketingContentCache() {
  cache.clear();
}

export function listWorkspaceMarketingContent(
  workspaceId: string,
  options?: MarketingContentListOptions,
): Promise<MarketingContentList> {
  return marketingContentJson<MarketingContentList>(
    `/api/workspaces/${workspaceId}/marketing-content${marketingContentQuery(options)}`,
  );
}

export function listCampaignMarketingContent(
  workspaceId: string,
  campaignId: string,
): Promise<MarketingContentList> {
  return marketingContentJson<MarketingContentList>(
    `/api/workspaces/${workspaceId}/campaigns/${campaignId}/marketing-content`,
  );
}

export function getMarketingContentItem(
  workspaceId: string,
  campaignId: string,
  contentItemId: string,
): Promise<MarketingContentItem> {
  return marketingContentJson<MarketingContentItem>(
    `/api/workspaces/${workspaceId}/campaigns/${campaignId}/marketing-content/${contentItemId}`,
  );
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

export function useCampaignMarketingContent(
  workspaceId: string | null,
  campaignId: string | null,
): MarketingContentResourceState<MarketingContentList> {
  const key =
    workspaceId && campaignId
      ? marketingContentQueryKeys.campaignList(workspaceId, campaignId)
      : null;
  const fetcher = useCallback(
    () => listCampaignMarketingContent(workspaceId ?? "", campaignId ?? ""),
    [campaignId, workspaceId],
  );
  return useMarketingContentResource(key, workspaceId && campaignId ? fetcher : null);
}
