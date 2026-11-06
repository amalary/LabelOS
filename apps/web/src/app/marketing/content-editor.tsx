"use client";

import {
  type ScheduleDisambiguation,
  scheduleOccurrences,
  occurrenceLabel,
  scheduleFromInstant,
} from "../../lib/schedule-timezones";
import {
  type SocialAccountConnection,
  useSocialAccountConnections,
} from "../../lib/social-account-connections";
import { type Campaign } from "../../lib/campaigns";
import {
  type CalendarFilters,
  approvedRevisionIsCurrent,
  humanize,
  approvalStateLabel,
  contentTypeOptions,
  channelOptions,
  campaignName,
} from "./marketing-presentation";
import {
  type MarketingContentItem,
  useCreateMarketingContentItem,
  useUpdateMarketingContentItem,
  useArchiveMarketingContentItem,
  type MarketingContentItemUpdate,
  useMarketingContentItem,
} from "../../lib/marketing-content";
import {
  type ContentEditorMode,
  type ContentEditorSurface,
  initialFormState,
  duplicateChannelTargets,
  type ContentFormState,
  type ChannelFormRow,
  formToPayload,
  parseAssetRefs,
  emptyChannelRow,
} from "./content-form";
import { useState } from "react";
import { useActiveWorkspaceProfile } from "../../lib/workspace-context";
import { can, capabilities } from "../../lib/authorization";
import { useSubmitMarketingContentForApproval } from "../../lib/approvals";
import { Card, Button, LoadingState, cn } from "@label-os/ui";
import { PreparedMediaUpload } from "./prepared-media-upload";
import { ChannelScheduling } from "./channel-scheduling";
import { PublicationHistory } from "./publication-history";

function ScheduleFeedback({
  localTime,
  timeZone,
  choice,
  disabled,
  onChoice,
}: {
  localTime: string;
  timeZone: string;
  choice: ScheduleDisambiguation;
  disabled: boolean;
  onChoice: (choice: ScheduleDisambiguation) => void;
}) {
  if (!localTime || !timeZone) return null;
  try {
    const occurrences = scheduleOccurrences(localTime, timeZone);
    return (
      <div className="text-xs text-slate-600">
        {occurrences.length > 1 && (
          <label className="grid gap-1">
            This local time occurs twice. Choose an occurrence.
            <select
              aria-label="Schedule occurrence"
              disabled={disabled}
              value={choice}
              onChange={(event) => onChoice(event.target.value as ScheduleDisambiguation)}
            >
              <option value="">Select earlier or later</option>
              <option value="earlier">Earlier: {occurrenceLabel(occurrences[0]!)}</option>
              <option value="later">Later: {occurrenceLabel(occurrences[1]!)}</option>
            </select>
          </label>
        )}
        {(occurrences.length === 1 || choice) && (
          <p>
            Time to store: {localTime} in {timeZone};{" "}
            {occurrenceLabel(occurrences[choice === "later" ? occurrences.length - 1 : 0]!)}
          </p>
        )}
      </div>
    );
  } catch (error) {
    return (
      <p role="alert" className="text-sm text-red-700">
        {error instanceof Error ? error.message : "Invalid schedule."}
      </p>
    );
  }
}

function accountConnectionLabel(connection: SocialAccountConnection): string {
  const handle =
    connection.handle ?? connection.display_name ?? connection.external_account_id ?? connection.id;
  const mode = connection.capabilities.includes("content_publish")
    ? "Automatic Publishing"
    : "Assisted Publishing";
  return `${handle} - ${mode}`;
}

function accountConnectionWarning(connection: SocialAccountConnection): string | null {
  if (connection.status === "disconnected") {
    return "Disconnected";
  }
  if (connection.status === "reconnect_required") {
    return "Reconnect required";
  }
  if (
    !connection.capabilities.includes("content_publish") &&
    !connection.capabilities.includes("manual_publish")
  ) {
    return "Missing publishing capability";
  }
  return null;
}

function ContentEditor({
  campaigns,
  canEdit,
  canArchive,
  canSubmitForReview,
  createDate,
  filters,
  item,
  mode,
  onCancel,
  onArchived,
  onOpenApprovalReview,
  onSaved,
  onReloadContent,
  surface,
  timeZone,
}: {
  campaigns: Campaign[];
  canEdit: boolean;
  canArchive: boolean;
  canSubmitForReview: boolean;
  createDate: string | null;
  filters: CalendarFilters;
  item: MarketingContentItem | null;
  mode: ContentEditorMode;
  onCancel: () => void;
  onArchived: (item: MarketingContentItem) => void;
  onOpenApprovalReview: (approvalRequestId: string | null) => void;
  onSaved: (item: MarketingContentItem | null) => void;
  onReloadContent: () => void;
  surface: ContentEditorSurface;
  timeZone: string;
}) {
  const [form, setForm] = useState(() =>
    initialFormState({ campaigns, createDate, filters, item, timeZone }),
  );
  const [clientError, setClientError] = useState<string | null>(null);
  const [schedulingBusy, setSchedulingBusy] = useState(false);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [publishNowNotice, setPublishNowNotice] = useState<string | null>(null);
  const profile = useActiveWorkspaceProfile();
  const canSchedule = Boolean(
    profile.subject && can(profile.subject, null, capabilities.marketingContentSchedule),
  );
  const dirty =
    JSON.stringify(form) !==
    JSON.stringify(initialFormState({ campaigns, createDate, filters, item, timeZone }));
  const selectedCampaign = campaigns.find((campaign) => campaign.id === form.campaignId) ?? null;
  const workspaceId = selectedCampaign?.workspace_id ?? item?.workspace_id ?? null;
  const socialAccounts = useSocialAccountConnections(workspaceId, {
    include_disconnected: true,
    limit: 100,
    offset: 0,
  });
  const create = useCreateMarketingContentItem(
    workspaceId,
    mode === "create" ? form.campaignId || null : null,
  );
  const update = useUpdateMarketingContentItem(
    workspaceId,
    item?.campaign_id ?? null,
    item?.id ?? null,
  );
  const submitApproval = useSubmitMarketingContentForApproval(
    workspaceId,
    item?.campaign_id ?? null,
    item?.id ?? null,
  );
  const archive = useArchiveMarketingContentItem(
    workspaceId,
    item?.campaign_id ?? null,
    item?.id ?? null,
  );
  const isEditable = (mode === "create" || canEdit) && !schedulingBusy && !uploadBusy;
  const artistOptions = selectedCampaign
    ? [
        ...(selectedCampaign.primary_artist ? [selectedCampaign.primary_artist] : []),
        ...selectedCampaign.artists.map((entry) => entry.artist),
      ].filter(
        (artist, index, artists) => artists.findIndex((entry) => entry.id === artist.id) === index,
      )
    : [];
  const releaseOptions = (
    selectedCampaign
      ? [
          ...(selectedCampaign.release ? [selectedCampaign.release] : []),
          ...selectedCampaign.releases.map((entry) => entry.release),
        ].filter(
          (release, index, releases) =>
            releases.findIndex((entry) => entry.id === release.id) === index,
        )
      : []
  ).filter(
    (release) => !form.artistId || !release.artist_id || release.artist_id === form.artistId,
  );
  const ownerOptions = selectedCampaign?.members ?? [];
  const duplicateChannels = duplicateChannelTargets(form.channels);
  const mutationError = create.error ?? update.error ?? submitApproval.error ?? archive.error;
  const isMutating =
    create.isMutating ||
    update.isMutating ||
    submitApproval.isMutating ||
    archive.isMutating ||
    schedulingBusy ||
    uploadBusy;
  const approvalState = item?.approval_state?.state ?? item?.status;
  const isCurrentlyApproved = item ? approvedRevisionIsCurrent(item) : false;
  const isDraftSurface = surface === "drafts";
  const accountConnections = socialAccounts.data?.social_account_connections ?? [];

  const setField = (next: Partial<ContentFormState>) => {
    setClientError(null);
    setForm((current) => ({ ...current, ...next }));
  };
  const setChannel = (id: string, next: Partial<ChannelFormRow>) => {
    setClientError(null);
    setForm((current) => ({
      ...current,
      channels: current.channels.map((channel) =>
        channel.id === id ? { ...channel, ...next } : channel,
      ),
    }));
  };

  async function saveDraft() {
    setClientError(null);
    if (!form.campaignId) {
      setClientError("Campaign is required.");
      return;
    }
    if (!form.title.trim()) {
      setClientError("Title is required.");
      return;
    }
    if (!form.contentType.trim()) {
      setClientError("Content type is required.");
      return;
    }
    if (form.channels.length < 1 || form.channels.some((channel) => !channel.channel.trim())) {
      setClientError("At least one channel is required.");
      return;
    }
    if (duplicateChannels) {
      setClientError("Each channel and placement target can only be selected once.");
      return;
    }
    if (form.artistId && !artistOptions.some((artist) => artist.id === form.artistId)) {
      setClientError("Choose an artist linked to this workspace campaign.");
      return;
    }
    if (form.releaseId && !releaseOptions.some((release) => release.id === form.releaseId)) {
      setClientError("Choose a release linked to this workspace campaign.");
      return;
    }
    try {
      const payload = formToPayload(form);
      if (mode === "create") {
        const saved = await create.mutate(payload);
        onSaved(saved);
      } else {
        if (
          isCurrentlyApproved &&
          !window.confirm(
            "This content is currently approved. Saving material edits will require reapproval before scheduling.",
          )
        ) {
          return;
        }
        const saved = await update.mutate(payload as MarketingContentItemUpdate);
        onSaved(saved);
      }
    } catch (error) {
      if (error instanceof SyntaxError || error instanceof Error) {
        setClientError(error.message);
      }
    }
  }

  async function submitForReview() {
    setClientError(null);
    if (!item || dirty) {
      return;
    }
    try {
      await submitApproval.mutate({ expected_resource_revision: item.content_revision });
      onSaved(null);
    } catch {
      // The mutation state renders API denial and invalid transition messages.
    }
  }

  async function archiveContent() {
    setClientError(null);
    if (!item) {
      return;
    }
    if (
      !window.confirm(
        `Archive "${item.title}"? It will be hidden from active Draft Posts and retained in Marketing Content history.`,
      )
    ) {
      return;
    }
    try {
      const archived = await archive.mutate();
      onArchived(archived);
    } catch {
      // The mutation state renders API authorization and lifecycle failures.
    }
  }

  return (
    <Card className="grid gap-4 p-4" role="region" aria-label="Marketing content editor">
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">
            {mode === "create"
              ? surface === "drafts"
                ? "Create draft post"
                : "Create content draft"
              : "Edit content"}
          </h2>
          <p className="text-sm text-slate-500">
            {isDraftSurface
              ? "Author channel-specific draft copy, assets, placements, and optional planned times before approval."
              : "Plan channel times, complete approval, then activate each approved channel schedule."}
          </p>
          {item ? (
            <p className="mt-1 text-xs font-medium text-slate-500">
              Current status: {item.status === "scheduled" ? "Planned" : humanize(item.status)} -
              Approval: {approvalStateLabel(item)} - Revision {item.content_revision}
            </p>
          ) : null}
        </div>
        <Button onClick={onCancel} size="sm" type="button" variant="secondary">
          Close
        </Button>
      </div>

      {clientError || mutationError ? (
        <div
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
          role="alert"
        >
          {clientError ?? mutationError?.message}
        </div>
      ) : null}

      <div className="grid gap-3 md:grid-cols-2">
        <label className="grid gap-1 text-sm font-medium text-slate-700">
          <span>Campaign</span>
          <select
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            disabled={!isEditable || mode === "edit"}
            onChange={(event) => {
              const campaign = campaigns.find((entry) => entry.id === event.target.value);
              setField({
                artistId: campaign?.primary_artist?.id ?? "",
                campaignId: event.target.value,
                ownerProfileId: campaign?.owner_profile_id ?? "",
                releaseId: campaign?.release?.id ?? "",
              });
            }}
            value={form.campaignId}
          >
            <option value="">Choose campaign</option>
            {campaigns.map((campaign) => (
              <option key={campaign.id} value={campaign.id}>
                {campaign.name}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700">
          <span>Title</span>
          <input
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            disabled={!isEditable}
            onChange={(event) => setField({ title: event.target.value })}
            value={form.title}
          />
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700">
          <span>Artist</span>
          <select
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            disabled={!isEditable || !selectedCampaign}
            onChange={(event) => setField({ artistId: event.target.value })}
            value={form.artistId}
          >
            <option value="">No artist</option>
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
            disabled={!isEditable || !selectedCampaign}
            onChange={(event) => setField({ releaseId: event.target.value })}
            value={form.releaseId}
          >
            <option value="">No release</option>
            {releaseOptions.map((release) => (
              <option key={release.id} value={release.id}>
                {release.title}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700">
          <span>Content Type</span>
          <select
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            disabled={!isEditable}
            onChange={(event) => setField({ contentType: event.target.value })}
            value={form.contentType}
          >
            {contentTypeOptions.map((contentType) => (
              <option key={contentType} value={contentType}>
                {humanize(contentType)}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700">
          <span>Owner</span>
          <select
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            disabled={!isEditable || !selectedCampaign}
            onChange={(event) => setField({ ownerProfileId: event.target.value })}
            value={form.ownerProfileId}
          >
            <option value="">No owner</option>
            {ownerOptions.map((member) => (
              <option key={member.profile_id} value={member.profile_id}>
                {member.display_name ?? member.profile_id}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700 md:col-span-2">
          <span>Planned publish time</span>
          <input
            aria-label="Planned publish time"
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
            disabled={!isEditable}
            onChange={(event) => setField({ scheduledAt: event.target.value, scheduleChoice: "" })}
            step="any"
            type="datetime-local"
            value={form.scheduledAt}
          />
          <span className="text-xs font-normal text-slate-500">
            Planning timezone: {form.scheduleTimezone}. Calendar display timezone: {timeZone}.
          </span>
        </label>
        <ScheduleFeedback
          localTime={form.scheduledAt}
          timeZone={form.scheduleTimezone}
          choice={form.scheduleChoice}
          disabled={!isEditable}
          onChoice={(scheduleChoice) => setField({ scheduleChoice })}
        />
        <label className="grid gap-1 text-sm font-medium text-slate-700 md:col-span-2">
          <span>Core Copy / Caption</span>
          <textarea
            className="min-h-24 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950"
            disabled={!isEditable}
            onChange={(event) => setField({ copyText: event.target.value })}
            value={form.copyText}
          />
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700 md:col-span-2">
          <span>Asset references</span>
          <textarea
            className="min-h-20 rounded-md border border-slate-300 bg-white px-3 py-2 font-mono text-xs text-slate-950"
            disabled={!isEditable}
            onChange={(event) => setField({ assetRefsJson: event.target.value })}
            placeholder="[]"
            value={form.assetRefsJson}
          />
        </label>
        <PreparedMediaUpload
          workspaceId={workspaceId}
          contentId={item?.id ?? null}
          disabled={!isEditable}
          label="Upload shared media"
          onBusy={setUploadBusy}
          onUploaded={(reference) =>
            setField({
              assetRefsJson: JSON.stringify(
                [
                  ...parseAssetRefs(form.assetRefsJson, "Asset references").filter(
                    (ref) =>
                      !(
                        ref &&
                        typeof ref === "object" &&
                        "sha256" in ref &&
                        ref.sha256 === reference.sha256
                      ),
                  ),
                  reference,
                ],
                null,
                2,
              ),
            })
          }
        />
      </div>

      <div className="grid gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-base font-semibold text-slate-950">Channel targets</h3>
          <Button
            disabled={!isEditable}
            onClick={() =>
              setForm((current) => ({
                ...current,
                channels: [...current.channels, emptyChannelRow(current.channels.length, timeZone)],
              }))
            }
            size="sm"
            type="button"
            variant="secondary"
          >
            Add channel
          </Button>
        </div>
        {duplicateChannels ? (
          <p className="text-sm font-medium text-red-700">
            Duplicate channel and placement targets are not allowed.
          </p>
        ) : null}
        {form.channels.length === 0 && (
          <p className="text-sm text-slate-600">
            No channel targets. Add a channel to configure content, destination, and schedule.
          </p>
        )}
        {form.channels.map((channel, index) => (
          <fieldset
            className="grid min-w-0 gap-3 rounded-md border border-slate-200 p-3"
            key={channel.id}
          >
            <legend className="px-1 text-sm font-semibold text-slate-700">
              Target {index + 1}: {humanize(channel.channel)}
              {channel.placement ? ` / ${channel.placement}` : ""}
            </legend>
            {(() => {
              const effectiveArtist = form.artistId || selectedCampaign?.primary_artist?.id;
              const providerAccounts = accountConnections.filter(
                (connection) =>
                  connection.provider === channel.channel &&
                  connection.workspace_id === workspaceId &&
                  (!effectiveArtist ||
                    !connection.artist_association ||
                    connection.artist_association.artist_id === effectiveArtist),
              );
              const selectedAccount =
                accountConnections.find(
                  (connection) => connection.id === channel.socialAccountConnectionId,
                ) ?? null;
              const accountWarning = selectedAccount
                ? accountConnectionWarning(selectedAccount)
                : null;
              return (
                <>
                  <div className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4 [&_input]:min-w-0 [&_select]:min-w-0">
                    <label className="grid gap-1 text-sm font-medium text-slate-700">
                      <span>Channel</span>
                      <select
                        className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                        disabled={!isEditable}
                        onChange={(event) =>
                          setChannel(channel.id, {
                            channel: event.target.value,
                            socialAccountConnectionId: "",
                          })
                        }
                        value={channel.channel}
                      >
                        <option value="">Choose channel</option>
                        {channelOptions.map((option) => (
                          <option key={option} value={option}>
                            {humanize(option)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="grid gap-1 text-sm font-medium text-slate-700">
                      <span>Placement</span>
                      <input
                        className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                        disabled={!isEditable}
                        onChange={(event) =>
                          setChannel(channel.id, { placement: event.target.value })
                        }
                        placeholder="default"
                        value={channel.placement}
                      />
                    </label>
                    <label className="grid gap-1 text-sm font-medium text-slate-700">
                      <span>Channel planned publish time</span>
                      <input
                        aria-label="Channel planned publish time"
                        className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                        disabled={!isEditable}
                        onChange={(event) =>
                          setChannel(channel.id, {
                            scheduledAt: event.target.value,
                            scheduleChoice: "",
                          })
                        }
                        step="any"
                        type="datetime-local"
                        value={channel.scheduledAt}
                      />
                    </label>
                    <label className="grid gap-1 text-sm font-medium text-slate-700">
                      <span>Channel authoring timezone</span>
                      <input
                        aria-label="Channel authoring timezone"
                        className="h-10 rounded-md border border-slate-300 bg-white px-3"
                        disabled={!isEditable}
                        placeholder="America/Los_Angeles"
                        value={channel.scheduleTimezone}
                        onChange={(event) =>
                          setChannel(channel.id, {
                            scheduleTimezone: event.target.value,
                            scheduleChoice: "",
                          })
                        }
                      />
                      {channel.legacyInstant && !channel.scheduleTimezone && (
                        <span>
                          Legacy planning time shown in {timeZone}. Confirm an IANA timezone to
                          author a schedule.
                        </span>
                      )}
                    </label>
                    <ScheduleFeedback
                      localTime={channel.scheduledAt}
                      timeZone={channel.scheduleTimezone}
                      choice={channel.scheduleChoice}
                      disabled={!isEditable}
                      onChoice={(scheduleChoice) => setChannel(channel.id, { scheduleChoice })}
                    />
                    <Button
                      type="button"
                      variant="secondary"
                      disabled={!isEditable || isMutating}
                      onClick={() => {
                        try {
                          const zone = channel.scheduleTimezone || timeZone;
                          const now = scheduleFromInstant(new Date().toISOString(), zone);
                          setChannel(channel.id, {
                            scheduledAt: now.localTime,
                            scheduleTimezone: zone,
                            scheduleChoice: now.choice,
                          });
                          setPublishNowNotice(
                            "Publish Now prepared a channel time edit. Save changes, submit for approval, complete review, then activate the approved schedule. If the delivery window passes during review, choose a new time and obtain reapproval.",
                          );
                        } catch (error) {
                          setClientError((error as Error).message);
                        }
                      }}
                    >
                      Publish Now
                    </Button>
                    <Button
                      className="self-end"
                      disabled={!isEditable || form.channels.length === 1}
                      onClick={() =>
                        setForm((current) => ({
                          ...current,
                          channels: current.channels.filter((entry) => entry.id !== channel.id),
                        }))
                      }
                      size="sm"
                      type="button"
                      variant="secondary"
                    >
                      Remove
                    </Button>
                  </div>
                  <label className="grid gap-1 text-sm font-medium text-slate-700">
                    <span>Destination account</span>
                    <select
                      aria-label="Destination account"
                      className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                      disabled={
                        !isEditable ||
                        !channel.channel ||
                        socialAccounts.isLoading ||
                        Boolean(socialAccounts.error)
                      }
                      onChange={(event) =>
                        setChannel(channel.id, { socialAccountConnectionId: event.target.value })
                      }
                      value={channel.socialAccountConnectionId}
                    >
                      <option value="">{humanize(channel.channel)} - No account selected</option>
                      {channel.socialAccountConnectionId &&
                        !providerAccounts.some(
                          (account) => account.id === channel.socialAccountConnectionId,
                        ) && (
                          <option value={channel.socialAccountConnectionId} disabled>
                            Selected account unavailable or incompatible — choose another
                          </option>
                        )}
                      {providerAccounts.map((connection) => (
                        <option key={connection.id} value={connection.id}>
                          {accountConnectionLabel(connection)}
                        </option>
                      ))}
                    </select>
                    {socialAccounts.isLoading && (
                      <span role="status">Loading destination accounts...</span>
                    )}
                    {!socialAccounts.isLoading &&
                      !socialAccounts.error &&
                      providerAccounts.length === 0 && (
                        <span>
                          No compatible accounts. Connect an account for this channel and artist in
                          Accounts.
                        </span>
                      )}
                    {socialAccounts.error ? (
                      <span className="text-xs font-normal text-amber-700">
                        {socialAccounts.error.message}
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          onClick={() => void socialAccounts.reload().catch(() => undefined)}
                        >
                          Retry accounts
                        </Button>
                      </span>
                    ) : null}
                    {accountWarning ? (
                      <span className="text-xs font-medium text-amber-700">{accountWarning}</span>
                    ) : null}
                  </label>
                  <label className="grid gap-1 text-sm font-medium text-slate-700">
                    <span>Channel copy override</span>
                    <textarea
                      className="min-h-16 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950"
                      disabled={!isEditable}
                      onChange={(event) =>
                        setChannel(channel.id, { copyTextOverride: event.target.value })
                      }
                      value={channel.copyTextOverride}
                    />
                  </label>
                  <label className="grid gap-1 text-sm font-medium text-slate-700">
                    <span>Channel asset references</span>
                    <textarea
                      className="min-h-16 rounded-md border border-slate-300 bg-white px-3 py-2 font-mono text-xs text-slate-950"
                      disabled={!isEditable}
                      onChange={(event) =>
                        setChannel(channel.id, { assetRefsJson: event.target.value })
                      }
                      placeholder="[]"
                      value={channel.assetRefsJson}
                    />
                  </label>
                  <PreparedMediaUpload
                    workspaceId={workspaceId}
                    contentId={item?.id ?? null}
                    disabled={!isEditable}
                    label={`Upload media for target ${index + 1}`}
                    onBusy={setUploadBusy}
                    onUploaded={(reference) =>
                      setChannel(channel.id, {
                        assetRefsJson: JSON.stringify(
                          [
                            ...parseAssetRefs(
                              channel.assetRefsJson,
                              "Channel asset references",
                            ).filter(
                              (ref) =>
                                !(
                                  ref &&
                                  typeof ref === "object" &&
                                  "sha256" in ref &&
                                  ref.sha256 === reference.sha256
                                ),
                            ),
                            reference,
                          ],
                          null,
                          2,
                        ),
                      })
                    }
                  />
                  <p className="text-xs text-slate-500">Target {index + 1}</p>
                  {item && item.channels.find((saved) => saved.id === channel.persistedId) && (
                    <ChannelScheduling
                      key={`${item.workspace_id}:${channel.persistedId}`}
                      item={item}
                      channel={item.channels.find((saved) => saved.id === channel.persistedId)!}
                      canSchedule={canSchedule}
                      dirty={dirty}
                      busy={isMutating}
                      onBusy={setSchedulingBusy}
                      onReloadContent={onReloadContent}
                    />
                  )}
                </>
              );
            })()}
          </fieldset>
        ))}
      </div>

      {item && (
        <PublicationHistory
          item={item}
          campaignName={campaignName(campaigns, item.campaign_id)}
          artistName={artistOptions.find((artist) => artist.id === item.artist_id)?.name}
        />
      )}

      {publishNowNotice && (
        <p role="status" className="text-sm text-amber-800">
          {publishNowNotice}
        </p>
      )}
      {dirty && item && (
        <p className="text-sm text-amber-800">
          Save changes before submitting this revision for approval.
        </p>
      )}
      {!item && (
        <p className="text-sm text-slate-600">
          Save this draft to inspect approval readiness and activate channel schedules after
          approval.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button disabled={!isEditable || isMutating} onClick={saveDraft} type="button">
          {mode === "create" ? "Save draft" : "Save changes"}
        </Button>
        {item?.status === "draft" && approvalState !== "changes_requested" && canSubmitForReview ? (
          <Button
            disabled={isMutating || dirty}
            onClick={submitForReview}
            type="button"
            variant="secondary"
          >
            Submit for approval
          </Button>
        ) : null}
        {item?.status === "draft" && approvalState === "changes_requested" && canSubmitForReview ? (
          <Button
            disabled={isMutating || dirty}
            onClick={submitForReview}
            type="button"
            variant="secondary"
          >
            Resubmit for approval
          </Button>
        ) : null}
        {item?.approval_request_id ? (
          <Button
            disabled={isMutating}
            onClick={() => onOpenApprovalReview(item.approval_request_id)}
            type="button"
            variant="secondary"
          >
            Open Approval Review
          </Button>
        ) : null}
        {item && isDraftSurface && canArchive && item.status === "draft" ? (
          <Button disabled={isMutating} onClick={archiveContent} type="button" variant="secondary">
            {archive.isMutating ? "Archiving..." : "Archive"}
          </Button>
        ) : null}
        {!isEditable ? (
          <span className="text-sm text-slate-500">
            You need edit access to change this content.
          </span>
        ) : null}
      </div>
    </Card>
  );
}

function contentDetailErrorMessage(code: string | undefined): string {
  if (code === "unauthorized") {
    return "Sign in again to open this marketing content.";
  }
  if (code === "forbidden") {
    return "You do not have access to this marketing content.";
  }
  if (code === "not_found") {
    return "This marketing content is missing or was deleted.";
  }
  return "Marketing content detail could not be loaded.";
}

export function ContentEditorDetail({
  campaigns,
  canEdit,
  canArchive,
  canSubmitForReview,
  createDate,
  filters,
  item,
  mode,
  onCancel,
  onArchived,
  onOpenApprovalReview,
  onSaved,
  surface,
  timeZone,
}: {
  campaigns: Campaign[];
  canEdit: boolean;
  canArchive: boolean;
  canSubmitForReview: boolean;
  createDate: string | null;
  filters: CalendarFilters;
  item: MarketingContentItem | null;
  mode: ContentEditorMode;
  onCancel: () => void;
  onArchived: (item: MarketingContentItem) => void;
  onOpenApprovalReview: (approvalRequestId: string | null) => void;
  onSaved: (item: MarketingContentItem | null) => void;
  surface: ContentEditorSurface;
  timeZone: string;
}) {
  const detail = useMarketingContentItem(
    mode === "edit" ? (item?.workspace_id ?? null) : null,
    mode === "edit" ? (item?.campaign_id ?? null) : null,
    mode === "edit" ? (item?.id ?? null) : null,
  );

  if (mode === "edit") {
    if (detail.isLoading && !detail.data) {
      return (
        <Card className="grid gap-3 p-4" role="region" aria-label="Marketing content editor">
          <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-950">Edit content</h2>
              <p className="text-sm text-slate-500">Loading the latest marketing content.</p>
            </div>
            <Button onClick={onCancel} size="sm" type="button" variant="secondary">
              Close
            </Button>
          </div>
          <LoadingState label="Loading marketing content detail" />
        </Card>
      );
    }

    if (detail.error || !detail.data) {
      return (
        <Card className="grid gap-4 p-4" role="region" aria-label="Marketing content editor">
          <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-950">Edit content</h2>
              <p className="text-sm text-slate-500">{item?.title ?? "Marketing content detail"}</p>
            </div>
            <Button onClick={onCancel} size="sm" type="button" variant="secondary">
              Close
            </Button>
          </div>
          <div
            className={cn(
              "rounded-md border px-4 py-3 text-sm",
              detail.error?.code === "unauthorized" || detail.error?.code === "forbidden"
                ? "border-amber-200 bg-amber-50 text-amber-900"
                : "border-red-200 bg-red-50 text-red-900",
            )}
            role={
              detail.error?.code === "unauthorized" || detail.error?.code === "forbidden"
                ? "status"
                : "alert"
            }
          >
            {contentDetailErrorMessage(detail.error?.code)}
          </div>
          {detail.error?.code !== "not_found" ? (
            <Button
              disabled={detail.isLoading}
              onClick={() => void detail.reload().catch(() => undefined)}
              size="sm"
              type="button"
              variant="secondary"
            >
              Retry
            </Button>
          ) : null}
        </Card>
      );
    }
  }

  const canonicalItem = mode === "edit" ? detail.data : item;

  return (
    <ContentEditor
      campaigns={campaigns}
      canEdit={canEdit}
      canArchive={canArchive}
      canSubmitForReview={canSubmitForReview}
      createDate={createDate}
      filters={filters}
      item={canonicalItem}
      key={canonicalItem ? `${canonicalItem.id}:${canonicalItem.updated_at}` : undefined}
      mode={mode}
      onCancel={onCancel}
      onArchived={onArchived}
      onOpenApprovalReview={onOpenApprovalReview}
      onSaved={onSaved}
      onReloadContent={() => void detail.reload().catch(() => undefined)}
      surface={surface}
      timeZone={timeZone}
    />
  );
}
