import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { CurrentWorkspaceRoles } from "./current-workspace-roles";

const state = vi.hoisted(() => ({
  data: {},
  isLoading: false,
  error: null as Error | null,
  roles: [
    { key: "member", name: "Member" },
    { key: "a_and_r", name: "A&R" },
  ],
}));
vi.mock("../../../lib/workspace-capabilities", () => ({ useEffectiveCapabilities: () => state }));
beforeEach(() => {
  state.error = null;
});
it("shows the actual workspace roles", () => {
  render(<CurrentWorkspaceRoles workspaceId="workspace" workspaceName="Calebasse" />);
  expect(screen.getByText("Your roles in Calebasse")).toBeInTheDocument();
  expect(screen.getByText("Member, A&R")).toBeInTheDocument();
});
it("does not show stale roles without an active workspace", () => {
  render(<CurrentWorkspaceRoles workspaceId={null} />);
  expect(screen.queryByText("Member, A&R")).not.toBeInTheDocument();
});
it("reports a load failure without displaying error details", () => {
  state.error = new Error("PRIVATE");
  render(<CurrentWorkspaceRoles workspaceId="workspace" workspaceName="Calebasse" />);
  expect(screen.getByText(/could not be loaded/)).toBeInTheDocument();
  expect(screen.queryByText("PRIVATE")).not.toBeInTheDocument();
});
