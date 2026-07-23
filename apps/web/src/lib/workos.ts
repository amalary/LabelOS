import "server-only";

import { WorkOS } from "@workos-inc/node";

import { validateWebServerEnv } from "./env";

let workosClient: WorkOS | null = null;

export function getWorkOSClient(): WorkOS {
  validateWebServerEnv();

  if (!workosClient) {
    workosClient = new WorkOS(process.env.WORKOS_API_KEY);
  }

  return workosClient;
}
