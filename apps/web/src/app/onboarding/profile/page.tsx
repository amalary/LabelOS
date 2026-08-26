import { redirect } from "next/navigation";

import { AppShell } from "../../../components/app-shell";
import { requireDashboardSession } from "../../../lib/dashboard-session";
import { getOrganizationSelection } from "../../../lib/organizations";
import { getCurrentUniversalProfile } from "../../../lib/profiles.server";
import { UniversalProfileOnboarding } from "./profile-onboarding";

export default async function UniversalProfileOnboardingPage() {
  await requireDashboardSession();
  const [organizationSelection, profile] = await Promise.all([
    getOrganizationSelection(),
    getCurrentUniversalProfile(),
  ]);

  if (profile.onboarding_status === "complete") {
    redirect(
      organizationSelection.organizations.length === 0 ? "/onboarding/workspace" : "/dashboard",
    );
  }

  return (
    <AppShell>
      <UniversalProfileOnboarding
        hasWorkspace={organizationSelection.organizations.length > 0}
        initialProfile={profile}
      />
    </AppShell>
  );
}
