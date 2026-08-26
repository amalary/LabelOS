import "server-only";

import { ApiClientError, apiFetch } from "./api-client";
import type { UniversalProfile } from "./profiles.types";

async function profileApiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");

  const response = await apiFetch(path, {
    ...init,
    headers,
  });

  if (!response.ok) {
    throw new ApiClientError(
      "network_failure",
      "The backend returned an unexpected profile response.",
      response.status,
    );
  }

  return (await response.json()) as T;
}

export async function getCurrentUniversalProfile(): Promise<UniversalProfile> {
  return profileApiJson<UniversalProfile>("/api/v1/profiles/me");
}
