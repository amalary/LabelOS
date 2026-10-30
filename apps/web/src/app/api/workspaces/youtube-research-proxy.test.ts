import { describe, expect, it, vi } from "vitest";
import { POST } from "./[workspaceId]/research/youtube/runs/[runId]/[operation]/route";
import { apiFetch } from "../../../lib/api-client";

vi.mock("../../../lib/api-client", () => ({
  apiFetch: vi.fn(),
  ApiClientError: class extends Error {},
}));
const context = (operation = "search") => ({
  params: Promise.resolve({
    workspaceId: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    runId: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    operation,
  }),
});
const request = () =>
  new Request("https://app.test/research", {
    method: "POST",
    body: JSON.stringify({ query: "Public" }),
  });

describe("YouTube proxy", () => {
  it("preserves cooldown without reflecting upstream diagnostics", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(
      Response.json(
        { detail: { code: "quota_exceeded", message: "SECRET" } },
        { status: 429, headers: { "Retry-After": "45" } },
      ),
    );
    const response = await POST(request(), context());
    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("45");
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.json()).toEqual({ detail: { code: "quota_exceeded" } });
  });
  it("rejects arbitrary operations", async () => {
    vi.mocked(apiFetch).mockClear();
    expect((await POST(request(), context("../../secrets"))).status).toBe(404);
    expect(apiFetch).not.toHaveBeenCalled();
  });
  it("does not expose unknown failure codes", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(
      Response.json({ detail: { code: "SECRET" } }, { status: 503 }),
    );
    const response = await POST(request(), context());
    expect(await response.json()).toEqual({ detail: { code: "error" } });
  });
});
