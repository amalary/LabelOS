import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const authkit = vi.hoisted(() => ({
  withAuth: vi.fn(),
}));

const navigation = vi.hoisted(() => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  }),
}));

const organizations = vi.hoisted(() => ({
  getOrganizationSelection: vi.fn(),
}));

const dashboardData = vi.hoisted(() => ({
  getDashboardData: vi.fn(),
  getEmptyDashboardData: vi.fn(),
}));

const profiles = vi.hoisted(() => ({
  getCurrentUniversalProfile: vi.fn(),
}));

vi.mock("@workos-inc/authkit-nextjs", () => authkit);
vi.mock("next/navigation", () => navigation);
vi.mock("../../lib/organizations", () => organizations);
vi.mock("../../lib/profiles.server", () => profiles);
vi.mock("./dashboard-data", () => dashboardData);
vi.mock("../../components/app-shell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const authenticatedSession = {
  accessToken: "access_token_secret",
  organizationId: "org_01LABEL",
  role: "label_admin",
  sessionId: "session_01SECRET",
  user: {
    email: "mara@example.com",
    firstName: "Mara",
    id: "user_01SECRET",
    lastName: "Chen",
    profilePictureUrl: "https://example.com/mara.png",
  },
};

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.resetModules();
    authkit.withAuth.mockReset();
    navigation.redirect.mockClear();
    organizations.getOrganizationSelection.mockReset();
    profiles.getCurrentUniversalProfile.mockReset();
    dashboardData.getDashboardData.mockReset();
    dashboardData.getEmptyDashboardData.mockReset();
    organizations.getOrganizationSelection.mockResolvedValue({
      activeOrganization: {
        id: "local_org_01LABEL",
        name: "Northstar Audio",
        slug: "northstar-audio",
        role: "owner",
        can_switch: true,
      },
      organizations: [
        {
          id: "local_org_01LABEL",
          name: "Northstar Audio",
          slug: "northstar-audio",
          role: "owner",
          can_switch: true,
        },
      ],
    });
    dashboardData.getDashboardData.mockResolvedValue({
      kpis: [
        {
          id: "active-artists",
          title: "Active Artists",
          primaryValue: "2",
          icon: "AR",
        },
        {
          id: "upcoming-releases",
          title: "Upcoming Releases",
          primaryValue: "2",
          icon: "UR",
        },
        {
          id: "active-campaigns",
          title: "Active Campaigns",
          primaryValue: "2",
          icon: "AC",
        },
        {
          id: "tasks-approvals",
          title: "Tasks / Approvals",
          primaryValue: "2",
          icon: "TA",
        },
      ],
      labelPerformance: { metrics: [], ranges: [] },
      releasePipeline: {
        stages: [
          {
            status: "planning",
            label: "Planning",
            count: 2,
            href: "/releases?status=planning",
          },
          {
            status: "production",
            label: "Production",
            count: 0,
            href: "/releases?status=production",
          },
          {
            status: "distribution",
            label: "Distribution",
            count: 0,
            href: "/releases?status=distribution",
          },
          {
            status: "scheduled",
            label: "Scheduled",
            count: 0,
            href: "/releases?status=scheduled",
          },
          {
            status: "released",
            label: "Released",
            count: 0,
            href: "/releases?status=released",
          },
        ],
      },
      recentActivity: { events: [] },
    });
    dashboardData.getEmptyDashboardData.mockReturnValue({
      kpis: [
        {
          id: "active-artists",
          title: "Active Artists",
          primaryValue: "0",
          icon: "AR",
          empty: true,
        },
        {
          id: "upcoming-releases",
          title: "Upcoming Releases",
          primaryValue: "0",
          icon: "UR",
          empty: true,
        },
        {
          id: "active-campaigns",
          title: "Active Campaigns",
          primaryValue: "0",
          icon: "AC",
          empty: true,
        },
        {
          id: "tasks-approvals",
          title: "Tasks / Approvals",
          primaryValue: "0",
          icon: "TA",
          empty: true,
        },
      ],
      labelPerformance: { metrics: [], ranges: [] },
      releasePipeline: { stages: [], emptyOrganization: true },
      recentActivity: { events: [] },
    });
    profiles.getCurrentUniversalProfile.mockResolvedValue({
      id: "profile_01",
      user_id: "user_01SECRET",
      display_name: "Mara Chen",
      headline: null,
      biography: null,
      avatar_url: null,
      location: null,
      profile_status: "active",
      onboarding_status: "complete",
      links: [],
      attributes: [],
      preferences: {
        locale: null,
        timezone: null,
        default_workspace_id: null,
        email_notifications_enabled: true,
        push_notifications_enabled: true,
        sms_notifications_enabled: false,
        marketing_notifications_enabled: false,
        interface_theme: null,
        interface_density: null,
        notification_preferences: {},
        interface_preferences: {},
        integration_preferences: {},
      },
    });
  });

  it("requires a signed-in WorkOS session and renders Dashboard V1 in the active organization", async () => {
    authkit.withAuth.mockResolvedValue(authenticatedSession);

    const { default: DashboardPage } = await import("./page");
    render(await DashboardPage());

    expect(authkit.withAuth).toHaveBeenCalledWith({ ensureSignedIn: true });
    expect(dashboardData.getDashboardData).toHaveBeenCalled();
    expect(screen.getByRole("heading", { level: 1, name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByText(/Operational view for Northstar Audio/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Active Artists" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Upcoming Releases" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Active Campaigns" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Tasks / Approvals" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Label Performance" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Release Pipeline" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Planning: 2 releases" })).toHaveAttribute(
      "href",
      "/releases?status=planning",
    );
    expect(screen.getByRole("heading", { level: 2, name: "Recent Activity" })).toBeInTheDocument();
    expect(screen.queryByText("access_token_secret")).not.toBeInTheDocument();
    expect(screen.queryByText("session_01SECRET")).not.toBeInTheDocument();
    expect(screen.queryByText("user_01SECRET")).not.toBeInTheDocument();
  });

  it("renders an onboarding empty state when the user has no active label workspace", async () => {
    authkit.withAuth.mockResolvedValue({
      ...authenticatedSession,
      organizationId: undefined,
    });
    organizations.getOrganizationSelection.mockResolvedValue({
      activeOrganization: null,
      organizations: [],
    });

    const { default: DashboardPage } = await import("./page");

    await expect(DashboardPage()).rejects.toThrow("NEXT_REDIRECT:/onboarding/workspace");
  });

  it("shows optional Universal Profile completion guidance without blocking the dashboard", async () => {
    authkit.withAuth.mockResolvedValue(authenticatedSession);
    profiles.getCurrentUniversalProfile.mockResolvedValue({
      id: "profile_01",
      user_id: "user_01SECRET",
      display_name: null,
      headline: null,
      biography: null,
      avatar_url: null,
      location: null,
      profile_status: "active",
      onboarding_status: "not_started",
      links: [],
      attributes: [],
      preferences: {
        locale: null,
        timezone: null,
        default_workspace_id: null,
        email_notifications_enabled: true,
        push_notifications_enabled: true,
        sms_notifications_enabled: false,
        marketing_notifications_enabled: false,
        interface_theme: null,
        interface_density: null,
        notification_preferences: {},
        interface_preferences: {},
        integration_preferences: {},
      },
      profile_completion: {
        ruleset: "artist",
        is_complete: false,
        percent: 25,
        completed_fields: ["Artist name"],
        missing_fields: ["Artist image", "Biography", "DSP links"],
        guidance: "Complete your artist profile",
        is_blocking: false,
      },
    });

    const { default: DashboardPage } = await import("./page");
    render(await DashboardPage());

    expect(screen.getByText("Complete your artist profile")).toBeInTheDocument();
    expect(screen.getByText(/Missing: Artist image, Biography, DSP links/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Update profile" })).toHaveAttribute(
      "href",
      "/profile",
    );
    expect(dashboardData.getDashboardData).toHaveBeenCalled();
    expect(screen.getByRole("heading", { level: 1, name: "Dashboard" })).toBeInTheDocument();
  });

  it("does not trust a stale active organization claim when backend access is gone", async () => {
    authkit.withAuth.mockResolvedValue(authenticatedSession);
    organizations.getOrganizationSelection.mockResolvedValue({
      activeOrganization: null,
      organizations: [
        {
          id: "local_org_02LABEL",
          name: "Backup Label",
          slug: "backup-label",
          role: "member",
          can_switch: true,
        },
      ],
    });

    const { default: DashboardPage } = await import("./page");
    render(await DashboardPage());

    expect(screen.getByRole("alert")).toHaveTextContent(/active organization selection/i);
    expect(dashboardData.getDashboardData).not.toHaveBeenCalled();
    expect(dashboardData.getEmptyDashboardData).toHaveBeenCalledWith({ emptyOrganization: true });
    expect(
      screen.getByRole("heading", { level: 2, name: "Label Performance" }),
    ).toBeInTheDocument();
  });

  it("redirects unauthenticated access through WorkOS AuthKit", async () => {
    authkit.withAuth.mockImplementation((options?: { ensureSignedIn?: boolean }) => {
      if (options?.ensureSignedIn) {
        throw new Error("NEXT_REDIRECT:https://auth.workos.test/login");
      }

      return Promise.resolve({ user: null });
    });

    const { default: DashboardPage } = await import("./page");

    await expect(DashboardPage()).rejects.toThrow("NEXT_REDIRECT:https://auth.workos.test/login");
    expect(authkit.withAuth).toHaveBeenCalledWith({ ensureSignedIn: true });
  });
});
