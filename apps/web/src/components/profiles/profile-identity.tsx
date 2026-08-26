"use client";

import { Badge, cn } from "@label-os/ui";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import type {
  UniversalProfile,
  WorkspacePeopleDirectoryEntry,
  WorkspaceProfileMembership,
} from "../../lib/profiles.types";

export type ProfileIdentity = {
  id: string;
  displayName: string | null;
  headline?: string | null;
  avatarUrl?: string | null;
  roles?: string[];
  departments?: string[];
  status?: string | null;
};

export type ProfileAvatarSize = "xs" | "sm" | "md" | "lg" | "xl";

const avatarSizes: Record<ProfileAvatarSize, string> = {
  xs: "h-6 w-6 text-[0.625rem]",
  sm: "h-8 w-8 text-xs",
  md: "h-10 w-10 text-sm",
  lg: "h-12 w-12 text-base",
  xl: "h-16 w-16 text-lg",
};

function displayValue(value: string) {
  return value.replace(/[-_]/g, " ");
}

export function profileDisplayName(profile: Pick<ProfileIdentity, "displayName"> | null) {
  return profile?.displayName?.trim() || "Unnamed profile";
}

export function profileInitials(profile: Pick<ProfileIdentity, "displayName"> | null) {
  const name = profile?.displayName?.trim();
  if (!name) {
    return "UP";
  }

  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

export function profileIdentityFromUniversalProfile(profile: UniversalProfile): ProfileIdentity {
  return {
    id: profile.id,
    displayName: profile.display_name,
    headline: profile.headline,
    avatarUrl: profile.avatar_url,
    status: profile.profile_status,
  };
}

export function profileIdentityFromMembership(
  membership: WorkspaceProfileMembership,
): ProfileIdentity {
  return {
    ...profileIdentityFromUniversalProfile(membership.profile),
    roles: [...membership.professional_roles, ...membership.workspace_roles],
    departments: membership.department_access,
    status: membership.status,
  };
}

export function profileIdentityFromDirectoryEntry(
  person: WorkspacePeopleDirectoryEntry,
): ProfileIdentity {
  return {
    id: person.profile_id,
    displayName: person.display_name,
    headline: person.headline,
    avatarUrl: person.avatar_url,
    roles: person.roles,
    departments: person.departments,
    status: person.membership_status,
  };
}

export function ProfileAvatar({
  className,
  profile,
  size = "md",
}: {
  className?: string;
  profile: ProfileIdentity | null;
  size?: ProfileAvatarSize;
}) {
  const name = profileDisplayName(profile);

  return (
    <div
      aria-label={`${name} avatar`}
      className={cn(
        "shrink-0 overflow-hidden rounded-md border border-slate-200 bg-slate-950 font-semibold text-white",
        avatarSizes[size],
        className,
      )}
      role="img"
    >
      {profile?.avatarUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          alt=""
          className="h-full w-full object-cover"
          referrerPolicy="no-referrer"
          src={profile.avatarUrl}
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center">
          {profileInitials(profile)}
        </div>
      )}
    </div>
  );
}

export function ProfileName({
  as = "span",
  className,
  profile,
  showHeadline = false,
}: {
  as?: "h2" | "span";
  className?: string;
  profile: ProfileIdentity | null;
  showHeadline?: boolean;
}) {
  const Component = as;

  return (
    <Component className={cn("block min-w-0", className)}>
      <span className="block truncate font-semibold text-slate-950">
        {profileDisplayName(profile)}
      </span>
      {showHeadline ? (
        <span className="mt-0.5 block truncate text-sm font-normal text-slate-500">
          {profile?.headline?.trim() || "No headline"}
        </span>
      ) : null}
    </Component>
  );
}

export function ProfileRoleBadge({ role }: { role: string }) {
  return (
    <Badge className="rounded-md capitalize" variant="neutral">
      {displayValue(role)}
    </Badge>
  );
}

export function ProfileDepartmentBadge({ department }: { department: string }) {
  return (
    <Badge className="rounded-md border-sky-200 bg-sky-50 capitalize text-sky-800" variant="neutral">
      {displayValue(department)}
    </Badge>
  );
}

function IdentityBadges({
  departments = [],
  roles = [],
}: {
  departments?: string[];
  roles?: string[];
}) {
  if (!roles.length && !departments.length) {
    return null;
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      {roles.map((role) => (
        <ProfileRoleBadge key={`role-${role}`} role={role} />
      ))}
      {departments.map((department) => (
        <ProfileDepartmentBadge department={department} key={`department-${department}`} />
      ))}
    </div>
  );
}

export function ProfileChip({
  className,
  onRemove,
  profile,
}: {
  className?: string;
  onRemove?: (profileId: string) => void;
  profile: ProfileIdentity;
}) {
  return (
    <span
      className={cn(
        "inline-flex min-w-0 items-center gap-2 rounded-md border border-slate-200 bg-white px-2 py-1 text-sm shadow-sm",
        className,
      )}
      data-profile-id={profile.id}
    >
      <ProfileAvatar profile={profile} size="xs" />
      <ProfileName className="max-w-48" profile={profile} />
      {onRemove ? (
        <button
          aria-label={`Remove ${profileDisplayName(profile)}`}
          className="flex h-5 w-5 items-center justify-center rounded text-slate-500 hover:bg-slate-100 hover:text-slate-950 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-700"
          onClick={() => onRemove(profile.id)}
          type="button"
        >
          x
        </button>
      ) : null}
    </span>
  );
}

export function ProfileCard({
  actions,
  className,
  profile,
}: {
  actions?: ReactNode;
  className?: string;
  profile: ProfileIdentity;
}) {
  return (
    <article
      className={cn("rounded-md border border-slate-200 bg-white p-4 shadow-sm", className)}
      data-profile-id={profile.id}
    >
      <div className="flex min-w-0 gap-3">
        <ProfileAvatar profile={profile} size="lg" />
        <div className="min-w-0 flex-1">
          <ProfileName profile={profile} showHeadline />
          <div className="mt-3">
            <IdentityBadges departments={profile.departments} roles={profile.roles} />
          </div>
        </div>
        {actions ? <div className="shrink-0">{actions}</div> : null}
      </div>
    </article>
  );
}

export function ProfilePopover({
  children,
  profile,
}: {
  children?: ReactNode;
  profile: ProfileIdentity;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const id = useId();

  return (
    <span className="relative inline-flex">
      <button
        aria-controls={isOpen ? id : undefined}
        aria-expanded={isOpen}
        className="rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-700"
        onBlur={() => setIsOpen(false)}
        onClick={() => setIsOpen((current) => !current)}
        onFocus={() => setIsOpen(true)}
        onMouseEnter={() => setIsOpen(true)}
        onMouseLeave={() => setIsOpen(false)}
        type="button"
      >
        {children ?? <ProfileChip profile={profile} />}
      </button>
      {isOpen ? (
        <span
          className="absolute left-0 top-full z-30 mt-2 block w-72 rounded-md border border-slate-200 bg-white p-4 text-left shadow-lg"
          id={id}
          role="dialog"
        >
          <ProfileCard className="border-0 p-0 shadow-none" profile={profile} />
        </span>
      ) : null}
    </span>
  );
}

export function ProfileSelector({
  className,
  disabled,
  emptyLabel = "No profiles available",
  onChange,
  placeholder = "Select profile",
  profiles,
  value,
}: {
  className?: string;
  disabled?: boolean;
  emptyLabel?: string;
  onChange: (profileId: string | null) => void;
  placeholder?: string;
  profiles: ProfileIdentity[];
  value: string | null;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const listboxId = useId();
  const selected = profiles.find((profile) => profile.id === value) ?? null;
  const buttonRef = useRef<HTMLButtonElement>(null);
  const optionRefs = useRef(new Map<string, HTMLButtonElement>());

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const firstProfile = selected ?? profiles[0];
    if (firstProfile) {
      optionRefs.current.get(firstProfile.id)?.focus();
    }
  }, [isOpen, profiles, selected]);

  function selectProfile(profileId: string | null) {
    onChange(profileId);
    setIsOpen(false);
    buttonRef.current?.focus();
  }

  function onButtonKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setIsOpen(true);
    }
  }

  function onOptionKeyDown(event: KeyboardEvent<HTMLButtonElement>, profileId: string) {
    const index = profiles.findIndex((profile) => profile.id === profileId);
    if (event.key === "Escape") {
      event.preventDefault();
      setIsOpen(false);
      buttonRef.current?.focus();
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      const next = profiles[Math.min(index + 1, profiles.length - 1)];
      if (next) {
        optionRefs.current.get(next.id)?.focus();
      }
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      const previous = profiles[Math.max(index - 1, 0)];
      if (previous) {
        optionRefs.current.get(previous.id)?.focus();
      }
    }
  }

  return (
    <div className={cn("relative", className)}>
      <button
        aria-controls={isOpen ? listboxId : undefined}
        aria-expanded={isOpen}
        className={cn(
          "inline-flex h-10 w-full items-center justify-between rounded-md border border-slate-300 bg-white px-4 text-sm font-medium text-slate-950 transition-colors hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-700 disabled:cursor-not-allowed disabled:opacity-50",
        )}
        disabled={disabled}
        onClick={() => setIsOpen((current) => !current)}
        onKeyDown={onButtonKeyDown}
        ref={buttonRef}
        type="button"
      >
        {selected ? (
          <span className="flex min-w-0 items-center gap-2">
            <ProfileAvatar profile={selected} size="xs" />
            <ProfileName className="max-w-56 text-left" profile={selected} />
          </span>
        ) : (
          <span className="text-slate-500">{placeholder}</span>
        )}
        <span aria-hidden="true" className="ml-3 text-slate-400">
          v
        </span>
      </button>
      {isOpen ? (
        <div
          className="absolute left-0 right-0 top-full z-20 mt-2 max-h-72 overflow-y-auto rounded-md border border-slate-200 bg-white p-1 shadow-lg"
          id={listboxId}
          role="listbox"
        >
          {profiles.length ? (
            profiles.map((profile) => (
              <button
                aria-selected={profile.id === value}
                className={cn(
                  "flex w-full min-w-0 items-center gap-2 rounded px-2 py-2 text-left text-sm hover:bg-slate-50 focus:bg-slate-50 focus:outline-none",
                  profile.id === value ? "bg-slate-100" : "bg-white",
                )}
                data-profile-id={profile.id}
                key={profile.id}
                onClick={() => selectProfile(profile.id)}
                onKeyDown={(event) => onOptionKeyDown(event, profile.id)}
                ref={(node) => {
                  if (node) {
                    optionRefs.current.set(profile.id, node);
                  } else {
                    optionRefs.current.delete(profile.id);
                  }
                }}
                role="option"
                type="button"
              >
                <ProfileAvatar profile={profile} size="sm" />
                <ProfileName profile={profile} showHeadline />
              </button>
            ))
          ) : (
            <div className="px-3 py-2 text-sm text-slate-500" role="status">
              {emptyLabel}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

export function ProfileMultiSelect({
  className,
  disabled,
  emptyLabel = "No profiles available",
  onChange,
  profiles,
  values,
}: {
  className?: string;
  disabled?: boolean;
  emptyLabel?: string;
  onChange: (profileIds: string[]) => void;
  profiles: ProfileIdentity[];
  values: string[];
}) {
  const selectedIds = useMemo(() => new Set(values), [values]);

  function toggleProfile(profileId: string) {
    const next = new Set(selectedIds);
    if (next.has(profileId)) {
      next.delete(profileId);
    } else {
      next.add(profileId);
    }
    onChange([...next]);
  }

  return (
    <div className={cn("rounded-md border border-slate-200 bg-white", className)}>
      {profiles.length ? (
        <div className="max-h-72 overflow-y-auto p-1">
          {profiles.map((profile) => (
            <label
              className={cn(
                "flex min-w-0 cursor-pointer items-center gap-3 rounded px-2 py-2 hover:bg-slate-50",
                disabled ? "cursor-not-allowed opacity-60" : null,
              )}
              data-profile-id={profile.id}
              key={profile.id}
            >
              <input
                checked={selectedIds.has(profile.id)}
                className="h-4 w-4 rounded border-slate-300 text-slate-950 focus:ring-slate-700"
                disabled={disabled}
                onChange={() => toggleProfile(profile.id)}
                type="checkbox"
              />
              <ProfileAvatar profile={profile} size="sm" />
              <ProfileName profile={profile} showHeadline />
            </label>
          ))}
        </div>
      ) : (
        <div className="px-3 py-2 text-sm text-slate-500" role="status">
          {emptyLabel}
        </div>
      )}
    </div>
  );
}
