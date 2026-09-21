"use client";

import { Button } from "@label-os/ui";
import { useRef, useState } from "react";
import {
  publicationCommand,
  PublicationCommandError,
  publicProviderUrl,
  type Publication,
  type PublicationCommand,
} from "../../lib/publications";
import {
  startSocialAccountOAuthConnection,
  navigateToSocialAccountAuthorization,
} from "../../lib/social-account-connections";

export function PublicationRecovery({
  publication,
  refreshing,
  onRefresh,
}: {
  publication: Publication;
  refreshing: boolean;
  onRefresh: () => Promise<void>;
}) {
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [externalId, setExternalId] = useState("");
  const [providerUrl, setProviderUrl] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const lock = useRef(false);
  const operation = useRef<{ signature: string; id: string } | null>(null);
  const terminal =
    ["published", "cancelled", "manually_completed"].includes(publication.resolution) ||
    [
      "published",
      "cancelled",
      "manual_action_required",
      "processing",
      "pending",
      "retrying",
    ].includes(publication.delivery_status);
  const allowed =
    publication.can_manage_recovery === true &&
    !terminal &&
    Number.isInteger(publication.transition_version) &&
    Number.isInteger(publication.action_version);
  const retry =
    allowed &&
    publication.can_authorize_retry === true &&
    publication.destination_identity_matches &&
    (publication.resolution !== "reconnect_required" ||
      ["connected", "limited"].includes(publication.destination_connection_status ?? ""));
  const reserve =
    allowed && publication.can_begin_manual === true && publication.destination_identity_matches;
  const complete =
    allowed &&
    publication.can_complete_manual === true &&
    publication.resolution === "manual_publishing";
  const reconnect =
    !terminal &&
    publication.resolution === "reconnect_required" &&
    publication.destination_identity_matches &&
    publication.can_manage_account === true;
  const directReconnect =
    reconnect &&
    publication.provider === "youtube" &&
    publication.destination_connection_method === "direct_api" &&
    process.env.NEXT_PUBLIC_YOUTUBE_DIRECT_OAUTH_ENABLED === "true";
  const disabled = refreshing || pending !== null;

  async function command(command: PublicationCommand) {
    if (
      lock.current ||
      disabled ||
      !(command === "recover" ? retry : command === "manual/start" ? reserve : complete)
    )
      return;
    const id = externalId.trim();
    const url = providerUrl.trim();
    if (
      command === "manual/complete" &&
      (!confirmed ||
        id.length > 512 ||
        [...externalId].some(
          (character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127,
        ) ||
        url.length > 2048 ||
        (url && !publicProviderUrl(url)))
    ) {
      setError(
        "Confirm delivery and use a valid resource ID and public HTTPS URL without credentials, query strings, or fragments.",
      );
      return;
    }
    const evidence =
      command === "manual/complete"
        ? {
            delivery_confirmed: true,
            ...(id ? { external_post_id: id } : {}),
            ...(url ? { provider_url: url } : {}),
          }
        : {};
    const signature = JSON.stringify([
      publication.id,
      command,
      publication.transition_version,
      publication.action_version,
      evidence,
    ]);
    if (operation.current?.signature !== signature)
      operation.current = { signature, id: crypto.randomUUID() };
    lock.current = true;
    setPending(command);
    setError(null);
    setNotice(null);
    try {
      await publicationCommand(publication, command, operation.current.id, evidence);
      operation.current = null;
      setNotice(
        command === "recover"
          ? "Retry authorized. The worker will revalidate delivery."
          : command === "manual/start"
            ? "Manual delivery reserved. Publish the prepared content, then confirm completion."
            : "Manual completion recorded. Automatic attempt history is preserved.",
      );
    } catch (reason) {
      setError(
        reason instanceof PublicationCommandError
          ? reason.message
          : "Recovery could not be confirmed. Refresh and try again.",
      );
    } finally {
      await onRefresh();
      lock.current = false;
      setPending(null);
    }
  }

  async function reconnectAccount() {
    if (lock.current || disabled || !directReconnect) return;
    lock.current = true;
    setPending("reconnect");
    setError(null);
    setNotice(null);
    // Keep the immutable publication handoff open while using the existing OAuth flow.
    const popup = window.open("about:blank", "labelos-social-reconnect");
    try {
      if (!popup) throw new Error("popup_blocked");
      popup.opener = null;
      const result = await startSocialAccountOAuthConnection(publication.workspace_id, {
        provider: publication.provider,
        redirect_uri: `${window.location.origin}/api/social-account-connections/oauth/youtube/callback`,
        safe_redirect_path: "/marketing?tab=accounts",
      });
      navigateToSocialAccountAuthorization(result.authorization_url, popup);
      setNotice(
        "Reconnect the original account in the opened window, then return here. Connection state refreshes automatically; choose Retry explicitly when ready.",
      );
    } catch {
      popup?.close();
      setError("Unable to start reconnection. Allow popups and try again, or open Accounts.");
    } finally {
      lock.current = false;
      setPending(null);
    }
  }

  return (
    <div className="grid gap-3" aria-label="Publication recovery actions">
      {error && (
        <p role="alert" className="text-sm text-red-800">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="text-sm text-indigo-800">
          {notice}
        </p>
      )}
      {reconnect && (
        <p className="text-sm">
          Reconnect the original destination account. Reconnection alone does not publish this
          content.
        </p>
      )}
      {directReconnect && (
        <Button
          type="button"
          variant="secondary"
          disabled={disabled}
          onClick={() => void reconnectAccount()}
        >
          {pending === "reconnect" ? "Opening reconnect..." : "Reconnect Account"}
        </Button>
      )}
      {reconnect && !directReconnect && (
        <a className="text-indigo-700 underline" href="/marketing?tab=accounts">
          Reconnect Account in Accounts
        </a>
      )}
      {retry && (
        <>
          <p className="text-sm">
            Confirm that the account access or other failure has been resolved before requesting
            another attempt.
          </p>
          <Button type="button" disabled={disabled} onClick={() => void command("recover")}>
            {pending === "recover" ? "Requesting retry..." : "Retry"}
          </Button>
        </>
      )}
      {reserve && (
        <>
          <p className="text-sm">
            Reserve manual delivery before publishing yourself. This pauses automatic delivery and
            cannot be released back to automation.
          </p>
          <Button
            type="button"
            variant="secondary"
            disabled={disabled}
            onClick={() => void command("manual/start")}
          >
            {pending === "manual/start"
              ? "Reserving manual delivery..."
              : "Reserve manual delivery"}
          </Button>
        </>
      )}
      {complete && (
        <form
          className="grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            void command("manual/complete");
          }}
        >
          <p>
            Publish the approved caption, hashtags, and prepared assets below yourself. This records
            human completion; it does not publish through the provider API.
          </p>
          <label className="grid gap-1">
            Provider resource ID (optional)
            <input
              className="rounded border border-slate-300 p-2"
              value={externalId}
              maxLength={512}
              disabled={disabled}
              onChange={(event) => setExternalId(event.target.value)}
            />
          </label>
          <label className="grid gap-1">
            Provider URL (optional)
            <input
              className="rounded border border-slate-300 p-2"
              type="url"
              value={providerUrl}
              maxLength={2048}
              disabled={disabled}
              onChange={(event) => setProviderUrl(event.target.value)}
            />
          </label>
          <p className="text-xs text-slate-500">
            Use a public HTTPS URL without credentials, query strings, or fragments.
          </p>
          <label className="flex gap-2">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={disabled}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            I confirm I published this prepared content to the original destination.
          </label>
          <Button type="submit" disabled={disabled || !confirmed}>
            {pending === "manual/complete"
              ? "Recording completion..."
              : "Mark publication completed"}
          </Button>
        </form>
      )}
    </div>
  );
}
