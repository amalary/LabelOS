import { AppShell } from "../../components/app-shell";
import { requireDashboardSession } from "../../lib/dashboard-session";
import { MarketingWorkspace } from "./marketing-workspace";

export default async function MarketingPage() {
  await requireDashboardSession();

  return (
    <AppShell>
      <MarketingWorkspace />
    </AppShell>
  );
}
