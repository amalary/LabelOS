import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { WorkspaceInvite } from "../../../lib/organizations";

vi.mock("react-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-dom")>()),
  useFormStatus: () => ({ pending: false }),
}));

vi.mock("./actions", () => ({
  acceptWorkspaceInviteAction: vi.fn(),
}));

const invite: WorkspaceInvite = {
  id: "invite_01",
  token: "token_01",
  email: "sarah@example.com",
  workspace: {
    id: "org_01",
    name: "Malary Records",
    slug: "malary-records",
  },
  inviter: {
    id: "user_01",
    email: "owner@malary.test",
    display_name: "Owner",
  },
  professional_roles: ["Legal", "Management"],
  proposed_department_access: ["legal", "contracts", "agreements", "management"],
  expiration: "2026-09-01T00:00:00Z",
  maximum_uses: null,
  use_count: 0,
  status: "active",
  join_path: "/join/token_01",
};

describe("InviteOnboardingFlow", () => {
  it("starts with the general invite prompt", async () => {
    const { InviteOnboardingFlow } = await import("./invite-onboarding-flow");

    render(<InviteOnboardingFlow hasInviteError={false} invite={invite} />);

    expect(screen.getByText("You've been invited to")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Malary Records" })).toBeInTheDocument();
    expect(screen.getByText("Legal")).toBeInTheDocument();
    expect(screen.getByText("Management")).toBeInTheDocument();
    expect(screen.getByText("Department Access")).toBeInTheDocument();
    expect(screen.getByText("contracts")).toBeInTheDocument();
    expect(screen.getByText("agreements")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Join Workspace" })).toBeEnabled();
    expect(screen.queryByText("Existing LabelOS account?")).not.toBeInTheDocument();
  });

  it("shows sign in and sign up paths after joining", async () => {
    const { InviteOnboardingFlow } = await import("./invite-onboarding-flow");

    render(<InviteOnboardingFlow hasInviteError={false} invite={invite} />);
    fireEvent.click(screen.getByRole("button", { name: "Join Workspace" }));

    const next = encodeURIComponent("/join/token_01?step=accept");
    expect(screen.getByRole("heading", { name: "Existing LabelOS account?" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      `/api/auth/login?next=${next}`,
    );
    expect(screen.getByRole("link", { name: "Sign up" })).toHaveAttribute(
      "href",
      `/api/auth/signup?next=${next}`,
    );
  });

  it("continues from the post-auth accept step and submits the assigned invite roles", async () => {
    const { InviteOnboardingFlow } = await import("./invite-onboarding-flow");

    render(
      <InviteOnboardingFlow hasInviteError={false} initialStep="accept" invite={invite} />,
    );

    expect(screen.getByRole("button", { name: "Accept Workspace Invitation" })).toBeEnabled();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});
