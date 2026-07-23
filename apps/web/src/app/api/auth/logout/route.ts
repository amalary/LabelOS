import { signOut } from "@workos-inc/authkit-nextjs";
import { NextRequest } from "next/server";

import { safeLogoutUrl } from "../../../../lib/auth-redirects";
import { validateWebServerEnv } from "../../../../lib/env";

export async function POST(request: NextRequest) {
  validateWebServerEnv();
  const returnTo =
    request.nextUrl.searchParams.get("returnTo") ?? request.nextUrl.searchParams.get("next");
  await signOut({ returnTo: safeLogoutUrl(request.url, returnTo) });
}
