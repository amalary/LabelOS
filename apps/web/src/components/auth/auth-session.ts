import "server-only";

import { withAuth } from "@workos-inc/authkit-nextjs";

import type { AuthUiState, AuthUser } from "./auth-types";

function readableRole(role?: string | null) {
  if (!role) {
    return "Member";
  }

  return role
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

export async function getNavigationAuthState(): Promise<AuthUiState> {
  const session = await withAuth();

  if (!session.user) {
    return {
      isAuthenticated: false,
      isLoading: false,
      user: null,
    };
  }

  const user: AuthUser = {
    email: session.user.email,
    firstName: session.user.firstName,
    imageUrl: session.user.profilePictureUrl,
    lastName: session.user.lastName,
    name: [session.user.firstName, session.user.lastName].filter(Boolean).join(" ") || null,
    organization: session.organizationId ?? null,
    role: readableRole(session.role),
    status: "online",
  };

  return {
    isAuthenticated: true,
    isLoading: false,
    user,
  };
}
