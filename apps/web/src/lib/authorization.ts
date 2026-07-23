export const permissions = {
  organizationManage: "organization:manage",
  membersManage: "members:manage",
  artistsView: "artists:view",
  artistsManage: "artists:manage",
  releasesView: "releases:view",
  releasesManage: "releases:manage",
  campaignsView: "campaigns:view",
  campaignsManage: "campaigns:manage",
  analyticsView: "analytics:view",
  royaltiesView: "royalties:view",
  royaltiesManage: "royalties:manage",
  contractsView: "contracts:view",
  contractsManage: "contracts:manage",
  agentsView: "agents:view",
  agentsManage: "agents:manage",
  settingsManage: "settings:manage",
} as const;

export type Permission = (typeof permissions)[keyof typeof permissions];
export type AppRole = "owner" | "admin" | "member";

export type AuthorizationSubject = {
  role?: string | null;
  permissions?: readonly string[] | null;
};

const roleRanks: Record<AppRole, number> = {
  member: 0,
  admin: 1,
  owner: 2,
};

function normalizeRole(role?: string | null): AppRole | null {
  const normalized = role?.trim().toLowerCase();
  if (normalized === "owner" || normalized === "admin" || normalized === "member") {
    return normalized;
  }
  return null;
}

export function hasRole(subject: AuthorizationSubject, minimumRole: AppRole): boolean {
  const role = normalizeRole(subject.role);
  return role !== null && roleRanks[role] >= roleRanks[minimumRole];
}

export function hasPermission(
  subject: AuthorizationSubject,
  permission: Permission | string,
): boolean {
  return subject.permissions?.includes(permission) ?? false;
}

export function unavailableActionProps(
  subject: AuthorizationSubject,
  permission: Permission | string,
): { disabled?: true; "aria-disabled"?: true } {
  return hasPermission(subject, permission) ? {} : { disabled: true, "aria-disabled": true };
}
