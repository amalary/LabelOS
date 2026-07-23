import { beforeEach, describe, expect, it, vi } from "vitest";

const tokenHelpers = vi.hoisted(() => ({
  AccessTokenError: class AccessTokenError extends Error {
    constructor(
      readonly code: "missing_session" | "expired_access_token",
      message: string,
    ) {
      super(message);
      this.name = "AccessTokenError";
    }
  },
  refreshAccessTokenForApi: vi.fn(),
  requireAccessTokenForApi: vi.fn(),
}));

vi.mock("./auth-token.server", () => {
  return {
    AccessTokenError: tokenHelpers.AccessTokenError,
    refreshAccessTokenForApi: tokenHelpers.refreshAccessTokenForApi,
    requireAccessTokenForApi: tokenHelpers.requireAccessTokenForApi,
  };
});

describe("authenticated backend API client", () => {
  beforeEach(() => {
    tokenHelpers.refreshAccessTokenForApi.mockReset();
    tokenHelpers.requireAccessTokenForApi.mockReset();
    vi.stubEnv("API_BASE_URL", "https://api.labelos.test");
    vi.stubGlobal("fetch", vi.fn());
  });

  it("adds the WorkOS access token as a bearer Authorization header", async () => {
    const { apiFetch } = await import("./api-client");
    tokenHelpers.requireAccessTokenForApi.mockResolvedValue("server_access_token");
    vi.mocked(fetch).mockResolvedValue(new Response("{}", { status: 200 }));

    await apiFetch("/api/v1/me");

    expect(fetch).toHaveBeenCalledWith(
      new URL("https://api.labelos.test/api/v1/me"),
      expect.objectContaining({
        cache: "no-store",
        headers: expect.any(Headers),
      }),
    );
    const headers = vi.mocked(fetch).mock.calls[0]?.[1]?.headers;
    expect(headers).toBeInstanceOf(Headers);
    expect((headers as Headers).get("Authorization")).toBe("Bearer server_access_token");
  });

  it("fetches the current backend user identity through the secure API client", async () => {
    const { getCurrentApiUser } = await import("./api-client");
    tokenHelpers.requireAccessTokenForApi.mockResolvedValue("server_access_token");
    vi.mocked(fetch).mockResolvedValue(
      Response.json({
        workos_user_id: "user_01TEST",
        organization_id: "org_01TEST",
        role: "admin",
        permissions: ["artists:read"],
      }),
    );

    await expect(getCurrentApiUser()).resolves.toEqual({
      workos_user_id: "user_01TEST",
      organization_id: "org_01TEST",
      role: "admin",
      permissions: ["artists:read"],
    });

    expect(fetch).toHaveBeenCalledWith(
      new URL("https://api.labelos.test/api/v1/me"),
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    );
  });

  it("surfaces missing WorkOS sessions as API client auth errors", async () => {
    const { apiFetch } = await import("./api-client");
    tokenHelpers.requireAccessTokenForApi.mockRejectedValue(
      new tokenHelpers.AccessTokenError(
        "missing_session",
        "A signed-in WorkOS session is required.",
      ),
    );

    await expect(apiFetch("/api/v1/me")).rejects.toMatchObject({
      code: "missing_session",
      name: "ApiClientError",
    });
  });

  it("refreshes the server-side WorkOS session once after a backend 401", async () => {
    const { apiFetch } = await import("./api-client");
    tokenHelpers.requireAccessTokenForApi.mockResolvedValue("expired_access_token");
    tokenHelpers.refreshAccessTokenForApi.mockResolvedValue("fresh_access_token");
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response("unauthorized", { status: 401 }))
      .mockResolvedValueOnce(new Response("{}", { status: 200 }));

    const response = await apiFetch("/api/v1/me");

    expect(response.status).toBe(200);
    expect(tokenHelpers.refreshAccessTokenForApi).toHaveBeenCalledTimes(1);
    const retryHeaders = vi.mocked(fetch).mock.calls[1]?.[1]?.headers;
    expect((retryHeaders as Headers).get("Authorization")).toBe("Bearer fresh_access_token");
  });

  it("throws unauthorized when the backend still returns 401 after refresh", async () => {
    const { apiFetch } = await import("./api-client");
    tokenHelpers.requireAccessTokenForApi.mockResolvedValue("expired_access_token");
    tokenHelpers.refreshAccessTokenForApi.mockResolvedValue("fresh_access_token");
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response("unauthorized", { status: 401 }))
      .mockResolvedValueOnce(new Response("unauthorized", { status: 401 }));

    await expect(apiFetch("/api/v1/me")).rejects.toMatchObject({
      code: "unauthorized",
      name: "ApiClientError",
      status: 401,
    });
  });

  it("throws forbidden when the backend returns 403", async () => {
    const { apiFetch } = await import("./api-client");
    tokenHelpers.requireAccessTokenForApi.mockResolvedValue("server_access_token");
    vi.mocked(fetch).mockResolvedValue(new Response("forbidden", { status: 403 }));

    await expect(apiFetch("/api/v1/admin")).rejects.toMatchObject({
      code: "forbidden",
      name: "ApiClientError",
      status: 403,
    });
  });

  it("throws network failures without logging or leaking the token", async () => {
    const { apiFetch } = await import("./api-client");
    tokenHelpers.requireAccessTokenForApi.mockResolvedValue("server_access_token");
    vi.mocked(fetch).mockRejectedValue(new TypeError("fetch failed"));

    await expect(apiFetch("/api/v1/me")).rejects.toMatchObject({
      code: "network_failure",
      name: "ApiClientError",
    });
  });
});
