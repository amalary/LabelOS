"use server";

import { withAuth } from "@workos-inc/authkit-nextjs";

import { ApiClientError } from "../../../lib/api-client";
import { createWorkspaceInvite } from "../../../lib/organizations";
import { logServerError } from "../../../lib/server-logging";

export type CreateWorkspaceInviteState = {
  error: string | null;
  inviteLink: string | null;
  status: "idle" | "success" | "error";
};

const initialInviteState: CreateWorkspaceInviteState = {
  error: null,
  inviteLink: null,
  status: "idle",
};

function parseOptionalPositiveInteger(value: FormDataEntryValue | null): number | null {
  if (typeof value !== "string" || value.trim().length === 0) {
    return null;
  }

  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function joinUrl(token: string): string {
  const baseUrl = process.env.WEB_BASE_URL ?? "http://localhost:3000";
  return new URL(`/join/${token}`, baseUrl).toString();
}

function inviteErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError) {
    if (error.status === 409) {
      return "An active invitation already exists for this email. Use the existing invite or wait for it to expire.";
    }
    if (error.status === 403) {
      return "You do not have permission to send this invitation. Ask a workspace owner or admin for help.";
    }
    if (error.status === 410) {
      return "This invitation is no longer available. Create a new invite and send the fresh link.";
    }
  }

  return "We could not send the invitation. Check the email and your workspace access, then try again.";
}

export async function createWorkspaceInviteAction(
  _previousState: CreateWorkspaceInviteState,
  formData: FormData,
): Promise<CreateWorkspaceInviteState> {
  await withAuth({ ensureSignedIn: true });

  const organizationId = formData.get("organizationId");
  if (typeof organizationId !== "string" || organizationId.length === 0) {
    return {
      ...initialInviteState,
      error: "Choose an active workspace before sending an invite.",
      status: "error",
    };
  }

  const email = formData.get("email");
  if (typeof email !== "string" || email.trim().length === 0) {
    return {
      ...initialInviteState,
      error: "Enter the email address for the person you want to invite.",
      status: "error",
    };
  }

  const professionalRoles = formData
    .getAll("professionalRoles")
    .filter((role): role is string => typeof role === "string");
  const workspaceRoles = formData
    .getAll("workspaceRoles")
    .filter((role): role is string => typeof role === "string");
  const departmentAccess = formData
    .getAll("departmentAccess")
    .filter((department): department is string => typeof department === "string");

  if (professionalRoles.length === 0) {
    return {
      ...initialInviteState,
      error: "Choose at least one role for this invitation.",
      status: "error",
    };
  }

  const expiresInDays = parseOptionalPositiveInteger(formData.get("expiresInDays")) ?? 7;
  const maximumUses = parseOptionalPositiveInteger(formData.get("maximumUses"));

  try {
    const invite = await createWorkspaceInvite(organizationId, {
      email,
      professional_roles: professionalRoles,
      workspace_roles: workspaceRoles,
      department_access: departmentAccess,
      expires_in_days: expiresInDays,
      maximum_uses: maximumUses,
    });
    return {
      error: null,
      inviteLink: joinUrl(invite.token),
      status: "success",
    };
  } catch (error) {
    if (!(error instanceof ApiClientError)) {
      logServerError("Workspace invite creation failed", error, {
        operation: "workspace_invite_create",
      });
    }
    return {
      ...initialInviteState,
      error: inviteErrorMessage(error),
      status: "error",
    };
  }
}
