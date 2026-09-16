"use client";

import { Badge, Button, LoadingState } from "@label-os/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import type {
  MarketingContentItem,
  MarketingContentItemChannel,
} from "../../lib/marketing-content";
import type {
  ChannelSchedulingEligibilityResponse,
  ScheduleActivationRequest,
  SchedulingJobResponse,
  SchedulingJobStatus,
} from "../../lib/generated/scheduling-api";
import {
  getChannelEligibility,
  listChannelJobs,
  reasonMessage,
  scheduleCommand,
  schedulingPaths,
  SchedulingApiError,
} from "../../lib/scheduling";

const stateLabels: Record<SchedulingJobStatus, string> = {
  pending: "Pending",
  claimed: "Claimed",
  handed_off: "Handed off",
  blocked: "Blocked",
  cancelled: "Cancelled",
  superseded: "Superseded",
};
const stateDescriptions: Record<SchedulingJobStatus, string> = {
  pending: "Activated and waiting for its delivery time. Publication is not confirmed.",
  claimed:
    "A worker is preparing delivery. Cancellation is possible only until durable handoff wins.",
  handed_off:
    "Delivery accepted this job. This is not confirmation of publication. The job can no longer be cancelled or edited.",
  blocked:
    "Delivery cannot proceed. Resolve the blocker and revalidate unchanged intent, or edit, reapprove, and activate a replacement.",
  cancelled:
    "This job will not be handed off. Its approved intent may be activated again through a replacement.",
  superseded:
    "This job was retired by a material edit or replacement. Inspect the latest job for current delivery state.",
};

function displayTime(instant: string, zone: string) {
  try {
    return `${new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "long", timeZone: zone }).format(new Date(instant))} (${zone})`;
  } catch {
    return `${instant} (${zone})`;
  }
}

export function ChannelScheduling({
  item,
  channel,
  canSchedule,
  dirty,
  busy,
  onBusy,
  onReloadContent,
}: {
  item: MarketingContentItem;
  channel: MarketingContentItemChannel;
  canSchedule: boolean;
  dirty: boolean;
  busy: boolean;
  onBusy: (value: boolean) => void;
  onReloadContent?: () => void;
}) {
  const [eligibility, setEligibility] = useState<ChannelSchedulingEligibilityResponse | null>(null);
  const [jobs, setJobs] = useState<SchedulingJobResponse[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [readError, setReadError] = useState<string | null>(null);
  const [eligibilityError, setEligibilityError] = useState<string | null>(null);
  const [commandError, setCommandError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [mutating, setMutating] = useState(false);
  const request = useRef<AbortController | null>(null);
  // Retain the UUID after an uncertain network/server outcome. A retry cannot create duplicate work.
  const operation = useRef<{ signature: string; id: string } | null>(null);
  const mutationLock = useRef(false);
  const { workspace_id: workspaceId, id: itemId, content_revision: revision } = item;
  const { id: channelId, schedule_generation: generation } = channel;

  const refresh = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    const [history, readiness] = await Promise.allSettled([
      listChannelJobs(workspaceId, itemId, channelId, controller.signal),
      canSchedule
        ? getChannelEligibility(workspaceId, itemId, channelId, controller.signal)
        : Promise.resolve(null),
    ]);
    if (controller.signal.aborted) return;
    if (history.status === "fulfilled") {
      setJobs(history.value.jobs);
      setCursor(history.value.next_cursor);
      setReadError(null);
    } else {
      setReadError(history.reason.message);
    }
    if (readiness.status === "fulfilled") {
      setEligibility(readiness.value);
      setEligibilityError(null);
    } else {
      setEligibility(null);
      setEligibilityError(readiness.reason.message);
    }
    setLoading(false);
    request.current = null;
  }, [workspaceId, itemId, channelId, canSchedule]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      if (!mutationLock.current && !request.current) void refresh();
    }, 15000);
    return () => {
      request.current?.abort();
      window.clearInterval(timer);
    };
  }, [refresh, revision, generation]);

  async function run(
    action: "activate" | "replace" | "cancel" | "revalidate",
    job?: SchedulingJobResponse,
  ) {
    if (mutationLock.current || busy) return;
    mutationLock.current = true;
    setMutating(true);
    onBusy(true);
    setCommandError(null);
    setNotice(null);
    const path =
      action === "activate"
        ? `${schedulingPaths.channel(workspaceId, itemId, channelId)}/activate`
        : `${schedulingPaths.jobs(workspaceId)}/${encodeURIComponent(job!.id)}/${action}`;
    const payload: ScheduleActivationRequest | Record<string, never> =
      action === "activate" || action === "replace"
        ? {
            expected_content_revision: eligibility!.content_revision,
            expected_schedule_generation: eligibility!.schedule_generation,
          }
        : {};
    const signature = JSON.stringify([path, payload]);
    if (operation.current?.signature !== signature)
      operation.current = { signature, id: crypto.randomUUID() };
    try {
      const result = await scheduleCommand(path, payload, operation.current.id);
      operation.current = null;
      setJobs((previous) => [
        result,
        ...(previous ?? []).filter((entry) => entry.id !== result.id),
      ]);
      setNotice(
        `${action === "cancel" ? "Cancellation recorded" : action === "revalidate" ? "Revalidation completed" : "Schedule activated"}. Current state: ${stateLabels[result.status]}.`,
      );
    } catch (error) {
      setCommandError(
        error instanceof Error ? error.message : "Scheduling failed. Refresh and retry.",
      );
      if (error instanceof SchedulingApiError && error.status >= 400 && error.status < 500)
        operation.current = null;
    } finally {
      await refresh();
      mutationLock.current = false;
      setMutating(false);
      onBusy(false);
    }
  }

  async function loadMore() {
    if (!cursor) return;
    setLoading(true);
    try {
      const page = await listChannelJobs(workspaceId, itemId, channelId, undefined, cursor);
      setJobs((previous) => [
        ...(previous ?? []),
        ...page.jobs.filter((job) => !previous?.some((entry) => entry.id === job.id)),
      ]);
      setCursor(page.next_cursor);
    } catch (error) {
      setReadError((error as Error).message);
    } finally {
      setLoading(false);
    }
  }

  const latest = jobs?.[0];
  const replacement =
    latest && ["cancelled", "blocked", "superseded"].includes(latest.status) ? latest : null;
  const approved =
    item.approved_revision === revision &&
    Boolean(item.approval_request_id ?? item.approval_state?.approval_request_id);
  const guardsMatch =
    eligibility?.content_revision === revision && eligibility?.schedule_generation === generation;
  const replacementReady =
    replacement &&
    eligibility &&
    eligibility.reason_codes.every(
      (code) => code === "replacement_required" || code === "active_job_conflict",
    ) &&
    (replacement.status === "cancelled" ||
      (revision > replacement.content_revision &&
        eligibility.approval_request_id !== replacement.approval_request_id));
  const ready =
    canSchedule &&
    approved &&
    guardsMatch &&
    !dirty &&
    !readError &&
    !eligibilityError &&
    eligibility?.authoring_enabled &&
    eligibility.execution_enabled &&
    eligibility.delivery_receiver_configured &&
    (replacement ? replacementReady : eligibility?.eligible);
  const disabled = busy || mutating || loading;

  return (
    <section
      className="grid min-w-0 gap-3 rounded-md border border-slate-200 bg-slate-50 p-3"
      aria-label={`${channel.channel} ${channel.placement ?? ""} scheduling`}
    >
      <h4 className="font-semibold text-slate-950">Channel scheduling</h4>
      <p className="text-sm text-slate-700">
        Planned:{" "}
        {channel.scheduled_at
          ? displayTime(channel.scheduled_at, channel.schedule_timezone ?? "UTC")
          : "No channel time set"}
      </p>
      <p className="text-sm text-slate-700">
        Approval readiness:{" "}
        {approved
          ? `Approved revision ${revision}. Activation is a separate step.`
          : `Revision ${revision} requires completed approval.`}
      </p>
      {channel.published_at ? (
        <p className="text-sm">
          Published: {displayTime(channel.published_at, channel.schedule_timezone ?? "UTC")}{" "}
          (recorded publication)
        </p>
      ) : (
        <p className="text-sm">Published: not confirmed.</p>
      )}
      <p className="text-sm text-slate-600">
        To reschedule, cancel mutable work first, edit the channel time or destination, save, submit
        for reapproval, complete approval, then activate the replacement. Handed-off work cannot be
        recalled.
      </p>
      {dirty && (
        <p className="text-sm text-amber-800">
          Save changes before approval or activation. Material edits require reapproval.
        </p>
      )}
      {eligibility && !guardsMatch && (
        <div className="grid gap-2 text-sm text-amber-800" role="status">
          <p>
            Saved content changed. Reload the current revision before activating. Save or discard
            local edits first.
          </p>
          {onReloadContent && (
            <Button
              type="button"
              variant="secondary"
              disabled={disabled || dirty}
              onClick={onReloadContent}
            >
              Reload saved content
            </Button>
          )}
        </div>
      )}
      {!canSchedule && (
        <p className="text-sm text-amber-800">
          You need marketing content schedule permission to activate, cancel, or revalidate. You can
          inspect job history.
        </p>
      )}
      {loading && <LoadingState label="Loading scheduling state" />}
      {readError && (
        <p role="alert" className="text-sm text-red-800">
          {readError}
        </p>
      )}
      {eligibilityError && (
        <p role="alert" className="text-sm text-red-800">
          {eligibilityError}
        </p>
      )}
      {eligibility && (
        <ul className="grid gap-1 text-sm text-amber-800">
          {[
            ...new Set([
              ...eligibility.reason_codes,
              ...(!eligibility.execution_enabled ? ["execution_disabled"] : []),
              ...(!eligibility.delivery_receiver_configured
                ? ["missing_durable_delivery_receiver"]
                : []),
            ]),
          ].map((code) => (
            <li key={code}>{reasonMessage(code)}</li>
          ))}
        </ul>
      )}
      {channel.destination_readiness?.status === "assisted" &&
        !eligibility?.reason_codes.includes("manual_delivery_required") && (
          <p className="text-sm text-amber-800">{reasonMessage("manual_delivery_required")}</p>
        )}
      <div className="flex flex-wrap gap-2">
        {canSchedule && (
          <Button
            type="button"
            disabled={disabled || !ready}
            onClick={() => void run(replacement ? "replace" : "activate", replacement ?? undefined)}
          >
            {replacement ? "Activate Replacement Schedule" : "Activate Schedule"}
          </Button>
        )}
        <Button
          type="button"
          variant="secondary"
          disabled={disabled}
          onClick={() => void refresh()}
        >
          Refresh scheduling state
        </Button>
      </div>
      {commandError && (
        <p role="alert" className="text-sm text-red-800">
          {commandError}
        </p>
      )}
      {notice && (
        <p role="status" className="text-sm text-slate-800">
          {notice}
        </p>
      )}
      {jobs?.length === 0 && !readError && (
        <p className="text-sm">
          No activated schedules. A planned time or completed approval alone does not queue
          delivery.
        </p>
      )}
      {jobs?.map((job, index) => (
        <article
          key={job.id}
          className="grid min-w-0 gap-2 rounded border border-slate-200 bg-white p-3"
          aria-label={`Schedule ${job.id}`}
        >
          <div className="flex flex-wrap gap-2">
            <Badge variant={job.status === "blocked" ? "warning" : "neutral"}>
              {stateLabels[job.status]}
            </Badge>
            <span className="text-sm">
              Activated revision {job.content_revision} / generation {job.schedule_generation}
            </span>
          </div>
          <p className="text-sm">{stateDescriptions[job.status]}</p>
          <p className="text-sm">{displayTime(job.scheduled_for, job.schedule_timezone)}</p>
          <p className="break-all text-xs text-slate-500">
            Job {job.id}
            {job.supersedes_job_id ? ` · Replaces ${job.supersedes_job_id}` : ""}
          </p>
          {job.blocked_reason_code && (
            <p className="text-sm text-amber-800">
              Blocked reason: {job.blocked_reason_code.replaceAll("_", " ")}.{" "}
              {reasonMessage(job.blocked_reason_code)}
            </p>
          )}
          {canSchedule && (
            <div className="flex flex-wrap gap-2">
              {["pending", "claimed", "blocked"].includes(job.status) && (
                <Button
                  type="button"
                  variant="secondary"
                  disabled={disabled || Boolean(readError)}
                  onClick={() => void run("cancel", job)}
                >
                  Cancel schedule
                </Button>
              )}
              {job.status === "blocked" && index === 0 && (
                <Button
                  type="button"
                  variant="secondary"
                  disabled={
                    disabled ||
                    dirty ||
                    !approved ||
                    !guardsMatch ||
                    !eligibility?.authoring_enabled ||
                    Boolean(readError) ||
                    job.content_revision !== revision ||
                    job.schedule_generation !== generation ||
                    job.approval_request_id !== eligibility?.approval_request_id
                  }
                  onClick={() => void run("revalidate", job)}
                >
                  Revalidate unchanged schedule
                </Button>
              )}
            </div>
          )}
        </article>
      ))}
      {cursor && (
        <Button
          type="button"
          variant="secondary"
          disabled={disabled}
          onClick={() => void loadMore()}
        >
          Load older schedules
        </Button>
      )}
    </section>
  );
}
