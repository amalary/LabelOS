"use client";

import { Button, cn } from "@label-os/ui";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { useCurrentProfile, useUpdateCurrentProfile } from "../../lib/profiles";
import { profileCompletionViewModel } from "../../lib/profile-completion";
import type { ProfileLinkInput, UniversalProfile } from "../../lib/profiles.types";
import { useActiveWorkspace, useActiveWorkspaceProfile } from "../../lib/workspace-context";

type SupportedService = {
  type: string;
  label: string;
  placeholder: string;
};

const supportedServices: SupportedService[] = [
  { type: "website", label: "Website", placeholder: "https://example.com" },
  { type: "spotify", label: "Spotify", placeholder: "https://open.spotify.com/artist/..." },
  { type: "apple_music", label: "Apple Music", placeholder: "https://music.apple.com/..." },
  { type: "youtube", label: "YouTube", placeholder: "https://youtube.com/..." },
  { type: "instagram", label: "Instagram", placeholder: "https://instagram.com/..." },
  { type: "tiktok", label: "TikTok", placeholder: "https://tiktok.com/@..." },
  { type: "linkedin", label: "LinkedIn", placeholder: "https://linkedin.com/in/..." },
  { type: "github", label: "GitHub", placeholder: "https://github.com/..." },
];

type ProfileFormState = {
  display_name: string;
  headline: string;
  biography: string;
  avatar_url: string;
  location: string;
  links: Record<string, string>;
  other_label: string;
  other_url: string;
};

function initialsForProfile(profile: UniversalProfile | null) {
  const name = profile?.display_name?.trim();
  if (!name) {
    return "LO";
  }
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

function serviceLabel(type: string) {
  return (
    supportedServices.find((service) => service.type === type)?.label ?? type.replace(/_/g, " ")
  );
}

function linkMapFor(profile: UniversalProfile | null) {
  return Object.fromEntries(
    supportedServices.map((service) => [
      service.type,
      profile?.links.find((link) => link.link_type === service.type)?.url ?? "",
    ]),
  );
}

function formStateFor(profile: UniversalProfile | null): ProfileFormState {
  const otherLink =
    profile?.links.find(
      (link) => !supportedServices.some((service) => service.type === link.link_type),
    ) ?? null;

  return {
    display_name: profile?.display_name ?? "",
    headline: profile?.headline ?? "",
    biography: profile?.biography ?? "",
    avatar_url: profile?.avatar_url ?? "",
    location: profile?.location ?? "",
    links: linkMapFor(profile),
    other_label: otherLink?.label ?? (otherLink ? serviceLabel(otherLink.link_type) : ""),
    other_url: otherLink?.url ?? "",
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

function profileLinksForSave(
  profile: UniversalProfile,
  form: ProfileFormState,
): ProfileLinkInput[] {
  const editableLinks = supportedServices
    .map((service, index) => ({
      link_type: service.type,
      label: service.label,
      url: normalizeUrl(form.links[service.type] ?? ""),
      username: null,
      external_id: null,
      status: "active",
      is_primary: service.type === "website",
      sort_order: index,
      metadata: {},
    }))
    .filter((link) => link.url);

  const otherUrl = normalizeUrl(form.other_url);
  const otherLinks: ProfileLinkInput[] = otherUrl
    ? [
        {
          link_type: "other",
          label: form.other_label.trim() || "Other",
          url: otherUrl,
          username: null,
          external_id: null,
          status: "active",
          is_primary: false,
          sort_order: supportedServices.length,
          metadata: {},
        },
      ]
    : [];

  const preservedLinks = profile.links
    .filter((link) => {
      if (supportedServices.some((service) => service.type === link.link_type)) {
        return false;
      }
      if (link.link_type === "other") {
        return false;
      }
      return true;
    })
    .map((link, index) => ({
      link_type: link.link_type,
      label: link.label,
      url: link.url,
      username: link.username,
      external_id: link.external_id,
      status: link.status,
      is_primary: link.is_primary,
      sort_order: supportedServices.length + otherLinks.length + index,
      metadata: link.metadata,
    }));

  return [...editableLinks, ...otherLinks, ...preservedLinks];
}

function EmptyValue({ children }: { children: string }) {
  return <span className="text-slate-400">{children}</span>;
}

export function ProfileAvatar({ profile }: { profile: UniversalProfile | null }) {
  return (
    <div className="relative h-24 w-24 shrink-0 overflow-hidden rounded-[24px] border border-white/80 bg-slate-950 text-white shadow-[0_24px_55px_rgba(15,23,42,0.18)]">
      {profile?.avatar_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          alt=""
          className="h-full w-full object-cover"
          referrerPolicy="no-referrer"
          src={profile.avatar_url}
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center bg-[linear-gradient(135deg,#0f172a,#164e63_58%,#0f766e)] text-2xl font-semibold">
          {initialsForProfile(profile)}
        </div>
      )}
    </div>
  );
}

export function ProfileHeader({
  isEditing,
  onEdit,
  profile,
}: {
  isEditing: boolean;
  onEdit: () => void;
  profile: UniversalProfile;
}) {
  return (
    <section className="relative overflow-hidden rounded-[24px] border border-white/75 bg-white/72 p-5 shadow-[0_22px_70px_rgba(15,23,42,0.1)] backdrop-blur-2xl sm:p-6">
      <div className="pointer-events-none absolute inset-x-6 top-0 h-px bg-gradient-to-r from-transparent via-sky-300/80 to-transparent" />
      <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 flex-col gap-4 sm:flex-row">
          <ProfileAvatar profile={profile} />
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
              Universal Profile
            </p>
            <h1 className="mt-2 text-3xl font-semibold tracking-normal text-slate-950">
              {profile.display_name || <EmptyValue>Unnamed profile</EmptyValue>}
            </h1>
            <p className="mt-2 max-w-2xl text-base leading-7 text-slate-700">
              {profile.headline || <EmptyValue>Add a headline</EmptyValue>}
            </p>
            {profile.location ? (
              <p className="mt-3 text-sm font-medium text-slate-500">{profile.location}</p>
            ) : null}
          </div>
        </div>
        <Button disabled={isEditing} onClick={onEdit} size="sm" variant="secondary">
          Edit Profile
        </Button>
      </div>
      <p className="mt-6 max-w-3xl whitespace-pre-line text-sm leading-7 text-slate-600">
        {profile.biography || (
          <EmptyValue>Add a biography that travels with your workspace identity.</EmptyValue>
        )}
      </p>
    </section>
  );
}

export function IdentitySection({
  departments,
  roles,
  workspaceName,
}: {
  departments: string[];
  roles: string[];
  workspaceName: string | null;
}) {
  return (
    <section className="rounded-[18px] border border-white/75 bg-white/68 p-5 shadow-sm backdrop-blur-xl">
      <h2 className="text-lg font-semibold tracking-normal text-slate-950">LabelOS Identity</h2>
      <div className="mt-5 grid gap-5 md:grid-cols-3">
        <IdentityBlock label="Current roles" values={roles} />
        <IdentityBlock label="Departments" values={departments} />
        <IdentityBlock label="Current workspace" values={workspaceName ? [workspaceName] : []} />
      </div>
    </section>
  );
}

function IdentityBlock({ label, values }: { label: string; values: string[] }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {values.length ? (
          values.map((value) => (
            <span
              className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-sm font-medium text-slate-700"
              key={value}
            >
              {value}
            </span>
          ))
        ) : (
          <EmptyValue>Not supplied</EmptyValue>
        )}
      </div>
    </div>
  );
}

export function LinksSection({ profile }: { profile: UniversalProfile }) {
  const sortedLinks = [...profile.links].sort((a, b) => a.sort_order - b.sort_order);

  return (
    <section className="rounded-[18px] border border-white/75 bg-white/68 p-5 shadow-sm backdrop-blur-xl">
      <h2 className="text-lg font-semibold tracking-normal text-slate-950">Links</h2>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {sortedLinks.length ? (
          sortedLinks.map((link) => (
            <a
              className="group rounded-lg border border-slate-200 bg-white/72 px-4 py-3 transition hover:border-sky-200 hover:bg-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500"
              href={link.url}
              key={link.id}
              rel="noreferrer"
              target="_blank"
            >
              <span className="block text-sm font-semibold text-slate-950">
                {link.label || serviceLabel(link.link_type)}
              </span>
              <span className="mt-1 block truncate text-sm text-slate-500">
                {link.username || link.url}
              </span>
            </a>
          ))
        ) : (
          <p className="text-sm leading-6 text-slate-500">No public links have been added yet.</p>
        )}
      </div>
    </section>
  );
}

export function ProfileCompletionPrompt({ profile }: { profile: UniversalProfile }) {
  const completionPrompt = profileCompletionViewModel(profile);
  if (!completionPrompt) {
    return null;
  }

  const completion = profile.profile_completion;

  return (
    <section className="rounded-[18px] border border-sky-200 bg-sky-50 p-5 text-sky-950 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-normal">{completionPrompt.title}</h2>
          <p className="mt-1 text-sm leading-6 text-sky-800">{completionPrompt.missingSummary}</p>
        </div>
        {completion ? (
          <span className="inline-flex h-8 items-center rounded-md border border-sky-200 bg-white/80 px-3 text-sm font-semibold text-sky-950">
            {completion.percent}% complete
          </span>
        ) : null}
      </div>
    </section>
  );
}

function ProfileEditForm({
  form,
  isSaving,
  onCancel,
  onChange,
  onLinkChange,
  onSubmit,
}: {
  form: ProfileFormState;
  isSaving: boolean;
  onCancel: () => void;
  onChange: (field: keyof Omit<ProfileFormState, "links">, value: string) => void;
  onLinkChange: (type: string, value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form
      className="rounded-[18px] border border-slate-200 bg-white p-5 shadow-[0_18px_55px_rgba(15,23,42,0.08)]"
      onSubmit={onSubmit}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">Edit profile</h2>
          <p className="mt-1 text-sm leading-6 text-slate-500">
            Updates save to your Universal Profile.
          </p>
        </div>
        <div className="flex gap-2">
          <Button disabled={isSaving} onClick={onCancel} size="sm" variant="ghost">
            Cancel
          </Button>
          <Button disabled={isSaving} size="sm" type="submit">
            {isSaving ? "Saving" : "Save"}
          </Button>
        </div>
      </div>

      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <ProfileField
          label="Display name"
          value={form.display_name}
          onChange={(value) => onChange("display_name", value)}
        />
        <ProfileField
          label="Headline"
          value={form.headline}
          onChange={(value) => onChange("headline", value)}
        />
        <ProfileField
          label="Location"
          value={form.location}
          onChange={(value) => onChange("location", value)}
        />
        <ProfileField
          label="Avatar URL"
          value={form.avatar_url}
          onChange={(value) => onChange("avatar_url", value)}
        />
        <ProfileField
          className="md:col-span-2"
          label="Biography"
          multiline
          value={form.biography}
          onChange={(value) => onChange("biography", value)}
        />
      </div>

      <div className="mt-6">
        <h3 className="text-sm font-semibold text-slate-950">Supported links</h3>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {supportedServices.map((service) => (
            <ProfileField
              key={service.type}
              label={service.label}
              placeholder={service.placeholder}
              value={form.links[service.type] ?? ""}
              onChange={(value) => onLinkChange(service.type, value)}
            />
          ))}
          <ProfileField
            label="Other label"
            value={form.other_label}
            onChange={(value) => onChange("other_label", value)}
          />
          <ProfileField
            label="Other URL"
            value={form.other_url}
            onChange={(value) => onChange("other_url", value)}
          />
        </div>
      </div>
    </form>
  );
}

function ProfileField({
  className,
  label,
  multiline,
  onChange,
  placeholder,
  value,
}: {
  className?: string;
  label: string;
  multiline?: boolean;
  onChange: (value: string) => void;
  placeholder?: string;
  value: string;
}) {
  const fieldClassName =
    "mt-1 w-full rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-sky-300 focus:bg-white focus-visible:ring-2 focus-visible:ring-sky-500";

  return (
    <label className={cn("block text-sm font-medium text-slate-700", className)}>
      {label}
      {multiline ? (
        <textarea
          className={cn(fieldClassName, "min-h-28 resize-y leading-6")}
          onChange={(event) => onChange(event.target.value)}
          value={value}
        />
      ) : (
        <input
          className={fieldClassName}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          type="text"
          value={value}
        />
      )}
    </label>
  );
}

export function UniversalProfileInterface() {
  const { activeWorkspace } = useActiveWorkspace();
  const currentProfile = useCurrentProfile();
  const workspaceProfile = useActiveWorkspaceProfile();
  const mutation = useUpdateCurrentProfile();
  const [isEditing, setIsEditing] = useState(false);
  const [form, setForm] = useState<ProfileFormState>(() => formStateFor(null));
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (currentProfile.data && !isEditing) {
      setForm(formStateFor(currentProfile.data));
    }
  }, [currentProfile.data, isEditing]);

  const roles = useMemo(() => workspaceProfile.roles, [workspaceProfile.roles]);
  const departments = workspaceProfile.departmentAccess;

  if (currentProfile.isLoading && !currentProfile.data) {
    return (
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
        <div className="h-48 rounded-[24px] border border-white/70 bg-white/60 auth-shimmer" />
        <div className="h-36 rounded-[18px] border border-white/70 bg-white/60 auth-shimmer" />
      </div>
    );
  }

  if (currentProfile.error || !currentProfile.data) {
    return (
      <div className="mx-auto max-w-3xl rounded-[18px] border border-red-200 bg-red-50 p-5 text-sm leading-6 text-red-900">
        Profile data could not be loaded. Sign in again or refresh the page.
      </div>
    );
  }

  const profile = currentProfile.data;

  const updateField = (field: keyof Omit<ProfileFormState, "links">, value: string) => {
    setForm((current) => ({ ...current, [field]: value }));
  };

  const updateLink = (type: string, value: string) => {
    setForm((current) => ({ ...current, links: { ...current.links, [type]: value } }));
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaveError(null);
    try {
      await mutation.mutate({
        display_name: form.display_name.trim(),
        headline: form.headline.trim() || null,
        biography: form.biography.trim() || null,
        avatar_url: normalizeUrl(form.avatar_url) || null,
        location: form.location.trim() || null,
        links: profileLinksForSave(profile, form),
      });
      setIsEditing(false);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "Profile update failed.");
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-5">
      <ProfileHeader isEditing={isEditing} onEdit={() => setIsEditing(true)} profile={profile} />
      <ProfileCompletionPrompt profile={profile} />

      {isEditing ? (
        <ProfileEditForm
          form={form}
          isSaving={mutation.isMutating}
          onCancel={() => {
            setForm(formStateFor(profile));
            setSaveError(null);
            setIsEditing(false);
          }}
          onChange={updateField}
          onLinkChange={updateLink}
          onSubmit={submit}
        />
      ) : null}

      {saveError ? (
        <div
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
          role="alert"
        >
          {saveError}
        </div>
      ) : null}

      <div className="grid gap-5">
        <IdentitySection
          departments={departments}
          roles={roles}
          workspaceName={activeWorkspace?.name ?? null}
        />
        <LinksSection profile={profile} />
      </div>
    </div>
  );
}
