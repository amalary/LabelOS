import { authkitMiddleware } from "@workos-inc/authkit-nextjs";

import { PUBLIC_ROUTES } from "./lib/route-protection";

export default authkitMiddleware({
  redirectUri: process.env.WORKOS_REDIRECT_URI ?? process.env.NEXT_PUBLIC_WORKOS_REDIRECT_URI,
  middlewareAuth: {
    enabled: true,
    unauthenticatedPaths: [...PUBLIC_ROUTES],
  },
});

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|.*\\.(?:avif|css|gif|ico|jpg|jpeg|js|json|map|otf|png|svg|ttf|txt|webp|woff|woff2|xml)$).*)",
  ],
};
