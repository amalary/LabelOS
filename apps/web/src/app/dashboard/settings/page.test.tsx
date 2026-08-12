import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const dashboardSession = vi.hoisted(() => ({
  requireDashboardSession: vi.fn(),
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
  getCurrentApiUser: vi.fn(),
}));

const navigation = vi.hoisted(() => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  }),
}));

const organizations = vi.hoisted(() => ({
  getActiveOrganization: vi.fn(),
  listOrganizationMembers: vi.fn(),
}));

const settingsPanel = vi.hoisted(() => ({
  SettingsPanel: vi.fn(
    ({
      canEditProfile,
      canEditRoles,
      invitations,
      members,
      membersError,
      organization,
    }: {
      canEditProfile: boolean;
      canEditRoles: boolean;
      invitations: unknown[];
      members: unknown[];
      membersError: string | null;
      organization: { name: string };
    }) => (
      <div
        data-can-edit-profile={String(canEditProfile)}
        data-can-edit-roles={String(canEditRoles)}
        data-invitation-count={invitations.length}
        data-member-count={members.length}
        data-members-error={membersError ?? ""}
      >
        {organization.name}
      </div>
    ),
  ),
}));

vi.mock("next/navigation", () => navigation);
vi.mock("../../../components/app-shell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("../../../lib/dashboard-session", () => dashboardSession);
vi.mock("../../../lib/api-client", () => apiClient);
vi.mock("../../../lib/organizations", () => organizations);
vi.mock("./settings-panel", () => settingsPanel);

const session = {
  organizationId: "org_WORKOS",
  user: {
    email: "owner@example.com",
    firstName: "Owner",
    lastName: "User",
    profileImageUrl: null,
  },
};

const organization = {
  id: "local_org_1",
  name: "Northstar Audio",
  slug: "northstar-audio",
  role: "owner",
  can_switch: true,
};

describe("OrganizationSettingsPage", () => {
  beforeEach(() => {
    vi.resetModules();
    dashboardSession.requireDashboardSession.mockReset();
    apiClient.getCurrentApiUser.mockReset();
    navigation.redirect.mockClear();
    organizations.getActiveOrganization.mockReset();
    organizations.listOrganizationMembers.mockReset();
    settingsPanel.SettingsPanel.mockClear();

    dashboardSession.requireDashboardSession.mockResolvedValue(session);
    apiClient.getCurrentApiUser.mockResolvedValue({
      organization_id: "local_org_1",
      permissions: ["organization:manage", "members:manage"],
      role: "owner",
      workos_user_id: "user_1",
    });
    organizations.getActiveOrganization.mockResolvedValue(organization);
    organizations.listOrganizationMembers.mockResolvedValue({
      members: [
        {
          id: "membership_1",
          user_id: "user_1",
          email: "owner@example.com",
          display_name: "Owner User",
          role: "owner",
          status: "active",
        },
      ],
      invitations: [],
      limit: 100,
      offset: 0,
      total: 1,
    });
  });

  it("loads organization settings and allows owner edits with required permissions", async () => {
    const { default: OrganizationSettingsPage } = await import("./page");

    render(await OrganizationSettingsPage());

    expect(screen.getByRole("heading", { name: "Organization settings" })).toBeInTheDocument();
    expect(screen.getByText("Northstar Audio")).toHaveAttribute("data-can-edit-profile", "true");
    expect(screen.getByText("Northstar Audio")).toHaveAttribute("data-can-edit-roles", "true");
    expect(screen.getByText("Northstar Audio")).toHaveAttribute("data-member-count", "1");
    expect(screen.getByText("Northstar Audio")).toHaveAttribute("data-invitation-count", "0");
    expect(organizations.listOrganizationMembers).toHaveBeenCalledWith("local_org_1");
  });

  it("prevents unauthorized editing and avoids member loading without permission", async () => {
    apiClient.getCurrentApiUser.mockResolvedValue({
      organization_id: "local_org_1",
      permissions: [],
      role: "member",
      workos_user_id: "user_1",
    });
    organizations.getActiveOrganization.mockResolvedValue({
      ...organization,
      role: "member",
    });

    const { default: OrganizationSettingsPage } = await import("./page");

    render(await OrganizationSettingsPage());

    expect(screen.getByText("Northstar Audio")).toHaveAttribute("data-can-edit-profile", "false");
    expect(screen.getByText("Northstar Audio")).toHaveAttribute("data-can-edit-roles", "false");
    expect(screen.getByText("Northstar Audio")).toHaveAttribute(
      "data-members-error",
      "You do not have permission to view organization members.",
    );
    expect(organizations.listOrganizationMembers).not.toHaveBeenCalled();
  });

  it("redirects users without an active session organization to onboarding", async () => {
    dashboardSession.requireDashboardSession.mockResolvedValue({
      ...session,
      organizationId: null,
    });

    const { default: OrganizationSettingsPage } = await import("./page");

    await expect(OrganizationSettingsPage()).rejects.toThrow("NEXT_REDIRECT:/onboarding/workspace");
  });
});
