import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

import {
  ACCESS_TOKEN_COOKIE,
  AUTH_STATE_COOKIE,
  PKCE_VERIFIER_COOKIE,
  applyAuthCookies,
  getAuthConfig,
} from "../../../../lib/auth";

type TokenResponse = {
  access_token?: string;
  expires_in?: number;
};

export async function GET(request: NextRequest) {
  const config = getAuthConfig();
  if (config === null) {
    return NextResponse.json(
      { detail: "Authentication provider is not configured" },
      { status: 503 },
    );
  }

  const code = request.nextUrl.searchParams.get("code");
  const state = request.nextUrl.searchParams.get("state");
  const cookieStore = await cookies();
  const expectedState = cookieStore.get(AUTH_STATE_COOKIE)?.value;
  const verifier = cookieStore.get(PKCE_VERIFIER_COOKIE)?.value;

  if (!code || !state || !expectedState || state !== expectedState || !verifier) {
    const response = NextResponse.redirect(new URL("/login?error=auth", request.url));
    response.cookies.delete(ACCESS_TOKEN_COOKIE);
    return response;
  }

  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: config.clientId,
    client_secret: config.clientSecret,
    code,
    code_verifier: verifier,
    redirect_uri: config.callbackUrl,
  });

  const tokenResponse = await fetch(config.tokenUrl, {
    body,
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    method: "POST",
  });

  if (!tokenResponse.ok) {
    const response = NextResponse.redirect(new URL("/login?error=auth", request.url));
    response.cookies.delete(ACCESS_TOKEN_COOKIE);
    return response;
  }

  const tokenPayload = (await tokenResponse.json()) as TokenResponse;
  if (!tokenPayload.access_token) {
    const response = NextResponse.redirect(new URL("/login?error=auth", request.url));
    response.cookies.delete(ACCESS_TOKEN_COOKIE);
    return response;
  }

  const response = NextResponse.redirect(new URL("/dashboard", request.url));
  applyAuthCookies(response, tokenPayload.access_token, tokenPayload.expires_in ?? 3600);
  return response;
}
