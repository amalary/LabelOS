import type { ReactNode } from "react";

import { AuthNavigation } from "./auth/auth-navigation";
import { getNavigationAuthState } from "./auth/auth-session";

type AppShellProps = {
  children: ReactNode;
};

export async function AppShell({ children }: AppShellProps) {
  const authState = await getNavigationAuthState();

  return (
    <div className="min-h-screen bg-[linear-gradient(135deg,#f8fafc_0%,#eef2f7_48%,#f8fafc_100%)] text-slate-950">
      <div className="grid min-h-screen md:grid-cols-[240px_1fr]">
        <aside className="border-b border-white/70 bg-white/45 p-4 shadow-[inset_-1px_0_0_rgba(255,255,255,0.7)] backdrop-blur-2xl md:border-b-0 md:border-r">
          <div className="flex items-center gap-3 rounded-[24px] border border-white/70 bg-white/55 p-3 shadow-[0_16px_50px_rgba(15,23,42,0.08)]">
            <span className="flex h-10 w-10 items-center justify-center rounded-[18px] bg-slate-950 text-xs font-semibold text-white">
              LO
            </span>
            <div>
              <div className="text-sm font-semibold text-slate-950">Label OS</div>
              <div className="text-xs text-slate-500">Operations</div>
            </div>
          </div>
        </aside>
        <div className="flex min-w-0 flex-col">
          <header className="border-b border-white/70 bg-white/45 px-6 py-4 backdrop-blur-2xl">
            <div className="flex items-center justify-between gap-4">
              <div className="min-w-0">
                <div className="text-sm font-semibold text-slate-950">Workspace</div>
                <div className="text-xs text-slate-500">Label operations dashboard</div>
              </div>
              <AuthNavigation {...authState} />
            </div>
          </header>
          <main className="flex-1 px-6 py-6">{children}</main>
        </div>
      </div>
    </div>
  );
}
