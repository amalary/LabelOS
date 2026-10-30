"use client";

import {
  type DraftFilters,
  type DraftUpdatedFilter,
  filtersActive,
  channelOptions,
  humanize,
  contentTypeOptions,
  approvalStateVariant,
  approvalStateLabel,
  revisionLabel,
  copyPreview,
  channelSummary,
  campaignName,
  relationshipLabel,
  channelPlacementSummary,
  ownerCreatorLabel,
} from "./marketing-presentation";
import { type Campaign } from "../../lib/campaigns";
import {
  type MarketingContentItem,
  type MarketingContentListOptions,
  useWorkspaceMarketingContent,
  useArchiveMarketingContentItem,
} from "../../lib/marketing-content";
import { useState, useCallback, useMemo, useEffect } from "react";
import { Card, Badge, Button, LoadingState, EmptyState } from "@label-os/ui";
import { useSubmitMarketingContentForApproval } from "../../lib/approvals";

const emptyDraftFilters: DraftFilters = {
  artistId: "",
  campaignId: "",
  channel: "",
  contentType: "",
  ownerProfileId: "",
  releaseId: "",
  search: "",
  updatedWithinDays: "",
};

function draftOwnerOptions(campaigns: Campaign[]) {
  return [
    ...campaigns.flatMap((campaign) => [
      ...(campaign.owner ? [campaign.owner] : []),
      ...campaign.members.map((member) => ({
        display_name: member.display_name,
        profile_id: member.profile_id,
      })),
    ]),
  ].filter(
    (owner, index, owners) =>
      owners.findIndex((entry) => entry.profile_id === owner.profile_id) === index,
  );
}

function draftSearchText(item: MarketingContentItem): string {
  return [item.title, item.copy_text, ...item.channels.map((channel) => channel.copy_text_override)]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function draftMatchesSearch(item: MarketingContentItem, search: string): boolean {
  const query = search.trim().toLowerCase();
  return !query || draftSearchText(item).includes(query);
}

function draftRecentlyUpdated(item: MarketingContentItem, updatedWithinDays: DraftUpdatedFilter) {
  if (!updatedWithinDays) {
    return true;
  }
  const updatedAt = new Date(item.updated_at).getTime();
  if (Number.isNaN(updatedAt)) {
    return false;
  }
  const days = Number(updatedWithinDays);
  return updatedAt >= Date.now() - days * 24 * 60 * 60 * 1000;
}

export function DraftsTab({
  canCreate,
  canArchive,
  canSubmitForReview,
  campaigns,
  onCreate,
  onArchived,
  onItemClick,
  savedRevision,
  workspaceId,
}: {
  canCreate: boolean;
  canArchive: boolean;
  canSubmitForReview: boolean;
  campaigns: Campaign[];
  onCreate: () => void;
  onArchived: (item: MarketingContentItem) => void;
  onItemClick: (item: MarketingContentItem) => void;
  savedRevision: number;
  workspaceId: string;
}) {
  const [filters, setFilters] = useState<DraftFilters>(emptyDraftFilters);
  const [archivedDraftIds, setArchivedDraftIds] = useState<Set<string>>(() => new Set());
  const updateFilter = useCallback((next: Partial<DraftFilters>) => {
    setFilters((current) => ({ ...current, ...next }));
  }, []);
  const resetFilters = useCallback(() => setFilters(emptyDraftFilters), []);
  const draftOptions = useMemo<MarketingContentListOptions>(
    () => ({
      artist_id: filters.artistId.trim() || null,
      campaign_id: filters.campaignId || null,
      channel: filters.channel || null,
      content_type: filters.contentType || null,
      limit: 500,
      offset: 0,
      owner_profile_id: filters.ownerProfileId || null,
      release_id: filters.releaseId.trim() || null,
      status: "draft",
    }),
    [
      filters.artistId,
      filters.campaignId,
      filters.channel,
      filters.contentType,
      filters.ownerProfileId,
      filters.releaseId,
    ],
  );
  const drafts = useWorkspaceMarketingContent(workspaceId, draftOptions);
  const markArchived = useCallback(
    (archived: MarketingContentItem) => {
      setArchivedDraftIds((current) => new Set(current).add(archived.id));
      onArchived(archived);
      void Promise.resolve(drafts.reload()).catch(() => undefined);
    },
    [drafts.reload, onArchived],
  );
  useEffect(() => {
    if (savedRevision > 0) {
      void Promise.resolve(drafts.reload()).catch(() => undefined);
    }
  }, [drafts.reload, savedRevision]);
  useEffect(() => {
    if (!drafts.data) {
      return;
    }
    const activeIds = new Set(
      drafts.data.marketing_content
        .filter((draft) => draft.status === "draft")
        .map((draft) => draft.id),
    );
    setArchivedDraftIds((current) => {
      const next = new Set([...current].filter((id) => activeIds.has(id)));
      const unchanged = next.size === current.size && [...next].every((id) => current.has(id));
      return unchanged ? current : next;
    });
  }, [drafts.data]);
  const serverDraftItems = (drafts.data?.marketing_content ?? []).filter(
    (draft) => draft.status === "draft" && !archivedDraftIds.has(draft.id),
  );
  const draftItems = useMemo(
    () =>
      serverDraftItems
        .filter(
          (draft) =>
            draftMatchesSearch(draft, filters.search) &&
            draftRecentlyUpdated(draft, filters.updatedWithinDays),
        )
        .sort(
          (left, right) =>
            new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime() ||
            left.title.localeCompare(right.title),
        ),
    [filters.search, filters.updatedWithinDays, serverDraftItems],
  );
  const activeFilters = filtersActive(filters);
  const ownerOptions = draftOwnerOptions(campaigns);
  const artistOptions = [
    ...campaigns.flatMap((campaign) => [
      ...(campaign.primary_artist ? [campaign.primary_artist] : []),
      ...campaign.artists.map((entry) => entry.artist),
    ]),
  ].filter(
    (artist, index, artists) => artists.findIndex((entry) => entry.id === artist.id) === index,
  );
  const releaseOptions = [
    ...campaigns.flatMap((campaign) => [
      ...(campaign.release ? [campaign.release] : []),
      ...campaign.releases.map((entry) => entry.release),
    ]),
  ].filter(
    (release, index, releases) => releases.findIndex((entry) => entry.id === release.id) === index,
  );

  return (
    <section className="grid gap-4" aria-label="Draft posts">
      <Card className="grid gap-1">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">Draft Posts</h2>
            <p className="text-sm text-slate-500">
              Unsubmitted marketing content where status is draft.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge>
              {draftItems.length}
              {activeFilters ? ` of ${serverDraftItems.length}` : ""} drafts
            </Badge>
            {canCreate ? (
              <Button onClick={onCreate} size="sm" type="button">
                Create Draft
              </Button>
            ) : null}
          </div>
        </div>
      </Card>

      <Card className="grid gap-3 p-4">
        <div className="grid gap-3 lg:grid-cols-[minmax(220px,1.5fr)_repeat(3,minmax(150px,1fr))]">
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            <span>Search title or copy</span>
            <input
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
              onChange={(event) => updateFilter({ search: event.target.value })}
              placeholder="Search drafts"
              type="search"
              value={filters.search}
            />
          </label>
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            <span>Campaign</span>
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
              onChange={(event) => updateFilter({ campaignId: event.target.value })}
              value={filters.campaignId}
            >
              <option value="">All campaigns</option>
              {campaigns.map((campaign) => (
                <option key={campaign.id} value={campaign.id}>
                  {campaign.name}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            <span>Channel</span>
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
              onChange={(event) => updateFilter({ channel: event.target.value })}
              value={filters.channel}
            >
              <option value="">Any channel</option>
              {channelOptions.map((channel) => (
                <option key={channel} value={channel}>
                  {humanize(channel)}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            <span>Content type</span>
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
              onChange={(event) => updateFilter({ contentType: event.target.value })}
              value={filters.contentType}
            >
              <option value="">Any type</option>
              {contentTypeOptions.map((contentType) => (
                <option key={contentType} value={contentType}>
                  {humanize(contentType)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="grid gap-3 md:grid-cols-4">
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            <span>Artist</span>
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
              onChange={(event) => updateFilter({ artistId: event.target.value })}
              value={filters.artistId}
            >
              <option value="">Any artist</option>
              {artistOptions.map((artist) => (
                <option key={artist.id} value={artist.id}>
                  {artist.name}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            <span>Release</span>
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
              onChange={(event) => updateFilter({ releaseId: event.target.value })}
              value={filters.releaseId}
            >
              <option value="">Any release</option>
              {releaseOptions.map((release) => (
                <option key={release.id} value={release.id}>
                  {release.title}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            <span>Owner</span>
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
              onChange={(event) => updateFilter({ ownerProfileId: event.target.value })}
              value={filters.ownerProfileId}
            >
              <option value="">Any owner</option>
              {ownerOptions.map((owner) => (
                <option key={owner.profile_id} value={owner.profile_id}>
                  {owner.display_name ?? owner.profile_id}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            <span>Recently updated</span>
            <select
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
              onChange={(event) =>
                updateFilter({ updatedWithinDays: event.target.value as DraftUpdatedFilter })
              }
              value={filters.updatedWithinDays}
            >
              <option value="">Any time</option>
              <option value="7">Last 7 days</option>
              <option value="30">Last 30 days</option>
            </select>
          </label>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-slate-500">
            Draft status is fixed. Linked filters use the marketing content API; search and updated
            recency apply to the loaded draft set.
          </p>
          <Button
            disabled={!activeFilters}
            onClick={resetFilters}
            size="sm"
            type="button"
            variant="secondary"
          >
            Clear filters
          </Button>
        </div>
      </Card>

      {drafts.error ? (
        <div
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
          role="alert"
        >
          {drafts.error.code === "forbidden"
            ? "Marketing content access was denied for drafts."
            : "Draft posts could not be loaded."}
        </div>
      ) : null}

      {drafts.isLoading && !drafts.data ? (
        <Card className="grid gap-3">
          <LoadingState label="Loading draft posts" />
          {Array.from({ length: 3 }, (_, index) => (
            <div className="h-14 rounded-md bg-slate-100 auth-shimmer" key={index} />
          ))}
        </Card>
      ) : draftItems.length === 0 ? (
        <EmptyState
          description={
            activeFilters
              ? "Try clearing filters or broadening the search terms."
              : "Draft posts appear here before they are submitted for approval or scheduled."
          }
          action={
            activeFilters ? (
              <Button onClick={resetFilters} type="button" variant="secondary">
                Clear filters
              </Button>
            ) : null
          }
          title={activeFilters ? "No matching draft posts" : "No draft posts"}
        />
      ) : (
        <Card className="overflow-hidden p-0">
          <div className="divide-y divide-slate-100">
            {draftItems.map((draft) => (
              <DraftRow
                canArchive={canArchive}
                canSubmitForReview={canSubmitForReview}
                campaigns={campaigns}
                draft={draft}
                key={draft.id}
                onArchived={markArchived}
                onItemClick={onItemClick}
                onSubmitted={() => void Promise.resolve(drafts.reload()).catch(() => undefined)}
                workspaceId={workspaceId}
              />
            ))}
          </div>
        </Card>
      )}
    </section>
  );
}

function DraftRow({
  canArchive,
  canSubmitForReview,
  campaigns,
  draft,
  onArchived,
  onItemClick,
  onSubmitted,
  workspaceId,
}: {
  canArchive: boolean;
  canSubmitForReview: boolean;
  campaigns: Campaign[];
  draft: MarketingContentItem;
  onArchived: (item: MarketingContentItem) => void;
  onItemClick: (item: MarketingContentItem) => void;
  onSubmitted: () => void;
  workspaceId: string;
}) {
  const submitApproval = useSubmitMarketingContentForApproval(
    workspaceId,
    draft.campaign_id,
    draft.id,
  );
  const archive = useArchiveMarketingContentItem(workspaceId, draft.campaign_id, draft.id);
  const approvalState = draft.approval_state?.state ?? draft.status;
  const canSubmitDraft = canSubmitForReview && draft.status === "draft";
  const submitLabel =
    approvalState === "changes_requested" ? "Resubmit for approval" : "Submit for approval";

  async function submitForReview() {
    try {
      await submitApproval.mutate({ expected_resource_revision: draft.content_revision });
      onSubmitted();
    } catch {
      // Mutation state renders the existing approval eligibility/capability errors.
    }
  }

  async function archiveDraft() {
    if (
      !window.confirm(
        `Archive "${draft.title}"? It will be hidden from active Draft Posts and retained in Marketing Content history.`,
      )
    ) {
      return;
    }
    try {
      const archived = await archive.mutate();
      onArchived(archived);
    } catch {
      // Mutation state renders authorization and API failures inline.
    }
  }

  return (
    <article className="grid gap-4 px-4 py-4 transition hover:bg-slate-50 md:grid-cols-[minmax(0,1.4fr)_minmax(160px,0.8fr)_minmax(150px,0.7fr)_minmax(150px,0.7fr)_auto]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="truncate text-sm font-semibold text-slate-950">{draft.title}</h3>
          <Badge variant={approvalStateVariant(draft)}>{approvalStateLabel(draft)}</Badge>
          <Badge>{revisionLabel(draft)}</Badge>
        </div>
        <p className="mt-2 line-clamp-2 text-sm text-slate-600">{copyPreview(draft)}</p>
        <p className="mt-2 truncate text-xs text-slate-500">
          {humanize(draft.content_type)} - {channelSummary(draft)}
        </p>
      </div>
      <div>
        <p className="text-xs font-semibold uppercase text-slate-500">Campaign</p>
        <p className="mt-1 truncate text-sm font-medium text-slate-800">
          {campaignName(campaigns, draft.campaign_id)}
        </p>
        <p className="mt-1 truncate text-xs text-slate-500">
          Artist: {relationshipLabel(draft.artist_id)}
        </p>
        <p className="truncate text-xs text-slate-500">
          Release: {relationshipLabel(draft.release_id)}
        </p>
      </div>
      <div>
        <p className="text-xs font-semibold uppercase text-slate-500">Placements</p>
        <p className="mt-1 line-clamp-2 text-sm font-medium text-slate-800">
          {channelPlacementSummary(draft)}
        </p>
      </div>
      <div>
        <p className="text-xs font-semibold uppercase text-slate-500">Updated</p>
        <p className="mt-1 truncate text-sm font-medium text-slate-800">
          {draft.updated_at.slice(0, 10)}
        </p>
        <p className="mt-1 truncate text-xs text-slate-500">{ownerCreatorLabel(draft)}</p>
      </div>
      <div className="flex flex-wrap items-start gap-2 md:justify-end">
        <Button
          aria-label={`Open draft ${draft.title}`}
          onClick={() => onItemClick(draft)}
          size="sm"
          type="button"
          variant="secondary"
        >
          Open
        </Button>
        {canSubmitDraft ? (
          <Button
            aria-label={`${submitLabel} ${draft.title}`}
            disabled={submitApproval.isMutating}
            onClick={submitForReview}
            size="sm"
            type="button"
            variant="secondary"
          >
            {submitApproval.isMutating ? "Submitting..." : submitLabel}
          </Button>
        ) : null}
        {canArchive ? (
          <Button
            aria-label={`Archive draft ${draft.title}`}
            disabled={archive.isMutating}
            onClick={archiveDraft}
            size="sm"
            type="button"
            variant="secondary"
          >
            {archive.isMutating ? "Archiving..." : "Archive"}
          </Button>
        ) : null}
        {submitApproval.error || archive.error ? (
          <p className="basis-full text-xs font-medium text-red-700" role="alert">
            {submitApproval.error?.message ?? archive.error?.message}
          </p>
        ) : null}
      </div>
    </article>
  );
}
