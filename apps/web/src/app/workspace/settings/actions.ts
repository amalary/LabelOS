"use server";

import { withAuth } from "@workos-inc/authkit-nextjs";
import { redirect } from "next/navigation";

import { ApiClientError } from "../../../lib/api-client";
import { createWorkspaceInvite } from "../../../lib/organizations";
import { logServerError } from "../../../lib/server-logging";

function parseOptionalPositiveInteger(value: FormDataEntryValue | null): number | null {
  if (typeof value !== "string" || value.trim().length === 0) {
    return null;
  }

  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

export async function createWorkspaceInviteAction(formData: FormData): Promise<void> {
  await withAuth({ ensureSignedIn: true });

  const organizationId = formData.get("organizationId");
  if (typeof organizationId !== "string" || organizationId.length === 0) {
    redirect("/workspace/settings?inviteError=missing-workspace");
  }

  const email = formData.get("email");
  if (typeof email !== "string" || email.trim().length === 0) {
    redirect("/workspace/settings?inviteError=missing-email");
  }

  const professionalRoles = formData
    .getAll("professionalRoles")
    .filter((role): role is string => typeof role === "string");
  const departmentAccess = formData
    .getAll("departmentAccess")
    .filter((department): department is string => typeof department === "string");

  if (professionalRoles.length === 0) {
    redirect("/workspace/settings?inviteError=missing-roles");
  }

  const expiresInDays = parseOptionalPositiveInteger(formData.get("expiresInDays")) ?? 7;
  const maximumUses = parseOptionalPositiveInteger(formData.get("maximumUses"));
  let token: string;

  try {
    const invite = await createWorkspaceInvite(organizationId, {
      email,
      professional_roles: professionalRoles,
      department_access: departmentAccess,
      expires_in_days: expiresInDays,
      maximum_uses: maximumUses,
    });
    token = invite.token;
  } catch (error) {
    if (!(error instanceof ApiClientError)) {
      logServerError("Workspace invite creation failed", error, {
        operation: "workspace_invite_create",
      });
    }
    redirect("/workspace/settings?inviteError=create-failed");
  }

  redirect(`/workspace/settings?invite=${encodeURIComponent(token)}`);
}
