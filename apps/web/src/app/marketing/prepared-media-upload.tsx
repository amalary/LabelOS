"use client";

import { useEffect, useRef, useState } from "react";

export type PreparedMediaReference = { sha256: string; size_bytes: number; media_type: string };

export function PreparedMediaUpload({
  workspaceId,
  contentId,
  disabled,
  label,
  onUploaded,
  onBusy,
}: {
  workspaceId: string | null;
  contentId: string | null;
  disabled: boolean;
  label: string;
  onUploaded: (reference: PreparedMediaReference) => void;
  onBusy: (busy: boolean) => void;
}) {
  const controller = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(
    () => () => {
      controller.current?.abort();
    },
    [workspaceId, contentId],
  );

  if (!workspaceId || !contentId)
    return <p className="text-xs text-slate-500">Save this draft before uploading media.</p>;

  async function upload(file: File) {
    setMessage(null);
    if (!file.size || file.size > 16 * 1024 * 1024) {
      setMessage("Choose a file between 1 byte and 16 MiB.");
      return;
    }
    if (!/^(image|video|audio)\/[a-z0-9][a-z0-9.+-]{0,63}$/.test(file.type)) {
      setMessage("Choose an image, video or audio file with a supported media type.");
      return;
    }
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    onBusy(true);
    try {
      const response = await fetch(
        `/api/workspaces/${workspaceId}/marketing-content/${contentId}/assets`,
        {
          method: "POST",
          headers: { "Content-Type": file.type },
          body: file,
          signal: abort.signal,
        },
      );
      if (!response.ok) throw new Error("upload failed");
      const reference = (await response.json()) as PreparedMediaReference;
      if (!abort.signal.aborted) {
        onUploaded(reference);
        setMessage("Uploaded. Save the draft to attach this media, then submit it for approval.");
      }
    } catch {
      if (!abort.signal.aborted) setMessage("Upload failed. Try again; the draft has not changed.");
    } finally {
      if (!abort.signal.aborted) {
        setBusy(false);
        onBusy(false);
      }
    }
  }

  return (
    <div className="grid gap-1 text-sm md:col-span-2">
      <label className="grid gap-1 font-medium text-slate-700">
        <span>{label}</span>
        <input
          type="file"
          accept="image/*,video/*,audio/*"
          disabled={disabled || busy}
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) void upload(file);
          }}
        />
      </label>
      <p className="text-xs text-slate-500">
        Up to 16 MiB per file. YouTube requires one video per target.
      </p>
      {busy && <p role="status">Uploading media…</p>}
      {message && <p role="status">{message}</p>}
    </div>
  );
}
