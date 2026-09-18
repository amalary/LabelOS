import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MarketingContentItem } from "../../lib/marketing-content";
import { type Publication, publicationStatusLabels } from "../../lib/publications";
import { notifySchedulingUpdate } from "../../lib/scheduling";
import {
  startSocialAccountOAuthConnection,
  navigateToSocialAccountAuthorization,
} from "../../lib/social-account-connections";
vi.mock("../../lib/social-account-connections", () => ({
  startSocialAccountOAuthConnection: vi.fn(),
  navigateToSocialAccountAuthorization: vi.fn(),
}));
import { PublicationHistory } from "./publication-history";

const item = {
  id: "content",
  workspace_id: "workspace",
  title: "Launch teaser",
  campaign_id: "campaign",
  artist_id: "artist",
} as MarketingContentItem;
function publication(overrides: Partial<Publication> = {}): Publication {
  return {
    id: "publication",
    workspace_id: "workspace",
    content_item_id: "content",
    channel_id: "channel",
    artist_profile_id: "artist-profile",
    scheduling_job_id: "job",
    schedule_generation: 1,
    origin: "scheduled",
    delivery_status: "retryable_failure",
    resolution: "reconnect_required",
    completion_source: null,
    external_post_id: null,
    provider_url: null,
    provider: "instagram",
    destination_id: "connection",
    destination_identity_matches: true,
    destination_account: {
      external_account_id: "account",
      username: "artist",
      display_name: "Artist account",
    },
    caption: "The approved teaser",
    hashtags: ["#newmusic"],
    asset_refs: [],
    channel: "instagram",
    placement: "feed",
    content_revision: 2,
    scheduled_for: "2026-09-17T12:00:00Z",
    authoring_timezone: "UTC",
    created_at: "2026-09-17T12:00:00Z",
    started_at: "2026-09-17T12:00:01Z",
    published_at: null,
    last_failed_at: "2026-09-17T12:00:02Z",
    manual_completed_at: null,
    next_retry_at: null,
    latest_failure_reason: "authorization_required",
    attempt_count: 1,
    attempts: [
      {
        id: "attempt",
        number: 1,
        started_at: "2026-09-17T12:00:01Z",
        completed_at: "2026-09-17T12:00:02Z",
        outcome: "retryable_failure",
        failure_reason: "authorization_required",
        external_post_id: null,
        observations: [],
      },
    ],
    transition_version: 2,
    action_version: 0,
    can_manage_recovery: true,
    can_manage_account: true,
    can_authorize_retry: true,
    can_begin_manual: true,
    can_complete_manual: false,
    destination_connection_status: "connected",
    actions: [],
    ...overrides,
  };
}
const fetchMock = vi.fn();
let current: Publication;
function panel(value = item) {
  return <PublicationHistory item={value} campaignName="Debut campaign" artistName="Nova" />;
}
async function openDetail() {
  fireEvent.click(await screen.findByRole("button", { name: "View delivery details" }));
  return screen.findByLabelText("Publication detail");
}

describe("publication history", () => {
  beforeEach(() => {
    current = publication();
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (path: string) =>
      Response.json(
        path.includes("?") ? { publications: [current], next_after_id: null } : current,
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("shows withdrawn approval as cancellation without inventing an attempt", async () => {
    current = publication({
      delivery_status: "cancelled",
      resolution: "cancelled",
      cancelled_at: "2026-09-17T12:01:00Z",
      cancellation_reason: "stale_approval",
      started_at: null,
      last_failed_at: null,
      latest_failure_reason: null,
      attempt_count: 0,
      attempts: [],
    });
    render(panel());
    const detail = await openDetail();
    expect(within(detail).getByText("Delivery cancelled")).toBeInTheDocument();
    expect(within(detail).getByText(/Approval is no longer valid/)).toBeInTheDocument();
    expect(within(detail).getByText("No delivery attempts have started.")).toBeInTheDocument();
    expect(within(detail).queryByRole("button", { name: /Retry|Recover/ })).not.toBeInTheDocument();
  });

  it("shows approved intent, context, destination, timing, attempts and reconnect guidance", async () => {
    render(panel());
    const detail = await openDetail();
    expect(screen.getByText(/Content: Launch teaser.*Debut campaign.*Nova/)).toBeInTheDocument();
    expect(screen.getByText(/instagram · Artist account/)).toBeInTheDocument();
    expect(within(detail).getByText("The approved teaser")).toBeInTheDocument();
    expect(within(detail).getByText("#newmusic")).toBeInTheDocument();
    expect(within(detail).getByText("Scheduling job")).toBeInTheDocument();
    expect(within(detail).getByText("Delivery started")).toBeInTheDocument();
    expect(within(detail).getByText("Latest failure")).toBeInTheDocument();
    expect(within(detail).getByRole("link", { name: "Open Accounts" })).toHaveAttribute(
      "href",
      "/marketing?tab=accounts",
    );
    expect(within(detail).getByText("Delivery attempts (1)")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/workspaces/workspace/publications/publication",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it.each(Object.entries(publicationStatusLabels))(
    "renders delivery status %s",
    async (status, label) => {
      current = publication({ delivery_status: status as Publication["delivery_status"] });
      render(panel());
      expect(await screen.findByText(label)).toBeInTheDocument();
    },
  );

  it("orders attempts oldest first and preserves later reconciliation on the original attempt", async () => {
    const first = current.attempts[0]!;
    current = publication({
      attempt_count: 2,
      attempts: [
        {
          ...first,
          id: "second",
          number: 2,
          outcome: null,
          completed_at: null,
          failure_reason: null,
        },
        {
          ...first,
          observations: [
            {
              version: 3,
              observed_at: "2026-09-17T12:00:03Z",
              source: "reconciliation",
              outcome: "retryable_failure",
              failure_reason: "authorization_required",
            },
            {
              version: 2,
              observed_at: "2026-09-17T12:00:02Z",
              source: "execution_interrupted",
              outcome: "unknown",
              failure_reason: "outcome_unknown",
            },
          ],
        },
      ],
    });
    render(panel());
    await openDetail();
    const attempts = within(screen.getByLabelText("Publication attempts")).getAllByRole("listitem");
    expect(attempts[0]).toHaveAccessibleName("Attempt 1");
    expect(attempts.at(-1)).toHaveAccessibleName("Attempt 2");
    const observations = within(screen.getByLabelText("Attempt 1 observations")).getAllByRole(
      "listitem",
    );
    expect(observations[0]).toHaveTextContent("Execution interrupted");
    expect(observations[1]).toHaveTextContent("Reconciliation");
    expect(screen.getByText("Attempt 2 · In progress")).toBeInTheDocument();
  });

  it("distinguishes manual completion from provider-confirmed success", async () => {
    current = publication({
      resolution: "manually_completed",
      completion_source: "human",
      manual_completed_at: "2026-09-17T12:10:00Z",
      external_post_id: "manual-post",
      provider_url: "https://www.instagram.com/p/manual-post/",
      actions: [{ version: 1, operation: "complete_manual", occurred_at: "2026-09-17T12:10:00Z" }],
    });
    render(panel());
    const detail = await openDetail();
    expect(screen.getByText(publicationStatusLabels.retryable_failure)).toBeInTheDocument();
    expect(within(detail).getByText(/separate from provider-confirmed/)).toBeInTheDocument();
    expect(within(detail).getByText("Manual completion recorded")).toBeInTheDocument();
    expect(within(detail).getByText("manual-post")).toBeInTheDocument();
    expect(within(detail).getByRole("link", { name: "View provider publication" })).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
    expect(screen.getByLabelText("Human resolution history")).toBeInTheDocument();
  });

  it("does not expose unknown errors, unsafe links, or a changed destination identity", async () => {
    current = publication({
      latest_failure_reason: "Bearer secret-value",
      provider_url: "https://provider.example/post?access_token=secret-value",
      destination_identity_matches: false,
      attempts: [],
    });
    render(panel());
    await openDetail();
    expect(screen.queryByText(/secret-value/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "View provider publication" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Artist account/)).not.toBeInTheDocument();
    expect(screen.getByText(/Original destination unavailable/)).toBeInTheDocument();
  });

  it("shows loading, empty, and failed reads without reflecting response bodies", async () => {
    let resolve!: (response: Response) => void;
    fetchMock.mockImplementationOnce(
      () =>
        new Promise<Response>((done) => {
          resolve = done;
        }),
    );
    render(panel());
    expect(screen.getByText("Loading publication history")).toBeInTheDocument();
    await act(async () => resolve(Response.json({ publications: [], next_after_id: null })));
    expect(await screen.findByText(/No publications yet/)).toBeInTheDocument();
    fetchMock.mockResolvedValueOnce(
      Response.json({ detail: "Authorization: Bearer secret-value" }, { status: 403 }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Refresh publications" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You do not have permission");
    expect(screen.queryByText(/secret-value/)).not.toBeInTheDocument();
  });

  it("paginates without duplicates and refreshes all visible pages", async () => {
    fetchMock.mockImplementation(async (path: string) =>
      Response.json(
        path.includes("after_id=")
          ? { publications: [current, publication({ id: "older" })], next_after_id: null }
          : { publications: [current], next_after_id: "cursor" },
      ),
    );
    render(panel());
    fireEvent.click(await screen.findByRole("button", { name: "Load more publications" }));
    await screen.findByLabelText("Publication older");
    expect(screen.getAllByRole("article")).toHaveLength(2);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("after_id=cursor"),
      expect.anything(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Refresh publications" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    expect(screen.getAllByRole("article")).toHaveLength(2);
  });

  it("refreshes on delivery notifications and clears data if permission is lost", async () => {
    render(panel());
    await openDetail();
    fetchMock.mockResolvedValue(Response.json({ detail: "private diagnostic" }, { status: 403 }));
    act(() => notifySchedulingUpdate("workspace", "content"));
    await screen.findByRole("alert");
    expect(screen.queryByLabelText("Publication detail")).not.toBeInTheDocument();
    expect(screen.queryByText("The approved teaser")).not.toBeInTheDocument();
  });

  it("ignores stale detail responses after switching workspace and content", async () => {
    let resolve!: (response: Response) => void;
    const { rerender } = render(panel());
    await screen.findByRole("button", { name: "View delivery details" });
    fetchMock.mockImplementationOnce(
      () =>
        new Promise<Response>((done) => {
          resolve = done;
        }),
    );
    fireEvent.click(screen.getByRole("button", { name: "View delivery details" }));
    fetchMock.mockResolvedValue(Response.json({ publications: [], next_after_id: null }));
    rerender(
      panel({ ...item, id: "other", workspace_id: "other-workspace", title: "Other content" }),
    );
    await screen.findByText(/No publications yet/);
    await act(async () => resolve(Response.json(current)));
    expect(screen.queryByText("The approved teaser")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/other-workspace/publications?content_item_id=other"),
      expect.anything(),
    );
  });
  it.each([
    { can_manage_recovery: false },
    { can_manage_recovery: undefined },
    { can_authorize_retry: false },
    { delivery_status: "published", resolution: "published" },
    { resolution: "manually_completed" },
    { delivery_status: "manual_action_required", resolution: "reconciliation_required" },
    { destination_connection_status: "reconnect_required" },
  ] satisfies Partial<Publication>[])("hides retry for ineligible state %j", async (state) => {
    current = publication(state);
    render(panel());
    await openDetail();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("retries once with canonical versions and refreshes the authorized state", async () => {
    render(panel());
    await openDetail();
    let finish!: (response: Response) => void;
    fetchMock.mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    );
    const retry = screen.getByRole("button", { name: "Retry" });
    fireEvent.click(retry);
    fireEvent.click(retry);
    expect(screen.getByRole("button", { name: "Requesting retry..." })).toBeDisabled();
    const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(posts).toHaveLength(1);
    expect(posts[0]?.[0]).toBe("/api/workspaces/workspace/publications/publication/recover");
    expect(JSON.parse(posts[0]?.[1].body)).toEqual({
      expected_version: 2,
      expected_action_version: 0,
    });
    expect(posts[0]?.[1].headers["Idempotency-Key"]).toMatch(/^[a-f0-9-]{36}$/);
    current = publication({
      resolution: "retry_authorized",
      can_authorize_retry: false,
      action_version: 1,
    });
    await act(async () => finish(Response.json(current)));
    expect(await screen.findByText(/Retry authorized. The worker/)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument(),
    );
    expect(screen.getByLabelText("Attempt 1")).toBeInTheDocument();
  });

  it("keeps an idempotency key after uncertain failure and never reflects provider errors", async () => {
    render(panel());
    await openDetail();
    fetchMock.mockResolvedValueOnce(
      Response.json({ detail: "Authorization: Bearer private" }, { status: 503 }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Recovery could not be confirmed");
    await waitFor(() => expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled());
    fetchMock.mockRejectedValueOnce(new Error("private token"));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled());
    const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(posts).toHaveLength(2);
    expect(posts[0]?.[1].headers["Idempotency-Key"]).toBe(posts[1]?.[1].headers["Idempotency-Key"]);
    expect(screen.queryByText(/private/)).not.toBeInTheDocument();
  });

  it("refreshes stale conflicts and removes controls for a published terminal state", async () => {
    render(panel());
    await openDetail();
    current = publication({
      delivery_status: "published",
      resolution: "published",
      completion_source: "provider",
    });
    fetchMock.mockResolvedValueOnce(Response.json({ detail: "private" }, { status: 409 }));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Publication state changed");
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("button", { name: "Reserve manual delivery" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Published")).toBeInTheDocument();
  });

  it("reserves manual delivery then records validated human evidence without replacing attempts", async () => {
    render(panel());
    await openDetail();
    current = publication({
      resolution: "manual_publishing",
      action_version: 1,
      can_authorize_retry: false,
      can_begin_manual: false,
      can_complete_manual: true,
      asset_refs: [{ sha256: "a".repeat(64), size_bytes: 10, media_type: "image/png" }],
    });
    fireEvent.click(screen.getByRole("button", { name: "Reserve manual delivery" }));
    const complete = await screen.findByRole("button", { name: "Mark publication completed" });
    expect(complete).toBeDisabled();
    expect(screen.getByRole("link", { name: "Download prepared asset" })).toHaveAttribute(
      "href",
      expect.stringContaining("/assets/"),
    );
    expect(screen.getByText(/does not publish through the provider API/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.change(screen.getByLabelText("Provider URL (optional)"), {
      target: { value: "https://example.com/post?access_token=private" },
    });
    fireEvent.click(complete);
    expect(await screen.findByRole("alert")).toHaveTextContent("valid resource ID");
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("Provider URL (optional)"), {
      target: { value: "https://example.com/post" },
    });
    fireEvent.change(screen.getByLabelText("Provider resource ID (optional)"), {
      target: { value: "post-123" },
    });
    current = publication({
      resolution: "manually_completed",
      action_version: 2,
      completion_source: "human",
      can_complete_manual: false,
    });
    fireEvent.click(complete);
    await screen.findByText(/Manual completion recorded. Automatic attempt/);
    const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(JSON.parse(posts[1]?.[1].body)).toEqual({
      expected_version: 2,
      expected_action_version: 1,
      delivery_confirmed: true,
      external_post_id: "post-123",
      provider_url: "https://example.com/post",
    });
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Mark publication completed" }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByLabelText("Attempt 1")).toBeInTheDocument();
  });

  it("offers no mutation controls to an unauthorized viewer", async () => {
    current = publication({ can_manage_recovery: false, can_manage_account: false });
    render(panel());
    const detail = await openDetail();
    expect(within(detail).queryByRole("button")).not.toBeInTheDocument();
    expect(
      within(detail).queryByRole("link", { name: /Reconnect Account/ }),
    ).not.toBeInTheDocument();
  });

  it("uses existing OAuth for reconnect, then refreshes account/publication state on return without publishing", async () => {
    vi.stubEnv("NEXT_PUBLIC_YOUTUBE_DIRECT_OAUTH_ENABLED", "true");
    current = publication({
      provider: "youtube",
      destination_connection_method: "direct_api",
      destination_connection_status: "reconnect_required",
    });
    const popup = { opener: {}, close: vi.fn() } as unknown as Window;
    vi.spyOn(window, "open").mockReturnValue(popup);
    vi.mocked(startSocialAccountOAuthConnection).mockResolvedValue({
      authorization_url: "https://accounts.google.com/oauth",
      state: "state",
      expires_at: "soon",
      scopes: [],
    });
    render(panel());
    await openDetail();
    fireEvent.click(screen.getByRole("button", { name: "Reconnect Account" }));
    await waitFor(() =>
      expect(navigateToSocialAccountAuthorization).toHaveBeenCalledWith(
        "https://accounts.google.com/oauth",
        popup,
      ),
    );
    expect(startSocialAccountOAuthConnection).toHaveBeenCalledWith("workspace", {
      provider: "youtube",
      redirect_uri: "http://localhost:3000/api/social-account-connections/oauth/youtube/callback",
      safe_redirect_path: "/marketing?tab=accounts",
    });
    current = { ...current, destination_connection_status: "connected" };
    fireEvent(window, new Event("focus"));
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
  });

  it("refreshes expanded recovery actions on realtime updates", async () => {
    render(panel());
    await openDetail();
    expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
    current = publication({ delivery_status: "published", resolution: "published" });
    act(() => notifySchedulingUpdate("workspace", "content"));
    await screen.findByText("Published");
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument(),
    );
  });
});
