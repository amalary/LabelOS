import { describe, expect, it } from "vitest";

import { hasPermission, hasRole, permissions, unavailableActionProps } from "./authorization";

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
});
