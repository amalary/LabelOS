import type { ReactNode } from "react";

import type { AuthUser } from "./auth/auth-types";
import type { OrganizationSummary } from "../lib/organizations";

type DashboardShellHeaderProps = {
  activeOrganization: OrganizationSummary | null;
  authNavigation: ReactNode;
  isLoading?: boolean;
  notificationsControl?: ReactNode;
  organizationSwitcher: ReactNode;
  realtimeStatus?: ReactNode;
  user: AuthUser | null;
};

function firstNameForGreeting(user: AuthUser | null) {
  return user?.firstName?.trim() || user?.name?.trim().split(/\s+/)[0] || null;
}

export function dashboardGreeting(date: Date, user: AuthUser | null) {
  const hour = date.getHours();
  const name = firstNameForGreeting(user);
  const daypart = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";

  return name ? `${daypart}, ${name}` : `${daypart}`;
}

function DefaultNotificationsControl() {
  return (
    <button
      aria-label="Open notifications"
      className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-white/70 bg-white/65 text-slate-700 shadow-[0_14px_34px_rgba(15,23,42,0.09)] backdrop-blur-2xl transition-colors duration-150 hover:bg-white/80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500"
      type="button"
    >
      <svg aria-hidden="true" className="h-5 w-5" fill="none" viewBox="0 0 24 24">
        <path
          d="M14.5 18.25a2.5 2.5 0 0 1-5 0M18.25 10.75a6.25 6.25 0 1 0-12.5 0c0 3.04-1.25 4.42-2 5.25-.43.47-.1 1.25.54 1.25h15.42c.64 0 .97-.78.54-1.25-.75-.83-2-2.21-2-5.25Z"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="1.8"
        />
      </svg>
    </button>
  );
}

export function DashboardShellHeader({
  activeOrganization,
  authNavigation,
  isLoading,
  notificationsControl,
  organizationSwitcher,
  realtimeStatus,
  user,
}: DashboardShellHeaderProps) {
  const organizationName = activeOrganization?.name ?? "Label operations dashboard";
  const description = activeOrganization
    ? `Here's what's happening across ${activeOrganization.name}.`
    : "Choose a workspace to see label operations.";

  return (
    <header className="border-b border-white/70 bg-white/50 px-3 py-4 backdrop-blur-xl sm:px-6 lg:backdrop-blur-2xl">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-600">{organizationName}</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-normal text-slate-950 sm:truncate">
            {isLoading ? "Dashboard" : dashboardGreeting(new Date(), user)}
          </h1>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-600">{description}</p>
        </div>

        <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-center xl:justify-end">
          <form action="/dashboard" className="relative min-w-0 lg:w-72" role="search">
            <label className="sr-only" htmlFor="dashboard-search">
              Search dashboard
            </label>
            <svg
              aria-hidden="true"
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
              fill="none"
              viewBox="0 0 24 24"
            >
              <path
                d="m20 20-4.5-4.5M18 10.75a7.25 7.25 0 1 1-14.5 0 7.25 7.25 0 0 1 14.5 0Z"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="1.8"
              />
            </svg>
            <input
              className="h-11 w-full rounded-full border border-white/70 bg-white/70 pl-10 pr-4 text-sm text-slate-900 shadow-[0_14px_34px_rgba(15,23,42,0.07)] outline-none transition-colors duration-150 placeholder:text-slate-400 focus:border-sky-300 focus:bg-white/85 focus-visible:ring-2 focus-visible:ring-sky-500"
              id="dashboard-search"
              name="q"
              placeholder="Search dashboard"
              type="search"
            />
          </form>

          <div className="flex min-w-0 flex-wrap items-center gap-3">
            {organizationSwitcher}
            {realtimeStatus}
            {notificationsControl ?? <DefaultNotificationsControl />}
            {authNavigation}
          </div>
        </div>
      </div>
    </header>
  );
}
