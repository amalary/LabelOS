import { AppShell } from "../../components/app-shell";
import { requireDashboardSession } from "../../lib/dashboard-session";
import { AnalyticsWorkspace } from "./analytics-workspace";

export default async function AnalyticsPage() {
  await requireDashboardSession();

  return (
    <AppShell>
      <AnalyticsWorkspace />
    </AppShell>
  );
}
