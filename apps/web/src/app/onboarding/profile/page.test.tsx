import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const dashboardSession = vi.hoisted(() => ({
  requireDashboardSession: vi.fn(),
}));

const navigation = vi.hoisted(() => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  }),
}));

const organizations = vi.hoisted(() => ({
  getOrganizationSelection: vi.fn(),
}));

const profiles = vi.hoisted(() => ({
  getCurrentUniversalProfile: vi.fn(),
}));

vi.mock("next/navigation", () => navigation);
vi.mock("../../../lib/dashboard-session", () => dashboardSession);
vi.mock("../../../lib/organizations", () => organizations);
vi.mock("../../../lib/profiles.server", () => profiles);
vi.mock("../../../components/app-shell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("./profile-onboarding", () => ({
  UniversalProfileOnboarding: () => <form aria-label="profile onboarding" />,
}));

const profile = {
  id: "profile_01",
  user_id: "user_01",
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
};

describe("UniversalProfileOnboardingPage", () => {
  beforeEach(() => {
    vi.resetModules();
    dashboardSession.requireDashboardSession.mockReset();
    navigation.redirect.mockClear();
    organizations.getOrganizationSelection.mockReset();
    profiles.getCurrentUniversalProfile.mockReset();
    dashboardSession.requireDashboardSession.mockResolvedValue({ organizationId: "org_01" });
    organizations.getOrganizationSelection.mockResolvedValue({
      activeOrganization: { id: "org_01", name: "Northstar Audio" },
      organizations: [{ id: "org_01", name: "Northstar Audio" }],
    });
    profiles.getCurrentUniversalProfile.mockResolvedValue(profile);
  });

  it("renders profile onboarding for authenticated users with incomplete profiles", async () => {
    const { default: UniversalProfileOnboardingPage } = await import("./page");

    render(await UniversalProfileOnboardingPage());

    expect(screen.getByRole("form", { name: "profile onboarding" })).toBeInTheDocument();
  });

  it("redirects completed profiles to the dashboard when a workspace exists", async () => {
    profiles.getCurrentUniversalProfile.mockResolvedValue({
      ...profile,
      onboarding_status: "complete",
    });
    const { default: UniversalProfileOnboardingPage } = await import("./page");

    await expect(UniversalProfileOnboardingPage()).rejects.toThrow("NEXT_REDIRECT:/dashboard");
  });
});
