import { redirect } from "next/navigation";

import { AppShell } from "../../components/app-shell";
import { requireDashboardSession } from "../../lib/dashboard-session";
import { getOrganizationSelection } from "../../lib/organizations";
import { DashboardGrid } from "./_components/dashboard-grid";
import { DashboardHeader } from "./_components/dashboard-header";
import { getDashboardData, getEmptyDashboardData } from "./dashboard-data";

export default async function DashboardPage() {
  const session = await requireDashboardSession();
  const organizationSelection = await getOrganizationSelection();
  if (!session.organizationId && organizationSelection.organizations.length === 0) {
    redirect("/onboarding/workspace");
  }

  const organization = organizationSelection.activeOrganization;
  const dashboardData = organization
    ? await getDashboardData()
    : getEmptyDashboardData({ emptyOrganization: true });

  return (
    <AppShell>
      <div className="dashboard-surface relative isolate -mx-2 overflow-hidden rounded-[28px] border border-slate-800/80 px-4 py-5 shadow-[0_32px_110px_rgba(2,6,23,0.28)] sm:-mx-3 sm:px-6 sm:py-6 lg:px-8 lg:py-8">
        <div className="pointer-events-none absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-cyan-300/50 to-transparent" />
        <div className="flex flex-col gap-7">
          <DashboardHeader organizationName={organization?.name ?? "selected workspace"} />
          {!organization ? (
            <section
              aria-live="polite"
              className="rounded-[18px] border border-amber-300/30 bg-amber-400/10 px-5 py-4 text-sm leading-6 text-amber-100"
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
