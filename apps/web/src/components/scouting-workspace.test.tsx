import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ScoutingPanel } from "./scouting-workspace";

vi.mock("../lib/workspace-context", () => ({
  useActiveWorkspace: () => ({ activeWorkspace: { id: "workspace" } }),
}));
afterEach(() => vi.unstubAllGlobals());

it("reopens saved candidates after remount, edits notes/status, and filters", async () => {
  let record = {
    id: "candidate",
    label: "My candidate",
    notes: "First listen",
    status: "new",
    revision: 1,
    channel_id: null,
    source_expires_at: null,
  };
  const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith("/runs")) return Response.json([]);
    if (options?.method === "PATCH") {
      record = { ...record, ...JSON.parse(options.body as string), revision: record.revision + 1 };
      return Response.json(record);
    }
    if (url.endsWith("/candidate")) return Response.json(record);
    return Response.json(url.includes("status=passed") ? [] : [record]);
  });
  vi.stubGlobal("fetch", fetchMock);
  const first = render(<ScoutingPanel workspaceId="workspace" />);
  fireEvent.click(await screen.findByRole("button", { name: "My candidate" }));
  await screen.findByDisplayValue("First listen");
  fireEvent.change(screen.getByLabelText("Human notes"), {
    target: { value: "Invite to showcase" },
  });
  fireEvent.change(screen.getByLabelText("Review status"), { target: { value: "shortlisted" } });
  fireEvent.click(screen.getByRole("button", { name: "Save review" }));
  await screen.findByText("Review saved.");
  first.unmount();
  render(<ScoutingPanel workspaceId="workspace" />);
  fireEvent.click(await screen.findByRole("button", { name: "My candidate" }));
  await screen.findByDisplayValue("Invite to showcase");
  expect(screen.getByLabelText("Review status")).toHaveValue("shortlisted");
  fireEvent.change(screen.getByLabelText("Review filter"), { target: { value: "passed" } });
  await screen.findByText("No saved candidates match this filter.");
  expect(fetchMock.mock.calls.every(([, options]) => options?.cache === "no-store")).toBe(true);
});

it("shows denied access without leaking backend diagnostics", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(Response.json({ detail: "SECRET" }, { status: 403 })),
  );
  render(<ScoutingPanel workspaceId="workspace" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("You do not have scouting access");
  expect(screen.queryByText("SECRET")).not.toBeInTheDocument();
});

it("retains unsaved notes on an edit conflict", async () => {
  const record = {
    id: "candidate",
    label: "My candidate",
    notes: "",
    status: "new",
    revision: 1,
    channel_id: null,
    source_expires_at: null,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === "PATCH") return Response.json({}, { status: 409 });
      if (url.endsWith("/runs")) return Response.json([]);
      return Response.json(url.endsWith("/candidate") ? record : [record]);
    }),
  );
  render(<ScoutingPanel workspaceId="workspace" />);
  fireEvent.click(await screen.findByRole("button", { name: "My candidate" }));
  await screen.findByLabelText("Human notes");
  fireEvent.change(screen.getByLabelText("Human notes"), { target: { value: "Unsaved thoughts" } });
  fireEvent.click(screen.getByRole("button", { name: "Save review" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("candidate changed"));
  expect(screen.getByLabelText("Human notes")).toHaveValue("Unsaved thoughts");
});
