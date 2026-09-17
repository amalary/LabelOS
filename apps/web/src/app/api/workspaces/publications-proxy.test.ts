import { beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "../../../lib/api-client";
import { GET as list } from "./[workspaceId]/publications/route";
import { GET as detail } from "./[workspaceId]/publications/[publicationId]/route";

vi.mock("../../../lib/api-client", () => ({
  ApiClientError: class ApiClientError extends Error {},
  apiFetch: vi.fn(),
}));
const context = {
  params: Promise.resolve({ workspaceId: "workspace", publicationId: "publication" }),
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiFetch).mockResolvedValue(Response.json({ publications: [], next_after_id: null }));
});

it("forwards content scope and pagination but no arbitrary query fields", async () => {
  const response = await list(
    new Request(
      "http://localhost?content_item_id=content&limit=25&after_id=cursor&access_token=private",
    ),
    context,
  );
  expect(apiFetch).toHaveBeenCalledWith(
    "/api/v1/workspaces/workspace/publications?content_item_id=content&limit=25&after_id=cursor",
    { headers: { Accept: "application/json" } },
  );
  expect(response.headers.get("cache-control")).toBe("no-store");
});

it("forwards publication detail with server-side authentication", async () => {
  await detail(new Request("http://localhost"), context);
  expect(apiFetch).toHaveBeenCalledWith("/api/v1/workspaces/workspace/publications/publication", {
    headers: { Accept: "application/json" },
  });
});

it.each([401, 403, 404, 422, 500, 503])(
  "suppresses unsafe upstream error bodies for %s",
  async (status) => {
    vi.mocked(apiFetch).mockResolvedValue(
      Response.json(
        { detail: "Authorization: Bearer private", credentials: "secret" },
        { status, headers: { Authorization: "private" } },
      ),
    );
    const response = await detail(new Request("http://localhost"), context);
    expect(response.status).toBe(status);
    expect(response.headers.get("authorization")).toBeNull();
    expect(await response.json()).toEqual({ detail: "Publication history unavailable" });
  },
);

it("suppresses network exception text", async () => {
  vi.mocked(apiFetch).mockRejectedValue(new Error("private provider response"));
  const response = await list(new Request("http://localhost"), context);
  expect(response.status).toBe(502);
  expect(await response.text()).not.toContain("private");
});
