"use client";

import { useOrganizationRealtime } from "../lib/realtime/use-organization-realtime";

type RealtimeWorkspaceSyncProps = {
  organizationId: string | null;
};

export function RealtimeWorkspaceSync({ organizationId }: RealtimeWorkspaceSyncProps) {
  const { connectionState, lastUpdatedBy, presence } = useOrganizationRealtime(organizationId);

  if (!organizationId) {
    return null;
  }

  return (
    <div className="flex items-center gap-3 text-xs text-slate-500" aria-live="polite">
      <span className="flex items-center gap-1.5">
        <span
          className={
            connectionState === "connected"
              ? "h-2 w-2 rounded-full bg-emerald-500"
              : "h-2 w-2 rounded-full bg-amber-500"
          }
        />
        {connectionState === "connected" ? "Live" : "Reconnecting"}
      </span>
      <span>{presence.length} active</span>
      {lastUpdatedBy ? <span className="hidden sm:inline">Updated by {lastUpdatedBy}</span> : null}
    </div>
  );
}
