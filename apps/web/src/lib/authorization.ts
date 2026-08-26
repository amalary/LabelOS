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

export const capabilities = {
  artistView: "artist.view",
  artistEdit: "artist.edit",
  artistCreate: "artist.create",
  campaignView: "campaign.view",
  campaignCreate: "campaign.create",
  campaignApprove: "campaign.approve",
  releaseView: "release.view",
  releaseEdit: "release.edit",
  contractView: "contract.view",
  contractUpload: "contract.upload",
  contractApprove: "contract.approve",
  contractSignRequest: "contract.sign_request",
  royaltyView: "royalty.view",
  financeView: "finance.view",
  analyticsView: "analytics.view",
  memberInvite: "member.invite",
  memberRemove: "member.remove",
  roleAssign: "role.assign",
  workspaceManage: "workspace.manage",
  profileEdit: "profile.edit",
} as const;

export type Permission = (typeof permissions)[keyof typeof permissions];
export type Capability = (typeof capabilities)[keyof typeof capabilities];
export type AppRole = "owner" | "admin" | "member";
export type WorkspacePermission = AppRole | "guest";

export type AuthorizationSubject = {
  role?: string | null;
  workspacePermission?: string | null;
  permissions?: readonly string[] | null;
  departmentAccess?: readonly string[] | null;
  capabilities?: readonly string[] | null;
};

export type AuthorizationWorkspace = {
  workspacePermission?: string | null;
  departmentAccess?: readonly string[] | null;
  capabilities?: readonly string[] | null;
} | null;

export type AuthorizationResource = {
  department?: string | null;
} | null;

const capabilityDepartments: Partial<Record<Capability, readonly string[]>> = {
  [capabilities.artistView]: ["artist", "a&r", "management"],
  [capabilities.artistEdit]: ["artist", "a&r", "management"],
  [capabilities.artistCreate]: ["a&r", "management"],
  [capabilities.campaignView]: ["marketing", "management"],
  [capabilities.campaignCreate]: ["marketing", "management"],
  [capabilities.campaignApprove]: ["marketing", "management"],
  [capabilities.releaseView]: ["release_operations", "management"],
  [capabilities.releaseEdit]: ["release_operations", "management"],
  [capabilities.contractView]: ["legal", "contracts"],
  [capabilities.contractUpload]: ["legal", "contracts"],
  [capabilities.contractApprove]: ["legal", "contracts"],
  [capabilities.contractSignRequest]: ["legal", "contracts"],
  [capabilities.royaltyView]: ["finance", "royalties"],
  [capabilities.financeView]: ["finance"],
  [capabilities.analyticsView]: ["analytics", "management"],
  [capabilities.memberInvite]: ["administration"],
  [capabilities.memberRemove]: ["administration"],
  [capabilities.roleAssign]: ["administration"],
  [capabilities.workspaceManage]: ["administration"],
  [capabilities.profileEdit]: [],
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

function normalizeWorkspacePermission(permission?: string | null): WorkspacePermission | null {
  const normalized = permission?.trim().toLowerCase();
  if (
    normalized === "owner" ||
    normalized === "admin" ||
    normalized === "member" ||
    normalized === "guest"
  ) {
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
  return can(subject, null, permission);
}

export function hasDepartmentAccess(subject: AuthorizationSubject, department: string): boolean {
  return canAccessDepartment(subject, null, department);
}

export function hasCapability(
  subject: AuthorizationSubject,
  capability: Capability | string,
): boolean {
  return can(subject, null, capability);
}

export function can(
  subject: AuthorizationSubject,
  workspace: AuthorizationWorkspace,
  capability: Permission | Capability | AppRole | string,
  resource: AuthorizationResource = null,
): boolean {
  if (isPermission(capability)) {
    return subject.permissions?.includes(capability) ?? false;
  }
  if (isCapability(capability)) {
    return canUseResolvedCapability(subject, workspace, capability, resource);
  }
  const role = normalizeRole(capability);
  return role !== null && hasRole(subject, role);
}

export function canAccessDepartment(
  subject: AuthorizationSubject,
  workspace: AuthorizationWorkspace,
  department: string,
): boolean {
  const resolvedWorkspace = workspace ?? subject;
  if (
    normalizeWorkspacePermission(resolvedWorkspace.workspacePermission ?? subject.role) === "owner"
  ) {
    return true;
  }
  return resolvedWorkspace.departmentAccess?.includes(department) ?? false;
}

function canUseResolvedCapability(
  subject: AuthorizationSubject,
  workspace: AuthorizationWorkspace,
  capability: Capability | string,
  resource: AuthorizationResource,
): boolean {
  const resolvedWorkspace = workspace ?? subject;
  if (
    normalizeWorkspacePermission(resolvedWorkspace.workspacePermission ?? subject.role) === "owner"
  ) {
    return true;
  }
  const allowedDepartments =
    resource?.department !== undefined && resource.department !== null
      ? [resource.department]
      : capabilityDepartments[capability as Capability] ?? [];
  if (
    allowedDepartments.length > 0 &&
    !allowedDepartments.some((department) =>
      canAccessDepartment(subject, resolvedWorkspace, department),
    )
  ) {
    return false;
  }
  return resolvedWorkspace.capabilities?.includes(capability) ?? false;
}

export function canUseCapability(
  subject: AuthorizationSubject,
  capability: Capability | string,
  department: string,
): boolean {
  return can(subject, null, capability, { department });
}

export function unavailableActionProps(
  subject: AuthorizationSubject,
  permission: Permission | string,
): { disabled?: true; "aria-disabled"?: true } {
  return hasPermission(subject, permission) ? {} : { disabled: true, "aria-disabled": true };
}

function isPermission(value: string): value is Permission {
  return Object.values(permissions).includes(value as Permission);
}

function isCapability(value: string): value is Capability {
  return Object.values(capabilities).includes(value as Capability);
}
