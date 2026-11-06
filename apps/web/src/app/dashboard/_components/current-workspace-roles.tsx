"use client";

import { useEffectiveCapabilities } from "../../../lib/workspace-capabilities";

export function CurrentWorkspaceRoles({
  workspaceId,
  workspaceName,
}: {
  workspaceId: string | null;
  workspaceName?: string;
}) {
  const authorization = useEffectiveCapabilities(workspaceId);
  if (!workspaceId) return null;
  return (
    <section
      aria-label="Your workspace roles"
      className="rounded-xl border border-slate-700 bg-slate-900/60 px-4 py-3 text-sm text-slate-100"
    >
      <p className="font-semibold">Your roles in {workspaceName}</p>
      <p className="mt-1 text-slate-300">
        {authorization.isLoading && !authorization.data
          ? "Loading roles…"
          : authorization.error
            ? "Your roles could not be loaded. Refresh to try again."
            : authorization.roles.map((role) => role.name).join(", ") || "No assigned roles"}
      </p>
    </section>
  );
}
