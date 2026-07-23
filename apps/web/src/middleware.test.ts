import { describe, expect, it, vi } from "vitest";

type AuthkitMiddlewareOptions = {
  middlewareAuth?: {
    enabled: boolean;
    unauthenticatedPaths: string[];
  };
};

const authkitCapture = vi.hoisted(() => ({
  options: undefined as AuthkitMiddlewareOptions | undefined,
}));

vi.mock("@workos-inc/authkit-nextjs", () => ({
  authkitMiddleware: vi.fn((options: AuthkitMiddlewareOptions) => {
    authkitCapture.options = options;

    return (request: { headers: Headers; nextUrl: URL }) => {
      const publicPaths = options.middlewareAuth?.unauthenticatedPaths ?? [];
      const isPublicRoute = publicPaths.includes(request.nextUrl.pathname);
      const isAuthenticated = request.headers.get("x-test-authenticated") === "true";

      if (isPublicRoute || isAuthenticated) {
        return new Response(null, { status: 200 });
      }

      return Response.redirect("https://auth.workos.test/login", 307);
    };
  }),
}));

import middleware, { config } from "./middleware";
import {
  PROTECTED_APPLICATION_ROUTES,
  PUBLIC_ROUTES,
  ROUTE_PROTECTION_MATCHER,
} from "./lib/route-protection";

const runMiddleware = middleware as unknown as (
  request: ReturnType<typeof createRequest>,
) => Response;

function createRequest(pathname: string, authenticated = false) {
  return {
    headers: new Headers(authenticated ? { "x-test-authenticated": "true" } : undefined),
    nextUrl: new URL(`https://labelos.test${pathname}`),
  };
}

function matchesRouteProtection(pathname: string) {
  const [matcher] = config.matcher;
  return new RegExp(`^${matcher}$`).test(pathname);
}

describe("route protection middleware", () => {
  it("configures WorkOS middleware auth with the intentional public route list", () => {
    expect(authkitCapture.options?.middlewareAuth).toEqual({
      enabled: true,
      unauthenticatedPaths: [...PUBLIC_ROUTES],
    });
    expect(config.matcher).toEqual(ROUTE_PROTECTION_MATCHER);
  });

  it("allows public routes without an authenticated session", () => {
    for (const route of PUBLIC_ROUTES) {
      expect(runMiddleware(createRequest(route))).toHaveProperty("status", 200);
    }
  });

  it("redirects unauthenticated users away from protected application routes", () => {
    for (const route of PROTECTED_APPLICATION_ROUTES) {
      expect(runMiddleware(createRequest(route))).toHaveProperty("status", 307);
      expect(runMiddleware(createRequest(`${route}/nested`))).toHaveProperty("status", 307);
    }
  });

  it("does not match static assets, image optimization routes, or framework internals", () => {
    expect(matchesRouteProtection("/_next/static/chunks/app.js")).toBe(false);
    expect(matchesRouteProtection("/_next/image")).toBe(false);
    expect(matchesRouteProtection("/favicon.ico")).toBe(false);
    expect(matchesRouteProtection("/logo.svg")).toBe(false);
    expect(matchesRouteProtection("/dashboard")).toBe(true);
  });

  it("allows authenticated access to protected application routes", () => {
    for (const route of PROTECTED_APPLICATION_ROUTES) {
      expect(runMiddleware(createRequest(route, true))).toHaveProperty("status", 200);
    }
  });
});
