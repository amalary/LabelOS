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
