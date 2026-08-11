"use server";

import { revalidatePath } from "next/cache";

import { ApiClientError } from "../../../lib/api-client";
import {
  inviteOrganizationMember,
  removeOrganizationMember,
  updateOrganization,
  updateOrganizationMemberRole,
  type OrganizationMemberRole,
} from "../../../lib/organizations";

const NAME_MAX_LENGTH = 200;
const SLUG_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,118}[a-z0-9])?$/;
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const EDITABLE_MEMBER_ROLES = new Set<OrganizationMemberRole>(["admin", "member", "viewer"]);

export type OrganizationSettingsActionState = {
  error: string | null;
  success: string | null;
};

const initialMessage = "The backend rejected this settings update.";

function fieldValue(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

function actionError(error: unknown, fallback = initialMessage): OrganizationSettingsActionState {
  if (error instanceof ApiClientError) {
    if (error.status === 403) {
      return { error: "You do not have permission to edit organization settings.", success: null };
    }
    if (error.status === 409) {
      return {
        error:
          fallback === initialMessage
            ? "Those settings conflict with an existing organization."
            : fallback,
        success: null,
      };
    }
  }

  return { error: fallback, success: null };
}

export async function saveOrganizationProfile(
  _previousState: OrganizationSettingsActionState,
  formData: FormData,
): Promise<OrganizationSettingsActionState> {
  const organizationId = fieldValue(formData, "organizationId");
  const name = fieldValue(formData, "name").replace(/\s+/g, " ").trim();
  const slug = fieldValue(formData, "slug").trim().toLowerCase();

  if (!organizationId) {
    return { error: "An active organization is required.", success: null };
  }
  if (name.length < 2 || name.length > NAME_MAX_LENGTH) {
    return { error: "Organization name must be between 2 and 200 characters.", success: null };
  }
  if (!SLUG_PATTERN.test(slug)) {
    return {
      error: "Slug must use lowercase letters, numbers, and single hyphens only.",
      success: null,
    };
  }

  try {
    await updateOrganization(organizationId, { name, slug });
  } catch (error) {
    return actionError(error);
  }

  revalidatePath("/dashboard/settings");
  revalidatePath("/dashboard");
  return { error: null, success: "Organization profile saved." };
}

export async function saveMemberRole(
  _previousState: OrganizationSettingsActionState,
  formData: FormData,
): Promise<OrganizationSettingsActionState> {
  const organizationId = fieldValue(formData, "organizationId");
  const membershipId = fieldValue(formData, "membershipId");
  const role = fieldValue(formData, "role") as OrganizationMemberRole;
  const confirmed = fieldValue(formData, "confirmRoleChange") === "on";

  if (!organizationId || !membershipId) {
    return { error: "Choose a member before changing roles.", success: null };
  }
  if (!EDITABLE_MEMBER_ROLES.has(role)) {
    return { error: "Choose admin, member, or viewer.", success: null };
  }
  if (!confirmed) {
    return { error: "Confirm the role change before saving.", success: null };
  }

  try {
    await updateOrganizationMemberRole(
      organizationId,
      membershipId,
      role as Exclude<OrganizationMemberRole, "owner">,
    );
  } catch (error) {
    return actionError(error, "We could not update that member role.");
  }

  revalidatePath("/dashboard/settings");
  return { error: null, success: "Member role updated." };
}

export async function inviteMember(
  _previousState: OrganizationSettingsActionState,
  formData: FormData,
): Promise<OrganizationSettingsActionState> {
  const organizationId = fieldValue(formData, "organizationId");
  const email = fieldValue(formData, "email").trim().toLowerCase();
  const role = fieldValue(formData, "role") as OrganizationMemberRole;

  if (!organizationId) {
    return { error: "An active organization is required.", success: null };
  }
  if (!EMAIL_PATTERN.test(email)) {
    return { error: "Enter a valid email address.", success: null };
  }
  if (!EDITABLE_MEMBER_ROLES.has(role)) {
    return { error: "Choose admin, member, or viewer.", success: null };
  }

  try {
    await inviteOrganizationMember(
      organizationId,
      { email, role: role as Exclude<OrganizationMemberRole, "owner"> },
    );
  } catch (error) {
    return actionError(error, "We could not send that invitation.");
  }

  revalidatePath("/dashboard/settings");
  return { error: null, success: "Invitation sent." };
}

export async function removeMember(
  _previousState: OrganizationSettingsActionState,
  formData: FormData,
): Promise<OrganizationSettingsActionState> {
  const organizationId = fieldValue(formData, "organizationId");
  const membershipId = fieldValue(formData, "membershipId");
  const confirmed = fieldValue(formData, "confirmRemoveMember") === "on";

  if (!organizationId || !membershipId) {
    return { error: "Choose a member before removing access.", success: null };
  }
  if (!confirmed) {
    return { error: "Confirm member removal before saving.", success: null };
  }

  try {
    await removeOrganizationMember(organizationId, membershipId);
  } catch (error) {
    return actionError(error, "We could not remove that member.");
  }

  revalidatePath("/dashboard/settings");
  revalidatePath("/dashboard");
  return { error: null, success: "Member removed." };
}
