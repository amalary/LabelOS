import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const authkit = vi.hoisted(() => ({
  getSignInUrl: vi.fn(),
  handleAuth: vi.fn(),
  signOut: vi.fn(),
}));

const navigation = vi.hoisted(() => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  }),
}));

vi.mock("server-only", () => ({}));
vi.mock("@workos-inc/authkit-nextjs", () => authkit);
vi.mock("next/navigation", () => navigation);
vi.mock("../../../../lib/env", () => ({
  validateWebServerEnv: vi.fn(),
}));

function request(url: string) {
  return new NextRequest(url);
}

describe("WorkOS auth routes", () => {
  beforeEach(() => {
    vi.resetModules();
    authkit.getSignInUrl.mockReset();
    authkit.handleAuth.mockReset();
    authkit.signOut.mockReset();
    navigation.redirect.mockClear();
  });

  it("redirects login requests to the WorkOS-hosted sign-in URL with a safe return path", async () => {
    authkit.getSignInUrl.mockResolvedValue("https://auth.workos.test/sign-in");
    const { GET } = await import("./login/route");

    await expect(
      GET(request("https://app.test/api/auth/login?next=https://evil.test/phish")),
    ).rejects.toThrow("NEXT_REDIRECT:https://auth.workos.test/sign-in");

    expect(authkit.getSignInUrl).toHaveBeenCalledWith({ returnTo: "/dashboard" });
    expect(navigation.redirect).toHaveBeenCalledWith("https://auth.workos.test/sign-in");
  });

  it("configures callback handling with a safe success path and safe error redirect", async () => {
    authkit.handleAuth.mockImplementation(
      (options: { onError: (params: { request: NextRequest }) => Response }) => {
        return (callbackRequest: NextRequest) => options.onError({ request: callbackRequest });
      },
    );
    const { GET } = await import("./callback/route");

    const response = await GET(
      request("https://app.test/api/auth/callback?code=secret&state=sealed"),
    );

    expect(authkit.handleAuth).toHaveBeenCalledWith(
      expect.objectContaining({ returnPathname: "/dashboard" }),
    );
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(
      "https://app.test/login?auth_error=sign_in_failed",
    );
  });

  it("clears the WorkOS session and passes only a same-origin logout return URL", async () => {
    authkit.signOut.mockResolvedValue(undefined);
    const { POST } = await import("./logout/route");

    await POST(request("https://app.test/api/auth/logout?returnTo=//evil.test/phish"));

    expect(authkit.signOut).toHaveBeenCalledWith({
      returnTo: "https://app.test/login",
    });
  });
});
