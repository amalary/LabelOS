import type { SchedulingJobProjection } from "../lib/marketing-content";

export function SchedulingJobState({ job }: { job?: SchedulingJobProjection | null }) {
  if (!job) return null;
  const label = {
    pending: "Delivery pending",
    claimed: "Preparing delivery",
    handed_off: "Handed off · publication unconfirmed",
    blocked: "Delivery blocked",
    cancelled: "Schedule job cancelled",
    superseded: "Schedule job superseded",
  }[job.status];
  return (
    <span className="block text-xs text-slate-600" data-active-execution={job.active}>
      {label}
      {!job.intent_matches ? " · previous intent" : ""}
    </span>
  );
}
