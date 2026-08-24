import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("./actions", () => ({
  createWorkspaceInviteAction: vi.fn(),
}));

describe("InviteTemplateForm", () => {
  it("starts from the artist preset", async () => {
    const { InviteTemplateForm } = await import("./invite-template-form");

    render(<InviteTemplateForm organizationId="org_01" />);

    expect(screen.getByRole("button", { name: /^Artist/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("checkbox", { name: "Role Artist" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Department Creative" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Department Releases" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Department Analytics" })).toBeChecked();
  });

  it("applies a template while leaving roles and departments customizable", async () => {
    const user = userEvent.setup();
    const { InviteTemplateForm } = await import("./invite-template-form");

    render(<InviteTemplateForm organizationId="org_01" />);

    await user.click(screen.getByRole("button", { name: /^Producer/ }));

    expect(screen.getByRole("checkbox", { name: "Role Producer" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Department Production" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Department Songs" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Department Sessions" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Department Credits" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Role Artist" })).not.toBeChecked();

    await user.click(screen.getByRole("checkbox", { name: "Role Artist" }));
    await user.click(screen.getByRole("checkbox", { name: "Department Credits" }));

    expect(screen.getByRole("checkbox", { name: "Role Artist" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Department Credits" })).not.toBeChecked();
  });

  it("marks the legal template as sensitive access", async () => {
    const user = userEvent.setup();
    const { InviteTemplateForm } = await import("./invite-template-form");

    render(<InviteTemplateForm organizationId="org_01" />);

    await user.click(screen.getByRole("button", { name: /^Legal/ }));

    expect(screen.getByText("Sensitive access: Requires approval")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Role Legal" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Department Contracts" })).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Department Agreement Reviews" }),
    ).not.toBeChecked();
  });
});
