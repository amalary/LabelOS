"use client";

import { useCallback, useEffect, useMemo, useSyncExternalStore } from "react";

import {
  type AuthorizationSubject,
  type Capability,
} from "./authorization";

export type WorkspaceCapabilityApiErrorCode =
  "unauthorized" | "forbidden" | "not_found" | "network_failure";

export class WorkspaceCapabilityApiError extends Error {
  constructor(
    readonly code: WorkspaceCapabilityApiErrorCode,
    message: string,
    readonly status?: number,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "WorkspaceCapabilityApiError";
  }
}

export type WorkspaceRoleSummary = {
  key: string;
  name: string;
};

export type WorkspaceAuthorizationContext = {
  workspace_id: string;
  roles: WorkspaceRoleSummary[];
  capabilities: string[];
};

export type WorkspaceRoleDefinition = {
  id: string;
  key: string;
  name: string;
  description: string;
  system_role: boolean;
  capabilities: string[];
};

export type WorkspaceRolesList = {
  roles: WorkspaceRoleDefinition[];
};

export type MemberRoleAssignmentSummary = {
  member_id: string;
  roles: WorkspaceRoleSummary[];
};

export type MemberRoleAssignmentsList = {
  assignments: MemberRoleAssignmentSummary[];
};

export type WorkspaceCapabilityState<T> = {
  data: T | null;
  error: WorkspaceCapabilityApiError | null;
  isLoading: boolean;
  reload: () => Promise<T>;
};

export type EffectiveCapabilitiesState = WorkspaceCapabilityState<WorkspaceAuthorizationContext> & {
  roles: WorkspaceRoleSummary[];
  capabilities: string[];
  subject: AuthorizationSubject | null;
  can: (capability: Capability | string) => boolean;
  hasCapability: (capability: Capability | string) => boolean;
};

type CacheEntry<T> = {
  data: T | null;
  error: WorkspaceCapabilityApiError | null;
  fetcher: (() => Promise<T>) | null;
  isLoading: boolean;
  listeners: Set<() => void>;
  promise: Promise<T> | null;
  version: number;
};

const cache = new Map<string, CacheEntry<unknown>>();

export const workspaceCapabilityQueryKeys = {
  all: "workspace-capabilities",
  authorizationContext: (workspaceId: string) =>
    `workspace-capabilities:authorization-context:${workspaceId}`,
  roles: (workspaceId: string) => `workspace-capabilities:roles:${workspaceId}`,
  memberRoleAssignments: (workspaceId: string) =>
    `workspace-capabilities:member-role-assignments:${workspaceId}`,
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

function toWorkspaceCapabilityApiError(status: number): WorkspaceCapabilityApiError {
  if (status === 401) {
    return new WorkspaceCapabilityApiError(
      "unauthorized",
      "Sign in again to load workspace capabilities.",
      status,
    );
  }
  if (status === 403) {
    return new WorkspaceCapabilityApiError(
      "forbidden",
      "You are not allowed to view this workspace capability data.",
      status,
    );
  }
  if (status === 404) {
    return new WorkspaceCapabilityApiError(
      "not_found",
      "Workspace capability data was not found.",
      status,
    );
  }
  return new WorkspaceCapabilityApiError(
    "network_failure",
    "Workspace capability data could not be loaded.",
    status,
  );
}

async function workspaceCapabilityJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");

  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      cache: "no-store",
      headers,
    });
  } catch (error) {
    throw new WorkspaceCapabilityApiError(
      "network_failure",
      "Unable to reach the workspace capability API.",
      undefined,
      { cause: error },
    );
  }

  if (!response.ok) {
    throw toWorkspaceCapabilityApiError(response.status);
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
        error instanceof WorkspaceCapabilityApiError
          ? error
          : new WorkspaceCapabilityApiError(
              "network_failure",
              "Workspace capability data could not be loaded.",
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

function useWorkspaceCapabilityResource<T>(
  key: string | null,
  fetcher: (() => Promise<T>) | null,
): WorkspaceCapabilityState<T> {
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
      throw new WorkspaceCapabilityApiError(
        "not_found",
        "A workspace capability resource key is required.",
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

export function invalidateWorkspaceCapabilityCache(predicate?: (key: string) => boolean) {
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

export function clearWorkspaceCapabilityCache() {
  cache.clear();
}

export function getCurrentWorkspaceAuthorization(
  workspaceId: string,
): Promise<WorkspaceAuthorizationContext> {
  return workspaceCapabilityJson<WorkspaceAuthorizationContext>(
    `/api/workspaces/${workspaceId}/authorization/context`,
  );
}

export function getEffectiveCapabilities(workspaceId: string): Promise<string[]> {
  return getCurrentWorkspaceAuthorization(workspaceId).then((context) => context.capabilities);
}

export function getCurrentWorkspaceRoles(workspaceId: string): Promise<WorkspaceRoleSummary[]> {
  return getCurrentWorkspaceAuthorization(workspaceId).then((context) => context.roles);
}

export function getWorkspaceRoles(workspaceId: string): Promise<WorkspaceRolesList> {
  return workspaceCapabilityJson<WorkspaceRolesList>(`/api/workspaces/${workspaceId}/roles`);
}

export function getMemberRoleAssignments(
  workspaceId: string,
): Promise<MemberRoleAssignmentsList> {
  return workspaceCapabilityJson<MemberRoleAssignmentsList>(
    `/api/workspaces/${workspaceId}/member-role-assignments`,
  );
}

export function useWorkspaceAuthorizationContext(
  workspaceId: string | null,
): WorkspaceCapabilityState<WorkspaceAuthorizationContext> {
  const key = workspaceId
    ? workspaceCapabilityQueryKeys.authorizationContext(workspaceId)
    : null;
  const fetcher = useCallback(
    () => getCurrentWorkspaceAuthorization(workspaceId ?? ""),
    [workspaceId],
  );
  return useWorkspaceCapabilityResource(key, workspaceId ? fetcher : null);
}

function resolvedWorkspacePermission(roles: WorkspaceRoleSummary[]): string | null {
  const roleKeys = new Set(roles.map((role) => role.key));
  if (roleKeys.has("owner")) {
    return "owner";
  }
  if (roleKeys.has("admin")) {
    return "admin";
  }
  if (roleKeys.has("member")) {
    return "member";
  }
  return roles[0]?.key ?? null;
}

export function useEffectiveCapabilities(workspaceId: string | null): EffectiveCapabilitiesState {
  const authorization = useWorkspaceAuthorizationContext(workspaceId);
  const roles = authorization.data?.roles ?? [];
  const capabilities = authorization.data?.capabilities ?? [];
  const workspacePermission = resolvedWorkspacePermission(roles);
  const subject = useMemo<AuthorizationSubject | null>(
    () =>
      authorization.data
        ? {
            capabilities,
            role: workspacePermission,
            workspacePermission,
          }
        : null,
    [authorization.data, capabilities, workspacePermission],
  );
  const can = useCallback(
    (capability: Capability | string) =>
      workspacePermission === "owner" || capabilities.includes(capability),
    [capabilities, workspacePermission],
  );
  const hasCapability = useCallback(
    (capability: Capability | string) => can(capability),
    [can],
  );

  return {
    ...authorization,
    roles,
    capabilities,
    subject,
    can,
    hasCapability,
  };
}

export function useCapabilities(workspaceId: string | null): EffectiveCapabilitiesState {
  return useEffectiveCapabilities(workspaceId);
}

export function useCurrentWorkspaceRoles(
  workspaceId: string | null,
): WorkspaceCapabilityState<WorkspaceRoleSummary[]> {
  const authorization = useWorkspaceAuthorizationContext(workspaceId);
  return useMemo(
    () => ({
      ...authorization,
      data: authorization.data?.roles ?? null,
      reload: async () => {
        const context = await authorization.reload();
        return context.roles;
      },
    }),
    [authorization],
  );
}

export function useWorkspaceRoles(
  workspaceId: string | null,
): WorkspaceCapabilityState<WorkspaceRolesList> {
  const key = workspaceId ? workspaceCapabilityQueryKeys.roles(workspaceId) : null;
  const fetcher = useCallback(() => getWorkspaceRoles(workspaceId ?? ""), [workspaceId]);
  return useWorkspaceCapabilityResource(key, workspaceId ? fetcher : null);
}

export function useMemberRoleAssignments(
  workspaceId: string | null,
): WorkspaceCapabilityState<MemberRoleAssignmentsList> {
  const key = workspaceId ? workspaceCapabilityQueryKeys.memberRoleAssignments(workspaceId) : null;
  const fetcher = useCallback(() => getMemberRoleAssignments(workspaceId ?? ""), [workspaceId]);
  return useWorkspaceCapabilityResource(key, workspaceId ? fetcher : null);
}

export function shouldInvalidateWorkspaceCapabilityRealtimeCacheKey({
  key,
  organizationId,
}: {
  key: string;
  organizationId: string;
}) {
  return (
    key === workspaceCapabilityQueryKeys.authorizationContext(organizationId) ||
    key === workspaceCapabilityQueryKeys.roles(organizationId) ||
    key === workspaceCapabilityQueryKeys.memberRoleAssignments(organizationId)
  );
}
