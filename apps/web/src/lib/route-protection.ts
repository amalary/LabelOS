export const PUBLIC_ROUTES = [
  "/",
  "/login",
  "/api/auth/login",
  "/api/auth/callback",
  "/privacy",
  "/terms",
  "/api/health",
] as const;

export const PROTECTED_APPLICATION_ROUTES = [
  "/dashboard",
  "/artists",
  "/releases",
  "/campaigns",
  "/analytics",
  "/royalties",
  "/contracts",
  "/agent-command-center",
  "/settings",
] as const;

export const ROUTE_PROTECTION_MATCHER = [
  "/((?!_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|.*\\.(?:avif|css|gif|ico|jpg|jpeg|js|json|map|otf|png|svg|ttf|txt|webp|woff|woff2|xml)$).*)",
] as const;
