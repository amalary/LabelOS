"use client";

import {
  type ApprovalActor,
  type ApprovalRequestStatus,
  type ApprovalListOptions,
  type ApprovalRequestSummary,
  type ApprovalDecision,
  useApprovalQueue,
  useApprovalRequest,
  useApprovalDecision,
  type ApprovalAction,
} from "../../lib/approvals";
import { useState, useMemo, useEffect } from "react";
import { useOrganizationRealtimeContext } from "../../lib/realtime/use-organization-realtime";
import { Button, Card, cn, LoadingState, EmptyState, Badge } from "@label-os/ui";
import { formatCalendarDateTime } from "../../lib/calendar-dates";
import { humanize } from "./marketing-presentation";

type ApprovalQueueView =
  "awaiting_review" | "submitted_by_me" | "changes_requested" | "approved" | "rejected" | "all";

const approvalQueueResourceType = "marketing_content_item";

const approvalQueueViews: Array<{ id: ApprovalQueueView; label: string }> = [
  { id: "awaiting_review", label: "Awaiting my review" },
  { id: "submitted_by_me", label: "Submitted by me" },
  { id: "changes_requested", label: "Changes requested" },
  { id: "approved", label: "Approved" },
  { id: "rejected", label: "Rejected" },
  { id: "all", label: "All" },
];

function actorName(actor: ApprovalActor | null | undefined): string {
  return actor?.display_name ?? actor?.profile_id ?? actor?.user_id ?? "Unassigned";
}

function approvalStatusVariant(status: ApprovalRequestStatus) {
  if (status === "approved") {
    return "success" as const;
  }
  if (status === "rejected" || status === "invalidated") {
    return "warning" as const;
  }
  if (status === "changes_requested" || status === "requested" || status === "in_review") {
    return "warning" as const;
  }
  return "neutral" as const;
}

const approvalPageSize = 50;

function approvalQueueOptions(view: ApprovalQueueView, offset: number): ApprovalListOptions {
  const base = {
    limit: approvalPageSize,
    offset,
    resource_type: approvalQueueResourceType,
  } satisfies ApprovalListOptions;
  if (view === "awaiting_review") {
    return { ...base, assigned_to_me: true, status: "in_review" };
  }
  if (view === "submitted_by_me") {
    return { ...base, submitted_by_me: true };
  }
  if (view === "changes_requested") {
    return { ...base, status: "changes_requested" };
  }
  if (view === "approved" || view === "rejected") {
    return { ...base, status: view };
  }
  return base;
}

function actionRequiredFor(
  approval: ApprovalRequestSummary,
  currentProfileId: string | null | undefined,
): boolean {
  return (
    Boolean(currentProfileId) &&
    (approval.status === "requested" || approval.status === "in_review") &&
    approval.stage_assignment?.profile_id === currentProfileId
  );
}

function hasStructuredFeedback(decision: ApprovalDecision): boolean {
  return Boolean(decision.payload && Object.keys(decision.payload).length > 0);
}

export function ApprovalQueue({
  currentProfileId,
  focusedApprovalId,
  onOpenCalendarItem,
  timeZone,
  workspaceId,
}: {
  currentProfileId: string | null | undefined;
  focusedApprovalId: string | null;
  onOpenCalendarItem: (contentItemId: string, campaignId: string | null) => void;
  timeZone: string;
  workspaceId: string;
}) {
  const [view, setView] = useState<ApprovalQueueView>("awaiting_review");
  const [page, setPage] = useState({ workspaceId, offset: 0 });
  const offset = page.workspaceId === workspaceId ? page.offset : 0;
  const [selectedApprovalId, setSelectedApprovalId] = useState<string | null>(focusedApprovalId);
  const options = useMemo(() => approvalQueueOptions(view, offset), [view, offset]);
  const queue = useApprovalQueue(workspaceId, options);
  const realtime = useOrganizationRealtimeContext();
  const latestApprovalEvent = realtime?.recentActivityEvents.find((event) =>
    event.type.startsWith("approval."),
  );
  const approvals = queue.data?.approvals ?? [];

  useEffect(() => {
    if (queue.data && offset > 0 && offset >= queue.data.total) {
      setPage({
        workspaceId,
        offset: Math.max(0, Math.ceil(queue.data.total / approvalPageSize) - 1) * approvalPageSize,
      });
    }
  }, [queue.data, offset, workspaceId]);

  useEffect(() => {
    if (focusedApprovalId) {
      setSelectedApprovalId(focusedApprovalId);
    }
  }, [focusedApprovalId]);

  return (
    <section className="grid gap-4" aria-label="Marketing approval queue">
      <div className="flex flex-col gap-3 rounded-md border border-slate-200 bg-white p-4 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">Approval Queue</h2>
          <p className="text-sm text-slate-500">
            Marketing content requests filtered to {approvalQueueResourceType}.
          </p>
        </div>
        <Button
          disabled={queue.isLoading}
          onClick={() => void queue.reload().catch(() => undefined)}
          size="sm"
          type="button"
          variant="secondary"
        >
          Refresh
        </Button>
      </div>

      <Card className="grid gap-3 p-4">
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Approval queue views">
          {approvalQueueViews.map((entry) => (
            <button
              aria-selected={view === entry.id}
              className={cn(
                "rounded-md border px-3 py-2 text-sm font-medium transition",
                view === entry.id
                  ? "border-slate-950 bg-slate-950 text-white"
                  : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50",
              )}
              key={entry.id}
              onClick={() => {
                setView(entry.id);
                setPage({ workspaceId, offset: 0 });
                setSelectedApprovalId(null);
              }}
              role="tab"
              type="button"
            >
              {entry.label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
          <span>{queue.data ? `${queue.data.total} approvals` : "Loading approvals"}</span>
          {latestApprovalEvent ? (
            <span aria-live="polite">
              Realtime refresh: {latestApprovalEvent.type} at{" "}
              {formatCalendarDateTime(latestApprovalEvent.createdAt, timeZone)}
            </span>
          ) : null}
        </div>
      </Card>

      <nav aria-label="Approval queue pages" className="flex items-center justify-between gap-3">
        <Button
          disabled={queue.isLoading || offset === 0}
          onClick={() => {
            setPage({ workspaceId, offset: Math.max(0, offset - approvalPageSize) });
            setSelectedApprovalId(null);
          }}
          size="sm"
          variant="secondary"
        >
          Previous approvals
        </Button>
        <span className="text-sm text-slate-500" aria-live="polite">
          Page {Math.floor(offset / approvalPageSize) + 1}
        </span>
        <Button
          disabled={queue.isLoading || !queue.data || offset + approvalPageSize >= queue.data.total}
          onClick={() => {
            setPage({ workspaceId, offset: offset + approvalPageSize });
            setSelectedApprovalId(null);
          }}
          size="sm"
          variant="secondary"
        >
          Next approvals
        </Button>
      </nav>

      {queue.error ? (
        <div
          className={cn(
            "rounded-md border px-4 py-3 text-sm",
            queue.error.code === "unauthorized" || queue.error.code === "forbidden"
              ? "border-amber-200 bg-amber-50 text-amber-900"
              : "border-red-200 bg-red-50 text-red-900",
          )}
          role={
            queue.error.code === "unauthorized" || queue.error.code === "forbidden"
              ? "status"
              : "alert"
          }
        >
          {queue.error.message}
        </div>
      ) : null}

      {queue.isLoading && !queue.data ? (
        <Card className="grid gap-3">
          <LoadingState label="Loading approval queue" />
          {Array.from({ length: 3 }, (_, index) => (
            <div className="h-20 rounded-md bg-slate-100 auth-shimmer" key={index} />
          ))}
        </Card>
      ) : null}

      {!queue.isLoading && !queue.error && approvals.length === 0 ? (
        <EmptyState
          description={
            view === "awaiting_review"
              ? "No marketing content approvals require your review."
              : "No marketing content approvals match this queue view."
          }
          title="No approvals in this queue"
        />
      ) : null}

      {approvals.length > 0 ? (
        <Card className="overflow-hidden p-0">
          <div className="divide-y divide-slate-100">
            {approvals.map((approval) => {
              const actionRequired = actionRequiredFor(approval, currentProfileId);
              return (
                <button
                  aria-pressed={selectedApprovalId === approval.id}
                  className="grid w-full gap-3 px-4 py-4 text-left transition hover:bg-slate-50 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_170px_160px]"
                  key={approval.id}
                  onClick={() => setSelectedApprovalId(approval.id)}
                  type="button"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="truncate text-sm font-semibold text-slate-950">
                        {approval.title}
                      </h3>
                      <Badge variant={approvalStatusVariant(approval.status)}>
                        {humanize(approval.status)}
                      </Badge>
                      {actionRequired ? <Badge variant="warning">Action required</Badge> : null}
                    </div>
                    <p className="mt-1 line-clamp-2 text-sm text-slate-600">
                      {approval.summary ?? "No content preview provided."}
                    </p>
                    <p className="mt-2 text-xs text-slate-500">
                      Submitted revision {approval.submitted_revision}
                    </p>
                  </div>
                  <div className="min-w-0">
                    <p className="text-xs font-semibold uppercase text-slate-500">Context</p>
                    <p className="mt-1 truncate text-sm font-medium text-slate-800">
                      {approval.campaign?.name ?? "Campaign not linked"}
                    </p>
                    <p className="truncate text-xs text-slate-500">
                      {approval.artist?.name ?? "Artist not linked"}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs font-semibold uppercase text-slate-500">People</p>
                    <p className="mt-1 truncate text-sm text-slate-800">
                      Submitter: {actorName(approval.submitter)}
                    </p>
                    <p className="truncate text-xs text-slate-500">
                      Reviewer: {actorName(approval.stage_assignment)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs font-semibold uppercase text-slate-500">Submitted</p>
                    <p className="mt-1 text-sm font-medium text-slate-800">
                      {formatCalendarDateTime(approval.submitted_at, timeZone)}
                    </p>
                    {approval.resolved_at ? (
                      <p className="text-xs text-slate-500">
                        Resolved {formatCalendarDateTime(approval.resolved_at, timeZone)}
                      </p>
                    ) : null}
                  </div>
                </button>
              );
            })}
          </div>
        </Card>
      ) : null}

      {selectedApprovalId ? (
        <ApprovalReviewDetail
          currentProfileId={currentProfileId}
          onClose={() => setSelectedApprovalId(null)}
          onOpenCalendarItem={onOpenCalendarItem}
          timeZone={timeZone}
          workspaceId={workspaceId}
          approvalRequestId={selectedApprovalId}
        />
      ) : null}
    </section>
  );
}

function ApprovalReviewDetail({
  approvalRequestId,
  currentProfileId,
  onClose,
  onOpenCalendarItem,
  timeZone,
  workspaceId,
}: {
  approvalRequestId: string;
  currentProfileId: string | null | undefined;
  onClose: () => void;
  onOpenCalendarItem: (contentItemId: string, campaignId: string | null) => void;
  timeZone: string;
  workspaceId: string;
}) {
  const detail = useApprovalRequest(workspaceId, approvalRequestId);
  const approve = useApprovalDecision(workspaceId, approvalRequestId, "approved");
  const requestChanges = useApprovalDecision(workspaceId, approvalRequestId, "changes_requested");
  const reject = useApprovalDecision(workspaceId, approvalRequestId, "rejected");
  const cancel = useApprovalDecision(workspaceId, approvalRequestId, "cancelled");
  const [reason, setReason] = useState("");
  const [clientError, setClientError] = useState<string | null>(null);
  const selected = detail.data;
  const decisionError = approve.error ?? requestChanges.error ?? reject.error ?? cancel.error;
  const isMutating =
    approve.isMutating || requestChanges.isMutating || reject.isMutating || cancel.isMutating;
  const availableActions = new Set<ApprovalAction>(selected?.available_actions ?? []);
  const actionRequired = selected ? actionRequiredFor(selected, currentProfileId) : false;
  const currentRevision =
    selected?.current_resource_revision ??
    selected?.marketing_content_preview?.current_revision ??
    null;
  const isStale =
    Boolean(selected?.is_stale) ||
    (currentRevision !== null && selected
      ? currentRevision !== selected.submitted_revision
      : false);
  const resolved =
    Boolean(selected?.resolved_at) ||
    ["approved", "rejected", "cancelled", "invalidated"].includes(selected?.status ?? "");

  async function decide(action: ApprovalAction) {
    setClientError(null);
    const trimmedReason = reason.trim();
    if ((action === "rejected" || action === "changes_requested") && !trimmedReason) {
      setClientError("A reason is required for rejection and requested changes.");
      return;
    }
    const mutation =
      action === "approved"
        ? approve
        : action === "changes_requested"
          ? requestChanges
          : action === "rejected"
            ? reject
            : cancel;
    try {
      await mutation.mutate({
        idempotency_key: `${approvalRequestId}:${action}:${Date.now()}`,
        reason: trimmedReason || null,
      });
      setReason("");
      await detail.reload().catch(() => undefined);
    } catch {
      // The mutation state renders the API error.
    }
  }

  return (
    <Card className="grid gap-4 p-4" role="region" aria-label="Approval review detail">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">Review detail</p>
          <h2 className="text-lg font-semibold text-slate-950">
            {selected?.title ?? "Approval request"}
          </h2>
          <p className="text-sm text-slate-500">Request {approvalRequestId}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {selected?.marketing_content_preview ? (
            <Button
              onClick={() =>
                onOpenCalendarItem(
                  selected.marketing_content_preview?.id ?? selected.resource_id,
                  selected.campaign?.id ?? null,
                )
              }
              size="sm"
              type="button"
              variant="secondary"
            >
              Open calendar item
            </Button>
          ) : null}
          <Button onClick={onClose} size="sm" type="button" variant="secondary">
            Close
          </Button>
        </div>
      </div>

      {detail.isLoading && !selected ? <LoadingState label="Loading approval detail" /> : null}

      {detail.error ? (
        <div
          className={cn(
            "rounded-md border px-4 py-3 text-sm",
            detail.error.code === "unauthorized" || detail.error.code === "forbidden"
              ? "border-amber-200 bg-amber-50 text-amber-900"
              : "border-red-200 bg-red-50 text-red-900",
          )}
          role={
            detail.error.code === "unauthorized" || detail.error.code === "forbidden"
              ? "status"
              : "alert"
          }
        >
          {detail.error.message}
        </div>
      ) : null}

      {selected ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={approvalStatusVariant(selected.status)}>
              {humanize(selected.status)}
            </Badge>
            <Badge variant={actionRequired ? "warning" : "neutral"}>
              {actionRequired ? "Action required from you" : "No action required"}
            </Badge>
            {isStale ? <Badge variant="warning">Stale approval</Badge> : null}
            {resolved ? <Badge variant="neutral">Resolved</Badge> : null}
          </div>

          {isStale ? (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              This request was submitted for revision {selected.submitted_revision}, but the current
              content revision is {currentRevision ?? "unknown"}. Review the latest calendar item
              before making a decision.
            </div>
          ) : null}

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
            <div className="grid gap-4">
              <section
                className="grid gap-2 rounded-md border border-slate-200 p-4"
                aria-label="Content preview"
              >
                <h3 className="text-base font-semibold text-slate-950">Content preview</h3>
                <p className="text-sm font-medium text-slate-800">
                  {selected.marketing_content_preview?.title ?? selected.title}
                </p>
                <p className="whitespace-pre-wrap text-sm leading-6 text-slate-600">
                  {selected.marketing_content_preview?.copy_text ??
                    selected.summary ??
                    "No preview copy was provided."}
                </p>
                <p className="text-xs text-slate-500">
                  Type: {humanize(selected.marketing_content_preview?.content_type)}
                </p>
              </section>

              <section
                className="grid gap-2 rounded-md border border-slate-200 p-4"
                aria-label="Decision history"
              >
                <h3 className="text-base font-semibold text-slate-950">Decision history</h3>
                {selected.decision_history.length === 0 ? (
                  <p className="text-sm text-slate-500">No decisions have been recorded yet.</p>
                ) : (
                  <ol className="grid gap-3">
                    {selected.decision_history.map((decision) => (
                      <li
                        className="rounded-md border border-slate-100 bg-slate-50 p-3"
                        key={decision.id}
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-sm font-semibold text-slate-900">
                            {humanize(decision.decision)}
                          </p>
                          <p className="text-xs text-slate-500">
                            {formatCalendarDateTime(decision.created_at, timeZone)}
                          </p>
                        </div>
                        <p className="mt-1 text-xs text-slate-500">
                          By{" "}
                          {decision.decided_by_profile_id ??
                            decision.decided_by_user_id ??
                            decision.actor_key ??
                            decision.actor_kind}
                        </p>
                        {decision.reason ? (
                          <p className="mt-2 text-sm text-slate-700">{decision.reason}</p>
                        ) : null}
                        {hasStructuredFeedback(decision) ? (
                          <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-white p-2 text-xs text-slate-700">
                            {JSON.stringify(decision.payload, null, 2)}
                          </pre>
                        ) : null}
                      </li>
                    ))}
                  </ol>
                )}
              </section>
            </div>

            <aside className="grid content-start gap-4">
              <section
                className="grid gap-3 rounded-md border border-slate-200 p-4"
                aria-label="Approval context"
              >
                <h3 className="text-base font-semibold text-slate-950">Context</h3>
                <dl className="grid gap-2 text-sm">
                  <div>
                    <dt className="text-xs font-semibold uppercase text-slate-500">Campaign</dt>
                    <dd className="text-slate-800">{selected.campaign?.name ?? "Not linked"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase text-slate-500">Artist</dt>
                    <dd className="text-slate-800">{selected.artist?.name ?? "Not linked"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase text-slate-500">Release</dt>
                    <dd className="text-slate-800">{selected.release?.name ?? "Not linked"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase text-slate-500">
                      Channels and placements
                    </dt>
                    <dd className="text-slate-800">
                      {selected.channels.length
                        ? selected.channels
                            .map(
                              (channel) =>
                                `${humanize(channel.channel)} / ${humanize(channel.placement)}`,
                            )
                            .join(", ")
                        : "Not provided"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase text-slate-500">
                      Submission note
                    </dt>
                    <dd className="text-slate-800">{selected.summary ?? "No note provided"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase text-slate-500">
                      Current stage
                    </dt>
                    <dd className="text-slate-800">
                      {selected.current_stage
                        ? `${humanize(selected.current_stage.status)} stage ${selected.current_stage.stage_order}`
                        : "No active stage"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase text-slate-500">
                      Reviewer assignment
                    </dt>
                    <dd className="text-slate-800">{actorName(selected.stage_assignment)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase text-slate-500">Revisions</dt>
                    <dd className="text-slate-800">
                      Submitted {selected.submitted_revision}; current{" "}
                      {currentRevision ?? "unknown"}
                    </dd>
                  </div>
                </dl>
              </section>

              <section
                className="grid gap-3 rounded-md border border-slate-200 p-4"
                aria-label="Approval decision"
              >
                <h3 className="text-base font-semibold text-slate-950">Decision</h3>
                {clientError || decisionError ? (
                  <div
                    className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900"
                    role="alert"
                  >
                    {clientError ?? decisionError?.message}
                  </div>
                ) : null}
                <label className="grid gap-1 text-sm font-medium text-slate-700">
                  <span>Reason or feedback</span>
                  <textarea
                    className="min-h-24 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950"
                    disabled={isMutating || resolved}
                    onChange={(event) => {
                      setClientError(null);
                      setReason(event.target.value);
                    }}
                    value={reason}
                  />
                </label>
                <div className="flex flex-wrap gap-2">
                  {availableActions.has("approved") ? (
                    <Button
                      disabled={isMutating || resolved}
                      onClick={() => void decide("approved")}
                      type="button"
                    >
                      {approve.isMutating ? "Approving..." : "Approve"}
                    </Button>
                  ) : null}
                  {availableActions.has("changes_requested") ? (
                    <Button
                      disabled={isMutating || resolved}
                      onClick={() => void decide("changes_requested")}
                      type="button"
                      variant="secondary"
                    >
                      {requestChanges.isMutating ? "Requesting..." : "Request changes"}
                    </Button>
                  ) : null}
                  {availableActions.has("rejected") ? (
                    <Button
                      disabled={isMutating || resolved}
                      onClick={() => void decide("rejected")}
                      type="button"
                      variant="secondary"
                    >
                      {reject.isMutating ? "Rejecting..." : "Reject"}
                    </Button>
                  ) : null}
                  {availableActions.has("cancelled") ? (
                    <Button
                      disabled={isMutating || resolved}
                      onClick={() => void decide("cancelled")}
                      type="button"
                      variant="secondary"
                    >
                      {cancel.isMutating ? "Cancelling..." : "Cancel request"}
                    </Button>
                  ) : null}
                </div>
                {!availableActions.size || resolved ? (
                  <p className="text-sm text-slate-500">
                    No approval actions are currently available.
                  </p>
                ) : null}
              </section>
            </aside>
          </div>
        </>
      ) : null}
    </Card>
  );
}
