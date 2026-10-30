import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { LocalResearchSetup } from "./local-research-setup";

const permissions = vi.hoisted(() => ({ allowed: true }));
vi.mock("../lib/workspace-capabilities", () => ({
  useEffectiveCapabilities: () => ({ can: () => permissions.allowed }),
}));
afterEach(() => {
  vi.unstubAllGlobals();
  permissions.allowed = true;
});

it("lets a governance manager explicitly prepare a session", async () => {
  const run = { id: "run", label: "Local research" };
  const fetch = vi.fn().mockResolvedValue(Response.json(run, { status: 201 }));
  vi.stubGlobal("fetch", fetch);
  const ready = vi.fn();
  render(<LocalResearchSetup workspaceId="workspace" onPrepared={ready} />);
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Prepare local YouTube session"));
  await waitFor(() => expect(ready).toHaveBeenCalledWith(run));
  expect(fetch).toHaveBeenCalledWith("/api/workspaces/workspace/scouting/local-session", {
    method: "POST",
    cache: "no-store",
  });
});

it("hides setup from ordinary scouts", () => {
  permissions.allowed = false;
  render(<LocalResearchSetup workspaceId="workspace" onPrepared={vi.fn()} />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("does not expose backend diagnostics", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(Response.json({ detail: "SECRET" }, { status: 403 })),
  );
  render(<LocalResearchSetup workspaceId="workspace" onPrepared={vi.fn()} />);
  fireEvent.click(screen.getByRole("button"));
  expect(await screen.findByRole("alert")).not.toHaveTextContent("SECRET");
});
