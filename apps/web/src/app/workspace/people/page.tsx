import { AppShell } from "../../../components/app-shell";
import { requireDashboardSession } from "../../../lib/dashboard-session";
import { WorkspacePeopleDirectory } from "./workspace-people-directory";

export default async function WorkspacePeopleDirectoryPage() {
  await requireDashboardSession();

  return (
    <AppShell>
      <WorkspacePeopleDirectory />
    </AppShell>
  );
}
