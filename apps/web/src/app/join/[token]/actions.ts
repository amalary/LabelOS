"use server";

import { withAuth } from "@workos-inc/authkit-nextjs";
import { redirect } from "next/navigation";

import { ApiClientError } from "../../../lib/api-client";
import { acceptWorkspaceInvite } from "../../../lib/organizations";
import { logServerError } from "../../../lib/server-logging";

export async function acceptWorkspaceInviteAction(formData: FormData): Promise<void> {
  await withAuth({ ensureSignedIn: true });

  const token = formData.get("token");
  if (typeof token !== "string" || token.length === 0) {
    redirect("/dashboard");
  }

  try {
    await acceptWorkspaceInvite(token);
  } catch (error) {
    if (!(error instanceof ApiClientError)) {
      logServerError("Workspace invite acceptance failed", error, {
        operation: "workspace_invite_accept",
      });
    }
    redirect(`/join/${encodeURIComponent(token)}?inviteError=accept-failed`);
  }

  redirect("/dashboard");
}
