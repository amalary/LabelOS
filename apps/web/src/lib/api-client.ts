import "server-only";

import { requireAccessTokenForApi } from "./auth";
import { validateWebServerEnv } from "./env";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";

type ApiFetchInit = Omit<RequestInit, "headers"> & {
  headers?: HeadersInit;
};

export async function apiFetch(path: string, init: ApiFetchInit = {}): Promise<Response> {
  validateWebServerEnv();

  const accessToken = await requireAccessTokenForApi();
  const url = new URL(path, apiBaseUrl);
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${accessToken}`);

  return fetch(url, {
    ...init,
    cache: "no-store",
    headers,
  });
}
