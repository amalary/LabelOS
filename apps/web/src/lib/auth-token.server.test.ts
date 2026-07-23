import { beforeEach, describe, expect, it, vi } from "vitest";

const authkit = vi.hoisted(() => ({
  refreshSession: vi.fn(),
  withAuth: vi.fn(),
}));

vi.mock("@workos-inc/authkit-nextjs", () => authkit);

describe("WorkOS API access-token helpers", () => {
  beforeEach(() => {
    authkit.refreshSession.mockReset();
    authkit.withAuth.mockReset();
  });

  it("returns the server-side WorkOS access token without exposing client storage", async () => {
    const { requireAccessTokenForApi } = await import("./auth-token.server");
    authkit.withAuth.mockResolvedValue({
      accessToken: "server_access_token",
      user: { id: "user_123" },
    });

    await expect(requireAccessTokenForApi()).resolves.toBe("server_access_token");
    expect(authkit.withAuth).toHaveBeenCalledWith();
  });

  it("reports a missing session when WorkOS does not return a signed-in user", async () => {
    const { requireAccessTokenForApi } = await import("./auth-token.server");
    authkit.withAuth.mockResolvedValue({ user: null });

    await expect(requireAccessTokenForApi()).rejects.toMatchObject({
      code: "missing_session",
      name: "AccessTokenError",
    });
  });

  it("reports an expired token when WorkOS session refresh fails", async () => {
    const { refreshAccessTokenForApi } = await import("./auth-token.server");
    const refreshError = new Error("refresh token expired");
    refreshError.name = "TokenRefreshError";
    authkit.refreshSession.mockRejectedValue(refreshError);

    await expect(refreshAccessTokenForApi()).rejects.toMatchObject({
      code: "expired_access_token",
      name: "AccessTokenError",
    });
  });
});
