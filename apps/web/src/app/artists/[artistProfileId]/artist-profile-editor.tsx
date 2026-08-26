"use client";

import { Button, Input, cn } from "@label-os/ui";
import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { can, capabilities } from "../../../lib/authorization";
import { useArtistProfile, useUpdateArtistProfile } from "../../../lib/profiles";
import { useActiveWorkspace, useActiveWorkspaceProfile } from "../../../lib/workspace-context";

function splitTags(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function joinTags(values: string[]): string {
  return values.join(", ");
}

function FieldLabel({ children }: { children: string }) {
  return <label className="text-sm font-medium text-slate-700">{children}</label>;
}

function MetadataCount({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-xs font-medium uppercase tracking-normal text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-semibold text-slate-950">{value}</div>
    </div>
  );
}

export function ArtistProfileEditor({ artistProfileId }: { artistProfileId: string }) {
  const { activeWorkspace } = useActiveWorkspace();
  const workspaceProfile = useActiveWorkspaceProfile();
  const artistProfile = useArtistProfile(activeWorkspace?.id ?? null, artistProfileId);
  const update = useUpdateArtistProfile(activeWorkspace?.id ?? null, artistProfileId);
  const canEdit = workspaceProfile.subject
    ? can(workspaceProfile.subject, null, capabilities.artistEdit)
    : false;
  const [stageName, setStageName] = useState("");
  const [careerStage, setCareerStage] = useState("");
  const [genres, setGenres] = useState("");
  const [influences, setInfluences] = useState("");
  const [saveState, setSaveState] = useState<"idle" | "saved">("idle");

  useEffect(() => {
    if (!artistProfile.data) {
      return;
    }
    setStageName(artistProfile.data.stage_name ?? "");
    setCareerStage(artistProfile.data.career_stage ?? "");
    setGenres(joinTags(artistProfile.data.genres));
    setInfluences(joinTags(artistProfile.data.influences));
    setSaveState("idle");
  }, [artistProfile.data]);

  const metadata = useMemo(() => {
    const detail = artistProfile.data;
    return {
      catalogReferences: detail?.catalog_references.length ?? 0,
      dspLinks: detail ? Object.keys(detail.dsp_links).length : 0,
      imagery: detail ? Object.keys(detail.imagery).length : 0,
    };
  }, [artistProfile.data]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canEdit) {
      return;
    }
    await update.mutate({
      career_stage: careerStage.trim() || null,
      genres: splitTags(genres),
      influences: splitTags(influences),
      stage_name: stageName.trim() || null,
    });
    setSaveState("saved");
  };

  if (!activeWorkspace) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900">
        Choose a workspace to view this artist profile.
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
      <div className="flex flex-col gap-3 border-b border-slate-200 pb-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
            Artist Profile
          </p>
          <h1 className="mt-2 text-2xl font-semibold tracking-normal text-slate-950">
            {artistProfile.data?.artist_name ?? "Artist profile"}
          </h1>
          <p className="mt-1 text-sm leading-6 text-slate-500">{activeWorkspace.name}</p>
        </div>
        <Link
          className="inline-flex h-8 items-center justify-center rounded-md border border-slate-300 bg-white px-3 text-sm font-medium text-slate-950 transition-colors hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-700"
          href="/artists"
        >
          Back to artist profiles
        </Link>
      </div>

      {artistProfile.error ? (
        <div
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
          role="alert"
        >
          Artist profile could not be loaded.
        </div>
      ) : null}

      {update.error ? (
        <div
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
          role="alert"
        >
          Artist profile could not be saved.
        </div>
      ) : null}

      <form
        className={cn(
          "grid gap-4 rounded-md border border-slate-200 bg-white p-4 shadow-sm",
          artistProfile.isLoading && !artistProfile.data ? "animate-pulse" : "",
        )}
        onSubmit={submit}
      >
        <div className="grid gap-4 md:grid-cols-2">
          <div className="grid gap-2">
            <FieldLabel>Stage name</FieldLabel>
            <Input
              disabled={!canEdit || artistProfile.isLoading}
              onChange={(event) => setStageName(event.target.value)}
              placeholder="Artist stage name"
              value={stageName}
            />
          </div>
          <div className="grid gap-2">
            <FieldLabel>Career stage</FieldLabel>
            <Input
              disabled={!canEdit || artistProfile.isLoading}
              onChange={(event) => setCareerStage(event.target.value)}
              placeholder="Emerging, developing, established"
              value={careerStage}
            />
          </div>
        </div>

        <div className="grid gap-2">
          <FieldLabel>Genres</FieldLabel>
          <textarea
            className="min-h-24 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 shadow-sm outline-none transition-colors placeholder:text-slate-400 focus:border-slate-950 focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500"
            disabled={!canEdit || artistProfile.isLoading}
            onChange={(event) => setGenres(event.target.value)}
            placeholder="Pop, R&B, Alternative"
            value={genres}
          />
        </div>

        <div className="grid gap-2">
          <FieldLabel>Influences</FieldLabel>
          <textarea
            className="min-h-24 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 shadow-sm outline-none transition-colors placeholder:text-slate-400 focus:border-slate-950 focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500"
            disabled={!canEdit || artistProfile.isLoading}
            onChange={(event) => setInfluences(event.target.value)}
            placeholder="Reference artists, scenes, or creative influences"
            value={influences}
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <MetadataCount label="DSP links" value={metadata.dspLinks} />
          <MetadataCount label="Imagery" value={metadata.imagery} />
          <MetadataCount label="Catalog refs" value={metadata.catalogReferences} />
        </div>

        <div className="flex flex-col gap-2 border-t border-slate-200 pt-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-slate-500">
            {canEdit
              ? "Changes save to the workspace artist profile module."
              : "You can view this artist profile, but editing requires artist edit access."}
          </p>
          <div className="flex items-center gap-3">
            {saveState === "saved" ? (
              <span className="text-sm font-medium text-emerald-700">Saved</span>
            ) : null}
            <Button
              disabled={!canEdit || update.isMutating || artistProfile.isLoading}
              type="submit"
            >
              {update.isMutating ? "Saving" : "Save artist profile"}
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}
