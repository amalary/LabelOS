import "server-only";

import { ApiClientError, apiFetch } from "./api-client";

export type OrganizationSummary = {
  id: string;
  name: string;
  slug: string;
  logoUrl?: string | null;
  logo_url?: string | null;
  role: "owner" | "admin" | "member" | "viewer";
  can_switch: boolean;
};

export type OrganizationMemberRole = "owner" | "admin" | "member" | "viewer";

export type OrganizationMember = {
  id: string;
  user_id: string;
  email: string;
  display_name: string | null;
  role: OrganizationMemberRole;
  status: string;
};

export type OrganizationInvitation = {
  id: string;
  email: string;
  role: Exclude<OrganizationMemberRole, "owner">;
  state: string;
  expires_at: string | null;
  created_at: string | null;
};

export type OrganizationSelection = {
  activeOrganization: OrganizationSummary | null;
  organizations: OrganizationSummary[];
};

export type OrganizationSettings = {
  organization: OrganizationSummary;
  members: OrganizationMember[];
  invitations: OrganizationInvitation[];
};

type OrganizationsListResponse = {
  organizations: OrganizationSummary[];
  limit: number;
  offset: number;
  total: number;
};

type OrganizationMembersListResponse = {
  members: OrganizationMember[];
  invitations: OrganizationInvitation[];
  limit: number;
  offset: number;
  total: number;
};

type OrganizationActivationResponse = {
  organization: OrganizationSummary;
  workos_organization_id: string;
};

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");

  const response = await apiFetch(path, {
    ...init,
    headers,
  });

  if (!response.ok) {
    throw new ApiClientError(
      "network_failure",
      "The backend returned an unexpected response.",
      response.status,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export async function listOrganizations(): Promise<OrganizationSummary[]> {
  const response = await apiJson<OrganizationsListResponse>("/api/v1/organizations?limit=100");
  return response.organizations;
}

export async function getActiveOrganization(): Promise<OrganizationSummary | null> {
  try {
    return await apiJson<OrganizationSummary>("/api/v1/organizations/current");
  } catch (error) {
    if (error instanceof ApiClientError && (error.status === 403 || error.status === 404)) {
      return null;
    }
    throw error;
  }
}

export async function getOrganizationSelection(): Promise<OrganizationSelection> {
  const [organizations, activeOrganization] = await Promise.all([
    listOrganizations(),
    getActiveOrganization(),
  ]);

  return {
    activeOrganization,
    organizations,
  };
}

export async function verifyOrganizationActivation(
  organizationId: string,
): Promise<OrganizationActivationResponse> {
  return apiJson<OrganizationActivationResponse>(`/api/v1/organizations/${organizationId}/activate`, {
    method: "POST",
  });
}

export async function listOrganizationMembers(
  organizationId: string,
): Promise<OrganizationMembersListResponse> {
  const response = await apiJson<OrganizationMembersListResponse>(
    `/api/v1/organizations/${organizationId}/members?limit=100`,
  );
  return response;
}

export async function getOrganizationSettings(): Promise<OrganizationSettings | null> {
  const organization = await getActiveOrganization();
  if (organization === null) {
    return null;
  }

  return {
    organization,
    ...(await listOrganizationMembers(organization.id)),
  };
}

export async function inviteOrganizationMember(
  organizationId: string,
  payload: { email: string; role: Exclude<OrganizationMemberRole, "owner"> },
): Promise<OrganizationInvitation> {
  return apiJson<OrganizationInvitation>(`/api/v1/organizations/${organizationId}/invitations`, {
    method: "POST",
    body: JSON.stringify(payload),
    headers: {
      "Content-Type": "application/json",
    },
  });
}

export async function updateOrganization(
  organizationId: string,
  payload: { name: string; slug: string },
): Promise<OrganizationSummary> {
  return apiJson<OrganizationSummary>(`/api/v1/organizations/${organizationId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
    headers: {
      "Content-Type": "application/json",
    },
  });
}

export async function updateOrganizationMemberRole(
  organizationId: string,
  membershipId: string,
  role: Exclude<OrganizationMemberRole, "owner">,
): Promise<OrganizationMember> {
  return apiJson<OrganizationMember>(
    `/api/v1/organizations/${organizationId}/members/${membershipId}`,
    {
      method: "PATCH",
      body: JSON.stringify({ role }),
      headers: {
        "Content-Type": "application/json",
      },
    },
  );
}

export async function removeOrganizationMember(
  organizationId: string,
  membershipId: string,
): Promise<void> {
  await apiJson<Record<string, never>>(
    `/api/v1/organizations/${organizationId}/members/${membershipId}`,
    {
      method: "DELETE",
    },
  );
}
