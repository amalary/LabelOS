import { beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "../../../lib/api-client";
import { GET as list } from "./[workspaceId]/publications/route";
import { POST as retry } from "./[workspaceId]/publications/[publicationId]/recover/route";
import { POST as start } from "./[workspaceId]/publications/[publicationId]/manual/start/route";
import { POST as complete } from "./[workspaceId]/publications/[publicationId]/manual/complete/route";
import { GET as asset } from "./[workspaceId]/publications/[publicationId]/assets/[sha256]/route";
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

it.each([
  ["recover", retry],
  ["manual/start", start],
  ["manual/complete", complete],
] as const)(
  "forwards %s versions and idempotency with server authentication",
  async (suffix, handler) => {
    const body = {
      expected_version: 2,
      expected_action_version: 1,
      ...(suffix === "manual/complete"
        ? {
            delivery_confirmed: true,
            external_post_id: "post",
            provider_url: "https://example.com/post",
          }
        : {}),
    };
    const response = await handler(
      new Request("http://localhost", {
        method: "POST",
        headers: { "Idempotency-Key": "operation", Authorization: "untrusted" },
        body: JSON.stringify(body),
      }),
      context,
    );
    expect(apiFetch).toHaveBeenCalledWith(
      `/api/v1/workspaces/workspace/publications/publication/${suffix}`,
      {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "Idempotency-Key": "operation",
        },
        body: JSON.stringify(body),
      },
    );
    expect(response.headers.get("cache-control")).toBe("no-store");
  },
);

it.each([401, 403, 404, 409, 422, 503])("sanitizes recovery error %s", async (status) => {
  vi.mocked(apiFetch).mockResolvedValue(
    Response.json({ detail: "Bearer private" }, { status, headers: { Authorization: "private" } }),
  );
  const response = await retry(
    new Request("http://localhost", { method: "POST", body: "{}" }),
    context,
  );
  expect(response.status).toBe(status);
  expect(await response.text()).not.toContain("private");
  expect(response.headers.get("authorization")).toBeNull();
});

it("rejects malformed command JSON without forwarding", async () => {
  const response = await retry(
    new Request("http://localhost", { method: "POST", body: "{" }),
    context,
  );
  expect(response.status).toBe(400);
  expect(apiFetch).not.toHaveBeenCalled();
});

it("downloads authorized prepared bytes with safe attachment headers", async () => {
  vi.mocked(apiFetch).mockResolvedValue(
    new Response("prepared bytes", {
      headers: { Authorization: "private", "Content-Type": "text/html" },
    }),
  );
  const digest = "a".repeat(64);
  const response = await asset(new Request("http://localhost"), {
    params: Promise.resolve({
      workspaceId: "workspace",
      publicationId: "publication",
      sha256: digest,
    }),
  });
  expect(apiFetch).toHaveBeenCalledWith(
    `/api/v1/workspaces/workspace/publications/publication/assets/${digest}`,
  );
  expect(await response.text()).toBe("prepared bytes");
  expect(response.headers.get("content-type")).toBe("application/octet-stream");
  expect(response.headers.get("content-disposition")).toContain(digest);
  expect(response.headers.get("authorization")).toBeNull();
  expect(response.headers.get("cache-control")).toBe("private, no-store");
});
