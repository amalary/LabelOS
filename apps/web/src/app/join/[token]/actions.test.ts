import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  withAuth: vi.fn(),
  accept: vi.fn(),
  redirect: vi.fn((path: string) => {
    throw new Error(`redirect:${path}`);
  }),
}));
vi.mock("@workos-inc/authkit-nextjs", () => ({ withAuth: mocks.withAuth }));
vi.mock("next/navigation", () => ({ redirect: mocks.redirect }));
vi.mock("../../../lib/organizations", () => ({ acceptWorkspaceInvite: mocks.accept }));
vi.mock("../../../lib/server-logging", () => ({ logServerError: vi.fn() }));

import { acceptWorkspaceInviteAction } from "./actions";

describe("invite acceptance authority", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.withAuth.mockResolvedValue({});
    mocks.accept.mockResolvedValue({});
  });

  it("forwards job titles only, ignoring forged authorization fields", async () => {
    const form = new FormData();
    form.set("token", "invite-token");
    form.append("professional_roles", "Legal");
    form.set("workspace_roles", "owner");
    form.set("department_access", "finance");
    form.set("workspace_permission", "owner");
    form.set("organization_id", "another-workspace");
    await expect(acceptWorkspaceInviteAction(form)).rejects.toThrow("redirect:/dashboard");
    expect(mocks.withAuth).toHaveBeenCalledWith({ ensureSignedIn: true });
    expect(mocks.accept).toHaveBeenCalledExactlyOnceWith("invite-token", {
      professional_roles: ["Legal"],
    });
  });

  it("does not accept an invite when authentication fails", async () => {
    mocks.withAuth.mockRejectedValue(new Error("unauthenticated"));
    const form = new FormData();
    form.set("token", "invite-token");
    await expect(acceptWorkspaceInviteAction(form)).rejects.toThrow("unauthenticated");
    expect(mocks.accept).not.toHaveBeenCalled();
  });

  it("returns to the invite when the backend denies acceptance", async () => {
    mocks.accept.mockRejectedValue(new Error("revoked"));
    const form = new FormData();
    form.set("token", "invite-token");
    await expect(acceptWorkspaceInviteAction(form)).rejects.toThrow(
      "redirect:/join/invite-token?inviteError=accept-failed",
    );
  });
});
