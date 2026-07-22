import { getSignInUrl } from "@workos-inc/authkit-nextjs";
import { redirect } from "next/navigation";
import { NextRequest } from "next/server";

import { safeAppPath } from "../../../../lib/auth-redirects";
import { validateWebServerEnv } from "../../../../lib/env";

export async function GET(request: NextRequest) {
  validateWebServerEnv();

  const returnTo = safeAppPath(
    request.nextUrl.searchParams.get("next"),
    "/dashboard",
    request.nextUrl.origin,
  );
  const signInUrl = await getSignInUrl({ returnTo });
  redirect(signInUrl);
}
