import { createHash, randomBytes } from "node:crypto";

import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { ACCESS_TOKEN_COOKIE, AUTH_STATE_COOKIE, PKCE_VERIFIER_COOKIE } from "./auth-cookies";

export { ACCESS_TOKEN_COOKIE, AUTH_STATE_COOKIE, PKCE_VERIFIER_COOKIE };

const isProduction = process.env.NODE_ENV === "production";

export type AuthConfig = {
  authorizationUrl: string;
  tokenUrl: string;
  clientId: string;
  clientSecret: string;
  callbackUrl: string;
  audience?: string;
  scope: string;
};

export function getAuthConfig(): AuthConfig | null {
  const authorizationUrl = process.env.AUTH_AUTHORIZATION_URL;
  const tokenUrl = process.env.AUTH_TOKEN_URL;
  const clientId = process.env.AUTH_CLIENT_ID;
  const clientSecret = process.env.AUTH_CLIENT_SECRET;
  const webBaseUrl = process.env.WEB_BASE_URL ?? "http://localhost:3000";

  if (!authorizationUrl || !tokenUrl || !clientId || !clientSecret) {
    return null;
  }

  return {
    authorizationUrl,
    tokenUrl,
    clientId,
    clientSecret,
    callbackUrl:
      process.env.AUTH_CALLBACK_URL ?? `${webBaseUrl.replace(/\/$/, "")}/api/auth/callback`,
    audience: process.env.AUTH_AUDIENCE,
    scope: process.env.AUTH_SCOPE ?? "openid email profile",
  };
}

export function createAuthState(): string {
  return randomBytes(32).toString("base64url");
}

export function createPkceVerifier(): string {
  return randomBytes(64).toString("base64url");
}

export function createPkceChallenge(verifier: string): string {
  return createHash("sha256").update(verifier).digest("base64url");
}

export function applyAuthCookies(
  response: NextResponse,
  accessToken: string,
  expiresIn: number,
): void {
  response.cookies.set(ACCESS_TOKEN_COOKIE, accessToken, {
    httpOnly: true,
    maxAge: Math.max(60, Math.min(expiresIn, 60 * 60)),
    path: "/",
    sameSite: "lax",
    secure: isProduction,
  });
  response.cookies.delete(AUTH_STATE_COOKIE);
  response.cookies.delete(PKCE_VERIFIER_COOKIE);
}

export async function getAccessTokenFromCookie(): Promise<string | undefined> {
  return (await cookies()).get(ACCESS_TOKEN_COOKIE)?.value;
}
