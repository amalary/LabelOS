import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, apiFetch } from "../../../lib/api-client";
import { GET as globalOauthCallback } from "../social-account-connections/oauth/[provider]/callback/route";
import { GET as oauthCallback } from "./[workspaceId]/social-account-connections/oauth/[provider]/callback/route";
import { POST as oauthStart } from "./[workspaceId]/social-account-connections/oauth/start/route";
import { POST as checkHealth } from "./[workspaceId]/social-account-connections/[connectionId]/health/route";
import { POST as syncMetadata } from "./[workspaceId]/social-account-connections/[connectionId]/sync/route";

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
const connectionContext = {
  params: Promise.resolve({ workspaceId: "workspace_01", connectionId: "connection_01" }),
};
const callbackContext = {
  params: Promise.resolve({ workspaceId: "workspace_01", provider: "youtube" }),
};
const globalCallbackContext = {
  params: Promise.resolve({ provider: "youtube" }),
};

describe("social account connections proxy routes", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiFetch).mockResolvedValue(Response.json({ ok: true }));
  });

  it("forwards OAuth start requests through the backend workspace route", async () => {
    await oauthStart(
      new Request(
        "http://localhost/api/workspaces/workspace_01/social-account-connections/oauth/start",
        {
          method: "POST",
          body: JSON.stringify({ provider: "youtube", redirect_uri: "https://app.test/callback" }),
          headers: { "Content-Type": "application/json" },
        },
      ),
      workspaceContext,
    );

    expect(apiFetch).toHaveBeenCalledWith(
      "/api/v1/workspaces/workspace_01/social-account-connections/oauth/start",
      expect.objectContaining({
        body: expect.stringContaining('"provider":"youtube"'),
        method: "POST",
      }),
    );
  });

  it("preserves backend OAuth callback redirects", async () => {
    vi.mocked(apiFetch).mockResolvedValue(
      new Response(null, {
        status: 303,
        headers: { Location: "/workspace/settings?tab=connections&oauth=connected" },
      }),
    );

    const response = await oauthCallback(
      new Request(
        "https://app.labelos.test/api/workspaces/workspace_01/social-account-connections/oauth/youtube/callback?state=state_01&code=code_01",
      ),
      callbackContext,
    );

    expect(apiFetch).toHaveBeenCalledWith(
      "/api/v1/workspaces/workspace_01/social-account-connections/oauth/youtube/callback" +
        "?state=state_01&code=code_01&redirect_uri=https%3A%2F%2Fapp.labelos.test%2Fapi%2Fworkspaces%2Fworkspace_01%2Fsocial-account-connections%2Foauth%2Fyoutube%2Fcallback",
      expect.objectContaining({ redirect: "manual" }),
    );
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(
      "/workspace/settings?tab=connections&oauth=connected",
    );
  });

  it("forwards stable OAuth callback requests without a workspace path segment", async () => {
    vi.mocked(apiFetch).mockResolvedValue(
      new Response(null, {
        status: 303,
        headers: { Location: "/marketing?tab=accounts&oauth=connected" },
      }),
    );

    const response = await globalOauthCallback(
      new Request(
        "https://app.labelos.test/api/social-account-connections/oauth/youtube/callback?state=state_01&code=code_01",
      ),
      globalCallbackContext,
    );

    expect(apiFetch).toHaveBeenCalledWith(
      "/api/v1/social-account-connections/oauth/youtube/callback" +
        "?state=state_01&code=code_01&redirect_uri=https%3A%2F%2Fapp.labelos.test%2Fapi%2Fsocial-account-connections%2Foauth%2Fyoutube%2Fcallback",
      expect.objectContaining({ redirect: "manual" }),
    );
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("/marketing?tab=accounts&oauth=connected");
  });

  it("forwards health and sync lifecycle requests", async () => {
    await checkHealth(
      new Request("http://localhost/health", { method: "POST" }),
      connectionContext,
    );
    await syncMetadata(new Request("http://localhost/sync", { method: "POST" }), connectionContext);

    expect(apiFetch).toHaveBeenNthCalledWith(
      1,
      "/api/v1/workspaces/workspace_01/social-account-connections/connection_01/health",
      expect.objectContaining({ method: "POST" }),
    );
    expect(apiFetch).toHaveBeenNthCalledWith(
      2,
      "/api/v1/workspaces/workspace_01/social-account-connections/connection_01/sync",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("maps API client failures through the shared proxy helper", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiClientError("unauthorized", "No session", 401));

    const response = await checkHealth(
      new Request("http://localhost/health", { method: "POST" }),
      connectionContext,
    );

    await expect(response.json()).resolves.toEqual({
      detail: "No session",
      code: "unauthorized",
    });
    expect(response.status).toBe(401);
  });
});
