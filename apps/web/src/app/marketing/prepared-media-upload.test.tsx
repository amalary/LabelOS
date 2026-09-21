import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PreparedMediaUpload } from "./prepared-media-upload";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const props = () => ({
  workspaceId: "workspace",
  contentId: "content",
  disabled: false,
  label: "Upload media",
  onBusy: vi.fn(),
  onUploaded: vi.fn(),
});

it("requires a saved draft", () => {
  render(<PreparedMediaUpload {...props()} contentId={null} />);
  expect(screen.getByText("Save this draft before uploading media.")).toBeTruthy();
  expect(screen.queryByLabelText("Upload media")).toBeNull();
});

it("uploads the file and returns its reference for the normal draft save", async () => {
  const ref = { sha256: "a".repeat(64), size_bytes: 5, media_type: "video/mp4" };
  const fetch = vi.fn().mockResolvedValue(Response.json(ref));
  vi.stubGlobal("fetch", fetch);
  const handlers = props();
  render(<PreparedMediaUpload {...handlers} />);
  const file = new File(["video"], "clip.mp4", { type: "video/mp4" });
  fireEvent.change(screen.getByLabelText("Upload media"), { target: { files: [file] } });
  await waitFor(() => expect(handlers.onUploaded).toHaveBeenCalledWith(ref));
  expect(fetch).toHaveBeenCalledWith(
    "/api/workspaces/workspace/marketing-content/content/assets",
    expect.objectContaining({ body: file, method: "POST" }),
  );
  expect(handlers.onBusy.mock.calls).toEqual([[true], [false]]);
});

it("does not attach failed uploads", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 403 })));
  const handlers = props();
  render(<PreparedMediaUpload {...handlers} />);
  fireEvent.change(screen.getByLabelText("Upload media"), {
    target: { files: [new File(["video"], "clip.mp4", { type: "video/mp4" })] },
  });
  await screen.findByText("Upload failed. Try again; the draft has not changed.");
  expect(handlers.onUploaded).not.toHaveBeenCalled();
});

it("aborts unmounted uploads without attaching media to another editor", async () => {
  let resolve!: (response: Response) => void;
  const fetch = vi.fn().mockImplementation(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  vi.stubGlobal("fetch", fetch);
  const handlers = props();
  const view = render(<PreparedMediaUpload {...handlers} />);
  fireEvent.change(screen.getByLabelText("Upload media"), {
    target: { files: [new File(["video"], "clip.mp4", { type: "video/mp4" })] },
  });
  view.unmount();
  expect(fetch.mock.calls[0]?.[1].signal.aborted).toBe(true);
  resolve(Response.json({ sha256: "a".repeat(64) }));
  await Promise.resolve();
  expect(handlers.onUploaded).not.toHaveBeenCalled();
});
