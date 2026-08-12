import { beforeEach, describe, expect, it, vi } from "vitest";

const authkit = vi.hoisted(() => ({
  refreshSession: vi.fn(),
  withAuth: vi.fn(),
}));

const organizations = vi.hoisted(() => ({
  verifyOrganizationActivation: vi.fn(),
}));

const apiClient = vi.hoisted(() => ({
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

const cache = vi.hoisted(() => ({
  revalidatePath: vi.fn(),
}));

const navigation = vi.hoisted(() => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  }),
}));

vi.mock("@workos-inc/authkit-nextjs", () => authkit);
vi.mock("next/cache", () => cache);
vi.mock("next/navigation", () => navigation);
vi.mock("../../lib/api-client", () => apiClient);
vi.mock("../../lib/organizations", () => organizations);
vi.mock("../../lib/server-logging", () => ({
  logServerError: vi.fn(),
}));

function formData(organizationId?: string) {
  const data = new FormData();
  if (organizationId) {
    data.set("organizationId", organizationId);
  }
  return data;
}

describe("switchOrganization", () => {
  beforeEach(() => {
    vi.resetModules();
    authkit.refreshSession.mockReset();
    authkit.withAuth.mockReset();
    organizations.verifyOrganizationActivation.mockReset();
    cache.revalidatePath.mockReset();
    navigation.redirect.mockClear();
    authkit.withAuth.mockResolvedValue({ user: { id: "user_01" } });
    authkit.refreshSession.mockResolvedValue({ organizationId: "org_BETA" });
    organizations.verifyOrganizationActivation.mockResolvedValue({
      organization: {
        id: "local_org_beta",
        name: "Beta Label",
        slug: "beta-label",
        role: "member",
        can_switch: true,
      },
      workos_organization_id: "org_BETA",
    });
  });

  it("verifies local access before refreshing the WorkOS organization session", async () => {
    const { switchOrganization } = await import("./actions");

    await expect(switchOrganization({ error: null }, formData("local_org_beta"))).rejects.toThrow(
      "NEXT_REDIRECT:/dashboard",
    );

    expect(authkit.withAuth).toHaveBeenCalledWith({ ensureSignedIn: true });
    expect(organizations.verifyOrganizationActivation).toHaveBeenCalledWith("local_org_beta");
    expect(authkit.refreshSession).toHaveBeenCalledWith({
      ensureSignedIn: true,
      organizationId: "org_BETA",
    });
    expect(cache.revalidatePath).toHaveBeenCalledWith("/dashboard", "layout");
  });

  it("does not refresh the session when backend access verification fails", async () => {
    organizations.verifyOrganizationActivation.mockRejectedValue(
      new apiClient.ApiClientError("network_failure", "Not found", 404),
    );
    const { switchOrganization } = await import("./actions");

    await expect(switchOrganization({ error: null }, formData("local_org_old"))).resolves.toEqual({
      error: "You no longer have access to that organization.",
    });

    expect(authkit.refreshSession).not.toHaveBeenCalled();
    expect(cache.revalidatePath).not.toHaveBeenCalled();
  });

  it("validates that an organization was selected", async () => {
    const { switchOrganization } = await import("./actions");

    await expect(switchOrganization({ error: null }, formData())).resolves.toEqual({
      error: "Choose an organization to switch workspaces.",
    });

    expect(organizations.verifyOrganizationActivation).not.toHaveBeenCalled();
  });
});
