"use client";

import { Button, cn } from "@label-os/ui";
import { useRouter } from "next/navigation";
import { FormEvent, useMemo, useState } from "react";

import { useUpdateCurrentProfile } from "../../../lib/profiles";
import type { ProfileAttributeInput, UniversalProfile } from "../../../lib/profiles.types";
import { useActiveWorkspace, useActiveWorkspaceProfile } from "../../../lib/workspace-context";

type RoleModule = {
  key: string;
  title: string;
  detail: string;
  interests: string[];
};

type ProfileOnboardingForm = {
  avatarUrl: string;
  displayName: string;
  headline: string;
  interests: string[];
  timezone: string;
};

const defaultInterests = [
  "Artist development",
  "Campaign planning",
  "Release operations",
  "Catalog strategy",
  "Audience growth",
  "Contracts",
];

const roleModules: RoleModule[] = [
  {
    key: "artist",
    title: "Creative setup",
    detail: "Shape the workspace around music, visuals, audience, and release readiness.",
    interests: ["Songwriting", "Live performance", "Visual identity", "Fan engagement"],
  },
  {
    key: "marketing",
    title: "Marketing setup",
    detail: "Prioritize campaigns, channels, analytics, and launch coordination.",
    interests: ["Campaign strategy", "Content calendar", "Audience segments", "Paid media"],
  },
  {
    key: "legal",
    title: "Rights setup",
    detail: "Keep contracts, approvals, obligations, and document review close at hand.",
    interests: ["Contract review", "Rights management", "Approvals", "Clearances"],
  },
  {
    key: "manager",
    title: "Management setup",
    detail: "Track artist priorities, communication, deadlines, and cross-team follow-through.",
    interests: ["Artist coordination", "Release planning", "Team approvals", "Partner updates"],
  },
];

function normalizedRole(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "_");
}

export function resolveOnboardingRoleModule(roles: string[], departments: string[]): RoleModule {
  const candidates = [...roles, ...departments].map(normalizedRole);
  return (
    roleModules.find((module) =>
      candidates.some((candidate) => candidate.includes(module.key)),
    ) ?? {
      key: "general",
      title: "Workspace setup",
      detail: "Start with the profile details your teammates need to recognize your work.",
      interests: defaultInterests,
    }
  );
}

function browserTimezone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "America/Los_Angeles";
}

function formStateFor(profile: UniversalProfile): ProfileOnboardingForm {
  return {
    avatarUrl: profile.avatar_url ?? "",
    displayName: profile.display_name ?? "",
    headline: profile.headline ?? "",
    interests: profile.attributes
      .filter((attribute) => attribute.attribute_type === "interest")
      .map((attribute) => attribute.value),
    timezone: profile.preferences.timezone ?? browserTimezone(),
  };
}

function normalizeUrl(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  if (/^https?:\/\//i.test(trimmed)) {
    return trimmed;
  }
  return `https://${trimmed}`;
}

export function profileOnboardingAttributes(
  profile: UniversalProfile,
  selectedInterests: string[],
): ProfileAttributeInput[] {
  const onboardingAttributes = selectedInterests.map((interest, index) => ({
    attribute_type: "interest",
    label: "Interest",
    value: interest,
    source: "onboarding",
    is_primary: index === 0,
    sort_order: index,
    metadata: {},
  }));
  const preservedAttributes = profile.attributes
    .filter((attribute) => attribute.attribute_type !== "interest")
    .map((attribute, index) => ({
      attribute_type: attribute.attribute_type,
      label: attribute.label,
      value: attribute.value,
      source: attribute.source,
      is_primary: attribute.is_primary,
      sort_order: onboardingAttributes.length + index,
      metadata: attribute.metadata,
    }));

  return [...onboardingAttributes, ...preservedAttributes];
}

function ToggleChip({
  checked,
  children,
  onClick,
}: {
  checked: boolean;
  children: string;
  onClick: () => void;
}) {
  return (
    <button
      aria-pressed={checked}
      className={cn(
        "rounded-full border px-3 py-2 text-sm font-medium transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500",
        checked
          ? "border-slate-950 bg-slate-950 text-white"
          : "border-slate-200 bg-white text-slate-700 hover:border-sky-200 hover:bg-sky-50",
      )}
      onClick={onClick}
      type="button"
    >
      {children}
    </button>
  );
}

export function UniversalProfileOnboarding({
  hasWorkspace,
  initialProfile,
}: {
  hasWorkspace: boolean;
  initialProfile: UniversalProfile;
}) {
  const router = useRouter();
  const { activeWorkspace, workspaces } = useActiveWorkspace();
  const workspaceProfile = useActiveWorkspaceProfile();
  const mutation = useUpdateCurrentProfile();
  const [form, setForm] = useState(() => formStateFor(initialProfile));
  const [error, setError] = useState<string | null>(null);

  const roleModule = useMemo(
    () => resolveOnboardingRoleModule(workspaceProfile.roles, workspaceProfile.departmentAccess),
    [workspaceProfile.departmentAccess, workspaceProfile.roles],
  );
  const interestOptions = useMemo(
    () => [...new Set([...roleModule.interests, ...defaultInterests])].slice(0, 10),
    [roleModule.interests],
  );

  const toggleInterest = (interest: string) => {
    setForm((current) => ({
      ...current,
      interests: current.interests.includes(interest)
        ? current.interests.filter((item) => item !== interest)
        : [...current.interests, interest].slice(0, 5),
    }));
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    const displayName = form.displayName.replace(/\s+/g, " ").trim();
    if (displayName.length < 2) {
      setError("Enter the name teammates should see in LabelOS.");
      return;
    }

    try {
      await mutation.mutate({
        attributes: profileOnboardingAttributes(initialProfile, form.interests),
        avatar_url: normalizeUrl(form.avatarUrl) || null,
        display_name: displayName,
        headline: form.headline.trim() || null,
        onboarding_status: "complete",
        preferences: {
          timezone: form.timezone.trim() || browserTimezone(),
        },
      });
      router.push(hasWorkspace || workspaces.length > 0 ? "/dashboard" : "/onboarding/workspace");
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Profile onboarding failed.");
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-5">
      <section className="rounded-[20px] border border-white/75 bg-white/72 p-5 shadow-[0_22px_70px_rgba(15,23,42,0.1)] backdrop-blur-2xl sm:p-6">
        <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">
          Universal Profile
        </p>
        <h1 className="mt-2 text-2xl font-semibold tracking-normal text-slate-950">
          Set up your LabelOS identity
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
          Add only the essentials now. Your profile follows you across workspaces and can be
          expanded later.
        </p>
      </section>

      <form className="grid gap-5" onSubmit={submit}>
        <section className="rounded-[18px] border border-white/75 bg-white/68 p-5 shadow-sm backdrop-blur-xl">
          <h2 className="text-lg font-semibold tracking-normal text-slate-950">Basic profile</h2>
          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <label className="block text-sm font-medium text-slate-700">
              Display name
              <input
                autoComplete="name"
                className="mt-1 h-11 w-full rounded-md border border-slate-200 bg-slate-50 px-3 text-base text-slate-950 outline-none transition focus:border-sky-300 focus:bg-white focus-visible:ring-2 focus-visible:ring-sky-500"
                maxLength={200}
                onChange={(event) =>
                  setForm((current) => ({ ...current, displayName: event.target.value }))
                }
                required
                value={form.displayName}
              />
            </label>
            <label className="block text-sm font-medium text-slate-700">
              Timezone
              <input
                autoComplete="off"
                className="mt-1 h-11 w-full rounded-md border border-slate-200 bg-slate-50 px-3 text-base text-slate-950 outline-none transition focus:border-sky-300 focus:bg-white focus-visible:ring-2 focus-visible:ring-sky-500"
                maxLength={120}
                onChange={(event) =>
                  setForm((current) => ({ ...current, timezone: event.target.value }))
                }
                value={form.timezone}
              />
            </label>
            <label className="block text-sm font-medium text-slate-700 sm:col-span-2">
              Headline
              <input
                className="mt-1 h-11 w-full rounded-md border border-slate-200 bg-slate-50 px-3 text-base text-slate-950 outline-none transition focus:border-sky-300 focus:bg-white focus-visible:ring-2 focus-visible:ring-sky-500"
                maxLength={240}
                onChange={(event) =>
                  setForm((current) => ({ ...current, headline: event.target.value }))
                }
                placeholder="Artist, marketer, manager, creator"
                value={form.headline}
              />
            </label>
            <label className="block text-sm font-medium text-slate-700 sm:col-span-2">
              Avatar URL
              <input
                className="mt-1 h-11 w-full rounded-md border border-slate-200 bg-slate-50 px-3 text-base text-slate-950 outline-none transition focus:border-sky-300 focus:bg-white focus-visible:ring-2 focus-visible:ring-sky-500"
                maxLength={2048}
                onChange={(event) =>
                  setForm((current) => ({ ...current, avatarUrl: event.target.value }))
                }
                placeholder="https://..."
                value={form.avatarUrl}
              />
            </label>
          </div>
        </section>

        <section className="rounded-[18px] border border-white/75 bg-white/68 p-5 shadow-sm backdrop-blur-xl">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold tracking-normal text-slate-950">
                {roleModule.title}
              </h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">{roleModule.detail}</p>
            </div>
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700">
              {activeWorkspace?.name ?? "Workspace pending"}
            </div>
          </div>
          <div className="mt-5 flex flex-wrap gap-2">
            {interestOptions.map((interest) => (
              <ToggleChip
                checked={form.interests.includes(interest)}
                key={interest}
                onClick={() => toggleInterest(interest)}
              >
                {interest}
              </ToggleChip>
            ))}
          </div>
        </section>

        <section className="rounded-[18px] border border-white/75 bg-white/68 p-5 shadow-sm backdrop-blur-xl">
          <h2 className="text-lg font-semibold tracking-normal text-slate-950">
            Workspace context
          </h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            {hasWorkspace
              ? "Your active workspace and invitation role are ready. You can switch workspaces after onboarding."
              : "Finish your profile first, then create or join a workspace."}
          </p>
          {workspaceProfile.roles.length ? (
            <div className="mt-4 flex flex-wrap gap-2">
              {workspaceProfile.roles.map((role) => (
                <span
                  className="rounded-full border border-slate-200 bg-white px-3 py-1 text-sm font-medium text-slate-700"
                  key={role}
                >
                  {role}
                </span>
              ))}
            </div>
          ) : null}
        </section>

        {error ? (
          <div
            className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-900"
            role="alert"
          >
            {error}
          </div>
        ) : null}

        <div className="flex justify-end">
          <Button disabled={mutation.isMutating} type="submit">
            {mutation.isMutating ? "Saving" : "Continue"}
          </Button>
        </div>
      </form>
    </div>
  );
}
