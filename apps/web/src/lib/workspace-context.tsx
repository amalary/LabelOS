"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";

import type { OrganizationSelection, OrganizationSummary } from "./organizations";

export type WorkspaceSummary = OrganizationSummary;

export type WorkspaceSelection = {
  activeWorkspace: WorkspaceSummary | null;
  workspaces: WorkspaceSummary[];
};

type ActiveWorkspaceContextValue = WorkspaceSelection & {
  hasActiveWorkspace: boolean;
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
