import { capabilities, capabilitySet, type Capability } from "./capability-registry";

export { capabilities, type Capability } from "./capability-registry";

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
export type WorkspacePermission = "owner" | "admin" | "member" | "guest";
export type ActorKind = "user" | "service_account" | "ai_agent";
export type ResourceKind =
  | "workspace"
  | "artist"
  | "release"
  | "campaign"
  | "contract"
  | "royalty"
  | "analytics"
  | "profile";

export type AuthorizationActor = {
  kind: ActorKind;
  subject: string;
  userId?: string | null;
  displayName?: string | null;
};

export type AuthorizationSubject = {
  actor?: AuthorizationActor | null;
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
  kind?: ResourceKind | string | null;
  id?: string | null;
  workspaceId?: string | null;
  department?: string | null;
  ownerActor?: AuthorizationActor | null;
  attributes?: Record<string, unknown> | null;
} | null;

export type AuthorizationDecision = {
  actor: AuthorizationActor;
  action: Permission | Capability | string | null;
  workspaceId?: string | null;
  resource?: AuthorizationResource;
  allowed: boolean;
  reason: string;
};

const capabilityDepartments: Partial<Record<Capability, readonly string[]>> = {
  [capabilities.workspaceView]: ["administration", "management"],
  [capabilities.workspaceUpdate]: ["administration"],
  [capabilities.workspaceMemberView]: ["administration", "management"],
  [capabilities.workspaceMemberInvite]: ["administration"],
  [capabilities.workspaceMemberRolesManage]: ["administration"],
  [capabilities.workspaceMemberRemove]: ["administration"],
  [capabilities.roleView]: ["administration", "management"],
  [capabilities.roleCreate]: ["administration"],
  [capabilities.roleUpdate]: ["administration"],
  [capabilities.roleDelete]: ["administration"],
  [capabilities.roleAssign]: ["administration"],
  [capabilities.profileView]: [],
  [capabilities.profileEdit]: [],
  [capabilities.artistProfileView]: ["artist", "a&r", "management"],
  [capabilities.artistProfileEdit]: ["artist", "a&r", "management"],
  [capabilities.artistProfileCreate]: ["a&r", "management"],
  [capabilities.artistProfileDelete]: ["a&r", "management"],
  [capabilities.arScoutingView]: ["a&r", "management"],
  [capabilities.arScoutingCreate]: ["a&r", "management"],
  [capabilities.arEvaluationView]: ["a&r", "management"],
  [capabilities.arEvaluationCreate]: ["a&r", "management"],
  [capabilities.arSigningApprove]: ["a&r", "management"],
  [capabilities.marketingCampaignView]: ["marketing", "management"],
  [capabilities.marketingCampaignCreate]: ["marketing", "management"],
  [capabilities.marketingCampaignEdit]: ["marketing", "management"],
  [capabilities.marketingCampaignApprove]: ["marketing", "management"],
  [capabilities.releaseView]: ["release_operations", "management"],
  [capabilities.releaseCreate]: ["release_operations", "management"],
  [capabilities.releaseEdit]: ["release_operations", "management"],
  [capabilities.releaseApprove]: ["release_operations", "management"],
  [capabilities.contractView]: ["legal", "contracts"],
  [capabilities.contractCreate]: ["legal", "contracts"],
  [capabilities.contractEdit]: ["legal", "contracts"],
  [capabilities.contractReview]: ["legal", "contracts"],
  [capabilities.contractApprove]: ["legal", "contracts"],
  [capabilities.contractExecute]: ["legal", "contracts"],
  [capabilities.royaltyView]: ["finance", "royalties"],
  [capabilities.royaltyCalculate]: ["finance", "royalties"],
  [capabilities.royaltyStatementView]: ["finance", "royalties"],
  [capabilities.royaltyStatementCreate]: ["finance", "royalties"],
  [capabilities.financeView]: ["finance"],
  [capabilities.financeReportView]: ["finance"],
  [capabilities.financePaymentView]: ["finance"],
  [capabilities.financePaymentApprove]: ["finance"],
  [capabilities.analyticsView]: ["analytics", "management"],
};

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
  capability: Permission | Capability | string,
  resource: AuthorizationResource = null,
): boolean {
  if (isPermission(capability)) {
    return subject.permissions?.includes(capability) ?? false;
  }
  if (isCapability(capability)) {
    return canUseResolvedCapability(subject, workspace, capability, resource);
  }
  return false;
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
      : (capabilityDepartments[capability as Capability] ?? []);
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
  return capabilitySet.has(value as Capability);
}
