import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("./actions", () => ({
  createWorkspaceInviteAction: vi.fn(),
}));

describe("InviteTemplateForm", () => {
  it("opens a role-aware invitation dialog with friendly role explanations", async () => {
    const user = userEvent.setup();
    const { InviteTemplateForm } = await import("./invite-template-form");

    render(<InviteTemplateForm canAssignInviteRoles canInviteMembers organizationId="org_01" />);

    await user.click(screen.getByRole("button", { name: "Invite person" }));

    expect(screen.getByRole("dialog", { name: "Invite person" })).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveAttribute("placeholder", "sarah@example.com");
    expect(screen.getByRole("checkbox", { name: "Role Artist" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Role Manager" })).not.toBeChecked();
    expect(screen.getByText("For campaign, launch, and audience growth work.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send invitation" })).toBeEnabled();
  });

  it("allows one or more invited roles", async () => {
    const user = userEvent.setup();
    const { InviteTemplateForm } = await import("./invite-template-form");

    render(<InviteTemplateForm canAssignInviteRoles canInviteMembers organizationId="org_01" />);

    await user.click(screen.getByRole("button", { name: "Invite person" }));
    await user.click(screen.getByRole("checkbox", { name: "Role Manager" }));
    await user.click(screen.getByRole("checkbox", { name: "Role Legal" }));

    expect(screen.getByRole("checkbox", { name: "Role Artist" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Role Manager" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Role Legal" })).toBeChecked();
  });

  it("disables invitation entry when the member cannot invite people", async () => {
    const { InviteTemplateForm } = await import("./invite-template-form");

    render(
      <InviteTemplateForm
        canAssignInviteRoles={false}
        canInviteMembers={false}
        organizationId="org_01"
      />,
    );

    expect(screen.queryByRole("button", { name: "Invite person" })).not.toBeInTheDocument();
    expect(
      screen.getByText("Ask a workspace owner or admin to invite new people."),
    ).toBeInTheDocument();
  });

  it("hides invite role controls without exposing capability names", async () => {
    const user = userEvent.setup();
    const { InviteTemplateForm } = await import("./invite-template-form");

    render(
      <InviteTemplateForm canAssignInviteRoles={false} canInviteMembers organizationId="org_01" />,
    );

    await user.click(screen.getByRole("button", { name: "Invite person" }));

    expect(screen.queryByRole("checkbox", { name: "Role Artist" })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Invite as" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send invitation" })).toBeEnabled();
    expect(
      screen.getByText("This invitation will use the workspace default starting access."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/role\.assign|member\.invite/)).not.toBeInTheDocument();
  });

  it("renders the success state with an invite link", async () => {
    const { InviteTemplateForm } = await import("./invite-template-form");

    render(
      <InviteTemplateForm
        canAssignInviteRoles
        canInviteMembers
        initialInviteLink="http://localhost:3000/join/token_01"
        organizationId="org_01"
      />,
    );

    expect(screen.getByText("Invitation ready")).toBeInTheDocument();
    expect(screen.getByText("http://localhost:3000/join/token_01")).toBeInTheDocument();
  });
});
