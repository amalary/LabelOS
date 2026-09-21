import { beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "../../../lib/api-client";
import { POST } from "./[workspaceId]/marketing-content/[contentId]/assets/route";

vi.mock("../../../lib/api-client", () => ({
  ApiClientError: class extends Error {},
  apiFetch: vi.fn(),
}));
const context = { params: Promise.resolve({ workspaceId: "workspace", contentId: "content" }) };
beforeEach(() => vi.clearAllMocks());

it("forwards exact media bytes through server authentication", async () => {
  const ref = { sha256: "a".repeat(64), size_bytes: 3, media_type: "video/mp4" };
  vi.mocked(apiFetch).mockResolvedValue(Response.json(ref));
  const response = await POST(
    new Request("http://localhost", {
      method: "POST",
      headers: { "Content-Type": "video/mp4" },
      body: new Uint8Array([0, 255, 4]),
    }),
    context,
  );
  expect(await response.json()).toEqual(ref);
  expect(apiFetch).toHaveBeenCalledWith(
    "/api/v1/workspaces/workspace/marketing-content/content/assets",
    { method: "POST", headers: { "Content-Type": "video/mp4" }, body: new Uint8Array([0, 255, 4]) },
  );
  expect(response.headers.get("cache-control")).toBe("no-store");
});

it.each(["text/html", "application/json"])("rejects %s uploads", async (type) => {
  expect(
    (
      await POST(
        new Request("http://localhost", {
          method: "POST",
          headers: { "Content-Type": type },
          body: "unsafe",
        }),
        context,
      )
    ).status,
  ).toBe(415);
  expect(apiFetch).not.toHaveBeenCalled();
});

it("enforces the byte limit even when content-length lies", async () => {
  const response = await POST(
    new Request("http://localhost", {
      method: "POST",
      headers: { "Content-Type": "video/mp4", "Content-Length": "1" },
      body: new Uint8Array(16 * 1024 * 1024 + 1),
    }),
    context,
  );
  expect(response.status).toBe(413);
  expect(apiFetch).not.toHaveBeenCalled();
});

it("suppresses upstream errors", async () => {
  vi.mocked(apiFetch).mockResolvedValue(
    Response.json({ detail: "private diagnostic" }, { status: 403 }),
  );
  const response = await POST(
    new Request("http://localhost", {
      method: "POST",
      headers: { "Content-Type": "video/mp4" },
      body: "video",
    }),
    context,
  );
  expect(response.status).toBe(403);
  expect(await response.text()).not.toContain("private");
});
