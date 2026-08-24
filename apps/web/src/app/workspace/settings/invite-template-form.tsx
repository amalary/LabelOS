"use client";

import { useMemo, useState } from "react";

import { createWorkspaceInviteAction } from "./actions";

const PROFESSIONAL_ROLES = [
  "Artist",
  "Producer",
  "Songwriter",
  "Management",
  "A&R",
  "Legal",
  "Marketing",
  "Finance",
] as const;

const DEPARTMENT_ACCESS_GROUPS = [
  {
    label: "Creative",
    departments: [
      { label: "Artist", value: "artist" },
      { label: "Creative", value: "creative" },
      { label: "Releases", value: "releases" },
      { label: "Analytics", value: "analytics" },
    ],
  },
  {
    label: "Production",
    departments: [
      { label: "Production", value: "production" },
      { label: "Songs", value: "songs" },
      { label: "Sessions", value: "sessions" },
      { label: "Credits", value: "credits" },
    ],
  },
  {
    label: "Management",
    departments: [
      { label: "Management", value: "management" },
      { label: "Campaigns", value: "marketing" },
      { label: "A&R", value: "a&r" },
      { label: "Discovery", value: "discovery" },
      { label: "Evaluations", value: "evaluations" },
    ],
  },
  {
    label: "Legal",
    departments: [
      { label: "Legal", value: "legal" },
      { label: "Contracts", value: "contracts" },
      { label: "Agreement Reviews", value: "agreements" },
    ],
  },
  {
    label: "Finance",
    departments: [
      { label: "Finance", value: "finance" },
      { label: "Royalties", value: "royalties" },
      { label: "Reporting", value: "reporting" },
    ],
  },
  {
    label: "Workspace Administration",
    departments: [{ label: "Workspace Administration", value: "administration" }],
  },
] as const;

const DEFAULT_INVITE_DEPARTMENT_ACCESS = ["artist", "creative", "releases", "analytics"] as const;

type InviteTemplate = {
  id: "artist" | "producer" | "manager" | "legal";
  name: string;
  role: RoleName;
  departments: readonly string[];
  sensitiveAccess?: string;
};

export const INVITE_TEMPLATES: readonly InviteTemplate[] = [
  {
    id: "artist",
    name: "Artist",
    role: "Artist",
    departments: ["artist", "creative", "releases", "analytics"],
  },
  {
    id: "producer",
    name: "Producer",
    role: "Producer",
    departments: ["production", "songs", "sessions", "credits"],
  },
  {
    id: "manager",
    name: "Manager",
    role: "Management",
    departments: ["management", "artist", "releases", "marketing", "analytics"],
  },
  {
    id: "legal",
    name: "Legal",
    role: "Legal",
    departments: ["legal", "contracts"],
    sensitiveAccess: "Requires approval",
  },
] as const;

const DEFAULT_INVITE_TEMPLATE = INVITE_TEMPLATES[0] as InviteTemplate;

type RoleName = (typeof PROFESSIONAL_ROLES)[number];

type InviteTemplateFormProps = {
  organizationId: string;
};

function departmentLabelsFor(template: InviteTemplate): string {
  const labelsByValue = new Map<string, string>(
    DEPARTMENT_ACCESS_GROUPS.flatMap((group) =>
      group.departments.map((department) => [department.value, department.label] as const),
    ),
  );

  return template.departments
    .map((department) => labelsByValue.get(department) ?? department)
    .join(", ");
}

export function InviteTemplateForm({ organizationId }: InviteTemplateFormProps) {
  const [selectedTemplateId, setSelectedTemplateId] = useState<InviteTemplate["id"]>(
    DEFAULT_INVITE_TEMPLATE.id,
  );
  const selectedTemplate = useMemo(
    () => INVITE_TEMPLATES.find((template) => template.id === selectedTemplateId),
    [selectedTemplateId],
  );
  const [selectedRoles, setSelectedRoles] = useState<Set<string>>(
    () => new Set([DEFAULT_INVITE_TEMPLATE.role]),
  );
  const [selectedDepartments, setSelectedDepartments] = useState<Set<string>>(
    () => new Set(DEFAULT_INVITE_DEPARTMENT_ACCESS),
  );

  function applyTemplate(template: InviteTemplate) {
    setSelectedTemplateId(template.id);
    setSelectedRoles(new Set([template.role]));
    setSelectedDepartments(new Set(template.departments));
  }

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

  function toggleDepartment(department: string) {
    setSelectedDepartments((currentDepartments) => {
      const nextDepartments = new Set(currentDepartments);
      if (nextDepartments.has(department)) {
        nextDepartments.delete(department);
      } else {
        nextDepartments.add(department);
      }
      return nextDepartments;
    });
  }

  return (
    <form action={createWorkspaceInviteAction} className="grid gap-5">
      <input name="organizationId" type="hidden" value={organizationId} />
      <label className="grid gap-2 text-sm font-medium text-slate-700">
        Email
        <input
          className="h-10 border border-slate-300 px-3 text-sm text-slate-950 outline-none focus:border-slate-950"
          name="email"
          placeholder="sarah@example.com"
          required
          type="email"
        />
      </label>

      <div className="grid gap-3">
        <div>
          <div className="text-sm font-medium text-slate-700">Invite Template</div>
          <p className="mt-1 text-sm leading-6 text-slate-600">
            Start from a common access preset, then customize it before creating the invite.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {INVITE_TEMPLATES.map((template) => {
            const isSelected = selectedTemplateId === template.id;
            return (
              <button
                aria-pressed={isSelected}
                className="grid min-h-28 gap-2 border border-slate-200 bg-slate-50 p-3 text-left text-sm transition hover:border-cyan-500 aria-pressed:border-cyan-500 aria-pressed:bg-cyan-50"
                key={template.id}
                onClick={() => applyTemplate(template)}
                type="button"
              >
                <span className="font-semibold text-slate-950">{template.name}</span>
                <span className="text-slate-700">Role: {template.role}</span>
                <span className="text-xs leading-5 text-slate-600">
                  {departmentLabelsFor(template)}
                </span>
                {template.sensitiveAccess ? (
                  <span className="w-fit border border-amber-300 bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-900">
                    {template.sensitiveAccess}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
        {selectedTemplate?.sensitiveAccess ? (
          <div className="border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            Sensitive access: {selectedTemplate.sensitiveAccess}
          </div>
        ) : null}
      </div>

      <div>
        <div className="text-sm font-medium text-slate-700">Invite As</div>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {PROFESSIONAL_ROLES.map((role) => (
            <label
              className="flex min-h-11 items-center gap-3 border border-slate-200 bg-slate-50 px-3 text-sm font-medium text-slate-800 transition has-[:checked]:border-cyan-500 has-[:checked]:bg-cyan-50"
              key={role}
            >
              <input
                aria-label={`Role ${role}`}
                checked={selectedRoles.has(role)}
                className="h-4 w-4 accent-cyan-600"
                name="professionalRoles"
                onChange={() => toggleRole(role)}
                type="checkbox"
                value={role}
              />
              {role}
            </label>
          ))}
        </div>
      </div>

      <div className="grid gap-3">
        <div>
          <div className="text-sm font-medium text-slate-700">Department Access</div>
          <p className="mt-1 text-sm leading-6 text-slate-600">
            Choose the exact workspace areas this invitation grants on acceptance.
          </p>
        </div>
        <div className="grid gap-4">
          {DEPARTMENT_ACCESS_GROUPS.map((group) => (
            <fieldset className="border border-slate-200 p-3" key={group.label}>
              <legend className="px-1 text-sm font-semibold text-slate-950">{group.label}</legend>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {group.departments.map((department) => (
                  <label
                    className="flex min-h-10 items-center gap-3 bg-slate-50 px-3 text-sm font-medium text-slate-800 transition has-[:checked]:bg-cyan-50 has-[:checked]:text-slate-950"
                    key={department.value}
                  >
                    <input
                      aria-label={`Department ${department.label}`}
                      checked={selectedDepartments.has(department.value)}
                      className="h-4 w-4 accent-cyan-600"
                      name="departmentAccess"
                      onChange={() => toggleDepartment(department.value)}
                      type="checkbox"
                      value={department.value}
                    />
                    {department.label}
                  </label>
                ))}
              </div>
            </fieldset>
          ))}
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <label className="grid gap-2 text-sm font-medium text-slate-700">
          Expiration
          <select
            className="h-10 border border-slate-300 bg-white px-3 text-sm text-slate-950 outline-none focus:border-slate-950"
            defaultValue="7"
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
            className="h-10 border border-slate-300 px-3 text-sm text-slate-950 outline-none focus:border-slate-950"
            min="1"
            name="maximumUses"
            placeholder="No limit"
            type="number"
          />
        </label>
        <div className="flex items-end">
          <button
            className="h-10 w-full bg-slate-950 px-4 text-sm font-semibold text-white outline-none transition hover:bg-slate-800 focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:ring-offset-2"
            type="submit"
          >
            Create Invite
          </button>
        </div>
      </div>
    </form>
  );
}
