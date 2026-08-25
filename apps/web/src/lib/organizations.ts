import "server-only";

import { ApiClientError, apiFetch } from "./api-client";

export type WorkspacePermission = "owner" | "admin" | "member" | "guest";

export type OrganizationSummary = {
  id: string;
  name: string;
  slug: string;
  logoUrl?: string | null;
  logo_url?: string | null;
  workspace_permission?: WorkspacePermission;
  role: WorkspacePermission;
  department_access?: string[];
  capability_permissions?: string[];
  can_switch: boolean;
};

export type OrganizationSelection = {
  activeOrganization: OrganizationSummary | null;
  organizations: OrganizationSummary[];
};

type OrganizationsListResponse = {
  organizations: OrganizationSummary[];
  limit: number;
  offset: number;
  total: number;
};

type OrganizationActivationResponse = {
  organization: OrganizationSummary;
  workos_organization_id: string;
};

export type WorkspaceInvite = {
  id: string;
  token: string;
  email: string | null;
  workspace: {
    id: string;
    name: string;
    slug: string;
  };
  inviter: {
    id: string;
    email: string;
    display_name: string | null;
  } | null;
  professional_roles: string[];
  proposed_department_access: string[];
  expiration: string;
  maximum_uses: number | null;
  use_count: number;
  status: string;
  join_path: string;
};

export type WorkspaceInviteAcceptResponse = {
  workspace: {
    id: string;
    name: string;
    slug: string;
  };
  membership_id: string;
  status: string;
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

  return (await response.json()) as T;
}

async function publicApiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  const response = await fetch(new URL(path, apiBaseUrl), {
    ...init,
    cache: "no-store",
    headers,
  });

  if (!response.ok) {
    throw new ApiClientError(
      "network_failure",
      "The backend returned an unexpected response.",
      response.status,
    );
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
  return apiJson<OrganizationActivationResponse>(
    `/api/v1/organizations/${organizationId}/activate`,
    {
      method: "POST",
    },
  );
}

export async function createWorkspaceInvite(
  organizationId: string,
  payload: {
    email: string;
    professional_roles: string[];
    department_access?: string[];
    expires_in_days?: number;
    maximum_uses?: number | null;
  },
): Promise<WorkspaceInvite> {
  return apiJson<WorkspaceInvite>(`/api/v1/organizations/${organizationId}/invites`, {
    method: "POST",
    body: JSON.stringify(payload),
    headers: {
      "Content-Type": "application/json",
    },
  });
}

export async function getWorkspaceInvite(token: string): Promise<WorkspaceInvite> {
  return publicApiJson<WorkspaceInvite>(`/api/v1/organizations/invites/${token}`);
}

export async function acceptWorkspaceInvite(
  token: string,
  payload?: { professional_roles?: string[] },
): Promise<WorkspaceInviteAcceptResponse> {
  return apiJson<WorkspaceInviteAcceptResponse>(`/api/v1/organizations/invites/${token}/accept`, {
    method: "POST",
    body: JSON.stringify(payload ?? {}),
    headers: {
      "Content-Type": "application/json",
    },
  });
}
