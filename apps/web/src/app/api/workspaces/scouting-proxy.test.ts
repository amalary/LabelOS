import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET, POST, PATCH, DELETE } from "./[workspaceId]/scouting/[...path]/route";
import { apiFetch } from "../../../lib/api-client";

vi.mock("../../../lib/api-client", () => ({
  apiFetch: vi.fn(),
  ApiClientError: class extends Error {},
}));
const workspace = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const candidate = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";
const context = (path: string[]) => ({ params: Promise.resolve({ workspaceId: workspace, path }) });
beforeEach(() => vi.mocked(apiFetch).mockReset());
describe("Scouting proxy", () => {
  it("preserves save status and no-store headers", async () => {
    vi.mocked(apiFetch).mockResolvedValue(Response.json({ id: candidate }, { status: 201 }));
    const result = await POST(
      new Request("http://app.test/scouting", {
        method: "POST",
        body: JSON.stringify({ channel_id: "UCaaaaaaaaaaaaaaaaaaaaaa" }),
      }),
      context(["candidates"]),
    );
    expect(result.status).toBe(201);
    expect(result.headers.get("cache-control")).toBe("no-store");
    expect(await result.json()).toEqual({ id: candidate });
  });
  it("allows only known paths and methods", async () => {
    expect((await GET(new Request("http://app.test"), context(["..", "secrets"]))).status).toBe(
      404,
    );
    expect(
      (await PATCH(new Request("http://app.test", { method: "PATCH" }), context(["runs"]))).status,
    ).toBe(404);
    expect(apiFetch).not.toHaveBeenCalled();
  });
  it("sanitizes denial diagnostics and preserves conflicts", async () => {
    vi.mocked(apiFetch).mockResolvedValue(Response.json({ detail: "SECRET" }, { status: 409 }));
    const result = await PATCH(
      new Request("http://app.test", { method: "PATCH", body: "{}" }),
      context(["candidates", candidate]),
    );
    expect(result.status).toBe(409);
    expect(await result.text()).not.toContain("SECRET");
  });
  it("forwards deletion without an unexpected response body", async () => {
    vi.mocked(apiFetch).mockResolvedValue(new Response(null, { status: 204 }));
    expect(
      (
        await DELETE(
          new Request("http://app.test", { method: "DELETE" }),
          context(["candidates", candidate, "source"]),
        )
      ).status,
    ).toBe(204);
  });
});
