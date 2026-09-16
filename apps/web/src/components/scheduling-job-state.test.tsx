import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SchedulingJobState } from "./scheduling-job-state";
import type { SchedulingJobProjection } from "../lib/marketing-content";

const job: SchedulingJobProjection = {
  job_id: "job",
  status: "pending",
  active: true,
  intent_matches: true,
  scheduled_for: "2026-11-01T06:30:00Z",
  schedule_timezone: "America/New_York",
  blocked_reason_code: null,
  transition_version: 1,
  correlation_id: "correlation",
};

describe("calendar execution projection", () => {
  it("does not infer execution without an activated job", () => {
    const { container } = render(<SchedulingJobState />);
    expect(container).toBeEmptyDOMElement();
  });
  it.each(["cancelled", "superseded"] as const)("shows %s as inactive history", (status) => {
    render(<SchedulingJobState job={{ ...job, status, active: false }} />);
    expect(screen.getByText(`Schedule job ${status}`)).toHaveAttribute(
      "data-active-execution",
      "false",
    );
  });
  it("distinguishes handoff from publication", () => {
    render(<SchedulingJobState job={{ ...job, status: "handed_off", active: false }} />);
    expect(screen.getByText("Handed off · publication unconfirmed")).toBeInTheDocument();
    expect(screen.queryByText("Published")).not.toBeInTheDocument();
  });
  it("identifies an old snapshot after a planning edit", () => {
    render(<SchedulingJobState job={{ ...job, active: false, intent_matches: false }} />);
    expect(screen.getByText("Delivery pending · previous intent")).toHaveAttribute(
      "data-active-execution",
      "false",
    );
  });
});
