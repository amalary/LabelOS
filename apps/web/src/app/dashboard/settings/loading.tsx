import { AppShell } from "../../../components/app-shell";

export default function OrganizationSettingsLoading() {
  return (
    <AppShell>
      <div className="flex flex-col gap-5" aria-live="polite" role="status">
        <div>
          <div className="h-8 w-64 rounded-md bg-white/70" />
          <div className="mt-3 h-5 w-96 max-w-full rounded-md bg-white/60" />
        </div>
        <div className="rounded-md border border-white/70 bg-white/60 p-5 shadow-sm backdrop-blur-2xl">
          <div className="h-16 w-16 rounded-md bg-slate-200" />
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            <div className="h-20 rounded-md bg-white/70" />
            <div className="h-20 rounded-md bg-white/70" />
          </div>
        </div>
        <div className="rounded-md border border-white/70 bg-white/60 p-5 shadow-sm backdrop-blur-2xl">
          <div className="h-6 w-32 rounded-md bg-white/70" />
          <div className="mt-5 h-40 rounded-md bg-white/70" />
        </div>
      </div>
    </AppShell>
  );
}
