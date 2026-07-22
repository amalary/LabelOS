import { describe, expect, it } from "vitest";

import { authErrorRedirectUrl, safeAppPath, safeLogoutUrl } from "./auth-redirects";

describe("auth redirect validation", () => {
  it("allows same-origin paths with query strings", () => {
    expect(safeAppPath("/dashboard?tab=artists", "/dashboard", "https://app.test")).toBe(
      "/dashboard?tab=artists",
    );
  });

  it("normalizes same-origin absolute URLs to app paths", () => {
    expect(
      safeAppPath("https://app.test/dashboard#top", "/dashboard", "https://app.test"),
    ).toBe("/dashboard#top");
  });

  it("rejects external and protocol-relative URLs", () => {
    expect(safeAppPath("https://evil.test/phish", "/dashboard", "https://app.test")).toBe(
      "/dashboard",
    );
    expect(safeAppPath("//evil.test/phish", "/dashboard", "https://app.test")).toBe(
      "/dashboard",
    );
  });

  it("rejects redirect values with unsafe characters", () => {
    expect(safeAppPath("/\\evil.test", "/dashboard", "https://app.test")).toBe(
      "/dashboard",
    );
  });

  it("builds a same-origin absolute logout URL", () => {
    expect(safeLogoutUrl("https://app.test/api/auth/logout", "/login?from=logout")).toBe(
      "https://app.test/login?from=logout",
    );
  });

  it("uses a fixed safe callback error URL", () => {
    expect(authErrorRedirectUrl("https://app.test/api/auth/callback?code=secret").toString()).toBe(
      "https://app.test/login?auth_error=sign_in_failed",
    );
  });
});
