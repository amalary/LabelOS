"use server";

import { refreshSession, withAuth } from "@workos-inc/authkit-nextjs";
import { redirect } from "next/navigation";

import { apiFetch, ApiClientError } from "../../../lib/api-client";
import { getWorkOSClient } from "../../../lib/workos";

export type WorkspaceOnboardingState = {
  error: string | null;
};

const MAX_ORGANIZATION_NAME_LENGTH = 120;

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
  membershipStatus,
  organizationId,
  organizationName,
  workosMembershipId,
}: {
  membershipStatus: string;
  organizationId: string;
  organizationName: string;
  workosMembershipId: string | null;
}) {
  const response = await apiFetch("/api/v1/onboarding/workspace", {
    body: JSON.stringify({
      membership_status: membershipStatus,
      organization_name: organizationName,
      workos_membership_id: workosMembershipId,
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
    const workos = getWorkOSClient();
    const organization = await workos.organizations.createOrganization(
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
    );
    organizationId = organization.id;

    const membership = await ensureOwnerMembership({
      organizationId,
      userId: session.user.id,
    });

    await syncLocalWorkspace({
      membershipStatus: membership.status,
      organizationId,
      organizationName: organization.name,
      workosMembershipId: membership.id,
    });

    await refreshSession({ organizationId, ensureSignedIn: true });
  } catch {
    console.error("Workspace onboarding failed");
    return {
      error:
        "We could not create the workspace. No local workspace records were saved unless WorkOS confirmed the organization and membership.",
    };
  }

  redirect("/dashboard");
}
