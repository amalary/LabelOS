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

vi.mock("next/navigation", () => navigation);
vi.mock("../../../lib/dashboard-session", () => dashboardSession);
vi.mock("../../../components/app-shell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("./onboarding-form", () => ({
  WorkspaceOnboardingForm: () => <form aria-label="workspace onboarding" />,
}));

describe("WorkspaceOnboardingPage", () => {
  beforeEach(() => {
    vi.resetModules();
    dashboardSession.requireDashboardSession.mockReset();
    navigation.redirect.mockClear();
  });

  it("renders for authenticated users without an active organization", async () => {
    dashboardSession.requireDashboardSession.mockResolvedValue({ organizationId: null });
    const { default: WorkspaceOnboardingPage } = await import("./page");

    render(await WorkspaceOnboardingPage());

    expect(
      screen.getByRole("heading", { name: "Create your label workspace" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("form", { name: "workspace onboarding" })).toBeInTheDocument();
  });

  it("redirects users who already have an active organization", async () => {
    dashboardSession.requireDashboardSession.mockResolvedValue({ organizationId: "org_01LABEL" });
    const { default: WorkspaceOnboardingPage } = await import("./page");

    await expect(WorkspaceOnboardingPage()).rejects.toThrow("NEXT_REDIRECT:/dashboard");
    expect(navigation.redirect).toHaveBeenCalledWith("/dashboard");
  });
});
