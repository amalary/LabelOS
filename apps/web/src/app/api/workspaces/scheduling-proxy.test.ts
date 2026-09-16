import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../../../lib/api-client";
import { GET as eligibility } from "./[workspaceId]/marketing-content/[contentId]/channels/[channelId]/scheduling/eligibility/route";
import { POST as activate } from "./[workspaceId]/marketing-content/[contentId]/channels/[channelId]/scheduling/activate/route";
import { GET as list } from "./[workspaceId]/scheduling/jobs/route";
import { GET as detail } from "./[workspaceId]/scheduling/jobs/[jobId]/route";
import { GET as blockedReasons } from "./[workspaceId]/scheduling/jobs/[jobId]/blocked-reasons/route";
import { POST as cancel } from "./[workspaceId]/scheduling/jobs/[jobId]/cancel/route";
import { POST as replace } from "./[workspaceId]/scheduling/jobs/[jobId]/replace/route";
import { POST as revalidate } from "./[workspaceId]/scheduling/jobs/[jobId]/revalidate/route";

vi.mock("../../../lib/api-client", () => ({
  ApiClientError: class ApiClientError extends Error {
    code = "unauthorized";
    status = 401;
  },
  apiFetch: vi.fn(),
}));
const context = {
  params: Promise.resolve({
    workspaceId: "workspace",
    contentId: "content",
    channelId: "channel",
    jobId: "job",
  }),
};
const key = "49a317d8-5353-451b-b907-032ac20865a1";

describe("scheduling web proxy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiFetch).mockResolvedValue(Response.json({ ok: true }));
  });
  it.each([
    [
      activate,
      "marketing-content/content/channels/channel/scheduling/activate",
      { expected_content_revision: 2, expected_schedule_generation: 3 },
    ],
    [cancel, "scheduling/jobs/job/cancel", {}],
    [
      replace,
      "scheduling/jobs/job/replace",
      { expected_content_revision: 3, expected_schedule_generation: 4 },
    ],
    [revalidate, "scheduling/jobs/job/revalidate", {}],
  ] as const)(
    "forwards command %s with its idempotency key and exact revision guards",
    async (handler, suffix, body) => {
      const request = new Request("http://localhost", {
        method: "POST",
        body: JSON.stringify(body),
        headers: { "Idempotency-Key": key },
      });
      const result = await handler(request, context);
      expect(apiFetch).toHaveBeenCalledWith(`/api/v1/workspaces/workspace/${suffix}`, {
        method: "POST",
        body: JSON.stringify(body),
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "Idempotency-Key": key,
        },
      });
      expect(result.headers.get("cache-control")).toBe("no-store");
    },
  );
  it.each([
    [eligibility, "marketing-content/content/channels/channel/scheduling/eligibility"],
    [detail, "scheduling/jobs/job"],
    [blockedReasons, "scheduling/jobs/job/blocked-reasons"],
  ] as const)("forwards inspection %s", async (handler, suffix) => {
    await handler(new Request("http://localhost"), context);
    expect(apiFetch).toHaveBeenCalledWith(`/api/v1/workspaces/workspace/${suffix}`, {
      headers: { Accept: "application/json" },
    });
  });
  it("preserves repeated statuses, channel filters, and pagination cursor", async () => {
    const query =
      "?status=pending&status=claimed&content_item_id=content&channel_id=channel&cursor=cursor";
    await list(new Request(`http://localhost${query}`), context);
    expect(apiFetch).toHaveBeenCalledWith(
      `/api/v1/workspaces/workspace/scheduling/jobs${query}`,
      expect.anything(),
    );
  });
  it.each([401, 403, 404, 409, 422, 503])(
    "preserves error status %s and structured reasons",
    async (status) => {
      const payload = { detail: { code: "scheduling_conflict", reason_codes: ["stale_approval"] } };
      vi.mocked(apiFetch).mockResolvedValue(Response.json(payload, { status }));
      const result = await activate(
        new Request("http://localhost", { method: "POST", body: "{}" }),
        context,
      );
      expect(result.status).toBe(status);
      expect(await result.json()).toEqual(payload);
    },
  );
  it("returns a recoverable proxy error when the backend cannot be reached", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new Error("offline"));
    expect((await list(new Request("http://localhost"), context)).status).toBe(502);
  });
});
