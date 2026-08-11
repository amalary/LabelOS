"use client";

import { Button, Input } from "@label-os/ui";
import { useActionState } from "react";

import {
  inviteMember,
  removeMember,
  saveMemberRole,
  saveOrganizationProfile,
  type OrganizationSettingsActionState,
} from "./actions";
import type {
  OrganizationInvitation,
  OrganizationMember,
  OrganizationSummary,
} from "../../../lib/organizations";

type SettingsPanelProps = {
  organization: OrganizationSummary;
  members: OrganizationMember[];
  invitations: OrganizationInvitation[];
  canEditProfile: boolean;
  canEditRoles: boolean;
  membersError: string | null;
};

const initialState: OrganizationSettingsActionState = { error: null, success: null };

function organizationInitials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
}

function roleLabel(role: string) {
  return `${role.charAt(0).toUpperCase()}${role.slice(1)}`;
}

function FormMessage({ state }: { state: OrganizationSettingsActionState }) {
  if (state.error) {
    return (
      <p className="text-sm leading-6 text-red-700" role="alert">
        {state.error}
      </p>
    );
  }
  if (state.success) {
    return (
      <p className="text-sm leading-6 text-emerald-700" role="status">
        {state.success}
      </p>
    );
  }
  return null;
}

function RoleForm({
  organizationId,
  member,
  canEditRoles,
}: {
  organizationId: string;
  member: OrganizationMember;
  canEditRoles: boolean;
}) {
  const [state, formAction, pending] = useActionState(saveMemberRole, initialState);
  const canChangeThisRole = canEditRoles && member.role !== "owner" && member.status === "active";

  return (
    <form action={formAction} className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
      <input name="organizationId" type="hidden" value={organizationId} />
      <input name="membershipId" type="hidden" value={member.id} />
      <div className="min-w-0">
        <label className="sr-only" htmlFor={`role-${member.id}`}>
          Role for {member.display_name ?? member.email}
        </label>
        <select
          className="h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500"
          defaultValue={member.role}
          disabled={!canChangeThisRole || pending}
          id={`role-${member.id}`}
          name="role"
        >
          <option value="owner" disabled>
            Owner
          </option>
          <option value="admin">Admin</option>
          <option value="member">Member</option>
          <option value="viewer">Viewer</option>
        </select>
        {canChangeThisRole ? (
          <label className="mt-2 flex items-start gap-2 text-xs leading-5 text-slate-600">
            <input
              className="mt-1 h-4 w-4 rounded border-slate-300 text-slate-950 focus:ring-slate-300"
              disabled={pending}
              name="confirmRoleChange"
              type="checkbox"
            />
            Confirm this role change
          </label>
        ) : (
          <p className="mt-2 text-xs leading-5 text-slate-500">
            {member.role === "owner"
              ? "Owner changes are not supported in v1."
              : "You do not have permission to edit this role."}
          </p>
        )}
        <FormMessage state={state} />
      </div>
      <Button disabled={!canChangeThisRole || pending} size="sm" type="submit" variant="secondary">
        {pending ? "Saving..." : "Save role"}
      </Button>
    </form>
  );
}

function InviteForm({
  organizationId,
  canInvite,
}: {
  organizationId: string;
  canInvite: boolean;
}) {
  const [state, formAction, pending] = useActionState(inviteMember, initialState);

  return (
    <form action={formAction} aria-label="Invite member" className="mt-5 grid gap-3 lg:grid-cols-[minmax(14rem,1fr)_12rem_auto]">
      <input name="organizationId" type="hidden" value={organizationId} />
      <div>
        <label className="text-sm font-medium text-slate-900" htmlFor="invite-email">
          Email
        </label>
        <Input
          disabled={!canInvite || pending}
          id="invite-email"
          maxLength={320}
          name="email"
          placeholder="artist@example.com"
          required
          type="email"
        />
      </div>
      <div>
        <label className="text-sm font-medium text-slate-900" htmlFor="invite-role">
          Role
        </label>
        <select
          className="h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 shadow-sm outline-none transition-colors focus:border-slate-950 focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500"
          defaultValue="member"
          disabled={!canInvite || pending}
          id="invite-role"
          name="role"
        >
          <option value="admin">Admin</option>
          <option value="member">Member</option>
          <option value="viewer">Viewer</option>
        </select>
      </div>
      <div className="flex items-end">
        <Button disabled={!canInvite || pending} type="submit">
          {pending ? "Sending..." : "Invite"}
        </Button>
      </div>
      <div className="lg:col-span-3">
        <FormMessage state={state} />
      </div>
    </form>
  );
}

function RemoveForm({
  organizationId,
  member,
  canRemove,
}: {
  organizationId: string;
  member: OrganizationMember;
  canRemove: boolean;
}) {
  const [state, formAction, pending] = useActionState(removeMember, initialState);

  return (
    <form action={formAction} className="mt-3 flex flex-col gap-2">
      <input name="organizationId" type="hidden" value={organizationId} />
      <input name="membershipId" type="hidden" value={member.id} />
      {canRemove ? (
        <label className="flex items-start gap-2 text-xs leading-5 text-slate-600">
          <input
            className="mt-1 h-4 w-4 rounded border-slate-300 text-red-700 focus:ring-red-200"
            disabled={pending}
            name="confirmRemoveMember"
            type="checkbox"
          />
          Confirm access removal
        </label>
      ) : null}
      <Button disabled={!canRemove || pending} size="sm" type="submit" variant="secondary">
        {pending ? "Removing..." : "Remove"}
      </Button>
      <FormMessage state={state} />
    </form>
  );
}

export function SettingsPanel({
  organization,
  members,
  invitations,
  canEditProfile,
  canEditRoles,
  membersError,
}: SettingsPanelProps) {
  const [profileState, profileAction, profilePending] = useActionState(
    saveOrganizationProfile,
    initialState,
  );
  const logoUrl = organization.logoUrl ?? organization.logo_url ?? null;

  return (
    <div className="flex flex-col gap-5">
      <section className="rounded-md border border-white/70 bg-white/60 p-5 shadow-sm backdrop-blur-2xl">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex min-w-0 items-center gap-4">
            {logoUrl ? (
              <span
                aria-label={`${organization.name} logo`}
                className="h-16 w-16 shrink-0 rounded-md bg-cover bg-center ring-1 ring-white/80"
                role="img"
                style={{ backgroundImage: `url("${logoUrl}")` }}
              />
            ) : (
              <span
                aria-hidden="true"
                className="flex h-16 w-16 shrink-0 items-center justify-center rounded-md bg-slate-950 text-sm font-semibold text-white"
              >
                {organizationInitials(organization.name)}
              </span>
            )}
            <div className="min-w-0">
              <h2 className="truncate text-lg font-semibold text-slate-950">
                Organization profile
              </h2>
              <p className="mt-1 text-sm leading-6 text-slate-600">
                Logo upload is unavailable in this workspace.
              </p>
            </div>
          </div>
          {!canEditProfile ? (
            <p className="max-w-md text-sm leading-6 text-amber-800" role="status">
              You can view organization settings, but only owners with organization management
              permission can edit them.
            </p>
          ) : null}
        </div>

        <form action={profileAction} aria-label="Organization profile" className="mt-6 grid gap-4">
          <input name="organizationId" type="hidden" value={organization.id} />
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="text-sm font-medium text-slate-900" htmlFor="organization-name">
                Organization name
              </label>
              <Input
                aria-describedby="organization-name-help"
                defaultValue={organization.name}
                disabled={!canEditProfile || profilePending}
                id="organization-name"
                maxLength={200}
                minLength={2}
                name="name"
                required
              />
              <p className="mt-1 text-xs leading-5 text-slate-500" id="organization-name-help">
                Use 2 to 200 characters.
              </p>
            </div>
            <div>
              <label className="text-sm font-medium text-slate-900" htmlFor="organization-slug">
                Organization slug
              </label>
              <Input
                aria-describedby="organization-slug-help"
                defaultValue={organization.slug}
                disabled={!canEditProfile || profilePending}
                id="organization-slug"
                name="slug"
                pattern="[a-z0-9](?:[a-z0-9-]{0,118}[a-z0-9])?"
                required
              />
              <p className="mt-1 text-xs leading-5 text-slate-500" id="organization-slug-help">
                Lowercase letters, numbers, and hyphens.
              </p>
            </div>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <FormMessage state={profileState} />
            <Button disabled={!canEditProfile || profilePending} type="submit">
              {profilePending ? "Saving..." : "Save organization"}
            </Button>
          </div>
        </form>
      </section>

      <section className="rounded-md border border-white/70 bg-white/60 p-5 shadow-sm backdrop-blur-2xl">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">Members</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              Invite members, review pending invitations, and manage access.
            </p>
          </div>
          {!canEditRoles ? (
            <p className="text-sm leading-6 text-amber-800" role="status">
              Role editing is limited to owners with member management permission.
            </p>
          ) : null}
        </div>

        <InviteForm canInvite={canEditRoles && !membersError} organizationId={organization.id} />

        {membersError ? (
          <div
            className="mt-5 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-950"
            role="alert"
          >
            {membersError}
          </div>
        ) : (
          <div className="mt-5 overflow-x-auto">
            <table className="w-full min-w-[42rem] border-separate border-spacing-0 text-left text-sm">
              <caption className="sr-only">Organization members and roles</caption>
              <thead>
                <tr className="text-xs font-semibold uppercase tracking-normal text-slate-500">
                  <th className="border-b border-slate-200 py-3 pr-4" scope="col">
                    Member
                  </th>
                  <th className="border-b border-slate-200 px-4 py-3" scope="col">
                    Status
                  </th>
                  <th className="border-b border-slate-200 px-4 py-3" scope="col">
                    Current role
                  </th>
                  <th className="border-b border-slate-200 py-3 pl-4" scope="col">
                    Manage
                  </th>
                </tr>
              </thead>
              <tbody>
                {members.map((member) => (
                  <tr key={member.id}>
                    <td className="border-b border-slate-100 py-4 pr-4">
                      <div className="font-medium text-slate-950">
                        {member.display_name ?? member.email}
                      </div>
                      <div className="text-xs text-slate-500">{member.email}</div>
                    </td>
                    <td className="border-b border-slate-100 px-4 py-4 text-slate-600">
                      {roleLabel(member.status)}
                    </td>
                    <td className="border-b border-slate-100 px-4 py-4 font-medium text-slate-900">
                      {roleLabel(member.role)}
                    </td>
                    <td className="border-b border-slate-100 py-4 pl-4">
                      <RoleForm
                        canEditRoles={canEditRoles}
                        member={member}
                        organizationId={organization.id}
                      />
                      <RemoveForm
                        canRemove={canEditRoles && member.role !== "owner" && member.status === "active"}
                        member={member}
                        organizationId={organization.id}
                      />
                    </td>
                  </tr>
                ))}
                {invitations.map((invitation) => (
                  <tr key={invitation.id}>
                    <td className="border-b border-slate-100 py-4 pr-4">
                      <div className="font-medium text-slate-950">{invitation.email}</div>
                      <div className="text-xs text-slate-500">Invitation pending</div>
                    </td>
                    <td className="border-b border-slate-100 px-4 py-4 text-slate-600">
                      {roleLabel(invitation.state)}
                    </td>
                    <td className="border-b border-slate-100 px-4 py-4 font-medium text-slate-900">
                      {roleLabel(invitation.role)}
                    </td>
                    <td className="border-b border-slate-100 py-4 pl-4 text-sm text-slate-500">
                      Awaiting acceptance
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
