import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChannelScheduling } from "./channel-scheduling";
import type { MarketingContentItem } from "../../lib/marketing-content";
import type {
  ChannelSchedulingEligibilityResponse,
  SchedulingJobResponse,
  SchedulingJobStatus,
} from "../../lib/generated/scheduling-api";
import { schedulingRecovery, notifySchedulingUpdate } from "../../lib/scheduling";

const content = {
  id: "content",
  workspace_id: "workspace",
  campaign_id: "campaign",
  content_revision: 2,
  approved_revision: 2,
  approval_request_id: "approval",
  status: "approved",
  channels: [
    {
      id: "channel",
      channel: "instagram",
      placement: "feed",
      schedule_generation: 3,
      scheduled_at: "2026-11-01T06:30:00Z",
      schedule_timezone: "America/New_York",
      published_at: null,
    },
  ],
} as MarketingContentItem;
const eligible: ChannelSchedulingEligibilityResponse = {
  eligible: true,
  content_revision: 2,
  schedule_generation: 3,
  approval_request_id: "approval",
  scheduled_for: "2026-11-01T06:30:00Z",
  schedule_timezone: "America/New_York",
  active_job_id: null,
  reason_codes: [],
  authoring_enabled: true,
  execution_enabled: true,
  delivery_receiver_configured: true,
};
function job(
  status: SchedulingJobStatus = "pending",
  overrides: Partial<SchedulingJobResponse> = {},
): SchedulingJobResponse {
  return {
    id: "job",
    workspace_id: "workspace",
    content_item_id: "content",
    channel_id: "channel",
    connection_id: "connection",
    approval_request_id: "approval",
    content_revision: 2,
    schedule_generation: 3,
    scheduled_for: eligible.scheduled_for!,
    schedule_timezone: "America/New_York",
    status,
    blocked_reason_code: null,
    supersedes_job_id: null,
    lineage_root_job_id: null,
    created_at: "2026-09-15T12:00:00Z",
    updated_at: "2026-09-15T12:00:00Z",
    cancelled_at: null,
    handed_off_at: null,
    ...overrides,
  };
}
const fetchMock = vi.fn();
let readiness: ChannelSchedulingEligibilityResponse;
let history: SchedulingJobResponse[];
let command: (path: string, init: RequestInit) => Promise<Response>;
function panel(overrides: Partial<React.ComponentProps<typeof ChannelScheduling>> = {}) {
  return (
    <ChannelScheduling
      item={content}
      channel={content.channels[0]!}
      canSchedule
      dirty={false}
      busy={false}
      onBusy={vi.fn()}
      {...overrides}
    />
  );
}
async function loaded() {
  await waitFor(() =>
    expect(screen.queryByText("Loading scheduling state")).not.toBeInTheDocument(),
  );
}

describe("channel scheduling", () => {
  beforeEach(() => {
    readiness = { ...eligible };
    history = [];
    command = async () => {
      history = [job()];
      readiness = {
        ...eligible,
        eligible: false,
        reason_codes: ["active_job_conflict"],
        active_job_id: "job",
      };
      return Response.json(history[0]);
    };
    fetchMock.mockReset().mockImplementation(async (path: string, init: RequestInit) => {
      if (init.method === "POST") return command(path, init);
      if (path.endsWith("/eligibility")) return Response.json(readiness);
      return Response.json({ jobs: history, limit: 100, next_cursor: null });
    });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("activates the exact approved channel revision and inspects pending work without marking publication", async () => {
    render(panel());
    expect(screen.getByText("Loading scheduling state")).toBeInTheDocument();
    await loaded();
    expect(screen.getByText(/No activated schedules/)).toBeInTheDocument();
    expect(screen.getByText(/Approval readiness: Approved revision 2/)).toBeInTheDocument();
    expect(screen.getByText(/Planned:.*1:30:00 AM EST/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Activate Schedule" }));
    await screen.findByText("Pending");
    const [path, init] = fetchMock.mock.calls.find(([, init]) => init.method === "POST")!;
    expect(path).toBe(
      "/api/workspaces/workspace/marketing-content/content/channels/channel/scheduling/activate",
    );
    expect(JSON.parse(init.body)).toEqual({
      expected_content_revision: 2,
      expected_schedule_generation: 3,
    });
    expect(init.headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(screen.getByText("Published: not confirmed.")).toBeInTheDocument();
    await loaded();
    expect(screen.getByRole("button", { name: "Activate Schedule" })).toBeDisabled();
  });

  it.each(["pending", "claimed", "blocked", "cancelled", "superseded", "handed_off"] as const)(
    "renders %s with accurate mutability",
    async (status) => {
      history = [job(status)];
      render(panel());
      await loaded();
      const row = within(screen.getByRole("article", { name: "Schedule job" }));
      expect(
        row.getByText(
          status === "handed_off" ? "Handed off" : status[0]!.toUpperCase() + status.slice(1),
        ),
      ).toBeInTheDocument();
      expect(Boolean(row.queryByRole("button", { name: "Cancel schedule" }))).toBe(
        ["pending", "claimed", "blocked"].includes(status),
      );
      expect(screen.getByText("Published: not confirmed.")).toBeInTheDocument();
      if (status === "handed_off")
        expect(row.getByText(/not confirmation of publication/)).toBeInTheDocument();
    },
  );

  it("cancels claimed work and replaces it after a material edit and fresh approval", async () => {
    history = [job("claimed")];
    readiness = {
      ...eligible,
      eligible: false,
      active_job_id: "job",
      reason_codes: ["active_job_conflict"],
    };
    command = async (path) => {
      if (path.endsWith("/cancel")) {
        history = [job("cancelled")];
        readiness = { ...eligible, eligible: false, reason_codes: ["replacement_required"] };
        return Response.json(history[0]);
      }
      history = [
        job("pending", {
          id: "successor",
          supersedes_job_id: "job",
          content_revision: 3,
          schedule_generation: 4,
        }),
        job("cancelled"),
      ];
      readiness = {
        ...readiness,
        reason_codes: ["active_job_conflict"],
        active_job_id: "successor",
      };
      return Response.json(history[0]);
    };
    const { rerender } = render(panel());
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Cancel schedule" }));
    await screen.findByText("Cancelled");
    await loaded();
    const revised = {
      ...content,
      content_revision: 3,
      approved_revision: null,
      approval_request_id: null,
    };
    readiness = {
      ...eligible,
      content_revision: 3,
      schedule_generation: 4,
      eligible: false,
      reason_codes: ["stale_approval", "replacement_required"],
    };
    rerender(
      panel({ item: revised, channel: { ...content.channels[0]!, schedule_generation: 4 } }),
    );
    await loaded();
    expect(screen.getByRole("button", { name: "Activate Replacement Schedule" })).toBeDisabled();
    readiness = {
      ...readiness,
      reason_codes: ["replacement_required"],
      approval_request_id: "new-approval",
    };
    rerender(
      panel({
        item: { ...revised, approved_revision: 3, approval_request_id: "new-approval" },
        channel: { ...content.channels[0]!, schedule_generation: 4 },
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Refresh scheduling state" }));
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Activate Replacement Schedule" }));
    await screen.findByText("Pending");
    expect(
      fetchMock.mock.calls.filter(([, init]) => init.method === "POST").map(([path]) => path),
    ).toEqual([
      "/api/workspaces/workspace/scheduling/jobs/job/cancel",
      "/api/workspaces/workspace/scheduling/jobs/job/replace",
    ]);
    expect(screen.getByText(/Replaces job/)).toBeInTheDocument();
  });

  it.each(Object.keys(schedulingRecovery))(
    "provides recovery for %s and blocks activation",
    async (reason) => {
      readiness = { ...eligible, eligible: false, reason_codes: [reason] };
      render(panel());
      await loaded();
      expect(screen.getByText(schedulingRecovery[reason]!)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Activate Schedule" })).toBeDisabled();
    },
  );

  it("revalidates only unchanged blocked intent", async () => {
    history = [job("blocked", { blocked_reason_code: "reconnect_required" })];
    readiness = { ...eligible, eligible: false, reason_codes: ["active_job_conflict"] };
    render(panel());
    await loaded();
    expect(screen.getByText(/Blocked reason: reconnect required/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Revalidate unchanged schedule" }));
    await screen.findByText("Pending");
    expect(fetchMock.mock.calls.find(([, init]) => init.method === "POST")?.[0]).toEqual(
      expect.stringContaining("/job/revalidate"),
    );
  });

  it.each([
    [401, "Sign in again"],
    [403, "permission"],
    [404, "no longer exists"],
    [422, "request is invalid"],
    [500, "could not be completed"],
  ])("renders read failure %s and retries", async (status, message) => {
    fetchMock.mockResolvedValueOnce(Response.json({}, { status: Number(status) }));
    render(panel());
    await loaded();
    expect(screen.getByRole("alert")).toHaveTextContent(String(message));
    expect(screen.getByRole("button", { name: "Activate Schedule" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Refresh scheduling state" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it.each([401, 403, 404, 409, 422, 500])(
    "shows mutation failure %s and refreshes operational state",
    async (status) => {
      command = async () =>
        Response.json(
          {
            detail: {
              code: "scheduling_conflict",
              reason_codes: status === 409 ? ["stale_approval"] : [],
            },
          },
          { status },
        );
      render(panel());
      await loaded();
      fireEvent.click(screen.getByRole("button", { name: "Activate Schedule" }));
      await screen.findByRole("alert");
      await loaded();
      expect(screen.queryByText("Pending")).not.toBeInTheDocument();
      expect(fetchMock.mock.calls.filter(([, init]) => !init.method)).toHaveLength(4);
    },
  );

  it("retains the idempotency key after uncertain network failure and blocks duplicate clicks", async () => {
    let rejectRequest: (error: Error) => void;
    command = () =>
      new Promise((_, reject) => {
        rejectRequest = reject;
      });
    render(panel());
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Activate Schedule" }));
    fireEvent.click(screen.getByRole("button", { name: "Activate Schedule" }));
    expect(fetchMock.mock.calls.filter(([, init]) => init.method === "POST")).toHaveLength(1);
    rejectRequest!(new Error("offline"));
    await screen.findByRole("alert");
    await loaded();
    command = async () => Response.json(job());
    fireEvent.click(screen.getByRole("button", { name: "Activate Schedule" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.filter(([, init]) => init.method === "POST")).toHaveLength(2),
    );
    const posts = fetchMock.mock.calls.filter(([, init]) => init.method === "POST");
    expect(posts[0]![1].headers["Idempotency-Key"]).toBe(posts[1]![1].headers["Idempotency-Key"]);
    await loaded();
  });

  it("refreshes a lost cancellation race to handed off without claiming cancellation succeeded", async () => {
    history = [job("claimed")];
    command = async () => {
      history = [job("handed_off")];
      return Response.json(
        { detail: { reason_codes: ["invalid_state_transition"] } },
        { status: 409 },
      );
    };
    render(panel());
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Cancel schedule" }));
    await screen.findByText("Handed off");
    expect(screen.getByRole("alert")).toHaveTextContent("may already be handed off");
    expect(screen.queryByRole("button", { name: "Cancel schedule" })).not.toBeInTheDocument();
    expect(screen.getByText("Published: not confirmed.")).toBeInTheDocument();
  });

  it("allows inspection without schedule permission and does not request restricted eligibility", async () => {
    history = [job("pending")];
    render(panel({ canSchedule: false }));
    await loaded();
    expect(screen.getByText(/need marketing content schedule permission/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel schedule" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Activate Schedule" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps history visible when eligibility permission is denied", async () => {
    history = [job("claimed")];
    fetchMock.mockImplementation(async (path: string) =>
      path.endsWith("eligibility")
        ? Response.json({}, { status: 403 })
        : Response.json({ jobs: history, next_cursor: null }),
    );
    render(panel());
    await loaded();
    expect(screen.getByText("Claimed")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("permission");
    expect(screen.getByRole("button", { name: "Activate Schedule" })).toBeDisabled();
  });

  it("offers a saved-content reload for revision drift while protecting unsaved edits", async () => {
    readiness.content_revision = 3;
    const reload = vi.fn();
    const { rerender } = render(panel({ onReloadContent: reload }));
    await loaded();
    expect(screen.getByText(/Saved content changed/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload saved content" }));
    expect(reload).toHaveBeenCalledOnce();
    rerender(panel({ onReloadContent: reload, dirty: true }));
    expect(screen.getByRole("button", { name: "Reload saved content" })).toBeDisabled();
  });

  it("loads older jobs using the channel-scoped pagination cursor", async () => {
    fetchMock.mockImplementation(async (path: string) => {
      if (path.endsWith("eligibility")) return Response.json(readiness);
      const query = new URL(path, "http://localhost").searchParams;
      expect(query.get("content_item_id")).toBe("content");
      expect(query.get("channel_id")).toBe("channel");
      return Response.json(
        query.get("cursor")
          ? { jobs: [job("superseded", { id: "old-job" })], next_cursor: null }
          : { jobs: [job("pending")], next_cursor: "older-page" },
      );
    });
    render(panel());
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Load older schedules" }));
    await screen.findByRole("article", { name: "Schedule old-job" });
    expect(screen.getByRole("article", { name: "Schedule job" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load older schedules" })).not.toBeInTheDocument();
  });

  it("keeps cancellation available when authoring and execution are disabled", async () => {
    history = [job("pending")];
    readiness = {
      ...eligible,
      authoring_enabled: false,
      execution_enabled: false,
      reason_codes: ["authoring_disabled", "execution_disabled"],
    };
    render(panel());
    await loaded();
    expect(screen.getByRole("button", { name: "Activate Schedule" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel schedule" })).toBeEnabled();
    expect(screen.getByText(schedulingRecovery.authoring_disabled!)).toBeInTheDocument();
  });

  it("does not label a handoff published even when showing a separate recorded publication", async () => {
    history = [job("handed_off")];
    render(panel({ channel: { ...content.channels[0]!, published_at: "2026-11-01T07:00:00Z" } }));
    await loaded();
    expect(screen.getByText("Handed off")).toBeInTheDocument();
    expect(screen.getByText(/Published:.*recorded publication/)).toBeInTheDocument();
    expect(
      within(screen.getByRole("article", { name: "Schedule job" })).queryByText("Published"),
    ).not.toBeInTheDocument();
  });

  it.each(["dirty", "stale", "approval", "execution", "authoring", "receiver"])(
    "fails closed for %s readiness",
    async (condition) => {
      if (condition === "stale") readiness.content_revision = 1;
      if (condition === "execution") readiness.execution_enabled = false;
      if (condition === "authoring") readiness.authoring_enabled = false;
      if (condition === "receiver") readiness.delivery_receiver_configured = false;
      render(
        panel({
          dirty: condition === "dirty",
          item: condition === "approval" ? { ...content, approved_revision: 1 } : content,
        }),
      );
      await loaded();
      expect(screen.getByRole("button", { name: "Activate Schedule" })).toBeDisabled();
    },
  );
  it("refreshes an open inspector on scoped scheduling activity", async () => {
    render(
      <ChannelScheduling
        item={content}
        channel={content.channels[0]!}
        canSchedule={true}
        dirty={false}
        busy={false}
        onBusy={() => {}}
      />,
    );
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    act(() => notifySchedulingUpdate("other-workspace", "content"));
    expect(fetch).toHaveBeenCalledTimes(2);
    act(() => notifySchedulingUpdate("workspace", "content"));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(4));
  });
});
