import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { YouTubeResearchPanel } from "./youtube-research-panel";
import { counterText, isDisplayable, type ChannelDisplay } from "../lib/youtube-research";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
function fixture(): ChannelDisplay {
  const provenance = {
    collected_at: new Date().toISOString(),
    expires_at: new Date(Date.now() + 30 * 86400000).toISOString(),
    source_url: "https://www.youtube.com/channel/UCaaaaaaaaaaaaaaaaaaaaaa",
    provider_fields: [],
  };
  return {
    artist: { external_id: "UCaaaaaaaaaaaaaaaaaaaaaa", name: "Test channel", provenance },
    items: [{ metric_key: "youtube.channel.views", value: 0, provenance }],
  };
}
function setup() {
  render(
    <YouTubeResearchPanel
      workspaceId="workspace"
      runId="run"
      privacyUrl="https://example.com/privacy"
      termsUrl="https://example.com/terms"
    />,
  );
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.change(screen.getByLabelText("Search YouTube channels"), { target: { value: "Test" } });
}

describe("YouTube research lifecycle", () => {
  it("erases an unavailable channel reference from the input and parent review", async () => {
    const channel = fixture().artist.external_id;
    const unavailable = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          Response.json({ detail: { code: "data_unavailable" } }, { status: 404 }),
        ),
    );
    render(
      <YouTubeResearchPanel
        workspaceId="workspace"
        runId="run"
        privacyUrl="https://example.com/privacy"
        termsUrl="https://example.com/terms"
        initialChannel={channel}
        onUnavailable={unavailable}
      />,
    );
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByText("Look up channel"));
    await waitFor(() => expect(unavailable).toHaveBeenCalledWith(channel));
    expect(screen.getByLabelText("YouTube channel ID")).toHaveValue("");
  });
  it("does not treat missing or hidden counters as zero", () => {
    const data = fixture();
    expect(counterText(data, "views")).toBe("0");
    expect(counterText(data, "subscribers")).toBe("Unavailable");
    data.artist.provenance.provider_fields = [{ key: "subscriber_count_status", value: "hidden" }];
    expect(counterText(data, "subscribers")).toBe("Hidden by channel");
    expect(isDisplayable(data.artist.provenance, Date.now() + 15 * 60000)).toBe(false);
    expect(isDisplayable({ ...data.artist.provenance, expires_at: "invalid" }, Date.now())).toBe(
      false,
    );
  });

  it("loads channels only on explicit action and removes data on clear", async () => {
    const data = fixture();
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ items: [data.artist] }))
      .mockResolvedValueOnce(Response.json(data))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);
    setup();
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Search channels"));
    fireEvent.click(await screen.findByRole("button", { name: "Test channel" }));
    await screen.findByRole("heading", { name: "Test channel" });
    expect(screen.getAllByText("Unavailable")).toHaveLength(2);
    expect(screen.getByText("0")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Clear YouTube display data"));
    expect(screen.queryByRole("heading", { name: "Test channel" })).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it("looks up an explicit channel, opens its source, and saves only its identifier", async () => {
    const data = fixture();
    const save = vi.fn().mockResolvedValue(undefined);
    const fetch = vi.fn().mockResolvedValue(Response.json(data));
    vi.stubGlobal("fetch", fetch);
    render(
      <YouTubeResearchPanel
        workspaceId="workspace"
        runId="run"
        privacyUrl="https://example.com/privacy"
        termsUrl="https://example.com/terms"
        onSave={save}
      />,
    );
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.change(screen.getByLabelText("YouTube channel ID"), {
      target: { value: data.artist.external_id },
    });
    fireEvent.click(screen.getByText("Look up channel"));
    await screen.findByRole("heading", { name: "Test channel" });
    expect(screen.getByText("View channel on YouTube")).toHaveAttribute(
      "href",
      `https://www.youtube.com/channel/${data.artist.external_id}`,
    );
    expect(screen.getByText("View channel on YouTube")).toHaveAttribute("target", "_blank");
    fireEvent.click(screen.getByText("Save candidate"));
    await waitFor(() => expect(save).toHaveBeenCalledWith(data.artist.external_id));
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    "quota_exceeded",
    "rate_limited",
    "timeout",
    "data_unavailable",
    "provider_unavailable",
  ])("renders a safe %s error", async (code) => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        Response.json(
          { detail: { code, message: "SECRET" } },
          { status: 429, headers: { "Retry-After": "17" } },
        ),
      );
    vi.stubGlobal("fetch", fetch);
    setup();
    fireEvent.click(screen.getByText("Search channels"));
    await screen.findByRole("alert");
    expect(screen.queryByText("SECRET")).not.toBeInTheDocument();
    expect(screen.getByText("Search channels")).toBeDisabled();
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("shows empty results", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ items: [] })));
    setup();
    fireEvent.click(screen.getByText("Search channels"));
    expect(await screen.findByText(/No current results/)).toBeInTheDocument();
  });

  it("marks stale data and evicts it without another provider request", async () => {
    const data = fixture();
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ items: [data.artist] }))
      .mockResolvedValueOnce(Response.json(data));
    vi.stubGlobal("fetch", fetch);
    setup();
    fireEvent.click(screen.getByText("Search channels"));
    fireEvent.click(await screen.findByRole("button", { name: "Test channel" }));
    await screen.findByRole("heading", { name: "Test channel" });
    // The active interval observes wall time; advance it without waiting 15 minutes.
    const dateSpy = vi
      .spyOn(Date, "now")
      .mockReturnValue(Date.parse(data.artist.provenance.collected_at) + 61000);
    await waitFor(() => expect(screen.getByText(/Stale YouTube data/)).toBeInTheDocument(), {
      timeout: 2000,
    });
    dateSpy.mockReturnValue(Date.parse(data.artist.provenance.collected_at) + 15 * 60000);
    await waitFor(
      () => expect(screen.queryByRole("heading", { name: "Test channel" })).not.toBeInTheDocument(),
      { timeout: 2000 },
    );
    dateSpy.mockRestore();
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("ignores a late response after data is cleared", async () => {
    let resolve!: (value: Response) => void;
    const fetch = vi
      .fn()
      .mockReturnValueOnce(
        new Promise<Response>((done) => {
          resolve = done;
        }),
      )
      .mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);
    setup();
    fireEvent.click(screen.getByText("Search channels"));
    expect(screen.getByText(/Loading YouTube/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Clear YouTube display data"));
    await act(async () => resolve(Response.json({ items: [fixture().artist] })));
    expect(screen.queryByText("Test channel")).not.toBeInTheDocument();
  });
});
