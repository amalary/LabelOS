import { describe, expect, it } from "vitest";

import { capabilities, type AuthorizationSubject } from "./authorization";
import {
  isWorkspaceNavigationItemCurrent,
  visibleWorkspaceNavigationItems,
} from "./workspace-navigation";

function subject(capabilityList: string[], departmentAccess: string[] = []): AuthorizationSubject {
  return {
    role: "member",
    workspacePermission: "member",
    capabilities: capabilityList,
    departmentAccess,
  };
}

function labelsFor(capabilityList: string[], departmentAccess: string[] = []): string[] {
  return visibleWorkspaceNavigationItems({
    hasActiveWorkspace: true,
    subject: subject(capabilityList, departmentAccess),
  }).map((item) => item.label);
}

describe("workspace navigation visibility", () => {
  it("shows marketing product areas from campaign and analytics capabilities", () => {
    expect(
      labelsFor(
        [capabilities.marketingCampaignView, capabilities.analyticsView],
        ["marketing", "analytics"],
      ),
    ).toEqual(
      expect.arrayContaining(["Marketing", "Campaigns", "Analytics", "Analytics Settings"]),
    );
    expect(labelsFor([capabilities.marketingCampaignView], ["marketing"])).not.toContain(
      "Contracts",
    );
  });

  it("only shows Campaign Calendar when campaign and content view capabilities are both available", () => {
    expect(labelsFor([capabilities.marketingCampaignView], ["marketing"])).not.toContain(
      "Campaign Calendar",
    );
    expect(labelsFor([capabilities.marketingContentView], ["marketing"])).not.toContain(
      "Campaign Calendar",
    );
    expect(
      labelsFor(
        [capabilities.marketingCampaignView, capabilities.marketingContentView],
        ["marketing"],
      ),
    ).toContain("Campaign Calendar");
  });

  it("shows legal product areas from contract capabilities", () => {
    const labels = labelsFor([capabilities.contractView, capabilities.contractApprove], ["legal"]);

    expect(labels).toEqual(expect.arrayContaining(["Contracts", "Legal Workflow"]));
    expect(labels).not.toContain("Campaigns");
  });

  it("shows artist areas from artist, release, creative, and analytics capabilities", () => {
    const labels = labelsFor(
      [
        capabilities.artistProfileView,
        capabilities.releaseView,
        capabilities.releaseEdit,
        capabilities.analyticsView,
        capabilities.profileEdit,
      ],
      ["artist", "release_operations", "analytics"],
    );

    expect(labels).toEqual(
      expect.arrayContaining(["Artist Profile", "Releases", "Creative Tools", "Analytics"]),
    );
  });

  it("shows administrative areas from workspace administration capabilities", () => {
    const labels = labelsFor(
      [
        capabilities.workspaceUpdate,
        capabilities.workspaceMemberInvite,
        capabilities.workspaceMemberRolesManage,
        capabilities.roleAssign,
      ],
      ["administration"],
    );

    expect(labels).toEqual(
      expect.arrayContaining(["Workspace Settings", "Member Management", "Roles"]),
    );
  });

  it("hides role assignment navigation without member role management capability", () => {
    const labels = labelsFor([capabilities.roleAssign], ["administration"]);

    expect(labels).not.toContain("Roles");
  });

  it("keeps workspace-only areas hidden without an active workspace", () => {
    const labels = visibleWorkspaceNavigationItems({
      hasActiveWorkspace: false,
      subject: subject([capabilities.marketingCampaignView, capabilities.workspaceUpdate]),
    }).map((item) => item.label);

    expect(labels).toEqual(["Profile"]);
  });

  it("marks nested navigation paths current", () => {
    expect(
      isWorkspaceNavigationItemCurrent(
        { href: "/workspace/settings", label: "Workspace Settings" },
        "/workspace/settings/invites",
      ),
    ).toBe(true);
  });
});
