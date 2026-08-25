import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const organizations = vi.hoisted(() => ({
  getWorkspaceInvite: vi.fn(),
}));

vi.mock("@workos-inc/authkit-nextjs", () => ({
  withAuth: vi.fn(async () => ({ user: null })),
}));

vi.mock("../../../components/app-shell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("../../../lib/organizations", () => organizations);

vi.mock("./invite-onboarding-flow", () => ({
  InviteOnboardingFlow: ({
    initialStep,
    invite,
  }: {
    initialStep: string;
    invite: {
      workspace: {
        name: string;
      };
    };
  }) => (
    <div>
      <span>step:{initialStep}</span>
      <h1>{invite.workspace.name}</h1>
    </div>
  ),
}));

const invite = {
  id: "invite_01",
  token: "token_01",
  email: "sarah@example.com",
  workspace: {
    id: "org_01",
    name: "Malary Records",
    slug: "malary-records",
  },
  inviter: null,
  professional_roles: ["Legal", "Management"],
  proposed_department_access: ["legal", "contracts", "agreements", "management"],
  expiration: "2026-09-01T00:00:00Z",
  maximum_uses: null,
  use_count: 0,
  status: "active",
  join_path: "/join/token_01",
};

describe("JoinWorkspacePage", () => {
  it("passes the accept step from query params into the onboarding flow", async () => {
    organizations.getWorkspaceInvite.mockResolvedValue(invite);
    const { default: JoinWorkspacePage } = await import("./page");

    render(
      await JoinWorkspacePage({
        params: Promise.resolve({ token: "token_01" }),
        searchParams: Promise.resolve({ step: "accept" }),
      }),
    );

    expect(organizations.getWorkspaceInvite).toHaveBeenCalledWith("token_01");
    expect(screen.getByText("step:accept")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Malary Records" })).toBeInTheDocument();
  });

  it("falls back to the intro step for unknown query values", async () => {
    organizations.getWorkspaceInvite.mockResolvedValue(invite);
    const { default: JoinWorkspacePage } = await import("./page");

    render(
      await JoinWorkspacePage({
        params: Promise.resolve({ token: "token_01" }),
        searchParams: Promise.resolve({ step: "unexpected" }),
      }),
    );

    expect(screen.getByText("step:intro")).toBeInTheDocument();
  });
});
