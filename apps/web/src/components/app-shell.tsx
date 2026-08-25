import type { ReactNode } from "react";

import { AuthNavigation } from "./auth/auth-navigation";
import { getNavigationAuthState } from "./auth/auth-session";
import { DashboardShellHeader } from "./dashboard-shell-header";
import { OrganizationSwitcher } from "./organization-switcher";
import { RealtimeWorkspaceSync } from "./realtime-workspace-sync";
import { ApiClientError } from "../lib/api-client";
import { getOrganizationSelection, type OrganizationSelection } from "../lib/organizations";
import { OrganizationRealtimeProvider } from "../lib/realtime/use-organization-realtime";
import { ActiveWorkspaceProvider } from "../lib/workspace-context";

type AppShellProps = {
  children: ReactNode;
};

export async function AppShell({ children }: AppShellProps) {
  const authState = await getNavigationAuthState();
  let organizationSelection: OrganizationSelection = {
    activeOrganization: null,
    organizations: [],
  };
  let organizationSelectionError: string | null = null;

  if (authState.isAuthenticated) {
    try {
      organizationSelection = await getOrganizationSelection();
    } catch (error) {
      if (!(error instanceof ApiClientError)) {
        throw error;
      }
      organizationSelectionError = "Workspaces unavailable";
    }
  }

  return (
    <div className="min-h-screen bg-[linear-gradient(135deg,#f8fafc_0%,#eef3f8_46%,#f7fafc_100%)] text-slate-950">
      <a
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-slate-950 focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-2 focus-visible:ring-offset-white"
        href="#main-content"
      >
        Skip to main content
      </a>
      <div className="grid min-h-screen lg:grid-cols-[240px_1fr]">
        <aside className="border-b border-white/70 bg-white/50 p-3 shadow-[inset_-1px_0_0_rgba(255,255,255,0.72)] backdrop-blur-xl sm:p-4 lg:border-b-0 lg:border-r lg:backdrop-blur-2xl">
          <div className="flex items-center gap-3 rounded-[16px] border border-white/75 bg-white/65 p-3 shadow-[0_14px_44px_rgba(15,23,42,0.07)] sm:rounded-[20px]">
            <span className="flex h-10 w-10 items-center justify-center rounded-[14px] bg-slate-950 text-xs font-semibold text-white">
              LO
            </span>
            <div>
              <div className="text-sm font-semibold text-slate-950">Label OS</div>
              <div className="text-xs text-slate-500">Operations</div>
            </div>
          </div>
          <nav aria-label="Workspace" className="mt-4 grid gap-1">
            <a
              className="rounded-md px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-white/70 hover:text-slate-950 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500"
              href="/dashboard"
            >
              Dashboard
            </a>
            <a
              className="rounded-md px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-white/70 hover:text-slate-950 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500"
              href="/workspace/settings"
            >
              Workspace Settings
            </a>
          </nav>
        </aside>
        <ActiveWorkspaceProvider selection={organizationSelection}>
          <OrganizationRealtimeProvider
            organizationId={organizationSelection.activeOrganization?.id ?? null}
          >
            <div className="flex min-w-0 flex-col">
              <DashboardShellHeader
                activeOrganization={organizationSelection.activeOrganization}
                authNavigation={<AuthNavigation {...authState} />}
                isLoading={authState.isLoading}
                organizationSwitcher={
                  <OrganizationSwitcher
                    {...organizationSelection}
                    error={organizationSelectionError}
                    isLoading={authState.isLoading}
                  />
                }
                realtimeStatus={<RealtimeWorkspaceSync />}
                user={authState.user}
              />
              <main className="flex-1 px-3 py-4 sm:px-4 sm:py-5 lg:px-6 lg:py-5" id="main-content">
                {children}
              </main>
            </div>
          </OrganizationRealtimeProvider>
        </ActiveWorkspaceProvider>
      </div>
    </div>
  );
}
