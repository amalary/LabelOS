import { handleAuth } from "@workos-inc/authkit-nextjs";
import { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { authErrorRedirectUrl } from "../../../../lib/auth-redirects";
import { validateWebServerEnv } from "../../../../lib/env";

const handler = handleAuth({
  returnPathname: "/dashboard",
  onError: ({ request }) => NextResponse.redirect(authErrorRedirectUrl(request.url), 303),
});

export async function GET(request: NextRequest) {
  validateWebServerEnv();
  return handler(request);
}
