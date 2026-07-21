import { NextResponse } from "next/server";

import {
  AUTH_STATE_COOKIE,
  PKCE_VERIFIER_COOKIE,
  createAuthState,
  createPkceChallenge,
  createPkceVerifier,
  getAuthConfig,
} from "../../../../lib/auth";

const isProduction = process.env.NODE_ENV === "production";

export function GET() {
  const config = getAuthConfig();
  if (config === null) {
    return NextResponse.json(
      { detail: "Authentication provider is not configured" },
      { status: 503 },
    );
  }

  const state = createAuthState();
  const verifier = createPkceVerifier();
  const authorizationUrl = new URL(config.authorizationUrl);
  authorizationUrl.searchParams.set("response_type", "code");
  authorizationUrl.searchParams.set("client_id", config.clientId);
  authorizationUrl.searchParams.set("redirect_uri", config.callbackUrl);
  authorizationUrl.searchParams.set("scope", config.scope);
  authorizationUrl.searchParams.set("state", state);
  authorizationUrl.searchParams.set("code_challenge", createPkceChallenge(verifier));
  authorizationUrl.searchParams.set("code_challenge_method", "S256");
  if (config.audience) {
    authorizationUrl.searchParams.set("audience", config.audience);
  }

  const response = NextResponse.redirect(authorizationUrl);
  response.cookies.set(AUTH_STATE_COOKIE, state, {
    httpOnly: true,
    maxAge: 10 * 60,
    path: "/",
    sameSite: "lax",
    secure: isProduction,
  });
  response.cookies.set(PKCE_VERIFIER_COOKIE, verifier, {
    httpOnly: true,
    maxAge: 10 * 60,
    path: "/",
    sameSite: "lax",
    secure: isProduction,
  });
  return response;
}
