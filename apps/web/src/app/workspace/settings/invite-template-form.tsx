"use client";

import { useActionState, useEffect, useId, useMemo, useState } from "react";
import { useFormStatus } from "react-dom";

import { createWorkspaceInviteAction, type CreateWorkspaceInviteState } from "./actions";

type RoleName = "Artist" | "Manager" | "Producer" | "Marketing" | "Legal";

type InviteRole = {
  label: RoleName;
  professionalRole: "Artist" | "Management" | "Producer" | "Marketing" | "Legal";
  workspaceRole: "artist" | "manager" | "producer" | "marketing" | "legal";
  description: string;
  departments: readonly string[];
};

const INVITE_ROLES: readonly InviteRole[] = [
  {
    label: "Artist",
    professionalRole: "Artist",
    workspaceRole: "artist",
    description: "Best for artists and artist teams who need project visibility.",
    departments: ["artist", "creative", "releases", "analytics"],
  },
  {
    label: "Manager",
    professionalRole: "Management",
    workspaceRole: "manager",
    description: "For day-to-day artist or campaign coordination.",
    departments: ["management", "artist", "releases", "marketing", "analytics"],
  },
  {
    label: "Producer",
    professionalRole: "Producer",
    workspaceRole: "producer",
    description: "For collaborators working on songs, sessions, credits, and delivery.",
    departments: ["production", "songs", "sessions", "credits"],
  },
  {
    label: "Marketing",
    professionalRole: "Marketing",
    workspaceRole: "marketing",
    description: "For campaign, launch, and audience growth work.",
    departments: ["marketing", "campaigns", "analytics"],
  },
  {
    label: "Legal",
    professionalRole: "Legal",
    workspaceRole: "legal",
    description: "For contract, agreement, and rights review workflows.",
    departments: ["legal", "contracts", "agreements"],
  },
] as const;

const initialState: CreateWorkspaceInviteState = {
  error: null,
  inviteLink: null,
  status: "idle",
};

type InviteTemplateFormProps = {
  canAssignInviteRoles: boolean;
  canInviteMembers: boolean;
  initialInviteLink?: string | null;
  organizationId: string;
};

function SubmitButton({ disabled }: { disabled: boolean }) {
  const { pending } = useFormStatus();

  return (
    <button
      className="inline-flex h-10 items-center justify-center rounded-md bg-slate-950 px-4 text-sm font-semibold text-white outline-none transition hover:bg-slate-800 focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-slate-400"
      disabled={disabled || pending}
      type="submit"
    >
      {pending ? "Sending invite..." : "Send invitation"}
    </button>
  );
}

function uniqueDepartmentsFor(roles: ReadonlySet<RoleName>): string[] {
  const departments = new Set<string>();
  for (const role of INVITE_ROLES) {
    if (!roles.has(role.label)) {
      continue;
    }
    role.departments.forEach((department) => departments.add(department));
  }
  return Array.from(departments);
}

export function InviteTemplateForm({
  canAssignInviteRoles,
  canInviteMembers,
  initialInviteLink = null,
  organizationId,
}: InviteTemplateFormProps) {
  const dialogTitleId = useId();
  const dialogDescriptionId = useId();
  const [isOpen, setIsOpen] = useState(false);
  const initialActionState: CreateWorkspaceInviteState = {
    ...initialState,
    inviteLink: initialInviteLink,
    status: initialInviteLink ? "success" : "idle",
  };
  const [state, formAction] = useActionState(createWorkspaceInviteAction, initialActionState);
  const [selectedRoles, setSelectedRoles] = useState<Set<RoleName>>(() => new Set(["Artist"]));
  const selectedDepartments = useMemo(() => uniqueDepartmentsFor(selectedRoles), [selectedRoles]);
  const canSubmit =
    canInviteMembers && (canAssignInviteRoles ? selectedRoles.size > 0 : true);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    }

    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [isOpen]);

  function toggleRole(role: RoleName) {
    setSelectedRoles((currentRoles) => {
      const nextRoles = new Set(currentRoles);
      if (nextRoles.has(role)) {
        nextRoles.delete(role);
      } else {
        nextRoles.add(role);
      }
      return nextRoles;
    });
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-sm font-semibold text-slate-950">Role-aware invitation</div>
          <p className="mt-1 text-sm leading-6 text-slate-600">
            Invite one person and choose the label roles they should start with.
          </p>
        </div>
        {canInviteMembers ? (
          <button
            className="inline-flex h-10 items-center justify-center rounded-md bg-slate-950 px-4 text-sm font-semibold text-white outline-none transition hover:bg-slate-800 focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-slate-400"
            onClick={() => setIsOpen(true)}
            type="button"
          >
            Invite person
          </button>
        ) : null}
      </div>

      {!canInviteMembers ? (
        <div
          className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900"
          role="status"
        >
          Ask a workspace owner or admin to invite new people.
        </div>
      ) : null}

      {state.status === "success" && state.inviteLink ? (
        <div className="grid gap-2 rounded-md border border-emerald-200 bg-emerald-50 p-4">
          <div className="text-sm font-semibold text-emerald-950">Invitation ready</div>
          <div className="break-all font-mono text-sm text-emerald-900">{state.inviteLink}</div>
        </div>
      ) : null}

      {isOpen ? (
        <div
          aria-labelledby={dialogTitleId}
          aria-describedby={dialogDescriptionId}
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-end bg-slate-950/45 p-3 sm:items-center sm:justify-center sm:p-6"
          role="dialog"
        >
          <div className="max-h-[92vh] w-full overflow-auto rounded-lg border border-slate-200 bg-white p-4 shadow-xl sm:max-w-2xl sm:p-5">
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 pb-4">
              <div>
                <h3 className="text-lg font-semibold text-slate-950" id={dialogTitleId}>
                  Invite person
                </h3>
                <p className="mt-1 text-sm leading-6 text-slate-600" id={dialogDescriptionId}>
                  Choose one or more friendly roles. Detailed access is handled by workspace policy.
                </p>
              </div>
              <button
                aria-label="Close invitation dialog"
                className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 text-lg leading-none text-slate-600 outline-none transition hover:bg-slate-50 hover:text-slate-950 focus-visible:ring-2 focus-visible:ring-cyan-500"
                onClick={() => setIsOpen(false)}
                type="button"
              >
                x
              </button>
            </div>

            <form action={formAction} className="mt-5 grid gap-5">
              <input name="organizationId" type="hidden" value={organizationId} />
              {canAssignInviteRoles
                ? selectedDepartments.map((department) => (
                    <input
                      key={department}
                      name="departmentAccess"
                      type="hidden"
                      value={department}
                    />
                  ))
                : null}
              {!canAssignInviteRoles ? (
                <input name="professionalRoles" type="hidden" value="Artist" />
              ) : null}

              <label className="grid gap-2 text-sm font-medium text-slate-700">
                Email
                <input
                  autoComplete="email"
                  className="h-11 rounded-md border border-slate-300 px-3 text-base text-slate-950 outline-none transition placeholder:text-slate-400 focus:border-cyan-600 focus:ring-2 focus:ring-cyan-100 disabled:bg-slate-100"
                  disabled={!canSubmit}
                  name="email"
                  placeholder="sarah@example.com"
                  required
                  type="email"
                />
              </label>

              {canAssignInviteRoles ? (
                <fieldset className="grid gap-3">
                  <legend className="text-sm font-medium text-slate-700">Invite as</legend>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {INVITE_ROLES.map((role) => {
                      const isSelected = selectedRoles.has(role.label);
                      const descriptionId = `${dialogDescriptionId}-${role.workspaceRole}`;

                      return (
                        <label
                          className="grid min-h-24 cursor-pointer gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm transition focus-within:ring-2 focus-within:ring-cyan-500 focus-within:ring-offset-2 has-[:checked]:border-cyan-500 has-[:checked]:bg-cyan-50 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60"
                          key={role.label}
                        >
                          <span className="flex items-center gap-3 font-semibold text-slate-950">
                            <input
                              aria-describedby={descriptionId}
                              aria-label={`Role ${role.label}`}
                              checked={isSelected}
                              className="h-4 w-4 accent-cyan-600"
                              name="professionalRoles"
                              onChange={() => toggleRole(role.label)}
                              type="checkbox"
                              value={role.professionalRole}
                            />
                            {isSelected ? (
                              <input
                                name="workspaceRoles"
                                type="hidden"
                                value={role.workspaceRole}
                              />
                            ) : null}
                            {role.label}
                          </span>
                          <span className="text-sm leading-5 text-slate-600" id={descriptionId}>
                            {role.description}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                </fieldset>
              ) : null}

              <div className="grid gap-4 sm:grid-cols-[1fr_1fr_auto]">
                <label className="grid gap-2 text-sm font-medium text-slate-700">
                  Expires
                  <select
                    className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950 outline-none transition focus:border-cyan-600 focus:ring-2 focus:ring-cyan-100 disabled:bg-slate-100"
                    defaultValue="7"
                    disabled={!canSubmit}
                    name="expiresInDays"
                  >
                    <option value="1">1 day</option>
                    <option value="7">7 days</option>
                    <option value="14">14 days</option>
                    <option value="30">30 days</option>
                    <option value="90">90 days</option>
                  </select>
                </label>
                <label className="grid gap-2 text-sm font-medium text-slate-700">
                  Maximum uses
                  <input
                    className="h-10 rounded-md border border-slate-300 px-3 text-sm text-slate-950 outline-none transition placeholder:text-slate-400 focus:border-cyan-600 focus:ring-2 focus:ring-cyan-100 disabled:bg-slate-100"
                    disabled={!canSubmit}
                    min="1"
                    name="maximumUses"
                    placeholder="No limit"
                    type="number"
                  />
                </label>
                <div className="flex items-end">
                  <SubmitButton disabled={!canSubmit} />
                </div>
              </div>

              {!canAssignInviteRoles ? (
                <div
                  className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900"
                  role="status"
                >
                  This invitation will use the workspace default starting access.
                </div>
              ) : null}

              {canAssignInviteRoles && selectedRoles.size === 0 ? (
                <div
                  className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900"
                  role="status"
                >
                  Choose at least one role before sending the invitation.
                </div>
              ) : null}

              {state.status === "error" && state.error ? (
                <div
                  aria-live="polite"
                  className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-900"
                  role="alert"
                >
                  {state.error}
                </div>
              ) : null}

              {state.status === "success" && state.inviteLink ? (
                <div
                  aria-live="polite"
                  className="grid gap-2 rounded-md border border-emerald-200 bg-emerald-50 p-4"
                  role="status"
                >
                  <div className="text-sm font-semibold text-emerald-950">Invitation sent</div>
                  <div className="break-all font-mono text-sm text-emerald-900">
                    {state.inviteLink}
                  </div>
                </div>
              ) : null}
            </form>
          </div>
        </div>
      ) : null}
    </div>
  );
}
