"use client";

import { Button, cn } from "@label-os/ui";
import { useEffect } from "react";
import type { ReactNode } from "react";

import { ProfileApiError, useWorkspaceProfile } from "../lib/profiles";
import type { UniversalProfile, WorkspaceProfileMembership } from "../lib/profiles.types";
import {
  ProfileAvatar,
  ProfileDepartmentBadge,
  ProfileName,
  ProfileRoleBadge,
  profileIdentityFromMembership,
} from "./profiles/profile-identity";

type ProfileQuickViewDrawerProps = {
  isOpen: boolean;
  onClose: () => void;
  profileId: string | null;
  workspaceId: string | null;
};

type ProfileQuickViewButtonProps = {
  className?: string;
  disabled?: boolean;
  onOpen: () => void;
};

const publicLinkTypes = new Set([
  "website",
  "spotify",
  "apple_music",
  "youtube",
  "instagram",
  "tiktok",
  "linkedin",
  "github",
  "soundcloud",
  "bandcamp",
  "press_kit",
  "other",
]);

function displayValue(value: string) {
  return value.replace(/[-_]/g, " ");
}

function linkLabel(linkType: string, label: string | null) {
  if (label?.trim()) {
    return label;
  }
  return displayValue(linkType).replace(/\b\w/g, (character) => character.toUpperCase());
}

function sortedPublicLinks(profile: UniversalProfile) {
  return [...profile.links]
    .filter((link) => link.status === "active" && publicLinkTypes.has(link.link_type))
    .sort((a, b) => a.sort_order - b.sort_order);
}

function sortedProfileAttributes(profile: UniversalProfile) {
  return [...profile.attributes]
    .filter((attribute) => attribute.value.trim().length > 0)
    .sort((a, b) => a.sort_order - b.sort_order);
}

function TagList({
  emptyLabel,
  kind,
  values,
}: {
  emptyLabel: string;
  kind: "department" | "role";
  values: string[];
}) {
  if (!values.length) {
    return <span className="text-sm text-slate-400">{emptyLabel}</span>;
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      {values.map((value) =>
        kind === "department" ? (
          <ProfileDepartmentBadge department={value} key={value} />
        ) : (
          <ProfileRoleBadge key={value} role={value} />
        ),
      )}
    </div>
  );
}

function DrawerSection({ children, title }: { children: ReactNode; title: string }) {
  return (
    <section className="border-t border-slate-200 pt-5">
      <h3 className="text-sm font-semibold text-slate-950">{title}</h3>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function ProfileDrawerContent({ membership }: { membership: WorkspaceProfileMembership }) {
  const profile = membership.profile;
  const identity = profileIdentityFromMembership(membership);
  const links = sortedPublicLinks(profile);
  const attributes = sortedProfileAttributes(profile);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex min-w-0 gap-4">
        <ProfileAvatar profile={identity} size="xl" />
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
            Universal Profile
          </p>
          <ProfileName as="h2" className="mt-1 text-xl" profile={identity} />
          <p className="mt-1 text-sm leading-6 text-slate-600">
            {profile.headline ?? "No headline supplied"}
          </p>
          {profile.location ? (
            <p className="mt-2 text-sm font-medium text-slate-500">{profile.location}</p>
          ) : null}
        </div>
      </div>

      {profile.biography ? (
        <p className="whitespace-pre-line text-sm leading-6 text-slate-600">{profile.biography}</p>
      ) : null}

      <DrawerSection title="Workspace Identity">
        <div className="grid gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
              Roles
            </p>
            <div className="mt-2">
              <TagList emptyLabel="No roles assigned" kind="role" values={identity.roles ?? []} />
            </div>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
              Department
            </p>
            <div className="mt-2">
              <TagList
                emptyLabel="No department access"
                kind="department"
                values={identity.departments ?? []}
              />
            </div>
          </div>
        </div>
      </DrawerSection>

      <DrawerSection title="Public Links">
        {links.length ? (
          <div className="grid gap-2">
            {links.map((link) => (
              <a
                className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm transition hover:border-sky-200 hover:bg-sky-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500"
                href={link.url}
                key={link.id}
                rel="noreferrer"
                target="_blank"
              >
                <span className="block font-semibold text-slate-950">
                  {linkLabel(link.link_type, link.label)}
                </span>
                <span className="mt-0.5 block truncate text-slate-500">
                  {link.username || link.url}
                </span>
              </a>
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-500">No public profile links have been added.</p>
        )}
      </DrawerSection>

      <DrawerSection title="Specialized Profile Information">
        {attributes.length ? (
          <dl className="grid gap-3">
            {attributes.map((attribute) => (
              <div key={attribute.id}>
                <dt className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                  {attribute.label || displayValue(attribute.attribute_type)}
                </dt>
                <dd className="mt-1 text-sm leading-6 text-slate-700">{attribute.value}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-sm text-slate-500">No specialized profile information is visible.</p>
        )}
      </DrawerSection>
    </div>
  );
}

function errorMessage(error: ProfileApiError | null) {
  if (!error) {
    return null;
  }
  if (error.code === "forbidden" || error.code === "not_found") {
    return "You do not have access to view this profile in the current workspace.";
  }
  if (error.code === "unauthorized") {
    return "Sign in again to view this profile.";
  }
  return "Profile details could not be loaded.";
}

export function ProfileQuickViewButton({
  className,
  disabled,
  onOpen,
}: ProfileQuickViewButtonProps) {
  return (
    <Button
      aria-label="View profile"
      className={className}
      disabled={disabled}
      onClick={onOpen}
      size="sm"
      variant="secondary"
    >
      View
    </Button>
  );
}

export function ProfileQuickViewDrawer({
  isOpen,
  onClose,
  profileId,
  workspaceId,
}: ProfileQuickViewDrawerProps) {
  const profile = useWorkspaceProfile(isOpen ? workspaceId : null, isOpen ? profileId : null);
  const message = errorMessage(profile.error);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50" role="presentation">
      <button
        aria-label="Dismiss profile drawer"
        className="absolute inset-0 h-full w-full cursor-default bg-slate-950/30"
        onClick={onClose}
        type="button"
      />
      <aside
        aria-labelledby="quick-profile-title"
        aria-modal="true"
        className={cn(
          "absolute right-0 top-0 flex h-full w-full max-w-[440px] flex-col bg-white shadow-2xl",
          "border-l border-slate-200",
        )}
        role="dialog"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-950" id="quick-profile-title">
            Profile
          </h2>
          <Button aria-label="Close profile" onClick={onClose} size="sm" variant="ghost">
            Close
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          {profile.isLoading && !profile.data ? (
            <div className="grid gap-3" aria-label="Profile loading">
              <div className="h-20 rounded-md bg-slate-100 auth-shimmer" />
              <div className="h-28 rounded-md bg-slate-100 auth-shimmer" />
              <div className="h-28 rounded-md bg-slate-100 auth-shimmer" />
            </div>
          ) : null}
          {message ? (
            <div
              className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900"
              role="alert"
            >
              {message}
            </div>
          ) : null}
          {!profile.isLoading && !message && profile.data ? (
            <ProfileDrawerContent membership={profile.data} />
          ) : null}
        </div>
      </aside>
    </div>
  );
}
