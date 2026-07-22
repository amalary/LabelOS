import "server-only";

import { withAuth } from "@workos-inc/authkit-nextjs";

export async function getAccessTokenForApi(): Promise<string | undefined> {
  const session = await withAuth();
  return session.accessToken;
}

export async function requireAccessTokenForApi(): Promise<string> {
  const session = await withAuth({ ensureSignedIn: true });
  return session.accessToken;
}
