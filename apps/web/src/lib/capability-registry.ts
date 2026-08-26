export const capabilityIdentifierPattern = /^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$/;

export const capabilities = {
  workspaceView: "workspace.view",
  workspaceUpdate: "workspace.update",
  workspaceMemberView: "workspace.member.view",
  workspaceMemberInvite: "workspace.member.invite",
  workspaceMemberRolesManage: "workspace.member.roles.manage",
  workspaceMemberRemove: "workspace.member.remove",
  roleView: "role.view",
  roleCreate: "role.create",
  roleUpdate: "role.update",
  roleDelete: "role.delete",
  roleAssign: "role.assign",
  profileView: "profile.view",
  profileEdit: "profile.edit",
  artistProfileView: "artist.profile.view",
  artistProfileCreate: "artist.profile.create",
  artistProfileEdit: "artist.profile.edit",
  artistProfileDelete: "artist.profile.delete",
  arScoutingView: "ar.scouting.view",
  arScoutingCreate: "ar.scouting.create",
  arEvaluationView: "ar.evaluation.view",
  arEvaluationCreate: "ar.evaluation.create",
  arSigningApprove: "ar.signing.approve",
  releaseView: "release.view",
  releaseCreate: "release.create",
  releaseEdit: "release.edit",
  releaseApprove: "release.approve",
  marketingCampaignView: "marketing.campaign.view",
  marketingCampaignCreate: "marketing.campaign.create",
  marketingCampaignEdit: "marketing.campaign.edit",
  marketingCampaignApprove: "marketing.campaign.approve",
  contractView: "contract.view",
  contractCreate: "contract.create",
  contractEdit: "contract.edit",
  contractReview: "contract.review",
  contractApprove: "contract.approve",
  contractExecute: "contract.execute",
  royaltyView: "royalty.view",
  royaltyCalculate: "royalty.calculate",
  royaltyStatementView: "royalty.statement.view",
  royaltyStatementCreate: "royalty.statement.create",
  financeView: "finance.view",
  financeReportView: "finance.report.view",
  financePaymentView: "finance.payment.view",
  financePaymentApprove: "finance.payment.approve",
  analyticsView: "analytics.view",
} as const;

export type Capability = (typeof capabilities)[keyof typeof capabilities];

export type CapabilityDefinition = {
  key: Capability;
  displayName: string;
  description: string;
  systemCapability: true;
};

function defineCapability(
  key: Capability,
  displayName: string,
  description: string,
): CapabilityDefinition {
  validateCapabilityIdentifier(key);
  return { key, displayName, description, systemCapability: true };
}

export function isValidCapabilityIdentifier(identifier: string): boolean {
  return capabilityIdentifierPattern.test(identifier);
}

export function validateCapabilityIdentifier(identifier: string): string {
  if (!isValidCapabilityIdentifier(identifier)) {
    throw new Error("Capability identifiers must use dot-separated lowercase segments.");
  }
  return identifier;
}

export const capabilityRegistry: readonly CapabilityDefinition[] = [
  defineCapability(capabilities.workspaceView, "View workspace", "View workspace settings."),
  defineCapability(capabilities.workspaceUpdate, "Update workspace", "Update workspace settings."),
  defineCapability(
    capabilities.workspaceMemberView,
    "View workspace members",
    "View workspace member directory and membership details.",
  ),
  defineCapability(
    capabilities.workspaceMemberInvite,
    "Invite workspace members",
    "Invite members to a workspace.",
  ),
  defineCapability(
    capabilities.workspaceMemberRolesManage,
    "Manage member roles",
    "Manage roles assigned to workspace members.",
  ),
  defineCapability(
    capabilities.workspaceMemberRemove,
    "Remove workspace members",
    "Remove members from a workspace.",
  ),
  defineCapability(capabilities.roleView, "View roles", "View workspace role definitions."),
  defineCapability(capabilities.roleCreate, "Create roles", "Create custom workspace roles."),
  defineCapability(capabilities.roleUpdate, "Update roles", "Update workspace roles."),
  defineCapability(capabilities.roleDelete, "Delete roles", "Delete custom workspace roles."),
  defineCapability(capabilities.roleAssign, "Assign roles", "Assign workspace roles to members."),
  defineCapability(capabilities.profileView, "View profile", "View user profile data."),
  defineCapability(capabilities.profileEdit, "Edit profile", "Edit the current user's profile."),
  defineCapability(
    capabilities.artistProfileView,
    "View artist profiles",
    "View artist profile records.",
  ),
  defineCapability(
    capabilities.artistProfileCreate,
    "Create artist profiles",
    "Create artist profile records.",
  ),
  defineCapability(
    capabilities.artistProfileEdit,
    "Edit artist profiles",
    "Edit artist profile records.",
  ),
  defineCapability(
    capabilities.artistProfileDelete,
    "Delete artist profiles",
    "Delete artist profile records.",
  ),
  defineCapability(capabilities.arScoutingView, "View A&R scouting", "View scouting pipelines."),
  defineCapability(capabilities.arScoutingCreate, "Create A&R scouting", "Create scouting leads."),
  defineCapability(
    capabilities.arEvaluationView,
    "View A&R evaluations",
    "View A&R evaluation records.",
  ),
  defineCapability(
    capabilities.arEvaluationCreate,
    "Create A&R evaluations",
    "Create A&R evaluation records.",
  ),
  defineCapability(
    capabilities.arSigningApprove,
    "Approve A&R signings",
    "Approve A&R signing recommendations.",
  ),
  defineCapability(capabilities.releaseView, "View releases", "View release records."),
  defineCapability(capabilities.releaseCreate, "Create releases", "Create release records."),
  defineCapability(capabilities.releaseEdit, "Edit releases", "Edit release records."),
  defineCapability(capabilities.releaseApprove, "Approve releases", "Approve release readiness."),
  defineCapability(
    capabilities.marketingCampaignView,
    "View campaigns",
    "View marketing campaign records.",
  ),
  defineCapability(
    capabilities.marketingCampaignCreate,
    "Create campaigns",
    "Create marketing campaign records.",
  ),
  defineCapability(
    capabilities.marketingCampaignEdit,
    "Edit campaigns",
    "Edit marketing campaign records.",
  ),
  defineCapability(
    capabilities.marketingCampaignApprove,
    "Approve campaigns",
    "Approve marketing campaign plans.",
  ),
  defineCapability(capabilities.contractView, "View contracts", "View contract records."),
  defineCapability(capabilities.contractCreate, "Create contracts", "Create contract records."),
  defineCapability(capabilities.contractEdit, "Edit contracts", "Edit contract records."),
  defineCapability(capabilities.contractReview, "Review contracts", "Review contract terms."),
  defineCapability(capabilities.contractApprove, "Approve contracts", "Approve contract records."),
  defineCapability(capabilities.contractExecute, "Execute contracts", "Execute approved contracts."),
  defineCapability(capabilities.royaltyView, "View royalties", "View royalty data."),
  defineCapability(
    capabilities.royaltyCalculate,
    "Calculate royalties",
    "Calculate royalty statements and allocations.",
  ),
  defineCapability(
    capabilities.royaltyStatementView,
    "View royalty statements",
    "View royalty statements.",
  ),
  defineCapability(
    capabilities.royaltyStatementCreate,
    "Create royalty statements",
    "Create royalty statements.",
  ),
  defineCapability(capabilities.financeView, "View finance", "View finance data."),
  defineCapability(capabilities.financeReportView, "View finance reports", "View finance reports."),
  defineCapability(capabilities.financePaymentView, "View payments", "View payment records."),
  defineCapability(
    capabilities.financePaymentApprove,
    "Approve payments",
    "Approve payment records.",
  ),
  defineCapability(capabilities.analyticsView, "View analytics", "View analytics data and reports."),
] as const;

export const capabilityKeys = capabilityRegistry.map((capability) => capability.key);
export const capabilitySet = new Set<Capability>(capabilityKeys);
