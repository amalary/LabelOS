"use client";

import { useState } from "react";
import { useEffectiveCapabilities } from "../lib/workspace-capabilities";

export function LocalResearchSetup({
  workspaceId,
  onPrepared,
}: {
  workspaceId: string;
  onPrepared: (run: { id: string; label: string }) => void;
}) {
  const { can } = useEffectiveCapabilities(workspaceId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!can("governance.manage")) return null;
  return (
    <section aria-label="Local research setup" className="space-y-3 rounded border p-5">
      <h2 className="text-xl font-semibold">Prepare local research</h2>
      <p>
        Create a local YouTube research session for this workspace. It uses draft documentation and
        does not approve production use. An existing active session is reused.
      </p>
      <button
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            const response = await fetch(
              `/api/workspaces/${encodeURIComponent(workspaceId)}/scouting/local-session`,
              { method: "POST", cache: "no-store" },
            );
            if (!response.ok)
              throw new Error(
                "Could not prepare the session. Check your governance access and try again.",
              );
            onPrepared(await response.json());
          } catch {
            setError("Could not prepare the session. Check your governance access and try again.");
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Preparing session…" : "Prepare local YouTube session"}
      </button>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
