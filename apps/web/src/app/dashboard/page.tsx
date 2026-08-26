import Link from "next/link";
import { redirect } from "next/navigation";

import { AppShell } from "../../components/app-shell";
import { requireDashboardSession } from "../../lib/dashboard-session";
import { getOrganizationSelection } from "../../lib/organizations";
import { profileCompletionViewModel } from "../../lib/profile-completion";
import { getCurrentUniversalProfile } from "../../lib/profiles.server";
import { DashboardGrid } from "./_components/dashboard-grid";
import { DashboardHeader } from "./_components/dashboard-header";
import { getDashboardData, getEmptyDashboardData } from "./dashboard-data";

export default async function DashboardPage() {
  const session = await requireDashboardSession();
  const [organizationSelection, profile] = await Promise.all([
    getOrganizationSelection(),
    getCurrentUniversalProfile(),
  ]);
  if (!session.organizationId && organizationSelection.organizations.length === 0) {
    redirect("/onboarding/workspace");
  }

  const organization = organizationSelection.activeOrganization;
  const completionPrompt = profileCompletionViewModel(profile);
  const dashboardData = organization
    ? await getDashboardData()
    : getEmptyDashboardData({ emptyOrganization: true });

  return (
    <AppShell>
      <div
        aria-labelledby="dashboard-page-title"
        className="dashboard-surface relative isolate max-w-full overflow-hidden rounded-[20px] border border-slate-800/70 px-3 py-4 shadow-[0_28px_90px_rgba(2,6,23,0.24)] sm:-mx-1 sm:rounded-[28px] sm:px-5 sm:py-5 lg:-mx-2 lg:px-7 lg:py-7"
      >
        <div className="pointer-events-none absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-cyan-200/45 to-transparent" />
        <div className="flex flex-col gap-6">
          <DashboardHeader organizationName={organization?.name ?? "selected workspace"} />
          {completionPrompt ? (
            <section
              aria-live="polite"
              className="rounded-[16px] border border-sky-300/25 bg-sky-400/10 px-4 py-3 text-sm leading-6 text-sky-50"
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="font-semibold text-white">{completionPrompt.title}</p>
                  <p className="text-sky-100">{completionPrompt.missingSummary}</p>
                </div>
                <Link
                  className="inline-flex h-9 items-center justify-center rounded-md border border-sky-200/40 px-3 text-sm font-semibold text-white transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-200"
                  href={completionPrompt.href}
                >
                  Update profile
                </Link>
              </div>
            </section>
          ) : null}
          {!organization ? (
            <section
              aria-live="polite"
              className="rounded-[16px] border border-amber-300/25 bg-amber-400/10 px-4 py-3 text-sm leading-6 text-amber-100"
              role="alert"
            >
              Your active organization selection needs attention. Choose another organization from
              the workspace selector to refresh this dashboard context.
            </section>
          ) : null}
          <DashboardGrid data={dashboardData} />
        </div>
      </div>
    </AppShell>
  );
}
