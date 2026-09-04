import { beforeEach, describe, expect, it, vi } from "vitest";

import { GET as listCampaignCalendar } from "./[workspaceId]/campaign-calendar/route";
import { ApiClientError, apiFetch } from "../../../lib/api-client";

vi.mock("../../../lib/api-client", () => ({
  ApiClientError: class ApiClientError extends Error {
    constructor(
      readonly code = "network_failure",
      message: string,
      readonly status = 502,
    ) {
      super(message);
      this.name = "ApiClientError";
    }
  },
  apiFetch: vi.fn(),
}));

const workspaceContext = { params: Promise.resolve({ workspaceId: "workspace_01" }) };

describe("campaign calendar proxy route", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiFetch).mockResolvedValue(Response.json({ ok: true }));
  });

  it("forwards campaign calendar requests with supported query parameters", async () => {
    await listCampaignCalendar(
      new Request(
        "http://localhost/api/workspaces/workspace_01/campaign-calendar?start=2026-09-01T00%3A00%3A00Z&end=2026-09-30T23%3A59%3A59Z&timezone=America%2FLos_Angeles&campaign_id=campaign_01&artist_id=artist_01&release_id=release_01&status=scheduled&event_types=campaign.start&event_types=marketing.content.scheduled&include_archived=false&include_published=true&limit=250&offset=25&ignored=true",
      ),
      workspaceContext,
    );

    expect(apiFetch).toHaveBeenCalledWith(
      "/api/v1/workspaces/workspace_01/campaign-calendar?start=2026-09-01T00%3A00%3A00Z&end=2026-09-30T23%3A59%3A59Z&timezone=America%2FLos_Angeles&campaign_id=campaign_01&artist_id=artist_01&release_id=release_01&status=scheduled&event_types=campaign.start&event_types=marketing.content.scheduled&include_archived=false&include_published=true&limit=250&offset=25",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("forwards upstream error responses through the shared proxy helper", async () => {
    vi.mocked(apiFetch).mockResolvedValue(
      Response.json({ detail: "Invalid campaign calendar timezone" }, { status: 400 }),
    );

    const response = await listCampaignCalendar(
      new Request(
        "http://localhost/api/workspaces/workspace_01/campaign-calendar?start=2026-09-01T00%3A00%3A00Z&end=2026-09-30T23%3A59%3A59Z&timezone=Not%2FAZone",
      ),
      workspaceContext,
    );

    await expect(response.json()).resolves.toEqual({
      detail: "Invalid campaign calendar timezone",
    });
    expect(response.status).toBe(400);
  });

  it("maps API client failures to JSON errors through the shared proxy helper", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiClientError("unauthorized", "No session", 401));

    const response = await listCampaignCalendar(
      new Request("http://localhost/api/workspaces/workspace_01/campaign-calendar"),
      workspaceContext,
    );

    await expect(response.json()).resolves.toEqual({
      detail: "No session",
      code: "unauthorized",
    });
    expect(response.status).toBe(401);
  });
});
