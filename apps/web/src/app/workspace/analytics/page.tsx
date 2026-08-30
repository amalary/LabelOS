import { AppShell } from "../../../components/app-shell";
import { requireDashboardSession } from "../../../lib/dashboard-session";
import { AnalyticsConfigurationPanel } from "./analytics-configuration-panel";

export default async function WorkspaceAnalyticsConfigurationPage() {
  await requireDashboardSession();

  return (
    <AppShell>
      <AnalyticsConfigurationPanel />
    </AppShell>
  );
}
