"use client";

import { Badge, Button, LoadingState } from "@label-os/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import type { MarketingContentItem } from "../../lib/marketing-content";
import {
  getPublication,
  listPublications,
  publicProviderUrl,
  publicationCancellationMessage,
  publicationErrorMessage,
  publicationFailureMessage,
  publicationResolution,
  publicationStatusLabels,
  type Publication,
} from "../../lib/publications";
import { subscribeSchedulingUpdates } from "../../lib/scheduling";

function timestamp(value: string | null, zone: string) {
  if (!value) return "Not recorded";
  try {
    return `${new Intl.DateTimeFormat("en", {
      dateStyle: "medium",
      timeStyle: "long",
      timeZone: zone,
    }).format(new Date(value))} (${zone})`;
  } catch {
    return "Time unavailable";
  }
}

function destination(publication: Publication) {
  const account = publication.destination_identity_matches ? publication.destination_account : null;
  return (
    account?.display_name ??
    account?.username ??
    account?.external_account_id ??
    "Original destination unavailable"
  );
}

function Status({ publication }: { publication: Publication }) {
  return (
    <Badge
      variant={
        publication.delivery_status === "published"
          ? "success"
          : publication.delivery_status.includes("failure") ||
              publication.delivery_status === "manual_action_required"
            ? "warning"
            : "neutral"
      }
    >
      {publicationStatusLabels[publication.delivery_status] ?? "Status unavailable"}
    </Badge>
  );
}

function Recovery({ publication }: { publication: Publication }) {
  const guidance = publicationResolution[publication.resolution] ?? {
    label: "Review required",
    instruction: "Refresh delivery state or ask a workspace administrator to investigate.",
  };
  return (
    <div className="grid gap-1 rounded border border-slate-200 bg-slate-50 p-3 text-sm">
      <p className="font-semibold">{guidance.label}</p>
      <p>{guidance.instruction}</p>
      {publication.resolution === "retry_scheduled" && publication.next_retry_at && (
        <p>Next retry: {timestamp(publication.next_retry_at, publication.authoring_timezone)}</p>
      )}
      {publication.resolution === "reconnect_required" && (
        <a className="font-medium text-indigo-700 underline" href="/marketing?tab=accounts">
          Open Accounts
        </a>
      )}
    </div>
  );
}

function PublicationDetail({ publication }: { publication: Publication }) {
  const url = publicProviderUrl(publication.provider_url);
  const zone = publication.authoring_timezone;
  const attempts = [...publication.attempts].sort((a, b) => a.number - b.number);
  return (
    <div className="grid min-w-0 gap-4 text-sm" aria-label="Publication detail">
      <Recovery publication={publication} />
      <section className="grid gap-2" aria-label="Approved publication intent">
        <h5 className="font-semibold">Approved publication intent</h5>
        <p>
          Revision {publication.content_revision} · {publication.channel}
          {publication.placement ? ` / ${publication.placement}` : ""}
        </p>
        <p className="whitespace-pre-wrap break-words">{publication.caption || "No caption"}</p>
        {publication.hashtags.length > 0 && (
          <p className="break-words">{publication.hashtags.join(" ")}</p>
        )}
        <p>
          {publication.asset_refs.length} prepared{" "}
          {publication.asset_refs.length === 1 ? "asset" : "assets"}
        </p>
        {publication.asset_refs.length > 0 && (
          <ul className="grid gap-1">
            {publication.asset_refs.map((asset) => (
              <li key={asset.sha256} className="break-all text-xs text-slate-600">
                {asset.media_type} · {asset.size_bytes.toLocaleString()} bytes · SHA-256{" "}
                {asset.sha256}
              </li>
            ))}
          </ul>
        )}
      </section>
      <dl className="grid gap-2 sm:grid-cols-2 [&_dt]:font-medium [&_dd]:break-words">
        <div>
          <dt>Publication ID</dt>
          <dd className="break-all">{publication.id}</dd>
        </div>
        <div>
          <dt>Destination connection</dt>
          <dd className="break-all">{publication.destination_id}</dd>
        </div>
        <div>
          <dt>Origin</dt>
          <dd>Scheduled delivery · generation {publication.schedule_generation}</dd>
        </div>
        <div>
          <dt>Scheduling job</dt>
          <dd className="break-all">{publication.scheduling_job_id}</dd>
        </div>
        <div>
          <dt>Delivery accepted</dt>
          <dd>{timestamp(publication.created_at, zone)}</dd>
        </div>
        <div>
          <dt>Delivery started</dt>
          <dd>
            {publication.started_at ? timestamp(publication.started_at, zone) : "Not started"}
          </dd>
        </div>
        <div>
          <dt>Provider-confirmed success</dt>
          <dd>{timestamp(publication.published_at, zone)}</dd>
        </div>
        <div>
          <dt>Latest failure</dt>
          <dd>{timestamp(publication.last_failed_at, zone)}</dd>
        </div>
        {publication.delivery_status === "cancelled" && (
          <div className="sm:col-span-2">
            <dt>Delivery cancelled</dt>
            <dd>{timestamp(publication.cancelled_at ?? null, zone)}</dd>
            <dd>{publicationCancellationMessage(publication.cancellation_reason)}</dd>
          </div>
        )}
        {publication.manual_completed_at && (
          <div>
            <dt>Manual completion recorded</dt>
            <dd>{timestamp(publication.manual_completed_at, zone)}</dd>
          </div>
        )}
        <div>
          <dt>Provider resource ID</dt>
          <dd>{publication.external_post_id ?? "Not available"}</dd>
        </div>
        <div>
          <dt>Provider URL</dt>
          <dd>
            {url ? (
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-indigo-700 underline"
              >
                View provider publication
              </a>
            ) : (
              "Not available"
            )}
          </dd>
        </div>
        <div className="sm:col-span-2">
          <dt>Latest safe failure reason</dt>
          <dd>{publicationFailureMessage(publication.latest_failure_reason)}</dd>
        </div>
      </dl>
      <section className="grid gap-3" aria-label="Publication attempts">
        <h5 className="font-semibold">Delivery attempts ({publication.attempt_count})</h5>
        <p className="text-xs text-slate-500">
          Oldest first. Later reconciliation is shown with the original attempt.
        </p>
        {attempts.length === 0 && <p>No delivery attempts have started.</p>}
        <ol className="grid gap-3">
          {attempts.map((attempt) => (
            <li
              key={attempt.id}
              className="grid gap-2 border-l-2 border-slate-200 pl-3"
              aria-label={`Attempt ${attempt.number}`}
            >
              <p className="font-semibold">
                Attempt {attempt.number} ·{" "}
                {attempt.outcome === null
                  ? "In progress"
                  : attempt.outcome === "unknown"
                    ? "Outcome unknown"
                    : (publicationStatusLabels[
                        attempt.outcome as keyof typeof publicationStatusLabels
                      ] ?? "Outcome unavailable")}
              </p>
              <p>Started: {timestamp(attempt.started_at, zone)}</p>
              <p>
                Execution completed:{" "}
                {attempt.completed_at ? timestamp(attempt.completed_at, zone) : "Not recorded"}
              </p>
              {attempt.failure_reason && <p>{publicationFailureMessage(attempt.failure_reason)}</p>}
              {attempt.external_post_id && (
                <p className="break-all">Provider resource ID: {attempt.external_post_id}</p>
              )}
              <ol
                className="grid gap-1 text-xs text-slate-600"
                aria-label={`Attempt ${attempt.number} observations`}
              >
                {[...attempt.observations]
                  .sort((a, b) => a.version - b.version)
                  .map((observation) => (
                    <li key={observation.version}>
                      {timestamp(observation.observed_at, zone)} ·{" "}
                      {observation.source === "reconciliation"
                        ? "Reconciliation"
                        : observation.source === "execution_interrupted"
                          ? "Execution interrupted"
                          : "Provider response"}{" "}
                      ·{" "}
                      {observation.outcome === "unknown"
                        ? "Outcome unknown"
                        : (publicationStatusLabels[
                            observation.outcome as keyof typeof publicationStatusLabels
                          ] ?? "Outcome unavailable")}
                      {observation.failure_reason
                        ? ` · ${publicationFailureMessage(observation.failure_reason)}`
                        : ""}
                    </li>
                  ))}
              </ol>
            </li>
          ))}
        </ol>
      </section>
      {publication.actions.length > 0 && (
        <section className="grid gap-2" aria-label="Human resolution history">
          <h5 className="font-semibold">Human resolution history</h5>
          <ol className="grid gap-1">
            {[...publication.actions]
              .sort((a, b) => a.version - b.version)
              .map((action) => (
                <li key={action.version}>
                  {timestamp(action.occurred_at, zone)} ·{" "}
                  {(
                    {
                      begin_manual: "Manual delivery reserved",
                      complete_manual: "Manual completion recorded",
                      authorize_retry: "Recovery authorized",
                    } as Record<string, string>
                  )[action.operation] ?? "Resolution recorded"}
                </li>
              ))}
          </ol>
        </section>
      )}
    </div>
  );
}

export function PublicationHistory(props: {
  item: MarketingContentItem;
  campaignName: string;
  artistName?: string;
}) {
  // Remount on scope changes so stale content can never appear under another workspace/item.
  return <PublicationHistoryPanel key={`${props.item.workspace_id}:${props.item.id}`} {...props} />;
}

function PublicationHistoryPanel({
  item,
  campaignName,
  artistName,
}: {
  item: MarketingContentItem;
  campaignName: string;
  artistName?: string;
}) {
  const [publications, setPublications] = useState<Publication[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Publication | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const request = useRef<AbortController | null>(null);
  const loadedPages = useRef(1);
  const { workspace_id: workspaceId, id: contentId } = item;

  const refresh = useCallback(
    async (afterId?: string) => {
      request.current?.abort();
      const controller = new AbortController();
      request.current = controller;
      setLoading(true);
      try {
        const page = await listPublications(workspaceId, contentId, controller.signal, afterId);
        if (!afterId) {
          // Refresh every visible page so polling does not discard expanded older records.
          for (let index = 1; index < loadedPages.current && page.next_after_id; index += 1) {
            const next = await listPublications(
              workspaceId,
              contentId,
              controller.signal,
              page.next_after_id,
            );
            page.publications.push(...next.publications);
            page.next_after_id = next.next_after_id;
          }
        }
        if (controller.signal.aborted) return;
        if (afterId) loadedPages.current += 1;
        setPublications((current) => [
          ...new Map(
            [...(afterId ? current : []), ...page.publications].map((entry) => [entry.id, entry]),
          ).values(),
        ]);
        setCursor(page.next_after_id);
        setError(null);
        setRefreshVersion((value) => value + 1);
      } catch (reason) {
        if (controller.signal.aborted) return;
        setError(publicationErrorMessage(reason));
        // Do not retain previously authorized data following a failed read.
        setPublications([]);
        loadedPages.current = 1;
        setCursor(null);
        setSelectedId(null);
        setDetail(null);
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
          request.current = null;
        }
      }
    },
    [workspaceId, contentId],
  );

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      if (!request.current && document.visibilityState !== "hidden") void refresh();
    }, 15000);
    const unsubscribe = subscribeSchedulingUpdates((workspace, content) => {
      if (workspace === workspaceId && (!content || content === contentId)) void refresh();
    });
    return () => {
      request.current?.abort();
      window.clearInterval(timer);
      unsubscribe();
    };
  }, [refresh, workspaceId, contentId]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setDetailLoading(false);
      return;
    }
    const controller = new AbortController();
    setDetailLoading(true);
    setDetailError(null);
    setDetail(null);
    void getPublication(workspaceId, selectedId, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setDetail(value);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setDetailError(publicationErrorMessage(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });
    return () => controller.abort();
  }, [workspaceId, selectedId, refreshVersion]);

  return (
    <section
      className="grid min-w-0 gap-4 rounded-md border border-slate-200 bg-white p-4"
      aria-label="Publication history"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="font-semibold text-slate-950">Publication history</h4>
        <Button type="button" variant="secondary" disabled={loading} onClick={() => void refresh()}>
          Refresh publications
        </Button>
      </div>
      <p className="text-sm text-slate-600">
        Content: {item.title} · Campaign: {campaignName}
        {item.artist_id ? ` · Artist: ${artistName ?? item.artist_id}` : ""}
      </p>
      <p className="text-xs text-slate-500">
        Delivery records use the approved snapshot, including earlier revisions and destinations.
        Schedule handoff alone does not confirm publication.
      </p>
      {loading && <LoadingState label="Loading publication history" />}
      {error && (
        <p role="alert" className="text-sm text-red-800">
          {error}
        </p>
      )}
      {!loading && !error && publications.length === 0 && (
        <p className="text-sm text-slate-600">
          No publications yet. Delivery history appears after an activated schedule is handed off.
        </p>
      )}
      {publications.map((publication) => (
        <article
          key={publication.id}
          className="grid min-w-0 gap-3 rounded border border-slate-200 p-3"
          aria-label={`Publication ${publication.id}`}
        >
          <div className="flex flex-wrap items-center gap-2">
            <Status publication={publication} />
            <span className="text-sm font-medium">
              {publication.provider} · {destination(publication)}
            </span>
          </div>
          {!publication.destination_identity_matches && (
            <p className="text-xs text-amber-800">
              The original account identity is unavailable. Current connection details may refer to
              a different destination.
            </p>
          )}
          <p className="text-sm">
            {publication.channel}
            {publication.placement ? ` / ${publication.placement}` : ""} · Revision{" "}
            {publication.content_revision} · {publication.attempt_count}{" "}
            {publication.attempt_count === 1 ? "attempt" : "attempts"}
          </p>
          <p className="text-sm">
            Scheduled: {timestamp(publication.scheduled_for, publication.authoring_timezone)}
          </p>
          <p className="text-sm font-medium">
            {publicationResolution[publication.resolution]?.label ?? "Review required"}
          </p>
          <Button
            type="button"
            variant="secondary"
            aria-expanded={selectedId === publication.id}
            aria-controls={`publication-${publication.id}`}
            onClick={() =>
              setSelectedId((current) => (current === publication.id ? null : publication.id))
            }
          >
            {selectedId === publication.id ? "Hide delivery details" : "View delivery details"}
          </Button>
          {selectedId === publication.id && (
            <div id={`publication-${publication.id}`}>
              {detailLoading && <LoadingState label="Loading publication detail" />}
              {detailError && (
                <p role="alert" className="text-sm text-red-800">
                  {detailError}
                </p>
              )}
              {detail?.id === publication.id && <PublicationDetail publication={detail} />}
            </div>
          )}
        </article>
      ))}
      {cursor && (
        <Button
          type="button"
          variant="secondary"
          disabled={loading}
          onClick={() => void refresh(cursor)}
        >
          Load more publications
        </Button>
      )}
    </section>
  );
}
