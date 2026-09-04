import { AppShell } from "../../components/app-shell";
import { requireDashboardSession } from "../../lib/dashboard-session";
import { CampaignCalendarWorkspace } from "./campaign-calendar-workspace";

export default async function CampaignCalendarPage() {
  await requireDashboardSession();

  return (
    <AppShell>
      <CampaignCalendarWorkspace />
    </AppShell>
  );
}
