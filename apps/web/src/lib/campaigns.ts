"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

export type CampaignApiErrorCode =
  "unauthorized" | "forbidden" | "not_found" | "conflict" | "network_failure";

export class CampaignApiError extends Error {
  constructor(
    readonly code: CampaignApiErrorCode,
    message: string,
    readonly status?: number,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "CampaignApiError";
  }
}

export type CampaignTeamMember = {
  workspace_membership_id: string;
  profile_id: string;
  display_name: string | null;
  participation_status: string;
  responsibility_label: string | null;
  is_owner: boolean;
};

export type CampaignOwner = {
  profile_id: string;
  display_name: string | null;
};

export type CampaignArtistSummary = {
  id: string;
  name: string;
};

export type CampaignReleaseSummary = {
  id: string;
  title: string;
  artist_id: string | null;
};

export type CampaignArtistRelationship = {
  artist: CampaignArtistSummary;
  relationship_kind: string;
  sort_order: number;
};

export type CampaignReleaseRelationship = {
  release: CampaignReleaseSummary;
  relationship_kind: string;
};

export type Campaign = {
  id: string;
  workspace_id: string;
  name: string;
  description: string | null;
  campaign_type: string;
  status: string;
  start_date: string | null;
  target_end_date: string | null;
  created_by_user_id: string | null;
  created_by_profile_id: string | null;
  owner_profile_id: string | null;
  owner: CampaignOwner | null;
  primary_artist: CampaignArtistSummary | null;
  release: CampaignReleaseSummary | null;
  members: CampaignTeamMember[];
  artists: CampaignArtistRelationship[];
  releases: CampaignReleaseRelationship[];
  created_at: string;
  updated_at: string;
};

export type CampaignsList = {
  campaigns: Campaign[];
  total: number;
  limit: number;
  offset: number;
};

export type CampaignMembersList = {
  members: CampaignTeamMember[];
};

export type CampaignMemberUpsert = {
  workspace_membership_id: string;
  participation_status?: string;
  responsibility_label?: string | null;
};

export type CampaignListOptions = {
  limit?: number;
  offset?: number;
};

export type CampaignCreate = {
  name: string;
  description?: string | null;
  campaign_type?: string;
  status?: string;
  start_date?: string | null;
  target_end_date?: string | null;
  owner_profile_id?: string | null;
  primary_artist_id?: string | null;
  release_id?: string | null;
};

export type CampaignGoal = {
  id: string;
  campaign_id: string;
  title: string;
  description: string | null;
  target_value: string | null;
  success_criteria: string | null;
  status: string;
  created_at: string;
  updated_at: string;
};

export type CampaignGoalsList = {
  goals: CampaignGoal[];
};

export type CampaignMilestone = {
  id: string;
  campaign_id: string;
  title: string;
  description: string | null;
  target_date: string | null;
  status: string;
  completed_at: string | null;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
};

export type CampaignMilestonesList = {
  milestones: CampaignMilestone[];
};

export type CampaignResourceState<T> = {
  data: T | null;
  error: CampaignApiError | null;
  isLoading: boolean;
  isMutating: boolean;
  reload: () => Promise<T>;
};

export type CampaignMutationState<TData, TVariables> = {
  data: TData | null;
  error: CampaignApiError | null;
  isMutating: boolean;
  mutate: (variables: TVariables) => Promise<TData>;
  reset: () => void;
};

type CacheEntry<T> = {
  data: T | null;
  error: CampaignApiError | null;
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

export const campaignQueryKeys = {
  all: "campaigns",
  workspaceList: (workspaceId: string, options?: CampaignListOptions) =>
    options?.limit || options?.offset
      ? `campaigns:workspace-list:${workspaceId}:limit:${options.limit ?? 50}:offset:${
          options.offset ?? 0
        }`
      : `campaigns:workspace-list:${workspaceId}`,
  detail: (workspaceId: string, campaignId: string) =>
    `campaigns:detail:${workspaceId}:${campaignId}`,
  goals: (workspaceId: string, campaignId: string) =>
    `campaigns:goals:${workspaceId}:${campaignId}`,
  milestones: (workspaceId: string, campaignId: string) =>
    `campaigns:milestones:${workspaceId}:${campaignId}`,
};

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

function toCampaignApiError(status: number): CampaignApiError {
  if (status === 401) {
    return new CampaignApiError("unauthorized", "Sign in again to load campaign data.", status);
  }
  if (status === 403) {
    return new CampaignApiError("forbidden", "You do not have access to this campaign.", status);
  }
  if (status === 404) {
    return new CampaignApiError("not_found", "Campaign data was not found.", status);
  }
  if (status === 409) {
    return new CampaignApiError("conflict", "Campaign data could not be changed.", status);
  }
  return new CampaignApiError("network_failure", "Campaign data could not be loaded.", status);
}

async function campaignJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      cache: "no-store",
      headers,
    });
  } catch (error) {
    throw new CampaignApiError("network_failure", "Unable to reach the campaign API.", undefined, {
      cause: error,
    });
  }

  if (!response.ok) {
    throw toCampaignApiError(response.status);
  }

  if (response.status === 204) {
    return undefined as T;
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
        error instanceof CampaignApiError
          ? error
          : new CampaignApiError(
              "network_failure",
              "Campaign data could not be loaded.",
              undefined,
              {
                cause: error,
              },
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

function useCampaignResource<T>(
  key: string | null,
  fetcher: (() => Promise<T>) | null,
): CampaignResourceState<T> {
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

  const getSnapshot = useCallback(() => {
    if (!key) {
      return 0;
    }
    return entryFor<T>(key).version;
  }, [key]);

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
      throw new CampaignApiError("not_found", "A campaign resource key is required.");
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

export function invalidateCampaignCache(predicate?: (key: string) => boolean) {
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

export function shouldInvalidateCampaignRealtimeCacheKey({
  campaignId,
  eventType,
  key,
  workspaceId,
}: {
  campaignId: string | null;
  eventType: string;
  key: string;
  workspaceId: string;
}) {
  const workspaceListPrefix = `campaigns:workspace-list:${workspaceId}:`;
  if (key === campaignQueryKeys.workspaceList(workspaceId) || key.startsWith(workspaceListPrefix)) {
    return true;
  }
  if (!key.startsWith(`${campaignQueryKeys.all}:`)) {
    return false;
  }
  if (!campaignId) {
    return key.startsWith(`campaigns:workspace-list:${workspaceId}`);
  }
  if (key === campaignQueryKeys.detail(workspaceId, campaignId)) {
    return true;
  }
  if (eventType.startsWith("campaign.goal_")) {
    return key === campaignQueryKeys.goals(workspaceId, campaignId);
  }
  if (eventType.startsWith("campaign.milestone_")) {
    return key === campaignQueryKeys.milestones(workspaceId, campaignId);
  }
  return false;
}

export function clearCampaignCache() {
  cache.clear();
  activeMutationCount = 0;
  mutationVersion = 0;
}

function campaignListQuery(options?: CampaignListOptions): string {
  const params = new URLSearchParams();
  if (options?.limit !== undefined) {
    params.set("limit", String(options.limit));
  }
  if (options?.offset !== undefined) {
    params.set("offset", String(options.offset));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function getCampaigns(
  workspaceId: string,
  options?: CampaignListOptions,
): Promise<CampaignsList> {
  return campaignJson<CampaignsList>(
    `/api/workspaces/${workspaceId}/campaigns${campaignListQuery(options)}`,
  );
}

export function createCampaign(workspaceId: string, payload: CampaignCreate): Promise<Campaign> {
  return campaignJson<Campaign>(`/api/workspaces/${workspaceId}/campaigns`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getCampaign(workspaceId: string, campaignId: string): Promise<Campaign> {
  return campaignJson<Campaign>(`/api/workspaces/${workspaceId}/campaigns/${campaignId}`);
}

export function getCampaignGoals(
  workspaceId: string,
  campaignId: string,
): Promise<CampaignGoalsList> {
  return campaignJson<CampaignGoalsList>(
    `/api/workspaces/${workspaceId}/campaigns/${campaignId}/goals`,
  );
}

export function getCampaignMilestones(
  workspaceId: string,
  campaignId: string,
): Promise<CampaignMilestonesList> {
  return campaignJson<CampaignMilestonesList>(
    `/api/workspaces/${workspaceId}/campaigns/${campaignId}/milestones`,
  );
}

export function getCampaignMembers(
  workspaceId: string,
  campaignId: string,
): Promise<CampaignMembersList> {
  return campaignJson<CampaignMembersList>(
    `/api/workspaces/${workspaceId}/campaigns/${campaignId}/members`,
  );
}

export function upsertCampaignMember(
  workspaceId: string,
  campaignId: string,
  payload: CampaignMemberUpsert,
): Promise<CampaignTeamMember> {
  return campaignJson<CampaignTeamMember>(
    `/api/workspaces/${workspaceId}/campaigns/${campaignId}/members`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  );
}

export function removeCampaignMember(
  workspaceId: string,
  campaignId: string,
  workspaceMembershipId: string,
): Promise<void> {
  return campaignJson<void>(
    `/api/workspaces/${workspaceId}/campaigns/${campaignId}/members/${workspaceMembershipId}`,
    {
      method: "DELETE",
    },
  );
}

export function useCampaigns(
  workspaceId: string | null,
  options?: CampaignListOptions,
): CampaignResourceState<CampaignsList> {
  const limit = options?.limit;
  const offset = options?.offset;
  const key = workspaceId ? campaignQueryKeys.workspaceList(workspaceId, { limit, offset }) : null;
  const fetcher = useCallback(
    () => getCampaigns(workspaceId ?? "", { limit, offset }),
    [limit, offset, workspaceId],
  );
  return useCampaignResource(key, workspaceId ? fetcher : null);
}

export function useCampaign(
  workspaceId: string | null,
  campaignId: string | null,
): CampaignResourceState<Campaign> {
  const key = workspaceId && campaignId ? campaignQueryKeys.detail(workspaceId, campaignId) : null;
  const fetcher = useCallback(
    () => getCampaign(workspaceId ?? "", campaignId ?? ""),
    [campaignId, workspaceId],
  );
  return useCampaignResource(key, workspaceId && campaignId ? fetcher : null);
}

export function useCampaignGoals(
  workspaceId: string | null,
  campaignId: string | null,
): CampaignResourceState<CampaignGoalsList> {
  const key = workspaceId && campaignId ? campaignQueryKeys.goals(workspaceId, campaignId) : null;
  const fetcher = useCallback(
    () => getCampaignGoals(workspaceId ?? "", campaignId ?? ""),
    [campaignId, workspaceId],
  );
  return useCampaignResource(key, workspaceId && campaignId ? fetcher : null);
}

export function useCampaignMilestones(
  workspaceId: string | null,
  campaignId: string | null,
): CampaignResourceState<CampaignMilestonesList> {
  const key =
    workspaceId && campaignId ? campaignQueryKeys.milestones(workspaceId, campaignId) : null;
  const fetcher = useCallback(
    () => getCampaignMilestones(workspaceId ?? "", campaignId ?? ""),
    [campaignId, workspaceId],
  );
  return useCampaignResource(key, workspaceId && campaignId ? fetcher : null);
}

export function useCreateCampaign(
  workspaceId: string | null,
): CampaignMutationState<Campaign, CampaignCreate> {
  const getVersion = useCallback(() => mutationVersion, []);
  const subscribe = useCallback((listener: () => void) => {
    mutationListeners.add(listener);
    return () => {
      mutationListeners.delete(listener);
    };
  }, []);
  useSyncExternalStore(subscribe, getVersion, getVersion);

  const entry = entryFor<Campaign>(`campaigns:mutation:create:${workspaceId ?? "none"}`);
  const mutate = useCallback(
    async (payload: CampaignCreate) => {
      if (!workspaceId) {
        throw new CampaignApiError("not_found", "A workspace resource key is required.");
      }
      activeMutationCount += 1;
      entry.isLoading = true;
      entry.error = null;
      emitMutationChange();
      try {
        const campaign = await createCampaign(workspaceId, payload);
        entry.data = campaign;
        entry.error = null;
        const detailEntry = entryFor<Campaign>(campaignQueryKeys.detail(workspaceId, campaign.id));
        detailEntry.data = campaign;
        detailEntry.error = null;
        emit(detailEntry);
        const workspaceListPrefix = `campaigns:workspace-list:${workspaceId}:`;
        invalidateCampaignCache(
          (key) =>
            key === campaignQueryKeys.workspaceList(workspaceId) ||
            key.startsWith(workspaceListPrefix),
        );
        return campaign;
      } catch (error) {
        entry.error =
          error instanceof CampaignApiError
            ? error
            : new CampaignApiError("network_failure", "Campaign creation failed.", undefined, {
                cause: error,
              });
        throw entry.error;
      } finally {
        activeMutationCount = Math.max(0, activeMutationCount - 1);
        entry.isLoading = false;
        emitMutationChange();
      }
    },
    [entry, workspaceId],
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
    isMutating: entry.isLoading,
    mutate,
    reset,
  };
}
