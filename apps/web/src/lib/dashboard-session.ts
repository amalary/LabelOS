import "server-only";

import { withAuth } from "@workos-inc/authkit-nextjs";

export type DashboardUser = {
  firstName: string | null;
  lastName: string | null;
  email: string | null;
  profileImageUrl: string | null;
};

export type DashboardSession = {
  user: DashboardUser;
  organizationId: string | null;
};

export async function requireDashboardSession(): Promise<DashboardSession> {
  const session = await withAuth({ ensureSignedIn: true });

  return {
    organizationId: session.organizationId ?? null,
    user: {
      email: session.user.email ?? null,
      firstName: session.user.firstName ?? null,
      lastName: session.user.lastName ?? null,
      profileImageUrl: session.user.profilePictureUrl ?? null,
    },
  };
}
