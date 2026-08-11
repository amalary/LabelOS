import { redirect } from "next/navigation";
import { SettingsPanel } from "./settings-panel";
import { AppShell } from "../../../components/app-shell";
import { ApiClientError, getCurrentApiUser } from "../../../lib/api-client";
import { hasPermission, permissions } from "../../../lib/authorization";
import { requireDashboardSession } from "../../../lib/dashboard-session";
import {
  getActiveOrganization,
  listOrganizationMembers,
  type OrganizationInvitation,
  type OrganizationMember,
} from "../../../lib/organizations";

const roleRanks = {
  viewer: 0,
  member: 1,
  admin: 2,
  owner: 3,
} as const;

function roleAtLeast(role: string | null | undefined, minimumRole: keyof typeof roleRanks) {
  const minimumRank = roleRanks[minimumRole];
  const roleRank = role && role in roleRanks ? roleRanks[role as keyof typeof roleRanks] : -1;
  return roleRank >= minimumRank;
}

export default async function OrganizationSettingsPage() {
  const session = await requireDashboardSession();
  if (!session.organizationId) {
    redirect("/onboarding/workspace");
  }

  const [organization, backendUser] = await Promise.all([
    getActiveOrganization(),
    getCurrentApiUser(),
  ]);
  if (organization === null) {
    redirect("/dashboard");
  }

  const canEditProfile =
    organization.role === "owner" && hasPermission(backendUser, permissions.organizationManage);
  const canViewMembers =
    roleAtLeast(organization.role, "admin") && hasPermission(backendUser, permissions.membersManage);
  const canEditRoles =
    organization.role === "owner" && hasPermission(backendUser, permissions.membersManage);

  let members: OrganizationMember[] = [];
  let invitations: OrganizationInvitation[] = [];
  let membersError: string | null = null;

  if (canViewMembers) {
    try {
      const membershipState = await listOrganizationMembers(organization.id);
      members = membershipState.members;
      invitations = membershipState.invitations;
    } catch (error) {
      if (!(error instanceof ApiClientError)) {
        throw error;
      }
      membersError = "Members could not be loaded for this organization.";
    }
  } else {
    membersError = "You do not have permission to view organization members.";
  }

  return (
    <AppShell>
      <div className="flex flex-col gap-5">
        <div>
          <h1 className="text-2xl font-semibold text-slate-950">Organization settings</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            Manage the active workspace profile and member roles.
          </p>
        </div>
        <SettingsPanel
          canEditProfile={canEditProfile}
          canEditRoles={canEditRoles}
          members={members}
          membersError={membersError}
          invitations={invitations}
          organization={organization}
        />
      </div>
    </AppShell>
  );
}
