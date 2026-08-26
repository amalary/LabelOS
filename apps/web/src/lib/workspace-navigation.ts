import { can, capabilities, type AuthorizationSubject, type Capability } from "./authorization";

export type WorkspaceNavigationItem = {
  href: string;
  label: string;
  requiredCapabilities?: readonly Capability[];
  requireAllCapabilities?: boolean;
  requiresActiveWorkspace?: boolean;
};

export type WorkspaceNavigationState = {
  hasActiveWorkspace: boolean;
  subject: AuthorizationSubject | null;
};

export const workspaceNavigationItems: readonly WorkspaceNavigationItem[] = [
  {
    href: "/dashboard",
    label: "Dashboard",
    requiresActiveWorkspace: true,
  },
  {
    href: "/profile",
    label: "Profile",
  },
  {
    href: "/workspace/people",
    label: "People Directory",
    requiresActiveWorkspace: true,
  },
  {
    href: "/artists",
    label: "Artist Profile",
    requiredCapabilities: [capabilities.artistView, capabilities.profileEdit],
    requiresActiveWorkspace: true,
  },
  {
    href: "/marketing",
    label: "Marketing",
    requiredCapabilities: [
      capabilities.campaignView,
      capabilities.campaignCreate,
      capabilities.campaignApprove,
    ],
    requiresActiveWorkspace: true,
  },
  {
    href: "/campaigns",
    label: "Campaigns",
    requiredCapabilities: [
      capabilities.campaignView,
      capabilities.campaignCreate,
      capabilities.campaignApprove,
    ],
    requiresActiveWorkspace: true,
  },
  {
    href: "/releases",
    label: "Releases",
    requiredCapabilities: [capabilities.releaseView, capabilities.releaseEdit],
    requiresActiveWorkspace: true,
  },
  {
    href: "/creative-tools",
    label: "Creative Tools",
    requiredCapabilities: [
      capabilities.artistEdit,
      capabilities.artistCreate,
      capabilities.releaseEdit,
      capabilities.profileEdit,
    ],
    requiresActiveWorkspace: true,
  },
  {
    href: "/analytics",
    label: "Analytics",
    requiredCapabilities: [capabilities.analyticsView],
    requiresActiveWorkspace: true,
  },
  {
    href: "/contracts",
    label: "Contracts",
    requiredCapabilities: [
      capabilities.contractView,
      capabilities.contractUpload,
      capabilities.contractApprove,
      capabilities.contractSignRequest,
    ],
    requiresActiveWorkspace: true,
  },
  {
    href: "/legal",
    label: "Legal Workflow",
    requiredCapabilities: [
      capabilities.contractUpload,
      capabilities.contractApprove,
      capabilities.contractSignRequest,
    ],
    requiresActiveWorkspace: true,
  },
  {
    href: "/workspace/settings",
    label: "Workspace Settings",
    requiredCapabilities: [capabilities.workspaceManage],
    requiresActiveWorkspace: true,
  },
  {
    href: "/workspace/members",
    label: "Member Management",
    requiredCapabilities: [capabilities.memberInvite, capabilities.memberRemove],
    requiresActiveWorkspace: true,
  },
  {
    href: "/workspace/roles",
    label: "Roles",
    requiredCapabilities: [capabilities.roleAssign],
    requiresActiveWorkspace: true,
  },
];

export function isWorkspaceNavigationItemVisible(
  item: WorkspaceNavigationItem,
  state: WorkspaceNavigationState,
): boolean {
  if (item.requiresActiveWorkspace && !state.hasActiveWorkspace) {
    return false;
  }
  if (!item.requiredCapabilities || item.requiredCapabilities.length === 0) {
    return true;
  }
  if (!state.subject) {
    return false;
  }

  const hasCapability = (capability: Capability) => can(state.subject!, null, capability);
  return item.requireAllCapabilities
    ? item.requiredCapabilities.every(hasCapability)
    : item.requiredCapabilities.some(hasCapability);
}

export function visibleWorkspaceNavigationItems(
  state: WorkspaceNavigationState,
  items: readonly WorkspaceNavigationItem[] = workspaceNavigationItems,
): WorkspaceNavigationItem[] {
  return items.filter((item) => isWorkspaceNavigationItemVisible(item, state));
}

export function isWorkspaceNavigationItemCurrent(
  item: WorkspaceNavigationItem,
  pathname: string,
): boolean {
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}
