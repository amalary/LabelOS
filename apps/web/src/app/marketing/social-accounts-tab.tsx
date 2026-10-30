"use client";

import {
  type SocialAccountCapability,
  type SocialAccountProvider,
  type SocialAccountConnection,
  type SocialAccountConnectionStatus,
  useSocialAccountConnections,
  useCreateAssistedSocialAccountConnection,
  useStartSocialAccountOAuthConnection,
  type AssistedSocialAccountConnectionCreate,
  navigateToSocialAccountAuthorization,
  useUpdateSocialAccountConnection,
  useDisconnectSocialAccountConnection,
} from "../../lib/social-account-connections";
import { humanize } from "./marketing-presentation";
import { type Campaign } from "../../lib/campaigns";
import { useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { Card, Badge, Button, LoadingState, EmptyState } from "@label-os/ui";

const socialAccountProviders = [
  "instagram",
  "facebook",
  "tiktok",
  "youtube",
  "spotify",
  "x",
] as const;

const assistedCapabilityOptions: SocialAccountCapability[] = [
  "manual_publish",
  "manual_metrics",
  "account_analytics_read",
  "post_analytics_read",
];

type SocialAccountFormState = {
  provider: SocialAccountProvider;
  artistProfileId: string;
  handle: string;
  displayName: string;
  profileUrl: string;
  capabilities: SocialAccountCapability[];
  providerMetadataJson: string;
};

function emptySocialAccountForm(): SocialAccountFormState {
  return {
    artistProfileId: "",
    capabilities: ["manual_publish"],
    displayName: "",
    handle: "",
    profileUrl: "",
    provider: "instagram",
    providerMetadataJson: "",
  };
}

function socialAccountFormFromConnection(
  connection: SocialAccountConnection,
): SocialAccountFormState {
  return {
    artistProfileId: connection.artist_association?.artist_profile_id ?? "",
    capabilities: connection.capabilities.length ? connection.capabilities : ["manual_publish"],
    displayName: connection.display_name ?? "",
    handle: connection.handle ?? "",
    profileUrl: connection.profile_url ?? "",
    provider: connection.provider,
    providerMetadataJson: Object.keys(connection.provider_metadata).length
      ? JSON.stringify(connection.provider_metadata, null, 2)
      : "",
  };
}

function parseMetadataJson(value: string): Record<string, unknown> {
  const trimmed = value.trim();
  if (!trimmed) {
    return {};
  }
  const parsed = JSON.parse(trimmed) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Provider metadata must be a JSON object.");
  }
  return parsed as Record<string, unknown>;
}

function providerLabel(provider: SocialAccountProvider): string {
  if (provider === "x") {
    return "X";
  }
  if (provider === "tiktok") {
    return "TikTok";
  }
  if (provider === "youtube") {
    return "YouTube";
  }
  return humanize(provider);
}

function connectionModeLabel(
  connection: Pick<SocialAccountConnection, "connection_method">,
): string {
  if (connection.connection_method === "assisted") {
    return "Assisted Publishing";
  }
  if (connection.connection_method === "direct_api") {
    return "Direct API";
  }
  return "Third-party";
}

function socialStatusVariant(status: SocialAccountConnectionStatus) {
  if (status === "connected") {
    return "success" as const;
  }
  if (status === "limited" || status === "reconnect_required" || status === "error") {
    return "warning" as const;
  }
  return "neutral" as const;
}

function socialAttentionLabel(connection: SocialAccountConnection): string {
  if (connection.status === "connected") {
    return "Active";
  }
  if (connection.status === "limited") {
    return "Limited access";
  }
  if (connection.status === "reconnect_required") {
    return "Needs reconnect";
  }
  if (connection.status === "error") {
    return connection.last_error_message ?? "Needs attention";
  }
  if (connection.status === "disconnected") {
    return "Disconnected";
  }
  return "Pending setup";
}

function capabilityLabel(capability: SocialAccountCapability): string {
  if (capability === "content_publish") {
    return "Auto-publish content";
  }
  if (capability === "manual_publish") {
    return "Assisted publishing checklist";
  }
  if (capability === "manual_metrics") {
    return "Manual metrics entry";
  }
  if (capability === "account_analytics_read") {
    return "Account analytics reference";
  }
  if (capability === "post_analytics_read") {
    return "Post analytics reference";
  }
  return humanize(capability);
}

function accountDisplayName(connection: SocialAccountConnection): string {
  return (
    connection.handle ||
    connection.display_name ||
    connection.external_account_id ||
    "Unnamed account"
  );
}

function providerAccountCount(
  accounts: SocialAccountConnection[],
  provider: (typeof socialAccountProviders)[number],
): number {
  return accounts.filter((account) => account.provider.toLowerCase() === provider).length;
}

function campaignArtistOptions(campaigns: Campaign[]) {
  return [
    ...campaigns.flatMap((campaign) => [
      ...(campaign.primary_artist ? [campaign.primary_artist] : []),
      ...campaign.artists.map((entry) => entry.artist),
    ]),
  ].filter(
    (artist, index, artists) => artists.findIndex((entry) => entry.id === artist.id) === index,
  );
}

function capabilityText(connection: SocialAccountConnection): string {
  const labels = connection.capabilities.map(capabilityLabel);
  if (connection.resolved_capabilities.requires_manual_publish && !labels.length) {
    labels.push("Assisted publishing checklist");
  }
  return labels.length ? labels.join(", ") : "No capabilities configured";
}

function isYouTubeDirectOAuthEnabled(): boolean {
  return process.env.NEXT_PUBLIC_YOUTUBE_DIRECT_OAUTH_ENABLED === "true";
}

export function SocialAccountsTab({
  campaigns,
  canManage,
  workspaceId,
}: {
  campaigns: Campaign[];
  canManage: boolean;
  workspaceId: string;
}) {
  const accounts = useSocialAccountConnections(workspaceId, {
    include_disconnected: true,
    limit: 100,
    offset: 0,
  });
  const create = useCreateAssistedSocialAccountConnection(workspaceId);
  const youtubeOAuth = useStartSocialAccountOAuthConnection(workspaceId);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<SocialAccountFormState>(() => emptySocialAccountForm());
  const [clientError, setClientError] = useState<string | null>(null);
  const accountItems = accounts.data?.social_account_connections ?? [];
  const artistOptions = campaignArtistOptions(campaigns);
  const youtubeDirectOAuthEnabled = isYouTubeDirectOAuthEnabled();
  const oauthResult = useSearchParams().get("oauth");

  function updateCapability(capability: SocialAccountCapability, checked: boolean) {
    setForm((current) => ({
      ...current,
      capabilities: checked
        ? [...new Set([...current.capabilities, capability])]
        : current.capabilities.filter((entry) => entry !== capability),
    }));
  }

  async function registerAccount() {
    setClientError(null);
    try {
      await create.mutate({
        artist_profile_id: form.artistProfileId.trim() || null,
        capabilities: form.capabilities,
        display_name: form.displayName.trim() || null,
        handle: form.handle.trim() || null,
        profile_url: form.profileUrl.trim() || null,
        provider: form.provider,
        provider_metadata: parseMetadataJson(form.providerMetadataJson),
      } satisfies AssistedSocialAccountConnectionCreate);
      setForm(emptySocialAccountForm());
      setShowForm(false);
      void accounts.reload().catch(() => undefined);
    } catch (error) {
      setClientError(
        error instanceof SyntaxError
          ? "Provider metadata must be valid JSON."
          : (error as Error).message,
      );
    }
  }

  async function connectYouTube() {
    setClientError(null);
    try {
      const redirectUri = `${window.location.origin}/api/social-account-connections/oauth/youtube/callback`;
      const result = await youtubeOAuth.mutate({
        provider: "youtube",
        redirect_uri: redirectUri,
        safe_redirect_path: "/marketing?tab=accounts",
      });
      navigateToSocialAccountAuthorization(result.authorization_url);
    } catch (error) {
      setClientError((error as Error).message);
    }
  }

  return (
    <section className="grid gap-4" aria-label="Social account connections">
      {oauthResult === "connected" && (
        <p role="status" className="text-sm text-indigo-800">
          Account connection updated. If recovering a publication, return to its delivery details
          and refresh. Reconnection does not publish; request Retry when ready.
        </p>
      )}
      {oauthResult === "failed" && (
        <p role="alert" className="text-sm text-red-800">
          Account connection could not be completed. Try reconnecting again.
        </p>
      )}
      <Card className="grid gap-1">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">Social Account Connections</h2>
            <p className="text-sm text-slate-500">
              Registered destinations for assisted and direct provider workflows.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge>{accountItems.length} accounts</Badge>
            {canManage && youtubeDirectOAuthEnabled ? (
              <Button
                disabled={youtubeOAuth.isMutating}
                onClick={connectYouTube}
                size="sm"
                type="button"
                variant="secondary"
              >
                {youtubeOAuth.isMutating ? "Connecting..." : "Connect YouTube"}
              </Button>
            ) : null}
            {canManage ? (
              <Button onClick={() => setShowForm((current) => !current)} size="sm" type="button">
                {showForm ? "Close" : "Register Account"}
              </Button>
            ) : null}
          </div>
        </div>
      </Card>

      {!canManage ? (
        <div
          className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
          role="status"
        >
          You can view social accounts, but need marketing account manage access to register, edit,
          or disconnect them.
        </div>
      ) : null}

      <Card className="grid gap-3 p-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
          {socialAccountProviders.map((provider) => {
            const count = providerAccountCount(accountItems, provider);
            return (
              <div className="rounded-md border border-slate-200 p-3" key={provider}>
                <p className="text-sm font-semibold text-slate-950">{providerLabel(provider)}</p>
                <p className="mt-1 text-xs text-slate-500">
                  {count
                    ? `${count} registered`
                    : provider === "youtube" && youtubeDirectOAuthEnabled
                      ? "Ready for direct connection"
                      : "Direct connection not yet available"}
                </p>
                <p className="mt-2 text-xs font-medium text-slate-700">
                  {provider === "youtube" && youtubeDirectOAuthEnabled
                    ? "Direct API supported"
                    : "Assisted Mode supported"}
                </p>
              </div>
            );
          })}
        </div>
      </Card>

      {showForm && canManage ? (
        <Card className="grid gap-4 p-4" role="region" aria-label="Assisted account registration">
          <div>
            <h3 className="text-base font-semibold text-slate-950">Register Assisted Account</h3>
            <p className="text-sm text-slate-500">
              This records the account and supported manual workflows. It does not create a direct
              provider login.
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              <span>Provider</span>
              <select
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    provider: event.target.value as SocialAccountProvider,
                  }))
                }
                value={form.provider}
              >
                {socialAccountProviders.map((provider) => (
                  <option key={provider} value={provider}>
                    {providerLabel(provider)}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              <span>Handle</span>
              <input
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                onChange={(event) =>
                  setForm((current) => ({ ...current, handle: event.target.value }))
                }
                placeholder="@artist"
                value={form.handle}
              />
            </label>
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              <span>Display name</span>
              <input
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                onChange={(event) =>
                  setForm((current) => ({ ...current, displayName: event.target.value }))
                }
                value={form.displayName}
              />
            </label>
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              <span>Artist profile ID</span>
              <input
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                list="social-account-artist-options"
                onChange={(event) =>
                  setForm((current) => ({ ...current, artistProfileId: event.target.value }))
                }
                placeholder="artist_profile_..."
                value={form.artistProfileId}
              />
              <datalist id="social-account-artist-options">
                {artistOptions.map((artist) => (
                  <option key={artist.id} value={artist.id}>
                    {artist.name}
                  </option>
                ))}
              </datalist>
            </label>
            <label className="grid gap-1 text-sm font-medium text-slate-700 md:col-span-2">
              <span>Profile URL</span>
              <input
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                onChange={(event) =>
                  setForm((current) => ({ ...current, profileUrl: event.target.value }))
                }
                placeholder="https://..."
                type="url"
                value={form.profileUrl}
              />
            </label>
          </div>
          <fieldset className="grid gap-2">
            <legend className="text-sm font-medium text-slate-700">LabelOS can</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {assistedCapabilityOptions.map((capability) => (
                <label className="flex items-center gap-2 text-sm text-slate-700" key={capability}>
                  <input
                    checked={form.capabilities.includes(capability)}
                    onChange={(event) => updateCapability(capability, event.target.checked)}
                    type="checkbox"
                  />
                  <span>{capabilityLabel(capability)}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            <span>Provider metadata JSON</span>
            <textarea
              className="min-h-24 rounded-md border border-slate-300 bg-white px-3 py-2 font-mono text-sm text-slate-950"
              onChange={(event) =>
                setForm((current) => ({ ...current, providerMetadataJson: event.target.value }))
              }
              placeholder='{"source":"artist-submitted"}'
              value={form.providerMetadataJson}
            />
          </label>
          {clientError || create.error ? (
            <p className="text-sm font-medium text-red-700" role="alert">
              {clientError ?? create.error?.message}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button disabled={create.isMutating} onClick={registerAccount} type="button">
              {create.isMutating ? "Registering..." : "Register Assisted Account"}
            </Button>
            <Button
              onClick={() => {
                setShowForm(false);
                setClientError(null);
              }}
              type="button"
              variant="secondary"
            >
              Cancel
            </Button>
          </div>
        </Card>
      ) : null}

      {accounts.error ? (
        <div
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
          role="alert"
        >
          {accounts.error.code === "forbidden"
            ? "Social account access was denied for this workspace."
            : "Social account connections could not be loaded."}
        </div>
      ) : null}

      {accounts.isLoading && !accounts.data ? (
        <Card className="grid gap-3">
          <LoadingState label="Loading social account connections" />
          {Array.from({ length: 3 }, (_, index) => (
            <div className="h-20 rounded-md bg-slate-100 auth-shimmer" key={index} />
          ))}
        </Card>
      ) : accountItems.length === 0 ? (
        <EmptyState
          action={
            canManage ? (
              <Button onClick={() => setShowForm(true)} type="button">
                Register Account
              </Button>
            ) : null
          }
          description="Register assisted social accounts to track provider, artist, publishing mode, capabilities, and attention states before OAuth is available."
          title="No social accounts registered"
        />
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {accountItems.map((connection) => (
            <SocialAccountCard
              canManage={canManage}
              connection={connection}
              key={connection.id}
              onChanged={() => void accounts.reload().catch(() => undefined)}
              workspaceId={workspaceId}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function SocialAccountCard({
  canManage,
  connection,
  onChanged,
  workspaceId,
}: {
  canManage: boolean;
  connection: SocialAccountConnection;
  onChanged: () => void;
  workspaceId: string;
}) {
  const update = useUpdateSocialAccountConnection(workspaceId, connection.id);
  const disconnect = useDisconnectSocialAccountConnection(workspaceId, connection.id);
  const [isEditing, setIsEditing] = useState(false);
  const [localConnection, setLocalConnection] = useState(connection);
  const [form, setForm] = useState(() => socialAccountFormFromConnection(connection));
  const [clientError, setClientError] = useState<string | null>(null);

  useEffect(() => {
    setLocalConnection(connection);
    setForm(socialAccountFormFromConnection(connection));
  }, [connection]);

  function updateCapability(capability: SocialAccountCapability, checked: boolean) {
    setForm((current) => ({
      ...current,
      capabilities: checked
        ? [...new Set([...current.capabilities, capability])]
        : current.capabilities.filter((entry) => entry !== capability),
    }));
  }

  async function saveAccount() {
    setClientError(null);
    try {
      const saved = await update.mutate({
        artist_profile_id: form.artistProfileId.trim() || null,
        capabilities: form.capabilities,
        display_name: form.displayName.trim() || null,
        handle: form.handle.trim() || null,
        profile_url: form.profileUrl.trim() || null,
        provider_metadata: parseMetadataJson(form.providerMetadataJson),
      });
      setLocalConnection(saved);
      setIsEditing(false);
      onChanged();
    } catch (error) {
      setClientError(
        error instanceof SyntaxError
          ? "Provider metadata must be valid JSON."
          : (error as Error).message,
      );
    }
  }

  async function disconnectAccount() {
    if (
      !window.confirm(
        `Disconnect ${providerLabel(localConnection.provider)} ${accountDisplayName(
          localConnection,
        )}? It will remain visible in social account history.`,
      )
    ) {
      return;
    }
    try {
      const disconnected = await disconnect.mutate();
      setLocalConnection(disconnected);
      onChanged();
    } catch {
      // Mutation state renders API failures inline.
    }
  }

  return (
    <Card className="grid gap-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-base font-semibold text-slate-950">
              {providerLabel(localConnection.provider)}
            </h3>
            <Badge variant={socialStatusVariant(localConnection.status)}>
              {humanize(localConnection.status)}
            </Badge>
            <Badge>{connectionModeLabel(localConnection)}</Badge>
          </div>
          <p className="mt-1 truncate text-sm font-medium text-slate-800">
            {accountDisplayName(localConnection)}
          </p>
          <p className="mt-1 text-xs text-slate-500">Direct connection not yet available</p>
        </div>
        {canManage ? (
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => {
                setIsEditing((current) => !current);
                setClientError(null);
              }}
              size="sm"
              type="button"
              variant="secondary"
            >
              {isEditing ? "Close" : "Edit"}
            </Button>
            {localConnection.status !== "disconnected" ? (
              <Button
                disabled={disconnect.isMutating}
                onClick={disconnectAccount}
                size="sm"
                type="button"
                variant="secondary"
              >
                {disconnect.isMutating ? "Disconnecting..." : "Disconnect"}
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>

      <dl className="grid gap-3 sm:grid-cols-2">
        <div>
          <dt className="text-xs font-semibold uppercase text-slate-500">Artist</dt>
          <dd className="mt-1 text-sm font-medium text-slate-800">
            {localConnection.artist_association?.stage_name ??
              localConnection.artist_association?.artist_name ??
              "Unassigned"}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase text-slate-500">Attention</dt>
          <dd className="mt-1 text-sm font-medium text-slate-800">
            {socialAttentionLabel(localConnection)}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase text-slate-500">LabelOS can</dt>
          <dd className="mt-1 text-sm font-medium text-slate-800">
            {capabilityText(localConnection)}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase text-slate-500">Last checked</dt>
          <dd className="mt-1 text-sm font-medium text-slate-800">
            {localConnection.last_health_checked_at?.slice(0, 10) ?? "Not checked"}
          </dd>
        </div>
      </dl>

      {isEditing ? (
        <div className="grid gap-3 border-t border-slate-100 pt-4">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              <span>Handle</span>
              <input
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                onChange={(event) =>
                  setForm((current) => ({ ...current, handle: event.target.value }))
                }
                value={form.handle}
              />
            </label>
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              <span>Display name</span>
              <input
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                onChange={(event) =>
                  setForm((current) => ({ ...current, displayName: event.target.value }))
                }
                value={form.displayName}
              />
            </label>
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              <span>Artist profile ID</span>
              <input
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                onChange={(event) =>
                  setForm((current) => ({ ...current, artistProfileId: event.target.value }))
                }
                value={form.artistProfileId}
              />
            </label>
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              <span>Profile URL</span>
              <input
                className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-950"
                onChange={(event) =>
                  setForm((current) => ({ ...current, profileUrl: event.target.value }))
                }
                type="url"
                value={form.profileUrl}
              />
            </label>
          </div>
          <fieldset className="grid gap-2">
            <legend className="text-sm font-medium text-slate-700">Capabilities</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {assistedCapabilityOptions.map((capability) => (
                <label className="flex items-center gap-2 text-sm text-slate-700" key={capability}>
                  <input
                    checked={form.capabilities.includes(capability)}
                    onChange={(event) => updateCapability(capability, event.target.checked)}
                    type="checkbox"
                  />
                  <span>{capabilityLabel(capability)}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            <span>Provider metadata JSON</span>
            <textarea
              className="min-h-24 rounded-md border border-slate-300 bg-white px-3 py-2 font-mono text-sm text-slate-950"
              onChange={(event) =>
                setForm((current) => ({ ...current, providerMetadataJson: event.target.value }))
              }
              value={form.providerMetadataJson}
            />
          </label>
          {clientError || update.error || disconnect.error ? (
            <p className="text-sm font-medium text-red-700" role="alert">
              {clientError ?? update.error?.message ?? disconnect.error?.message}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button disabled={update.isMutating} onClick={saveAccount} size="sm" type="button">
              {update.isMutating ? "Saving..." : "Save changes"}
            </Button>
            <Button
              onClick={() => {
                setForm(socialAccountFormFromConnection(localConnection));
                setIsEditing(false);
                setClientError(null);
              }}
              size="sm"
              type="button"
              variant="secondary"
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : null}

      {!isEditing && disconnect.error ? (
        <p className="text-sm font-medium text-red-700" role="alert">
          {disconnect.error.message}
        </p>
      ) : null}
    </Card>
  );
}
