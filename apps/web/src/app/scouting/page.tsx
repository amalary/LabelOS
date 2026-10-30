import { AppShell } from "../../components/app-shell";
import { requireDashboardSession } from "../../lib/dashboard-session";
import { ScoutingWorkspace } from "../../components/scouting-workspace";
import { researchPolicies } from "../../lib/research-policy";

export default async function ScoutingPage() {
  await requireDashboardSession();
  const { privacyUrl, termsUrl, localSetup } = researchPolicies();
  return (
    <AppShell>
      <ScoutingWorkspace privacyUrl={privacyUrl} termsUrl={termsUrl} localSetup={localSetup} />
    </AppShell>
  );
}
