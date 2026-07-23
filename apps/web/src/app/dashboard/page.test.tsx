import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const authkit = vi.hoisted(() => ({
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
  getCurrentApiUser: vi.fn(),
}));

const navigation = vi.hoisted(() => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  }),
}));

vi.mock("@workos-inc/authkit-nextjs", () => authkit);
vi.mock("next/navigation", () => navigation);
vi.mock("../../lib/api-client", () => apiClient);
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
    apiClient.getCurrentApiUser.mockReset();
    navigation.redirect.mockClear();
    apiClient.getCurrentApiUser.mockResolvedValue({
      workos_user_id: "user_01SECRET",
      organization_id: "org_01LABEL",
      role: "admin",
      permissions: ["artists:read"],
    });
  });

  it("requires a signed-in WorkOS session and renders safe backend identity data", async () => {
    authkit.withAuth.mockResolvedValue(authenticatedSession);

    const { default: DashboardPage } = await import("./page");
    render(await DashboardPage());

    expect(authkit.withAuth).toHaveBeenCalledWith({ ensureSignedIn: true });
    expect(screen.getByRole("heading", { level: 1, name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getAllByText("Mara Chen").length).toBeGreaterThan(0);
    expect(screen.getAllByText("mara@example.com").length).toBeGreaterThan(0);
    expect(screen.getByText("org_01LABEL")).toBeInTheDocument();
    expect(screen.getByText("admin")).toBeInTheDocument();
    expect(screen.getByText("artists:read")).toBeInTheDocument();
    expect(apiClient.getCurrentApiUser).toHaveBeenCalledTimes(1);
    expect(screen.getAllByRole("img", { name: "Mara Chen profile image" }).length).toBeGreaterThan(
      0,
    );
    expect(screen.queryByText("access_token_secret")).not.toBeInTheDocument();
    expect(screen.queryByText("session_01SECRET")).not.toBeInTheDocument();
    expect(screen.queryByText("user_01SECRET")).not.toBeInTheDocument();
  });

  it("renders an onboarding empty state when the user has no active label workspace", async () => {
    authkit.withAuth.mockResolvedValue({
      ...authenticatedSession,
      organizationId: undefined,
    });
    apiClient.getCurrentApiUser.mockResolvedValue({
      workos_user_id: "user_01SECRET",
      organization_id: null,
      role: "member",
      permissions: [],
    });

    const { default: DashboardPage } = await import("./page");

    await expect(DashboardPage()).rejects.toThrow("NEXT_REDIRECT:/onboarding/workspace");
  });

  it("renders a safe error state when the backend rejects the session", async () => {
    authkit.withAuth.mockResolvedValue(authenticatedSession);
    apiClient.getCurrentApiUser.mockRejectedValue(
      new apiClient.ApiClientError(
        "unauthorized",
        "The backend rejected the WorkOS access token.",
        401,
      ),
    );

    const { default: DashboardPage } = await import("./page");
    render(await DashboardPage());

    expect(screen.getByRole("alert")).toHaveTextContent(/backend could not verify/i);
    expect(screen.queryByText("access_token_secret")).not.toBeInTheDocument();
    expect(screen.queryByText("session_01SECRET")).not.toBeInTheDocument();
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
