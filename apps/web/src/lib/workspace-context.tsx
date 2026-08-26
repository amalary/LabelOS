"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";

import { can, capabilities, type AuthorizationSubject } from "./authorization";
import type { OrganizationSelection, OrganizationSummary } from "./organizations";
import { useCurrentProfile, useWorkspaceProfile } from "./profiles";
import type { WorkspaceProfileMembership } from "./profiles.types";

export type WorkspaceSummary = OrganizationSummary;

export type WorkspaceSelection = {
  activeWorkspace: WorkspaceSummary | null;
  workspaces: WorkspaceSummary[];
};

type ActiveWorkspaceContextValue = WorkspaceSelection & {
  hasActiveWorkspace: boolean;
};

export type ActiveWorkspaceProfileContext = {
  membership: WorkspaceProfileMembership | null;
  subject: AuthorizationSubject | null;
  roles: string[];
  departmentAccess: string[];
  capabilities: string[];
  responsibilities: string[];
  canEditProfile: boolean;
  isLoading: boolean;
};

const ActiveWorkspaceContext = createContext<ActiveWorkspaceContextValue | null>(null);

export function toWorkspaceSelection(selection: OrganizationSelection): WorkspaceSelection {
  return {
    activeWorkspace: selection.activeOrganization,
    workspaces: selection.organizations,
  };
}

export function ActiveWorkspaceProvider({
  children,
  selection,
}: {
  children: ReactNode;
  selection: OrganizationSelection;
}) {
  const workspaceSelection = toWorkspaceSelection(selection);
  const value = useMemo(
    () => ({
      ...workspaceSelection,
      hasActiveWorkspace: workspaceSelection.activeWorkspace !== null,
    }),
    [workspaceSelection.activeWorkspace, workspaceSelection.workspaces],
  );

  return (
    <ActiveWorkspaceContext.Provider value={value}>{children}</ActiveWorkspaceContext.Provider>
  );
}

export function useActiveWorkspace() {
  const context = useContext(ActiveWorkspaceContext);
  if (context === null) {
    throw new Error("useActiveWorkspace must be used within ActiveWorkspaceProvider");
  }
  return context;
}

export function workspaceProfileSubject(
  membership: WorkspaceProfileMembership | null,
  fallbackWorkspace: WorkspaceSummary | null,
): AuthorizationSubject | null {
  const workspacePermission =
    membership?.role ?? fallbackWorkspace?.workspace_permission ?? fallbackWorkspace?.role ?? null;
  if (!workspacePermission && !membership) {
    return null;
  }
  return {
    role: workspacePermission,
    workspacePermission,
    departmentAccess: membership?.department_access ?? fallbackWorkspace?.department_access ?? [],
    capabilities:
      membership?.capability_permissions ?? fallbackWorkspace?.capability_permissions ?? [],
  };
}

function uniqueValues(values: string[]): string[] {
  return [...new Set(values.filter((value) => value.trim().length > 0))];
}

export function resolvedWorkspaceRoles(membership: WorkspaceProfileMembership | null): string[] {
  if (!membership) {
    return [];
  }
  return uniqueValues([
    ...membership.professional_roles,
    ...membership.workspace_roles,
    ...(membership.role ? [membership.role] : []),
  ]);
}

export function useActiveWorkspaceProfile(): ActiveWorkspaceProfileContext {
  const { activeWorkspace } = useActiveWorkspace();
  const currentProfile = useCurrentProfile();
  const membership = useWorkspaceProfile(
    activeWorkspace?.id ?? null,
    currentProfile.data?.id ?? null,
  );
  const subject = workspaceProfileSubject(membership.data, activeWorkspace);
  const roles = resolvedWorkspaceRoles(membership.data);
  const departmentAccess =
    membership.data?.department_access ?? activeWorkspace?.department_access ?? [];
  const workspaceCapabilities =
    membership.data?.capability_permissions ?? activeWorkspace?.capability_permissions ?? [];

  return {
    membership: membership.data,
    subject,
    roles,
    departmentAccess,
    capabilities: workspaceCapabilities,
    responsibilities: workspaceCapabilities,
    canEditProfile: subject ? can(subject, null, capabilities.profileEdit) : false,
    isLoading: currentProfile.isLoading || membership.isLoading,
  };
}
