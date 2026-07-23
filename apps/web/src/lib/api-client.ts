import "server-only";

import {
  AccessTokenError,
  refreshAccessTokenForApi,
  requireAccessTokenForApi,
} from "./auth-token.server";
import { validateWebServerEnv } from "./env";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";

export type CurrentApiUser = {
  workos_user_id: string;
  organization_id: string | null;
  role: string | null;
  permissions: string[];
};

type ApiFetchInit = Omit<RequestInit, "headers"> & {
  headers?: HeadersInit;
  retryOnUnauthorized?: boolean;
};

type BackendFetchInit = Omit<ApiFetchInit, "retryOnUnauthorized">;

export type ApiClientErrorCode =
  "missing_session" | "expired_access_token" | "unauthorized" | "forbidden" | "network_failure";

export class ApiClientError extends Error {
  constructor(
    readonly code: ApiClientErrorCode,
    message: string,
    readonly status?: number,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "ApiClientError";
  }
}

function toApiAuthError(error: unknown): ApiClientError {
  if (error instanceof ApiClientError) {
    return error;
  }

  if (error instanceof AccessTokenError) {
    return new ApiClientError(error.code, error.message, undefined, { cause: error });
  }

  return new ApiClientError(
    "missing_session",
    "A signed-in WorkOS session is required.",
    undefined,
    {
      cause: error,
    },
  );
}

function isNetworkError(error: unknown): boolean {
  return error instanceof TypeError;
}

async function fetchWithToken(
  url: URL,
  init: BackendFetchInit,
  accessToken: string,
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${accessToken}`);

  try {
    return await fetch(url, {
      ...init,
      cache: "no-store",
      headers,
    });
  } catch (error) {
    if (isNetworkError(error)) {
      throw new ApiClientError("network_failure", "Unable to reach the backend API.", undefined, {
        cause: error,
      });
    }

    throw error;
  }
}

async function assertAuthorizedResponse(response: Response): Promise<Response> {
  if (response.status === 401) {
    throw new ApiClientError("unauthorized", "The backend rejected the WorkOS access token.", 401);
  }

  if (response.status === 403) {
    throw new ApiClientError(
      "forbidden",
      "The authenticated user is not allowed to access this resource.",
      403,
    );
  }

  return response;
}

export async function apiFetch(path: string, init: ApiFetchInit = {}): Promise<Response> {
  validateWebServerEnv();

  const { retryOnUnauthorized = true, ...fetchInit } = init;
  const url = new URL(path, apiBaseUrl);

  let accessToken: string;
  try {
    accessToken = await requireAccessTokenForApi();
  } catch (error) {
    throw toApiAuthError(error);
  }

  const response = await fetchWithToken(url, fetchInit, accessToken);

  if (response.status !== 401 || !retryOnUnauthorized) {
    return assertAuthorizedResponse(response);
  }

  let refreshedAccessToken: string;
  try {
    refreshedAccessToken = await refreshAccessTokenForApi();
  } catch (error) {
    throw toApiAuthError(error);
  }

  return assertAuthorizedResponse(await fetchWithToken(url, fetchInit, refreshedAccessToken));
}

export async function getCurrentApiUser(): Promise<CurrentApiUser> {
  const response = await apiFetch("/api/v1/me", {
    headers: {
      Accept: "application/json",
    },
  });

  if (!response.ok) {
    throw new ApiClientError(
      "network_failure",
      "The backend returned an unexpected response.",
      response.status,
    );
  }

  return (await response.json()) as CurrentApiUser;
}
