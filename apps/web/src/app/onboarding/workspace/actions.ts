"use server";

import { refreshSession, withAuth } from "@workos-inc/authkit-nextjs";
import { redirect } from "next/navigation";

import { apiFetch, apiFetchWithAccessToken, ApiClientError } from "../../../lib/api-client";
import { logServerError } from "../../../lib/server-logging";
import { getWorkOSClient } from "../../../lib/workos";

export type WorkspaceOnboardingState = {
  error: string | null;
};

const MAX_ORGANIZATION_NAME_LENGTH = 120;

class OnboardingSetupError extends Error {}

async function findIncompleteOrganization(userId: string, name: string) {
  const workos = getWorkOSClient();
  let after: string | undefined;
  // Bound the administrative lookup and fail closed rather than create another
  // organization when a large environment cannot be fully checked.
  const matches = [];
  for (let page = 0; page < 10; page++) {
    const result = await workos.organizations.listOrganizations({ limit: 100, after });
    matches.push(
      ...result.data.filter(
        (org) =>
          org.metadata?.created_by === userId &&
          org.metadata?.product === "label-os" &&
          org.name.toLowerCase() === name.toLowerCase(),
      ),
    );
    after = result.listMetadata.after ?? undefined;
    if (!after) {
      for (const org of matches.sort((a, b) => a.createdAt.localeCompare(b.createdAt))) {
        const memberships = await workos.userManagement.listOrganizationMemberships({
          organizationId: org.id,
          statuses: ["active", "inactive", "pending"],
          limit: 100,
        });
        // Creator metadata is not ownership proof after a transfer or revocation.
        // Resume only an empty organization or one where this user is still owner.
        if (
          memberships.data.length === 0 ||
          memberships.data.some(
            (membership) =>
              membership.userId === userId &&
              membership.status === "active" &&
              membership.role.slug === "owner",
          )
        )
          return org;
        throw new OnboardingSetupError(
          "A workspace with this name already has members. Ask its owner to restore access before retrying.",
        );
      }
      return undefined;
    }
  }
  throw new OnboardingSetupError(
    "Workspace lookup could not finish. Contact the operator before retrying.",
  );
}

function sanitizeOrganizationName(value: FormDataEntryValue | null): string {
  if (typeof value !== "string") {
    return "";
  }

  return value.replace(/\s+/g, " ").trim().slice(0, MAX_ORGANIZATION_NAME_LENGTH);
}

function organizationIdempotencyKey(userId: string, organizationName: string): string {
  const normalizedName = organizationName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return `labelos-onboarding-${userId}-${normalizedName || "workspace"}`;
}

async function syncLocalWorkspace({
  accessToken,
  organizationId,
  organizationName,
}: {
  accessToken: string;
  organizationId: string;
  organizationName: string;
}) {
  const response = await apiFetchWithAccessToken("/api/v1/onboarding/workspace", accessToken, {
    body: JSON.stringify({
      organization_name: organizationName,
      workos_organization_id: organizationId,
    }),
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    method: "POST",
  });

  if (!response.ok) {
    throw new ApiClientError(
      "network_failure",
      "The backend could not finish workspace onboarding.",
      response.status,
    );
  }
}

async function ensureOwnerMembership({
  organizationId,
  userId,
}: {
  organizationId: string;
  userId: string;
}) {
  const workos = getWorkOSClient();
  const memberships = await workos.userManagement.listOrganizationMemberships({
    organizationId,
    statuses: ["active", "inactive", "pending"],
    userId,
  });

  for (const membership of memberships.data) {
    if (membership.userId === userId && membership.organizationId === organizationId) {
      if (membership.status !== "active" || membership.role.slug !== "owner") {
        throw new Error("An active WorkOS owner membership is required.");
      }
      return membership;
    }
  }

  return workos.userManagement.createOrganizationMembership({
    organizationId,
    roleSlug: "owner",
    userId,
  });
}

export async function onboardWorkspace(
  _previousState: WorkspaceOnboardingState,
  formData: FormData,
): Promise<WorkspaceOnboardingState> {
  const organizationName = sanitizeOrganizationName(formData.get("organizationName"));
  if (organizationName.length < 2) {
    return { error: "Enter a label or company name with at least 2 characters." };
  }

  const session = await withAuth({ ensureSignedIn: true });
  if (session.organizationId) {
    await refreshSession({ organizationId: session.organizationId, ensureSignedIn: true });
    redirect("/dashboard");
  }

  let organizationId: string;
  try {
    const eligibility = await apiFetch("/api/v1/onboarding/workspace/eligibility");
    if (!eligibility.ok) {
      throw new Error("Workspace creation is not authorized.");
    }
    const workos = getWorkOSClient();
    try {
      await workos.authorization.getEnvironmentRole("owner");
    } catch {
      throw new OnboardingSetupError(
        "Workspace setup is unavailable: the operator must configure the WorkOS owner role. No new workspace was created.",
      );
    }
    const existingMemberships = await workos.userManagement.listOrganizationMemberships({
      userId: session.user.id,
      statuses: ["active", "inactive", "pending"],
    });
    // An organization-less session does not imply that the user is new.
    if (
      existingMemberships.data.length > 0 &&
      !existingMemberships.data.some(
        (membership) => membership.status === "active" && membership.role.slug === "owner",
      )
    ) {
      throw new Error("Select an existing workspace before creating another workspace.");
    }
    const organization =
      (await findIncompleteOrganization(session.user.id, organizationName)) ??
      (await workos.organizations.createOrganization(
        {
          name: organizationName,
          metadata: {
            created_by: session.user.id,
            product: "label-os",
          },
        },
        {
          idempotencyKey: organizationIdempotencyKey(session.user.id, organizationName),
        },
      ));
    organizationId = organization.id;

    await ensureOwnerMembership({
      organizationId,
      userId: session.user.id,
    });

    const refreshed = await refreshSession({ organizationId, ensureSignedIn: true });
    if (!refreshed.accessToken || refreshed.organizationId !== organizationId) {
      throw new Error("WorkOS did not confirm the new workspace session.");
    }
    await syncLocalWorkspace({
      accessToken: refreshed.accessToken,
      organizationId,
      organizationName: organization.name,
    });
  } catch (error) {
    // Never log raw SDK exceptions: they can carry request/response details.
    logServerError(
      "Workspace onboarding failed",
      new Error(
        error instanceof OnboardingSetupError
          ? error.message
          : "Workspace onboarding operation failed",
      ),
      {
        operation: "workspace_onboarding",
      },
    );
    return {
      error:
        error instanceof OnboardingSetupError
          ? error.message
          : "We could not create the workspace. No local workspace records were saved unless WorkOS confirmed the organization and membership.",
    };
  }

  redirect("/dashboard");
}
