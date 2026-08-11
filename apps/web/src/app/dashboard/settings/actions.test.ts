import { beforeEach, describe, expect, it, vi } from "vitest";

const cache = vi.hoisted(() => ({
  revalidatePath: vi.fn(),
}));

const organizations = vi.hoisted(() => ({
  inviteOrganizationMember: vi.fn(),
  removeOrganizationMember: vi.fn(),
  updateOrganization: vi.fn(),
  updateOrganizationMemberRole: vi.fn(),
}));

vi.mock("next/cache", () => cache);
vi.mock("../../../lib/api-client", () => ({
  ApiClientError: class ApiClientError extends Error {
    constructor(
      readonly code: string,
      message: string,
      readonly status?: number,
    ) {
      super(message);
      this.name = "ApiClientError";
    }
  },
}));
vi.mock("../../../lib/organizations", () => organizations);

function form(entries: Record<string, string>) {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) {
    data.set(key, value);
  }
  return data;
}

describe("organization settings actions", () => {
  beforeEach(() => {
    organizations.updateOrganization.mockReset();
    organizations.updateOrganizationMemberRole.mockReset();
    organizations.inviteOrganizationMember.mockReset();
    organizations.removeOrganizationMember.mockReset();
    cache.revalidatePath.mockReset();
  });

  it("validates organization profile fields before saving", async () => {
    const { saveOrganizationProfile } = await import("./actions");

    const response = await saveOrganizationProfile(
      { error: null, success: null },
      form({ organizationId: "org_1", name: "A", slug: "Bad Slug" }),
    );

    expect(response.error).toMatch(/between 2 and 200/i);
    expect(organizations.updateOrganization).not.toHaveBeenCalled();
  });

  it("normalizes valid profile values and revalidates settings pages", async () => {
    organizations.updateOrganization.mockResolvedValue({
      id: "org_1",
      name: "Northstar Audio",
      slug: "northstar-audio",
      role: "owner",
      can_switch: true,
    });

    const { saveOrganizationProfile } = await import("./actions");
    const response = await saveOrganizationProfile(
      { error: null, success: null },
      form({ organizationId: "org_1", name: "  Northstar   Audio  ", slug: "Northstar-Audio" }),
    );

    expect(response).toEqual({ error: null, success: "Organization profile saved." });
    expect(organizations.updateOrganization).toHaveBeenCalledWith("org_1", {
      name: "Northstar Audio",
      slug: "northstar-audio",
    });
    expect(cache.revalidatePath).toHaveBeenCalledWith("/dashboard/settings");
    expect(cache.revalidatePath).toHaveBeenCalledWith("/dashboard");
  });

  it("requires explicit confirmation before changing a member role", async () => {
    const { saveMemberRole } = await import("./actions");
    const response = await saveMemberRole(
      { error: null, success: null },
      form({ organizationId: "org_1", membershipId: "membership_1", role: "admin" }),
    );

    expect(response.error).toMatch(/confirm/i);
    expect(organizations.updateOrganizationMemberRole).not.toHaveBeenCalled();
  });

  it("saves confirmed member role changes", async () => {
    organizations.updateOrganizationMemberRole.mockResolvedValue({
      id: "membership_1",
      user_id: "user_2",
      email: "member@example.com",
      display_name: "Member",
      role: "admin",
      status: "active",
    });

    const { saveMemberRole } = await import("./actions");
    const response = await saveMemberRole(
      { error: null, success: null },
      form({
        organizationId: "org_1",
        membershipId: "membership_1",
        role: "admin",
        confirmRoleChange: "on",
      }),
    );

    expect(response).toEqual({ error: null, success: "Member role updated." });
    expect(organizations.updateOrganizationMemberRole).toHaveBeenCalledWith(
      "org_1",
      "membership_1",
      "admin",
    );
    expect(cache.revalidatePath).toHaveBeenCalledWith("/dashboard/settings");
  });

  it("validates and sends member invitations", async () => {
    organizations.inviteOrganizationMember.mockResolvedValue({
      id: "invitation_1",
      email: "member@example.com",
      role: "member",
      state: "pending",
      expires_at: null,
      created_at: null,
    });

    const { inviteMember } = await import("./actions");
    const response = await inviteMember(
      { error: null, success: null },
      form({ organizationId: "org_1", email: " Member@Example.COM ", role: "member" }),
    );

    expect(response).toEqual({ error: null, success: "Invitation sent." });
    expect(organizations.inviteOrganizationMember).toHaveBeenCalledWith("org_1", {
      email: "member@example.com",
      role: "member",
    });
    expect(cache.revalidatePath).toHaveBeenCalledWith("/dashboard/settings");
  });

  it("requires confirmation before removing a member", async () => {
    const { removeMember } = await import("./actions");
    const response = await removeMember(
      { error: null, success: null },
      form({ organizationId: "org_1", membershipId: "membership_1" }),
    );

    expect(response.error).toMatch(/confirm/i);
    expect(organizations.removeOrganizationMember).not.toHaveBeenCalled();
  });

  it("removes confirmed members and revalidates workspace pages", async () => {
    organizations.removeOrganizationMember.mockResolvedValue(undefined);

    const { removeMember } = await import("./actions");
    const response = await removeMember(
      { error: null, success: null },
      form({
        organizationId: "org_1",
        membershipId: "membership_1",
        confirmRemoveMember: "on",
      }),
    );

    expect(response).toEqual({ error: null, success: "Member removed." });
    expect(organizations.removeOrganizationMember).toHaveBeenCalledWith(
      "org_1",
      "membership_1",
    );
    expect(cache.revalidatePath).toHaveBeenCalledWith("/dashboard/settings");
    expect(cache.revalidatePath).toHaveBeenCalledWith("/dashboard");
  });
});
