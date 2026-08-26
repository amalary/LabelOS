import { AppShell } from "../../components/app-shell";
import { requireDashboardSession } from "../../lib/dashboard-session";
import { UniversalProfileInterface } from "./profile-interface";

export default async function ProfilePage() {
  await requireDashboardSession();

  return (
    <AppShell>
      <UniversalProfileInterface />
    </AppShell>
  );
}
