import { AppShell } from "../../components/app-shell";
import { requireDashboardSession } from "../../lib/dashboard-session";
import { ArtistProfilesWorkspace } from "./artist-profiles-workspace";

export default async function ArtistProfilesPage() {
  await requireDashboardSession();

  return (
    <AppShell>
      <ArtistProfilesWorkspace />
    </AppShell>
  );
}
