import { describe, expect, it } from "vitest";

import {
  can,
  canUseCapability,
  capabilities,
  hasCapability,
  hasDepartmentAccess,
  hasPermission,
  hasRole,
  permissions,
  unavailableActionProps,
} from "./authorization";

describe("frontend authorization helpers", () => {
  it("checks the Owner/Admin/Member role hierarchy", () => {
    expect(hasRole({ role: "owner" }, "admin")).toBe(true);
    expect(hasRole({ role: "Admin" }, "member")).toBe(true);
    expect(hasRole({ role: "member" }, "admin")).toBe(false);
    expect(hasRole({ role: null }, "member")).toBe(false);
  });

  it("checks explicit permissions from the backend token", () => {
    const subject = { permissions: [permissions.artistsView, permissions.releasesManage] };

    expect(hasPermission(subject, permissions.releasesManage)).toBe(true);
    expect(hasPermission(subject, permissions.settingsManage)).toBe(false);
  });

  it("returns disabled props for actions the user cannot perform", () => {
    expect(unavailableActionProps({ permissions: [] }, permissions.artistsManage)).toEqual({
      "aria-disabled": true,
      disabled: true,
    });
    expect(
      unavailableActionProps(
        { permissions: [permissions.artistsManage] },
        permissions.artistsManage,
      ),
    ).toEqual({});
  });

  it("checks capability authorization with department access", () => {
    const subject = {
      workspacePermission: "member",
      departmentAccess: ["legal"],
      capabilities: [capabilities.contractUpload],
    };

    expect(hasDepartmentAccess(subject, "legal")).toBe(true);
    expect(hasCapability(subject, capabilities.contractUpload)).toBe(true);
    expect(canUseCapability(subject, capabilities.contractUpload, "legal")).toBe(true);
    expect(canUseCapability(subject, capabilities.contractSignRequest, "legal")).toBe(false);
    expect(canUseCapability(subject, capabilities.contractUpload, "production")).toBe(false);
  });

  it("applies default capability departments when no resource department is provided", () => {
    const subject = {
      workspacePermission: "member",
      departmentAccess: ["marketing"],
      capabilities: [capabilities.contractUpload, capabilities.campaignCreate],
    };

    expect(hasCapability(subject, capabilities.contractUpload)).toBe(false);
    expect(hasCapability(subject, capabilities.campaignCreate)).toBe(true);
    expect(can(subject, null, capabilities.contractUpload, { department: "legal" })).toBe(false);
  });

  it("uses can as the central authorization resolver", () => {
    const subject = {
      role: "member",
      permissions: [permissions.contractsManage],
      workspacePermission: "member",
      departmentAccess: ["legal"],
      capabilities: [capabilities.contractApprove],
    };

    expect(can(subject, null, permissions.contractsManage)).toBe(true);
    expect(can(subject, null, "admin")).toBe(false);
    expect(can(subject, null, capabilities.contractApprove, { department: "legal" })).toBe(true);
    expect(can(subject, null, capabilities.contractApprove, { department: "finance" })).toBe(false);
    expect(can(subject, null, capabilities.contractSignRequest, { department: "legal" })).toBe(
      false,
    );
  });

  it("treats workspace owners as having every department and capability", () => {
    const subject = { workspacePermission: "owner" };

    expect(hasDepartmentAccess(subject, "legal")).toBe(true);
    expect(hasCapability(subject, capabilities.workspaceManage)).toBe(true);
    expect(canUseCapability(subject, capabilities.releaseEdit, "release_operations")).toBe(true);
  });
});
