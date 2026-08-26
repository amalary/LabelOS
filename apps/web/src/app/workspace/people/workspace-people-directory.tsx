"use client";

import { Button, Input, cn } from "@label-os/ui";
import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  ProfileQuickViewButton,
  ProfileQuickViewDrawer,
} from "../../../components/profile-quick-view";
import {
  ProfileAvatar,
  ProfileDepartmentBadge,
  ProfileName,
  ProfileRoleBadge,
  profileIdentityFromDirectoryEntry,
} from "../../../components/profiles/profile-identity";
import { useWorkspacePeopleDirectory } from "../../../lib/profiles";
import { useActiveWorkspace } from "../../../lib/workspace-context";

const pageSize = 25;

function displayValue(value: string) {
  return value.replace(/[-_]/g, " ");
}

function TagList({
  emptyLabel,
  kind = "role",
  values,
}: {
  emptyLabel: string;
  kind?: "department" | "role";
  values: string[];
}) {
  if (!values.length) {
    return <span className="text-sm text-slate-400">{emptyLabel}</span>;
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      {values.map((value) => (
        kind === "department" ? (
          <ProfileDepartmentBadge department={value} key={value} />
        ) : (
          <ProfileRoleBadge key={value} role={value} />
        )
      ))}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-7 items-center rounded-md border px-2.5 text-xs font-semibold capitalize",
        status === "active"
          ? "border-emerald-200 bg-emerald-50 text-emerald-800"
          : "border-slate-200 bg-slate-50 text-slate-600",
      )}
    >
      {displayValue(status)}
    </span>
  );
}

function EmptyState({ hasQuery }: { hasQuery: boolean }) {
  return (
    <div className="rounded-md border border-dashed border-slate-300 bg-white/70 p-8 text-center">
      <h2 className="text-base font-semibold text-slate-950">
        {hasQuery ? "No people match this search" : "No workspace people yet"}
      </h2>
      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">
        {hasQuery
          ? "Try a different name, role, or department."
          : "Active workspace members with Universal Profiles will appear here."}
      </p>
    </div>
  );
}

export function WorkspacePeopleDirectory() {
  const { activeWorkspace } = useActiveWorkspace();
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [selectedProfileId, setSelectedProfileId] = useState<string | null>(null);
  const directory = useWorkspacePeopleDirectory(activeWorkspace?.id ?? null, {
    query,
    limit: pageSize,
    offset,
  });

  useEffect(() => {
    setOffset(0);
    setSelectedProfileId(null);
  }, [activeWorkspace?.id]);

  const total = directory.data?.total ?? 0;
  const people = directory.data?.people ?? [];
  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + pageSize, total);
  const canGoBack = offset > 0;
  const canGoForward = offset + pageSize < total;
  const hasSearch = query.trim().length > 0;
  const pageLabel = useMemo(() => {
    if (directory.isLoading && !directory.data) {
      return "Loading people";
    }
    return `${pageStart}-${pageEnd} of ${total}`;
  }, [directory.data, directory.isLoading, pageEnd, pageStart, total]);

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setQuery(searchInput.trim());
    setOffset(0);
  };

  if (!activeWorkspace) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900">
        Choose a workspace to browse its people directory.
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4">
      <div className="flex flex-col gap-4 border-b border-slate-200 pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
            Universal Profiles
          </p>
          <h1 className="mt-2 text-2xl font-semibold tracking-normal text-slate-950">
            People Directory
          </h1>
          <p className="mt-1 text-sm leading-6 text-slate-500">
            {activeWorkspace.name}
          </p>
        </div>
        <form className="flex w-full gap-2 lg:w-[460px]" onSubmit={submitSearch}>
          <Input
            aria-label="Search by name, role, or department"
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Search name, role, or department"
            value={searchInput}
          />
          <Button type="submit">Search</Button>
        </form>
      </div>

      {directory.error ? (
        <div
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
          role="alert"
        >
          People directory could not be loaded.
        </div>
      ) : null}

      <div className="overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-col gap-2 border-b border-slate-200 bg-slate-50 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-sm font-medium text-slate-700">{pageLabel}</div>
          <div className="flex gap-2">
            {hasSearch ? (
              <Button
                onClick={() => {
                  setSearchInput("");
                  setQuery("");
                  setOffset(0);
                }}
                size="sm"
                variant="ghost"
              >
                Clear
              </Button>
            ) : null}
            <Button
              disabled={!canGoBack || directory.isLoading}
              onClick={() => setOffset((current) => Math.max(0, current - pageSize))}
              size="sm"
              variant="secondary"
            >
              Previous
            </Button>
            <Button
              disabled={!canGoForward || directory.isLoading}
              onClick={() => setOffset((current) => current + pageSize)}
              size="sm"
              variant="secondary"
            >
              Next
            </Button>
          </div>
        </div>

        {directory.isLoading && !directory.data ? (
          <div className="grid gap-3 p-4">
            {Array.from({ length: 6 }, (_, index) => (
              <div className="h-16 rounded-md bg-slate-100 auth-shimmer" key={index} />
            ))}
          </div>
        ) : people.length === 0 ? (
          <div className="p-4">
            <EmptyState hasQuery={hasSearch} />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-[980px] w-full border-separate border-spacing-0 text-left">
              <thead>
                <tr className="text-xs font-semibold uppercase tracking-normal text-slate-500">
                  <th className="border-b border-slate-200 px-4 py-3">Person</th>
                  <th className="border-b border-slate-200 px-4 py-3">Roles</th>
                  <th className="border-b border-slate-200 px-4 py-3">Departments</th>
                  <th className="border-b border-slate-200 px-4 py-3">Module</th>
                  <th className="border-b border-slate-200 px-4 py-3">Status</th>
                  <th className="border-b border-slate-200 px-4 py-3">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {people.map((person) => {
                  const identity = profileIdentityFromDirectoryEntry(person);

                  return (
                  <tr className="align-top hover:bg-slate-50/80" key={person.id}>
                    <td className="border-b border-slate-100 px-4 py-3">
                      <div className="flex min-w-0 items-center gap-3">
                        <ProfileAvatar profile={identity} />
                        <ProfileName profile={identity} showHeadline />
                      </div>
                    </td>
                    <td className="border-b border-slate-100 px-4 py-3">
                      <TagList emptyLabel="No roles" values={identity.roles ?? []} />
                    </td>
                    <td className="border-b border-slate-100 px-4 py-3">
                      <TagList
                        emptyLabel="No departments"
                        kind="department"
                        values={identity.departments ?? []}
                      />
                    </td>
                    <td className="border-b border-slate-100 px-4 py-3">
                      <TagList emptyLabel="Universal" values={person.profile_modules} />
                    </td>
                    <td className="border-b border-slate-100 px-4 py-3">
                      <StatusBadge status={person.membership_status} />
                    </td>
                    <td className="border-b border-slate-100 px-4 py-3 text-right">
                      <ProfileQuickViewButton
                        onOpen={() => setSelectedProfileId(person.profile_id)}
                      />
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <ProfileQuickViewDrawer
        isOpen={selectedProfileId !== null}
        onClose={() => setSelectedProfileId(null)}
        profileId={selectedProfileId}
        workspaceId={activeWorkspace.id}
      />
    </div>
  );
}
