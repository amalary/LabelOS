import { AppShell } from "../../components/app-shell";
import { requireDashboardSession } from "../../lib/dashboard-session";
import { CampaignsWorkspace } from "./campaigns-workspace";

export default async function CampaignsPage() {
  await requireDashboardSession();

  return (
    <AppShell>
      <CampaignsWorkspace />
    </AppShell>
  );
}
