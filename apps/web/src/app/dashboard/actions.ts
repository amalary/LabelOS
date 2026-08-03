"use server";

import { refreshSession, withAuth } from "@workos-inc/authkit-nextjs";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { ApiClientError } from "../../lib/api-client";
import { verifyOrganizationActivation } from "../../lib/organizations";
import { logServerError } from "../../lib/server-logging";

export type SwitchOrganizationState = {
  error: string | null;
};

export async function switchOrganization(
  _previousState: SwitchOrganizationState,
  formData: FormData,
): Promise<SwitchOrganizationState> {
  await withAuth({ ensureSignedIn: true });

  const organizationId = formData.get("organizationId");
  if (typeof organizationId !== "string" || organizationId.length === 0) {
    return { error: "Choose an organization to switch workspaces." };
  }

  try {
    const activation = await verifyOrganizationActivation(organizationId);
    await refreshSession({
      ensureSignedIn: true,
      organizationId: activation.workos_organization_id,
    });
  } catch (error) {
    if (error instanceof ApiClientError && (error.status === 403 || error.status === 404)) {
      return {
        error: "You no longer have access to that organization.",
      };
    }

    logServerError("Organization switch failed", error, {
      operation: "organization_switch",
    });
    return {
      error: "We could not switch organizations. Try again.",
    };
  }

  revalidatePath("/dashboard", "layout");
  redirect("/dashboard");
}
