"use client";

import { cn } from "@label-os/ui";
import Link from "next/link";

import {
  ProfileAvatar,
  ProfileName,
  profileIdentityFromDirectoryEntry,
} from "../../components/profiles/profile-identity";
import { useWorkspacePeopleDirectory } from "../../lib/profiles";
import { useActiveWorkspace } from "../../lib/workspace-context";

export function ArtistProfilesWorkspace() {
  const { activeWorkspace } = useActiveWorkspace();
  const directory = useWorkspacePeopleDirectory(activeWorkspace?.id ?? null, {
    limit: 50,
    offset: 0,
  });
  const artists =
    directory.data?.people.filter((person) => person.artist_profile_id !== null) ?? [];

  if (!activeWorkspace) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900">
        Choose a workspace to view artist profiles.
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4">
      <div className="border-b border-slate-200 pb-4">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
          Universal Profiles
        </p>
        <h1 className="mt-2 text-2xl font-semibold tracking-normal text-slate-950">
          Artist Profiles
        </h1>
        <p className="mt-1 text-sm leading-6 text-slate-500">{activeWorkspace.name}</p>
      </div>

      {directory.error ? (
        <div
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
          role="alert"
        >
          Artist profiles could not be loaded.
        </div>
      ) : null}

      <div className="overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 bg-slate-50 px-4 py-3 text-sm font-medium text-slate-700">
          {directory.isLoading && !directory.data
            ? "Loading artist profiles"
            : `${artists.length} artist profile${artists.length === 1 ? "" : "s"}`}
        </div>
        {directory.isLoading && !directory.data ? (
          <div className="grid gap-3 p-4">
            {Array.from({ length: 4 }, (_, index) => (
              <div className="h-16 rounded-md bg-slate-100 auth-shimmer" key={index} />
            ))}
          </div>
        ) : artists.length === 0 ? (
          <div className="p-8 text-center">
            <h2 className="text-base font-semibold text-slate-950">
              No artist profile modules found
            </h2>
            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">
              Artist profile modules appear here after an artist is linked to a Universal Profile.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {artists.map((person) => {
              const identity = profileIdentityFromDirectoryEntry(person);

              return (
                <div
                  className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
                  key={person.id}
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <ProfileAvatar profile={identity} />
                    <ProfileName profile={identity} showHeadline />
                  </div>
                  <Link
                    className={cn(
                      "inline-flex h-8 w-full items-center justify-center rounded-md border border-slate-300 bg-white px-3 text-sm font-medium text-slate-950 transition-colors hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-700 sm:w-auto",
                    )}
                    href={`/artists/${person.artist_profile_id}`}
                  >
                    Open artist profile
                  </Link>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
