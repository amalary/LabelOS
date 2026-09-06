"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

export type SocialAccountConnectionApiErrorCode =
  "unauthorized" | "forbidden" | "not_found" | "conflict" | "validation" | "network_failure";

export class SocialAccountConnectionApiError extends Error {
  constructor(
    readonly code: SocialAccountConnectionApiErrorCode,
    message: string,
    readonly status?: number,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "SocialAccountConnectionApiError";
  }
}

export type SocialAccountProvider =
  | "instagram"
  | "facebook"
  | "tiktok"
  | "youtube"
  | "spotify"
  | "x"
  | (string & {});

export type SocialAccountConnectionMethod = "direct_api" | "third_party" | "assisted";

export type SocialAccountConnectionStatus =
  | "pending"
  | "connected"
  | "limited"
  | "reconnect_required"
  | "disconnected"
  | "error";

export type SocialAccountCapability =
  | "content_publish"
  | "manual_publish"
  | "manual_metrics"
  | "account_analytics_read"
  | "post_analytics_read"
  | (string & {});

export type SocialAccountArtistAssociation = {
  artist_profile_id: string;
  artist_id: string;
  artist_name: string;
  stage_name: string | null;
};

export type SocialAccountResolvedCapabilities = {
  can_auto_publish: boolean;
  requires_manual_publish: boolean;
  supports_manual_metrics: boolean;
  can_read_account_analytics: boolean;
  can_read_post_analytics: boolean;
};

export type SocialAccountConnectionHealth = {
  token_expires_at: string | null;
  last_synced_at: string | null;
  last_health_checked_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
};

export type SocialAccountConnection = SocialAccountConnectionHealth & {
  id: string;
  workspace_id: string;
  provider: SocialAccountProvider;
  external_account_id: string | null;
  handle: string | null;
  display_name: string | null;
  profile_url: string | null;
  artist_association: SocialAccountArtistAssociation | null;
  connection_method: SocialAccountConnectionMethod;
  status: SocialAccountConnectionStatus;
  capabilities: SocialAccountCapability[];
  resolved_capabilities: SocialAccountResolvedCapabilities;
  provider_metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type SocialAccountConnectionsList = {
  social_account_connections: SocialAccountConnection[];
  total: number;
  limit: number;
  offset: number;
};

export type SocialAccountConnectionsListOptions = {
  provider?: SocialAccountProvider | null;
  status?: SocialAccountConnectionStatus | null;
  artist?: string | null;
  artist_profile_id?: string | null;
  include_disconnected?: boolean | null;
  limit?: number;
  offset?: number;
};

export type AssistedSocialAccountConnectionCreate = {
  provider: SocialAccountProvider;
  artist_profile_id?: string | null;
  external_account_id?: string | null;
  handle?: string | null;
  display_name?: string | null;
  profile_url?: string | null;
  capabilities?: SocialAccountCapability[] | null;
  provider_metadata?: Record<string, unknown> | null;
};

export type SocialAccountConnectionUpdate = {
  artist_profile_id?: string | null;
  handle?: string | null;
  display_name?: string | null;
  profile_url?: string | null;
  capabilities?: SocialAccountCapability[] | null;
  provider_metadata?: Record<string, unknown> | null;
};

export type SocialAccountConnectionResourceState<T> = {
  data: T | null;
  error: SocialAccountConnectionApiError | null;
  isLoading: boolean;
  isMutating: boolean;
  reload: () => Promise<T>;
};

export type SocialAccountConnectionMutationState<TData, TVariables> = {
  data: TData | null;
  error: SocialAccountConnectionApiError | null;
  isMutating: boolean;
  mutate: (variables: TVariables) => Promise<TData>;
  reset: () => void;
};

type CacheEntry<T> = {
  data: T | null;
  error: SocialAccountConnectionApiError | null;
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

export const socialAccountConnectionQueryKeys = {
  all: "social-account-connections",
  list: (workspaceId: string, options?: SocialAccountConnectionsListOptions) =>
    `social-account-connections:list:${workspaceId}:${stableQueryKey(
      normalizeSocialAccountConnectionsListOptions(options),
    )}`,
  detail: (workspaceId: string, connectionId: string) =>
    `social-account-connections:detail:${workspaceId}:${connectionId}`,
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

function normalizeSocialAccountConnectionsListOptions(
  options?: SocialAccountConnectionsListOptions,
): Record<string, string | number | boolean | null | undefined> {
  if (!options) {
    return {};
  }
  const normalized: Record<string, string | number | boolean | null | undefined> = { ...options };
  if (normalized.artist_profile_id === undefined && options.artist !== undefined) {
    normalized.artist_profile_id = options.artist;
  }
  delete normalized.artist;
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

function toSocialAccountConnectionApiError(
  status: number,
  detail?: string | null,
): SocialAccountConnectionApiError {
  if (status === 401) {
    return new SocialAccountConnectionApiError(
      "unauthorized",
      "Sign in again to load social account connections.",
      status,
    );
  }
  if (status === 403) {
    return new SocialAccountConnectionApiError(
      "forbidden",
      "You do not have access to social account connections.",
      status,
    );
  }
  if (status === 404) {
    return new SocialAccountConnectionApiError(
      "not_found",
      "Social account connection was not found.",
      status,
    );
  }
  if (status === 422) {
    return new SocialAccountConnectionApiError(
      "validation",
      detail || "Social account connection has validation errors.",
      status,
    );
  }
  if (status === 400 || status === 409) {
    return new SocialAccountConnectionApiError(
      "conflict",
      detail || "Social account connection could not be changed.",
      status,
    );
  }
  return new SocialAccountConnectionApiError(
    "network_failure",
    "Social account connections could not be loaded.",
    status,
  );
}

async function socialAccountConnectionJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(path, { ...init, cache: "no-store", headers });
  } catch (error) {
    throw new SocialAccountConnectionApiError(
      "network_failure",
      "Unable to reach the social account connections API.",
      undefined,
      { cause: error },
    );
  }

  if (!response.ok) {
    throw toSocialAccountConnectionApiError(response.status, await responseErrorDetail(response));
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
        error instanceof SocialAccountConnectionApiError
          ? error
          : new SocialAccountConnectionApiError(
              "network_failure",
              "Social account connections could not be loaded.",
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

function socialAccountConnectionsQuery(options?: SocialAccountConnectionsListOptions): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(
    normalizeSocialAccountConnectionsListOptions(options),
  )) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

function useSocialAccountConnectionResource<T>(
  key: string | null,
  fetcher: (() => Promise<T>) | null,
): SocialAccountConnectionResourceState<T> {
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
      throw new SocialAccountConnectionApiError(
        "not_found",
        "A social account connection resource key is required.",
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

function useSocialAccountConnectionMutation<TData, TVariables>(
  key: string,
  mutation: (variables: TVariables) => Promise<TData>,
): SocialAccountConnectionMutationState<TData, TVariables> {
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
          error instanceof SocialAccountConnectionApiError
            ? error
            : new SocialAccountConnectionApiError(
                "network_failure",
                "Social account connection mutation failed.",
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

export function invalidateSocialAccountConnectionCache(predicate?: (key: string) => boolean) {
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

export function shouldInvalidateSocialAccountConnectionRealtimeCacheKey({
  connectionId,
  key,
  workspaceId,
}: {
  connectionId: string | null;
  key: string;
  workspaceId: string;
}) {
  if (key.startsWith(`social-account-connections:list:${workspaceId}:`)) {
    return true;
  }
  return connectionId
    ? key === socialAccountConnectionQueryKeys.detail(workspaceId, connectionId)
    : false;
}

export function invalidateSocialAccountConnectionWorkspaceCache(workspaceId: string) {
  invalidateSocialAccountConnectionCache((key) =>
    shouldInvalidateSocialAccountConnectionRealtimeCacheKey({
      connectionId: null,
      key,
      workspaceId,
    }),
  );
}

function invalidateConnectionCaches(workspaceId: string, connectionId?: string) {
  invalidateSocialAccountConnectionCache((key) => {
    if (key.startsWith(`social-account-connections:list:${workspaceId}:`)) {
      return true;
    }
    return connectionId
      ? key === socialAccountConnectionQueryKeys.detail(workspaceId, connectionId)
      : false;
  });
}

export function clearSocialAccountConnectionCache() {
  cache.clear();
  activeMutationCount = 0;
  mutationVersion = 0;
}

export function supportsSocialAccountCapability(
  connectionOrCapabilities: SocialAccountConnection | readonly SocialAccountCapability[],
  capability: SocialAccountCapability,
): boolean {
  const capabilities =
    "capabilities" in connectionOrCapabilities
      ? connectionOrCapabilities.capabilities
      : connectionOrCapabilities;
  return capabilities.includes(capability);
}

export function canAutoPublish(connection: SocialAccountConnection): boolean {
  return (
    connection.resolved_capabilities.can_auto_publish ||
    supportsSocialAccountCapability(connection, "content_publish")
  );
}

export function requiresManualPublish(connection: SocialAccountConnection): boolean {
  return (
    connection.resolved_capabilities.requires_manual_publish ||
    (supportsSocialAccountCapability(connection, "manual_publish") && !canAutoPublish(connection))
  );
}

export function canReadAnalytics(connection: SocialAccountConnection): boolean {
  return (
    connection.resolved_capabilities.can_read_account_analytics ||
    connection.resolved_capabilities.can_read_post_analytics ||
    supportsSocialAccountCapability(connection, "account_analytics_read") ||
    supportsSocialAccountCapability(connection, "post_analytics_read")
  );
}

export function listSocialAccountConnections(
  workspaceId: string,
  options?: SocialAccountConnectionsListOptions,
): Promise<SocialAccountConnectionsList> {
  return socialAccountConnectionJson<SocialAccountConnectionsList>(
    `/api/workspaces/${workspaceId}/social-account-connections${socialAccountConnectionsQuery(
      options,
    )}`,
  );
}

export function getSocialAccountConnection(
  workspaceId: string,
  connectionId: string,
): Promise<SocialAccountConnection> {
  return socialAccountConnectionJson<SocialAccountConnection>(
    `/api/workspaces/${workspaceId}/social-account-connections/${connectionId}`,
  );
}

export async function createAssistedSocialAccountConnection(
  workspaceId: string,
  payload: AssistedSocialAccountConnectionCreate,
): Promise<SocialAccountConnection> {
  const connection = await socialAccountConnectionJson<SocialAccountConnection>(
    `/api/workspaces/${workspaceId}/social-account-connections`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
  invalidateConnectionCaches(workspaceId, connection.id);
  return connection;
}

export async function updateSocialAccountConnection(
  workspaceId: string,
  connectionId: string,
  payload: SocialAccountConnectionUpdate,
): Promise<SocialAccountConnection> {
  const connection = await socialAccountConnectionJson<SocialAccountConnection>(
    `/api/workspaces/${workspaceId}/social-account-connections/${connectionId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
  invalidateConnectionCaches(workspaceId, connectionId);
  return connection;
}

export async function disconnectSocialAccountConnection(
  workspaceId: string,
  connectionId: string,
): Promise<SocialAccountConnection> {
  const connection = await socialAccountConnectionJson<SocialAccountConnection>(
    `/api/workspaces/${workspaceId}/social-account-connections/${connectionId}/disconnect`,
    {
      method: "POST",
    },
  );
  invalidateConnectionCaches(workspaceId, connectionId);
  return connection;
}

export function useSocialAccountConnections(
  workspaceId: string | null,
  options?: SocialAccountConnectionsListOptions,
): SocialAccountConnectionResourceState<SocialAccountConnectionsList> {
  const key = workspaceId ? socialAccountConnectionQueryKeys.list(workspaceId, options) : null;
  const fetcher = useCallback(
    () => listSocialAccountConnections(workspaceId ?? "", options),
    [options, workspaceId],
  );
  return useSocialAccountConnectionResource(key, workspaceId ? fetcher : null);
}

export function useSocialAccountConnection(
  workspaceId: string | null,
  connectionId: string | null,
): SocialAccountConnectionResourceState<SocialAccountConnection> {
  const key =
    workspaceId && connectionId
      ? socialAccountConnectionQueryKeys.detail(workspaceId, connectionId)
      : null;
  const fetcher = useCallback(
    () => getSocialAccountConnection(workspaceId ?? "", connectionId ?? ""),
    [connectionId, workspaceId],
  );
  return useSocialAccountConnectionResource(key, workspaceId && connectionId ? fetcher : null);
}

export function useCreateAssistedSocialAccountConnection(
  workspaceId: string | null,
): SocialAccountConnectionMutationState<
  SocialAccountConnection,
  AssistedSocialAccountConnectionCreate
> {
  const mutation = useCallback(
    (payload: AssistedSocialAccountConnectionCreate) => {
      if (!workspaceId) {
        throw new SocialAccountConnectionApiError(
          "not_found",
          "A workspace resource key is required.",
        );
      }
      return createAssistedSocialAccountConnection(workspaceId, payload);
    },
    [workspaceId],
  );
  return useSocialAccountConnectionMutation(
    `social-account-connections:mutation:create:${workspaceId ?? "none"}`,
    mutation,
  );
}

export function useUpdateSocialAccountConnection(
  workspaceId: string | null,
  connectionId: string | null,
): SocialAccountConnectionMutationState<SocialAccountConnection, SocialAccountConnectionUpdate> {
  const mutation = useCallback(
    (payload: SocialAccountConnectionUpdate) => {
      if (!workspaceId || !connectionId) {
        throw new SocialAccountConnectionApiError(
          "not_found",
          "A social account connection key is required.",
        );
      }
      return updateSocialAccountConnection(workspaceId, connectionId, payload);
    },
    [connectionId, workspaceId],
  );
  return useSocialAccountConnectionMutation(
    `social-account-connections:mutation:update:${workspaceId ?? "none"}:${
      connectionId ?? "none"
    }`,
    mutation,
  );
}

export function useDisconnectSocialAccountConnection(
  workspaceId: string | null,
  connectionId: string | null,
): SocialAccountConnectionMutationState<SocialAccountConnection, void> {
  const mutation = useCallback(() => {
    if (!workspaceId || !connectionId) {
      throw new SocialAccountConnectionApiError(
        "not_found",
        "A social account connection key is required.",
      );
    }
    return disconnectSocialAccountConnection(workspaceId, connectionId);
  }, [connectionId, workspaceId]);
  return useSocialAccountConnectionMutation(
    `social-account-connections:mutation:disconnect:${workspaceId ?? "none"}:${
      connectionId ?? "none"
    }`,
    mutation,
  );
}
