"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@label-os/ui";

import {
  isWorkspaceNavigationItemCurrent,
  visibleWorkspaceNavigationItems,
} from "../lib/workspace-navigation";
import { useActiveWorkspace, useActiveWorkspaceProfile } from "../lib/workspace-context";

export function WorkspaceNavigation() {
  const pathname = usePathname();
  const { hasActiveWorkspace } = useActiveWorkspace();
  const workspaceProfile = useActiveWorkspaceProfile();
  const items = visibleWorkspaceNavigationItems({
    hasActiveWorkspace,
    subject: workspaceProfile.subject,
  });

  return (
    <nav aria-label="Workspace" className="mt-4 grid gap-1">
      {items.map((item) => {
        const isCurrent = isWorkspaceNavigationItemCurrent(item, pathname);
        return (
          <Link
            aria-current={isCurrent ? "page" : undefined}
            className={cn(
              "rounded-md px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-white/70 hover:text-slate-950 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500",
              isCurrent ? "bg-white/80 text-slate-950 shadow-sm" : "",
            )}
            href={item.href}
            key={item.href}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
