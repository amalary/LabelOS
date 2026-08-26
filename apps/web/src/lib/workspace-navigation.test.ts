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
        [capabilities.campaignView, capabilities.analyticsView],
        ["marketing", "analytics"],
      ),
    ).toEqual(expect.arrayContaining(["Marketing", "Campaigns", "Analytics"]));
    expect(labelsFor([capabilities.campaignView], ["marketing"])).not.toContain("Contracts");
  });

  it("shows legal product areas from contract capabilities", () => {
    const labels = labelsFor([capabilities.contractView, capabilities.contractApprove], ["legal"]);

    expect(labels).toEqual(expect.arrayContaining(["Contracts", "Legal Workflow"]));
    expect(labels).not.toContain("Campaigns");
  });

  it("shows artist areas from artist, release, creative, and analytics capabilities", () => {
    const labels = labelsFor(
      [
        capabilities.artistView,
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
      [capabilities.workspaceManage, capabilities.memberInvite, capabilities.roleAssign],
      ["administration"],
    );

    expect(labels).toEqual(
      expect.arrayContaining(["Workspace Settings", "Member Management", "Roles"]),
    );
  });

  it("keeps workspace-only areas hidden without an active workspace", () => {
    const labels = visibleWorkspaceNavigationItems({
      hasActiveWorkspace: false,
      subject: subject([capabilities.campaignView, capabilities.workspaceManage]),
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
