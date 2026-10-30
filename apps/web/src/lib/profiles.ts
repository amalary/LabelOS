"use client";

import { createResourceCache, useCachedResource } from "./resource-cache";

import { useCallback, useMemo, useSyncExternalStore } from "react";

import type {
  ArtistProfileCreate,
  ArtistProfileDetail,
  ArtistProfileUpdate,
  UniversalProfile,
  UniversalProfileUpdate,
  WorkspacePeopleDirectory,
  WorkspaceProfileMembership,
  WorkspaceProfilesList,
} from "./profiles.types";

export type ProfileApiErrorCode =
  "unauthorized" | "forbidden" | "not_found" | "conflict" | "network_failure";

export class ProfileApiError extends Error {
  constructor(
    readonly code: ProfileApiErrorCode,
    message: string,
    readonly status?: number,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "ProfileApiError";
  }
}

export type AsyncResourceState<T> = {
  data: T | null;
  error: ProfileApiError | null;
  isLoading: boolean;
  isMutating: boolean;
  reload: () => Promise<T>;
};

export type MutationState<TData, TVariables> = {
  data: TData | null;
  error: ProfileApiError | null;
  isMutating: boolean;
  mutate: (variables: TVariables) => Promise<TData>;
  reset: () => void;
};

const cache = createResourceCache({
  toError: (error: unknown) =>
    error instanceof ProfileApiError
      ? error
      : new ProfileApiError("network_failure", "Profile data could not be loaded.", undefined, {
          cause: error,
        }),
  missingKeyError: () => new ProfileApiError("not_found", "A profile resource key is required."),
});
const { entryFor, emit } = cache;
const mutationListeners = new Set<() => void>();
let mutationVersion = 0;
let activeMutationCount = 0;

export const profileQueryKeys = {
  all: "profiles",
  current: "profiles:current",
  workspaceMembers: (workspaceId: string, limit = 50, offset = 0) =>
    `profiles:workspace-members:${workspaceId}:${limit}:${offset}`,
  workspacePeople: (workspaceId: string, query = "", limit = 25, offset = 0) =>
    `profiles:workspace-people:${workspaceId}:${query}:${limit}:${offset}`,
  workspaceProfile: (workspaceId: string, profileId: string) =>
    `profiles:workspace-profile:${workspaceId}:${profileId}`,
  artistProfile: (workspaceId: string, artistProfileId: string) =>
    `profiles:artist-profile:${workspaceId}:${artistProfileId}`,
};

function emitMutationChange() {
  mutationVersion += 1;
  for (const listener of mutationListeners) {
    listener();
  }
}

function toProfileApiError(status: number): ProfileApiError {
  if (status === 401) {
    return new ProfileApiError("unauthorized", "Sign in again to load profile data.", status);
  }
  if (status === 403) {
    return new ProfileApiError("forbidden", "You do not have access to this profile data.", status);
  }
  if (status === 404) {
    return new ProfileApiError("not_found", "Profile data was not found.", status);
  }
  if (status === 409) {
    return new ProfileApiError(
      "conflict",
      "Profile data changed before your update was saved.",
      status,
    );
  }
  return new ProfileApiError("network_failure", "Profile data could not be loaded.", status);
}

async function profileJson<T>(path: string, init?: RequestInit): Promise<T> {
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
    throw new ProfileApiError("network_failure", "Unable to reach the profile API.", undefined, {
      cause: error,
    });
  }

  if (!response.ok) {
    throw toProfileApiError(response.status);
  }

  return (await response.json()) as T;
}

function useProfileResource<T>(
  key: string | null,
  fetcher: (() => Promise<T>) | null,
): AsyncResourceState<T> {
  return { ...useCachedResource(cache, key, fetcher), isMutating: activeMutationCount > 0 };
}

export function invalidateProfileCache(predicate?: (key: string) => boolean) {
  cache.invalidate(predicate);
}

export function clearProfileCache() {
  cache.clear();
  activeMutationCount = 0;
  mutationVersion = 0;
}

export function getCurrentProfile(): Promise<UniversalProfile> {
  return profileJson<UniversalProfile>("/api/profiles/me");
}

export function getProfile(profileId: string): Promise<UniversalProfile> {
  return profileJson<UniversalProfile>(`/api/profiles/${profileId}`);
}

export function updateCurrentProfile(payload: UniversalProfileUpdate): Promise<UniversalProfile> {
  return profileJson<UniversalProfile>("/api/profiles/me", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function getWorkspaceMembers(
  workspaceId: string,
  options: { limit?: number; offset?: number } = {},
): Promise<WorkspaceProfilesList> {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  });
  return profileJson<WorkspaceProfilesList>(
    `/api/profiles/workspaces/${workspaceId}/profiles?${params.toString()}`,
  );
}

export function getWorkspacePeopleDirectory(
  workspaceId: string,
  options: { query?: string; limit?: number; offset?: number } = {},
): Promise<WorkspacePeopleDirectory> {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 25),
    offset: String(options.offset ?? 0),
  });
  const query = options.query?.trim();
  if (query) {
    params.set("query", query);
  }
  return profileJson<WorkspacePeopleDirectory>(
    `/api/profiles/workspaces/${workspaceId}/people?${params.toString()}`,
  );
}

export function getWorkspaceProfile(
  workspaceId: string,
  profileId: string,
): Promise<WorkspaceProfileMembership> {
  return profileJson<WorkspaceProfileMembership>(
    `/api/profiles/workspaces/${workspaceId}/profiles/${profileId}`,
  );
}

export function getArtistProfile(
  workspaceId: string,
  artistProfileId: string,
): Promise<ArtistProfileDetail> {
  return profileJson<ArtistProfileDetail>(
    `/api/profiles/workspaces/${workspaceId}/artist-profiles/${artistProfileId}`,
  );
}

export function createArtistProfile(
  workspaceId: string,
  payload: ArtistProfileCreate,
): Promise<ArtistProfileDetail> {
  return profileJson<ArtistProfileDetail>(
    `/api/profiles/workspaces/${workspaceId}/artist-profiles`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function updateArtistProfile(
  workspaceId: string,
  artistProfileId: string,
  payload: ArtistProfileUpdate,
): Promise<ArtistProfileDetail> {
  return profileJson<ArtistProfileDetail>(
    `/api/profiles/workspaces/${workspaceId}/artist-profiles/${artistProfileId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function useCurrentProfile(): AsyncResourceState<UniversalProfile> {
  return useProfileResource(profileQueryKeys.current, getCurrentProfile);
}

export function useWorkspaceMembers(
  workspaceId: string | null,
  options: { limit?: number; offset?: number } = {},
): AsyncResourceState<WorkspaceProfilesList> {
  const limit = options.limit ?? 50;
  const offset = options.offset ?? 0;
  const key = workspaceId ? profileQueryKeys.workspaceMembers(workspaceId, limit, offset) : null;
  const fetcher = useCallback(
    () => getWorkspaceMembers(workspaceId ?? "", { limit, offset }),
    [limit, offset, workspaceId],
  );
  return useProfileResource(key, workspaceId ? fetcher : null);
}

export function useWorkspacePeopleDirectory(
  workspaceId: string | null,
  options: { query?: string; limit?: number; offset?: number } = {},
): AsyncResourceState<WorkspacePeopleDirectory> {
  const query = options.query?.trim() ?? "";
  const limit = options.limit ?? 25;
  const offset = options.offset ?? 0;
  const key = workspaceId
    ? profileQueryKeys.workspacePeople(workspaceId, query, limit, offset)
    : null;
  const fetcher = useCallback(
    () => getWorkspacePeopleDirectory(workspaceId ?? "", { query, limit, offset }),
    [limit, offset, query, workspaceId],
  );
  return useProfileResource(key, workspaceId ? fetcher : null);
}

export function useWorkspaceProfile(
  workspaceId: string | null,
  profileId: string | null,
): AsyncResourceState<WorkspaceProfileMembership> {
  const key =
    workspaceId && profileId ? profileQueryKeys.workspaceProfile(workspaceId, profileId) : null;
  const fetcher = useCallback(
    () => getWorkspaceProfile(workspaceId ?? "", profileId ?? ""),
    [profileId, workspaceId],
  );
  return useProfileResource(key, workspaceId && profileId ? fetcher : null);
}

export function useArtistProfile(
  workspaceId: string | null,
  artistProfileId: string | null,
): AsyncResourceState<ArtistProfileDetail> {
  const key =
    workspaceId && artistProfileId
      ? profileQueryKeys.artistProfile(workspaceId, artistProfileId)
      : null;
  const fetcher = useCallback(
    () => getArtistProfile(workspaceId ?? "", artistProfileId ?? ""),
    [artistProfileId, workspaceId],
  );
  return useProfileResource(key, workspaceId && artistProfileId ? fetcher : null);
}

export function useProfileRoles(
  workspaceId: string | null,
  profileId: string | null,
): AsyncResourceState<string[]> {
  const workspaceProfile = useWorkspaceProfile(workspaceId, profileId);
  return useMemo(
    () => ({
      ...workspaceProfile,
      data: workspaceProfile.data
        ? [...workspaceProfile.data.professional_roles, ...workspaceProfile.data.workspace_roles]
        : null,
      reload: async () => {
        const membership = await workspaceProfile.reload();
        return [...membership.professional_roles, ...membership.workspace_roles];
      },
    }),
    [workspaceProfile],
  );
}

export function useProfileCapabilities(
  workspaceId: string | null,
  profileId: string | null,
): AsyncResourceState<string[]> {
  const workspaceProfile = useWorkspaceProfile(workspaceId, profileId);
  return useMemo(
    () => ({
      ...workspaceProfile,
      data: workspaceProfile.data?.capability_permissions ?? null,
      reload: async () => {
        const membership = await workspaceProfile.reload();
        return membership.capability_permissions;
      },
    }),
    [workspaceProfile],
  );
}

export function useUpdateCurrentProfile(): MutationState<UniversalProfile, UniversalProfileUpdate> {
  const getVersion = useCallback(() => mutationVersion, []);
  const subscribe = useCallback((listener: () => void) => {
    mutationListeners.add(listener);
    return () => {
      mutationListeners.delete(listener);
    };
  }, []);
  useSyncExternalStore(subscribe, getVersion, getVersion);

  const entry = entryFor<UniversalProfile>("profiles:mutation:update-current");
  const mutate = useCallback(
    async (payload: UniversalProfileUpdate) => {
      activeMutationCount += 1;
      entry.isLoading = true;
      entry.error = null;
      emitMutationChange();
      try {
        const profile = await updateCurrentProfile(payload);
        entry.data = profile;
        entry.error = null;
        const currentEntry = entryFor<UniversalProfile>(profileQueryKeys.current);
        currentEntry.data = profile;
        currentEntry.error = null;
        emit(currentEntry);
        invalidateProfileCache((key) => key.startsWith("profiles:workspace-"));
        return profile;
      } catch (error) {
        entry.error =
          error instanceof ProfileApiError
            ? error
            : new ProfileApiError("network_failure", "Profile update failed.", undefined, {
                cause: error,
              });
        throw entry.error;
      } finally {
        activeMutationCount = Math.max(0, activeMutationCount - 1);
        entry.isLoading = false;
        emitMutationChange();
      }
    },
    [entry],
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

export function useUpdateArtistProfile(
  workspaceId: string | null,
  artistProfileId: string | null,
): MutationState<ArtistProfileDetail, ArtistProfileUpdate> {
  const getVersion = useCallback(() => mutationVersion, []);
  const subscribe = useCallback((listener: () => void) => {
    mutationListeners.add(listener);
    return () => {
      mutationListeners.delete(listener);
    };
  }, []);
  useSyncExternalStore(subscribe, getVersion, getVersion);

  const entry = entryFor<ArtistProfileDetail>(
    `profiles:mutation:update-artist-profile:${workspaceId ?? "none"}:${artistProfileId ?? "none"}`,
  );
  const mutate = useCallback(
    async (payload: ArtistProfileUpdate) => {
      if (!workspaceId || !artistProfileId) {
        throw new ProfileApiError("not_found", "An artist profile resource key is required.");
      }
      activeMutationCount += 1;
      entry.isLoading = true;
      entry.error = null;
      emitMutationChange();
      try {
        const artistProfile = await updateArtistProfile(workspaceId, artistProfileId, payload);
        entry.data = artistProfile;
        entry.error = null;
        const profileEntry = entryFor<ArtistProfileDetail>(
          profileQueryKeys.artistProfile(workspaceId, artistProfileId),
        );
        profileEntry.data = artistProfile;
        profileEntry.error = null;
        emit(profileEntry);
        invalidateProfileCache((key) =>
          key.startsWith(`profiles:workspace-people:${workspaceId}:`),
        );
        return artistProfile;
      } catch (error) {
        entry.error =
          error instanceof ProfileApiError
            ? error
            : new ProfileApiError("network_failure", "Artist profile update failed.", undefined, {
                cause: error,
              });
        throw entry.error;
      } finally {
        activeMutationCount = Math.max(0, activeMutationCount - 1);
        entry.isLoading = false;
        emitMutationChange();
      }
    },
    [artistProfileId, entry, workspaceId],
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

export function useCreateArtistProfile(
  workspaceId: string | null,
): MutationState<ArtistProfileDetail, ArtistProfileCreate> {
  const getVersion = useCallback(() => mutationVersion, []);
  const subscribe = useCallback((listener: () => void) => {
    mutationListeners.add(listener);
    return () => {
      mutationListeners.delete(listener);
    };
  }, []);
  useSyncExternalStore(subscribe, getVersion, getVersion);

  const entry = entryFor<ArtistProfileDetail>(
    `profiles:mutation:create-artist-profile:${workspaceId ?? "none"}`,
  );
  const mutate = useCallback(
    async (payload: ArtistProfileCreate) => {
      if (!workspaceId) {
        throw new ProfileApiError("not_found", "A workspace resource key is required.");
      }
      activeMutationCount += 1;
      entry.isLoading = true;
      entry.error = null;
      emitMutationChange();
      try {
        const artistProfile = await createArtistProfile(workspaceId, payload);
        entry.data = artistProfile;
        entry.error = null;
        const profileEntry = entryFor<ArtistProfileDetail>(
          profileQueryKeys.artistProfile(workspaceId, artistProfile.id),
        );
        profileEntry.data = artistProfile;
        profileEntry.error = null;
        emit(profileEntry);
        invalidateProfileCache((key) =>
          key.startsWith(`profiles:workspace-people:${workspaceId}:`),
        );
        return artistProfile;
      } catch (error) {
        entry.error =
          error instanceof ProfileApiError
            ? error
            : new ProfileApiError("network_failure", "Artist profile creation failed.", undefined, {
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
