import "server-only";

import { refreshSession, withAuth } from "@workos-inc/authkit-nextjs";

export type AccessTokenFailureCode = "missing_session" | "expired_access_token";

export class AccessTokenError extends Error {
  constructor(
    readonly code: AccessTokenFailureCode,
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "AccessTokenError";
  }
}

function isTokenRefreshFailure(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false;
  }

  return error.name === "TokenRefreshError" || error.message.toLowerCase().includes("refresh");
}

function toAccessTokenError(error: unknown): AccessTokenError {
  if (error instanceof AccessTokenError) {
    return error;
  }

  if (isTokenRefreshFailure(error)) {
    return new AccessTokenError("expired_access_token", "The WorkOS access token expired.", {
      cause: error,
    });
  }

  return new AccessTokenError("missing_session", "A signed-in WorkOS session is required.", {
    cause: error,
  });
}

export async function getAccessTokenForApi(): Promise<string | undefined> {
  try {
    const session = await withAuth();
    return session.accessToken;
  } catch (error) {
    if (isTokenRefreshFailure(error)) {
      throw toAccessTokenError(error);
    }
    return undefined;
  }
}

export async function requireAccessTokenForApi(): Promise<string> {
  try {
    const session = await withAuth();

    if (!session.user || !session.accessToken) {
      throw new AccessTokenError("missing_session", "A signed-in WorkOS session is required.");
    }

    return session.accessToken;
  } catch (error) {
    throw toAccessTokenError(error);
  }
}

export async function refreshAccessTokenForApi(): Promise<string> {
  try {
    const session = await refreshSession();

    if (!session.user || !session.accessToken) {
      throw new AccessTokenError(
        "expired_access_token",
        "The WorkOS access token could not refresh.",
      );
    }

    return session.accessToken;
  } catch (error) {
    throw toAccessTokenError(error);
  }
}
