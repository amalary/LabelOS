"use client";

export type CampaignApiErrorCode =
  "unauthorized" | "forbidden" | "not_found" | "conflict" | "network_failure";

export class CampaignApiError extends Error {
  constructor(
    readonly code: CampaignApiErrorCode,
    message: string,
    readonly status?: number,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "CampaignApiError";
  }
}

export type CampaignTeamMember = {
  workspace_membership_id: string;
  profile_id: string;
  display_name: string | null;
  participation_status: string;
  responsibility_label: string | null;
  is_owner: boolean;
};

export type CampaignOwner = {
  profile_id: string;
  display_name: string | null;
};

export type Campaign = {
  id: string;
  workspace_id: string;
  name: string;
  description: string | null;
  campaign_type: string;
  status: string;
  start_date: string | null;
  target_end_date: string | null;
  created_by_user_id: string | null;
  created_by_profile_id: string | null;
  owner_profile_id: string | null;
  owner: CampaignOwner | null;
  members: CampaignTeamMember[];
  created_at: string;
  updated_at: string;
};

export type CampaignsList = {
  campaigns: Campaign[];
  total: number;
};

export type CampaignMembersList = {
  members: CampaignTeamMember[];
};

export type CampaignMemberUpsert = {
  workspace_membership_id: string;
  participation_status?: string;
  responsibility_label?: string | null;
};

function toCampaignApiError(status: number): CampaignApiError {
  if (status === 401) {
    return new CampaignApiError("unauthorized", "Sign in again to load campaign data.", status);
  }
  if (status === 403) {
    return new CampaignApiError("forbidden", "You do not have access to this campaign.", status);
  }
  if (status === 404) {
    return new CampaignApiError("not_found", "Campaign data was not found.", status);
  }
  if (status === 409) {
    return new CampaignApiError("conflict", "Campaign data could not be changed.", status);
  }
  return new CampaignApiError("network_failure", "Campaign data could not be loaded.", status);
}

async function campaignJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      cache: "no-store",
      headers,
    });
  } catch (error) {
    throw new CampaignApiError("network_failure", "Unable to reach the campaign API.", undefined, {
      cause: error,
    });
  }

  if (!response.ok) {
    throw toCampaignApiError(response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export function getCampaigns(workspaceId: string): Promise<CampaignsList> {
  return campaignJson<CampaignsList>(`/api/workspaces/${workspaceId}/campaigns`);
}

export function getCampaign(workspaceId: string, campaignId: string): Promise<Campaign> {
  return campaignJson<Campaign>(`/api/workspaces/${workspaceId}/campaigns/${campaignId}`);
}

export function getCampaignMembers(
  workspaceId: string,
  campaignId: string,
): Promise<CampaignMembersList> {
  return campaignJson<CampaignMembersList>(
    `/api/workspaces/${workspaceId}/campaigns/${campaignId}/members`,
  );
}

export function upsertCampaignMember(
  workspaceId: string,
  campaignId: string,
  payload: CampaignMemberUpsert,
): Promise<CampaignTeamMember> {
  return campaignJson<CampaignTeamMember>(
    `/api/workspaces/${workspaceId}/campaigns/${campaignId}/members`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  );
}

export function removeCampaignMember(
  workspaceId: string,
  campaignId: string,
  workspaceMembershipId: string,
): Promise<void> {
  return campaignJson<void>(
    `/api/workspaces/${workspaceId}/campaigns/${campaignId}/members/${workspaceMembershipId}`,
    {
      method: "DELETE",
    },
  );
}
