import { beforeEach, describe, expect, it, vi } from "vitest";

const authkit = vi.hoisted(() => ({
  refreshSession: vi.fn(),
  withAuth: vi.fn(),
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
  apiFetch: vi.fn(),
}));

const navigation = vi.hoisted(() => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  }),
}));

const workos = vi.hoisted(() => ({
  organizations: {
    createOrganization: vi.fn(),
  },
  userManagement: {
    createOrganizationMembership: vi.fn(),
    listOrganizationMemberships: vi.fn(),
  },
}));

vi.mock("@workos-inc/authkit-nextjs", () => authkit);
vi.mock("next/navigation", () => navigation);
vi.mock("../../../lib/api-client", () => apiClient);
vi.mock("../../../lib/workos", () => ({
  getWorkOSClient: () => workos,
}));

const sessionWithoutOrganization = {
  organizationId: undefined,
  user: {
    id: "user_01OWNER",
  },
};

function formData(name: string) {
  const data = new FormData();
  data.set("organizationName", name);
  return data;
}

describe("workspace onboarding action", () => {
  beforeEach(() => {
    vi.resetModules();
    authkit.withAuth.mockReset();
    authkit.refreshSession.mockReset();
    apiClient.apiFetch.mockReset();
    navigation.redirect.mockClear();
    workos.organizations.createOrganization.mockReset();
    workos.userManagement.createOrganizationMembership.mockReset();
    workos.userManagement.listOrganizationMemberships.mockReset();

    authkit.withAuth.mockResolvedValue(sessionWithoutOrganization);
    authkit.refreshSession.mockResolvedValue({ organizationId: "org_01LABEL" });
    workos.organizations.createOrganization.mockResolvedValue({
      id: "org_01LABEL",
      name: "Acme Label",
    });
    workos.userManagement.listOrganizationMemberships.mockResolvedValue({ data: [] });
    workos.userManagement.createOrganizationMembership.mockResolvedValue({
      id: "om_01OWNER",
      organizationId: "org_01LABEL",
      status: "active",
      userId: "user_01OWNER",
    });
    apiClient.apiFetch.mockResolvedValue(new Response("{}", { status: 200 }));
  });

  it("creates WorkOS organization and owner membership, syncs locally, refreshes, and redirects", async () => {
    const { onboardWorkspace } = await import("./actions");

    await expect(onboardWorkspace({ error: null }, formData("  Acme   Label  "))).rejects.toThrow(
      "NEXT_REDIRECT:/dashboard",
    );

    expect(workos.organizations.createOrganization).toHaveBeenCalledWith(
      expect.objectContaining({
        metadata: expect.objectContaining({ created_by: "user_01OWNER" }),
        name: "Acme Label",
      }),
      expect.objectContaining({
        idempotencyKey: "labelos-onboarding-user_01OWNER-acme-label",
      }),
    );
    expect(workos.userManagement.createOrganizationMembership).toHaveBeenCalledWith({
      organizationId: "org_01LABEL",
      roleSlug: "owner",
      userId: "user_01OWNER",
    });
    expect(apiClient.apiFetch).toHaveBeenCalledWith(
      "/api/v1/onboarding/workspace",
      expect.objectContaining({
        method: "POST",
      }),
    );
    expect(authkit.refreshSession).toHaveBeenCalledWith({
      ensureSignedIn: true,
      organizationId: "org_01LABEL",
    });
    expect(navigation.redirect).toHaveBeenCalledWith("/dashboard");
  });

  it("reuses an existing WorkOS membership on duplicate submissions", async () => {
    workos.userManagement.listOrganizationMemberships.mockResolvedValue({
      data: [
        {
          id: "om_01OWNER",
          organizationId: "org_01LABEL",
          status: "active",
          userId: "user_01OWNER",
        },
      ],
    });
    const { onboardWorkspace } = await import("./actions");

    await expect(onboardWorkspace({ error: null }, formData("Acme Label"))).rejects.toThrow(
      "NEXT_REDIRECT:/dashboard",
    );

    expect(workos.userManagement.createOrganizationMembership).not.toHaveBeenCalled();
  });

  it("returns a validation error for an empty organization name", async () => {
    const { onboardWorkspace } = await import("./actions");

    await expect(onboardWorkspace({ error: null }, formData(" a "))).resolves.toEqual({
      error: "Enter a label or company name with at least 2 characters.",
    });
    expect(workos.organizations.createOrganization).not.toHaveBeenCalled();
  });

  it("does not sync local records when WorkOS organization creation fails", async () => {
    workos.organizations.createOrganization.mockRejectedValue(new Error("workos unavailable"));
    const { onboardWorkspace } = await import("./actions");

    await expect(onboardWorkspace({ error: null }, formData("Acme Label"))).resolves.toEqual({
      error:
        "We could not create the workspace. No local workspace records were saved unless WorkOS confirmed the organization and membership.",
    });
    expect(apiClient.apiFetch).not.toHaveBeenCalled();
    expect(authkit.refreshSession).not.toHaveBeenCalled();
  });
});
