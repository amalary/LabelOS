"use client";

import { Button, cn } from "@label-os/ui";
import { useEffect, useMemo, useState } from "react";

import { capabilities } from "../../../lib/authorization";
import { useActiveWorkspace } from "../../../lib/workspace-context";
import {
  replaceMemberWorkspaceRoles,
  type MemberRoleAssignmentSummary,
  type WorkspaceMember,
  type WorkspaceRoleDefinition,
  useEffectiveCapabilities,
  useMemberRoleAssignments,
  useWorkspaceMembers,
  useWorkspaceRoles,
} from "../../../lib/workspace-capabilities";

const assignableRoleKeys = new Set([
  "a_and_r",
  "manager",
  "artist",
  "producer",
  "legal",
  "marketing",
  "finance",
]);

const roleOrder = ["a_and_r", "manager", "artist", "producer", "legal", "marketing", "finance"];

function roleLabel(role: { key: string; name: string }) {
  return role.name || role.key.replace(/_/g, " ");
}

function sameSet(left: Iterable<string>, right: Iterable<string>) {
  const leftSet = new Set(left);
  const rightSet = new Set(right);
  if (leftSet.size !== rightSet.size) {
    return false;
  }
  for (const value of leftSet) {
    if (!rightSet.has(value)) {
      return false;
    }
  }
  return true;
}

function roleKeysFor(
  assignment: MemberRoleAssignmentSummary | undefined,
  allowedKeys: ReadonlySet<string>,
) {
  return new Set(
    (assignment?.roles ?? [])
      .map((role) => role.key)
      .filter((roleKey) => allowedKeys.has(roleKey)),
  );
}

function memberName(member: WorkspaceMember) {
  return member.display_name ?? member.email;
}

function assignmentStatus(error: string | undefined, isSaving: boolean, isDirty: boolean) {
  if (error) {
    return error;
  }
  if (isSaving) {
    return "Saving roles...";
  }
  if (isDirty) {
    return "Unsaved changes";
  }
  return "Roles saved";
}

export function MemberRoleAssignmentPanel() {
  const { activeWorkspace } = useActiveWorkspace();
  const workspaceId = activeWorkspace?.id ?? null;
  const authorization = useEffectiveCapabilities(workspaceId);
  const members = useWorkspaceMembers(workspaceId);
  const roles = useWorkspaceRoles(workspaceId);
  const assignments = useMemberRoleAssignments(workspaceId);
  const [drafts, setDrafts] = useState<Record<string, Set<string>>>({});
  const [savingMemberId, setSavingMemberId] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const canModifyRoles =
    authorization.can(capabilities.workspaceMemberRolesManage) &&
    authorization.can(capabilities.roleAssign);

  const roleDefinitions = useMemo(() => {
    const definitions = (roles.data?.roles ?? []).filter((role) =>
      assignableRoleKeys.has(role.key),
    );
    return definitions.sort((left, right) => {
      const leftIndex = roleOrder.indexOf(left.key);
      const rightIndex = roleOrder.indexOf(right.key);
      return (
        (leftIndex === -1 ? Number.MAX_SAFE_INTEGER : leftIndex) -
          (rightIndex === -1 ? Number.MAX_SAFE_INTEGER : rightIndex) ||
        roleLabel(left).localeCompare(roleLabel(right))
      );
    });
  }, [roles.data]);

  const allRolesByKey = useMemo(() => {
    const roleMap = new Map<string, WorkspaceRoleDefinition>();
    for (const role of roles.data?.roles ?? []) {
      roleMap.set(role.key, role);
    }
    return roleMap;
  }, [roles.data]);

  const assignmentsByMemberId = useMemo(() => {
    const roleMap = new Map<string, MemberRoleAssignmentSummary>();
    for (const assignment of assignments.data?.assignments ?? []) {
      roleMap.set(assignment.member_id, assignment);
    }
    return roleMap;
  }, [assignments.data]);

  useEffect(() => {
    const assignmentData = assignments.data;
    if (!assignmentData) {
      return;
    }
    setDrafts((currentDrafts) => {
      const nextDrafts = { ...currentDrafts };
      for (const assignment of assignmentData.assignments) {
        nextDrafts[assignment.member_id] = roleKeysFor(assignment, assignableRoleKeys);
      }
      return nextDrafts;
    });
  }, [assignments.data]);

  function toggleRole(memberId: string, roleKey: string) {
    setDrafts((currentDrafts) => {
      const base =
        currentDrafts[memberId] ??
        roleKeysFor(assignmentsByMemberId.get(memberId), assignableRoleKeys);
      const nextRoles = new Set(base);
      if (nextRoles.has(roleKey)) {
        nextRoles.delete(roleKey);
      } else {
        nextRoles.add(roleKey);
      }
      return { ...currentDrafts, [memberId]: nextRoles };
    });
    setErrors((currentErrors) => {
      const nextErrors = { ...currentErrors };
      delete nextErrors[memberId];
      return nextErrors;
    });
  }

  async function saveRoles(member: WorkspaceMember) {
    if (!workspaceId) {
      return;
    }
    const assignment = assignmentsByMemberId.get(member.id);
    const previousAssignableKeys = roleKeysFor(assignment, assignableRoleKeys);
    const requestedAssignableKeys = drafts[member.id] ?? previousAssignableKeys;
    const preservedHiddenKeys = (assignment?.roles ?? [])
      .map((role) => role.key)
      .filter((roleKey) => !assignableRoleKeys.has(roleKey));
    const orderedRequestedKeys = roleDefinitions
      .map((role) => role.key)
      .filter((roleKey) => requestedAssignableKeys.has(roleKey));
    const roleIds = [...preservedHiddenKeys, ...orderedRequestedKeys]
      .map((roleKey) => allRolesByKey.get(roleKey)?.id)
      .filter((roleId): roleId is string => Boolean(roleId));

    setSavingMemberId(member.id);
    setErrors((currentErrors) => {
      const nextErrors = { ...currentErrors };
      delete nextErrors[member.id];
      return nextErrors;
    });
    try {
      await replaceMemberWorkspaceRoles(workspaceId, member.id, roleIds);
      await assignments.reload();
    } catch {
      setDrafts((currentDrafts) => ({
        ...currentDrafts,
        [member.id]: previousAssignableKeys,
      }));
      setErrors((currentErrors) => ({
        ...currentErrors,
        [member.id]: "Role changes were not saved. The previous roles were restored.",
      }));
    } finally {
      setSavingMemberId((currentMemberId) =>
        currentMemberId === member.id ? null : currentMemberId,
      );
    }
  }

  if (!activeWorkspace) {
    return (
      <section className="border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        Choose an active workspace before assigning member roles.
      </section>
    );
  }

  const isInitialLoading =
    (members.isLoading && !members.data) ||
    (roles.isLoading && !roles.data) ||
    (assignments.isLoading && !assignments.data);
  const loadFailed = members.error || roles.error || assignments.error;

  return (
    <section className="grid gap-5 border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">Member Roles</h2>
          <p className="mt-1 text-sm leading-6 text-slate-600">
            Assign one or more workspace roles to each active member.
          </p>
        </div>
        <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-600">
          {canModifyRoles ? "Role editing enabled" : "View only"}
        </div>
      </div>

      {!canModifyRoles ? (
        <div
          className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900"
          role="status"
        >
          Ask a workspace owner or admin to change member roles.
        </div>
      ) : null}

      {loadFailed ? (
        <div
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-900"
          role="alert"
        >
          Member role data could not be loaded.
        </div>
      ) : null}

      {isInitialLoading ? (
        <div className="grid gap-3">
          {Array.from({ length: 3 }, (_, index) => (
            <div className="h-28 rounded-md bg-slate-100 auth-shimmer" key={index} />
          ))}
        </div>
      ) : null}

      {!isInitialLoading && members.data?.members.length === 0 ? (
        <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm text-slate-500">
          No workspace members are available for role assignment.
        </div>
      ) : null}

      {!isInitialLoading && members.data?.members.length ? (
        <div className="overflow-hidden rounded-md border border-slate-200">
          <div className="grid gap-0 divide-y divide-slate-200">
            {members.data.members.map((member) => {
              const assignment = assignmentsByMemberId.get(member.id);
              const persistedKeys = roleKeysFor(assignment, assignableRoleKeys);
              const draftKeys = drafts[member.id] ?? persistedKeys;
              const isDirty = !sameSet(draftKeys, persistedKeys);
              const isSaving = savingMemberId === member.id;
              const canEditMember = canModifyRoles && member.status === "active";
              const statusText = assignmentStatus(errors[member.id], isSaving, isDirty);

              return (
                <div className="grid gap-4 bg-white p-4" key={member.id}>
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div className="min-w-0">
                      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                        Member
                      </div>
                      <div className="mt-1 truncate text-base font-semibold text-slate-950">
                        {memberName(member)}
                      </div>
                      <div className="mt-1 text-sm text-slate-500">{member.email}</div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="inline-flex h-7 items-center rounded-md border border-slate-200 bg-slate-50 px-2.5 text-xs font-semibold capitalize text-slate-600">
                        {member.workspace_permission}
                      </span>
                      <span
                        className={cn(
                          "text-sm",
                          errors[member.id]
                            ? "text-red-700"
                            : isDirty
                              ? "text-amber-700"
                              : "text-slate-500",
                        )}
                        role={errors[member.id] ? "alert" : "status"}
                      >
                        {statusText}
                      </span>
                    </div>
                  </div>

                  <fieldset className="grid gap-2" disabled={!canEditMember || isSaving}>
                    <legend className="text-sm font-medium text-slate-700">Roles</legend>
                    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                      {roleDefinitions.map((role) => (
                        <label
                          className="flex min-h-11 cursor-pointer items-center gap-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-800 transition focus-within:ring-2 focus-within:ring-cyan-500 focus-within:ring-offset-2 has-[:checked]:border-cyan-500 has-[:checked]:bg-cyan-50 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60"
                          key={role.id}
                        >
                          <input
                            aria-label={`${memberName(member)} role ${roleLabel(role)}`}
                            checked={draftKeys.has(role.key)}
                            className="h-4 w-4 accent-cyan-600"
                            onChange={() => toggleRole(member.id, role.key)}
                            type="checkbox"
                          />
                          <span>{roleLabel(role)}</span>
                        </label>
                      ))}
                    </div>
                  </fieldset>

                  <div className="flex justify-end">
                    <Button
                      disabled={!canEditMember || !isDirty || isSaving}
                      onClick={() => void saveRoles(member)}
                      size="sm"
                      type="button"
                    >
                      {isSaving ? "Saving..." : "Save roles"}
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </section>
  );
}
