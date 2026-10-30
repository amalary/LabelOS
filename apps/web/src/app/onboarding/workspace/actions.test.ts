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
  apiFetchWithAccessToken: vi.fn(),
}));

const navigation = vi.hoisted(() => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  }),
}));

const serverLogging = vi.hoisted(() => ({
  logServerError: vi.fn(),
}));

const workos = vi.hoisted(() => ({
  authorization: { getEnvironmentRole: vi.fn() },
  organizations: {
    createOrganization: vi.fn(),
    listOrganizations: vi.fn(),
  },
  userManagement: {
    createOrganizationMembership: vi.fn(),
    listOrganizationMemberships: vi.fn(),
  },
}));

vi.mock("@workos-inc/authkit-nextjs", () => authkit);
vi.mock("next/navigation", () => navigation);
vi.mock("../../../lib/api-client", () => apiClient);
vi.mock("../../../lib/server-logging", () => serverLogging);
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
    apiClient.apiFetchWithAccessToken.mockReset();
    serverLogging.logServerError.mockReset();
    navigation.redirect.mockClear();
    workos.organizations.createOrganization.mockReset();
    workos.authorization.getEnvironmentRole.mockReset().mockResolvedValue({ slug: "owner" });
    workos.organizations.listOrganizations.mockReset().mockResolvedValue({
      data: [],
      listMetadata: { after: null },
    });
    workos.userManagement.createOrganizationMembership.mockReset();
    workos.userManagement.listOrganizationMemberships.mockReset();

    authkit.withAuth.mockResolvedValue(sessionWithoutOrganization);
    authkit.refreshSession.mockResolvedValue({
      organizationId: "org_01LABEL",
      accessToken: "new_owner_token",
    });
    workos.organizations.createOrganization.mockResolvedValue({
      id: "org_01LABEL",
      name: "Acme Label",
    });
    workos.userManagement.listOrganizationMemberships.mockResolvedValue({ data: [] });
    workos.userManagement.createOrganizationMembership.mockResolvedValue({
      id: "om_01OWNER",
      organizationId: "org_01LABEL",
      status: "active",
      role: { slug: "owner" },
      userId: "user_01OWNER",
    });
    apiClient.apiFetch.mockResolvedValue(new Response("{}", { status: 200 }));
    apiClient.apiFetchWithAccessToken.mockResolvedValue(new Response("{}", { status: 200 }));
  });

  it("creates WorkOS organization and owner membership, refreshes, syncs with owner proof, and redirects", async () => {
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
    expect(apiClient.apiFetchWithAccessToken).toHaveBeenCalledWith(
      "/api/v1/onboarding/workspace",
      "new_owner_token",
      expect.objectContaining({
        method: "POST",
      }),
    );
    expect(authkit.refreshSession).toHaveBeenCalledWith({
      ensureSignedIn: true,
      organizationId: "org_01LABEL",
    });
    expect(navigation.redirect).toHaveBeenCalledWith("/dashboard");
    expect(authkit.refreshSession.mock.invocationCallOrder[0]).toBeLessThan(
      apiClient.apiFetchWithAccessToken.mock.invocationCallOrder[0]!,
    );
    expect(JSON.parse(apiClient.apiFetchWithAccessToken.mock.calls[0]![2].body)).toEqual({
      organization_name: "Acme Label",
      workos_organization_id: "org_01LABEL",
    });
  });

  it("reuses an existing WorkOS membership on duplicate submissions", async () => {
    workos.userManagement.listOrganizationMemberships.mockResolvedValue({
      data: [
        {
          id: "om_01OWNER",
          organizationId: "org_01LABEL",
          status: "active",
          role: { slug: "owner" },
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

  it("checks the owner role before creating an organization", async () => {
    workos.authorization.getEnvironmentRole.mockRejectedValue(new Error("not found SECRET"));
    const { onboardWorkspace } = await import("./actions");
    const result = await onboardWorkspace({ error: null }, formData("Acme Label"));
    expect(result.error).toContain("configure the WorkOS owner role");
    expect(result.error).not.toContain("SECRET");
    expect(workos.organizations.createOrganization).not.toHaveBeenCalled();
    expect(workos.userManagement.createOrganizationMembership).not.toHaveBeenCalled();
  });

  it("resumes the creator's earliest matching organization after a partial failure", async () => {
    workos.organizations.listOrganizations.mockResolvedValue({
      data: [
        {
          id: "foreign",
          name: "Acme Label",
          createdAt: "2026-01-01",
          metadata: { created_by: "someone_else", product: "label-os" },
        },
        {
          id: "org_01LABEL",
          name: "Acme Label",
          createdAt: "2026-02-01",
          metadata: { created_by: "user_01OWNER", product: "label-os" },
        },
      ],
      listMetadata: { after: null },
    });
    const { onboardWorkspace } = await import("./actions");
    await expect(onboardWorkspace({ error: null }, formData("Acme Label"))).rejects.toThrow(
      "NEXT_REDIRECT:/dashboard",
    );
    expect(workos.organizations.createOrganization).not.toHaveBeenCalled();
    expect(workos.userManagement.createOrganizationMembership).toHaveBeenCalledWith({
      organizationId: "org_01LABEL",
      roleSlug: "owner",
      userId: "user_01OWNER",
    });
  });

  it("does not turn old creator metadata into ownership of an occupied organization", async () => {
    workos.organizations.listOrganizations.mockResolvedValue({
      data: [
        {
          id: "org_01LABEL",
          name: "Acme Label",
          createdAt: "2026-02-01",
          metadata: { created_by: "user_01OWNER", product: "label-os" },
        },
      ],
      listMetadata: { after: null },
    });
    workos.userManagement.listOrganizationMemberships
      .mockResolvedValueOnce({ data: [] })
      .mockResolvedValueOnce({
        data: [{ userId: "someone_else", status: "active", role: { slug: "owner" } }],
      });
    const { onboardWorkspace } = await import("./actions");
    const result = await onboardWorkspace({ error: null }, formData("Acme Label"));
    expect(result.error).toContain("already has members");
    expect(workos.userManagement.createOrganizationMembership).not.toHaveBeenCalled();
    expect(workos.organizations.createOrganization).not.toHaveBeenCalled();
  });

  it("does not sync local records when WorkOS organization creation fails", async () => {
    workos.organizations.createOrganization.mockRejectedValue(new Error("workos unavailable"));
    const { onboardWorkspace } = await import("./actions");

    await expect(onboardWorkspace({ error: null }, formData("Acme Label"))).resolves.toEqual({
      error:
        "We could not create the workspace. No local workspace records were saved unless WorkOS confirmed the organization and membership.",
    });
    expect(apiClient.apiFetchWithAccessToken).not.toHaveBeenCalled();
    expect(authkit.refreshSession).not.toHaveBeenCalled();
    expect(serverLogging.logServerError).toHaveBeenCalledWith(
      "Workspace onboarding failed",
      expect.any(Error),
      { operation: "workspace_onboarding" },
    );
  });

  it.each(["guest", "member", "admin"])(
    "blocks an org-less existing %s before WorkOS creation",
    async (role) => {
      workos.userManagement.listOrganizationMemberships.mockResolvedValue({
        data: [{ status: "active", role: { slug: role } }],
      });
      const { onboardWorkspace } = await import("./actions");
      const result = await onboardWorkspace({ error: null }, formData("Acme Label"));
      expect(result.error).toBeTruthy();
      expect(workos.organizations.createOrganization).not.toHaveBeenCalled();
      expect(apiClient.apiFetchWithAccessToken).not.toHaveBeenCalled();
    },
  );

  it("blocks creation when backend eligibility fails", async () => {
    apiClient.apiFetch.mockResolvedValue(new Response("{}", { status: 403 }));
    const { onboardWorkspace } = await import("./actions");
    expect((await onboardWorkspace({ error: null }, formData("Acme Label"))).error).toBeTruthy();
    expect(workos.organizations.createOrganization).not.toHaveBeenCalled();
  });

  it.each(["inactive", "pending", "non-owner"])(
    "rejects an existing %s membership returned after creation",
    async (state) => {
      workos.userManagement.listOrganizationMemberships
        .mockResolvedValueOnce({ data: [] })
        .mockResolvedValueOnce({
          data: [
            {
              organizationId: "org_01LABEL",
              userId: "user_01OWNER",
              status: state === "non-owner" ? "active" : state,
              role: { slug: state === "non-owner" ? "member" : "owner" },
            },
          ],
        });
      const { onboardWorkspace } = await import("./actions");
      expect((await onboardWorkspace({ error: null }, formData("Acme Label"))).error).toBeTruthy();
      expect(authkit.refreshSession).not.toHaveBeenCalled();
      expect(apiClient.apiFetchWithAccessToken).not.toHaveBeenCalled();
    },
  );

  it("does not sync if owner session refresh fails", async () => {
    authkit.refreshSession.mockRejectedValue(new Error("Refresh failed"));
    const { onboardWorkspace } = await import("./actions");
    expect((await onboardWorkspace({ error: null }, formData("Acme Label"))).error).toBeTruthy();
    expect(apiClient.apiFetchWithAccessToken).not.toHaveBeenCalled();
  });
});
