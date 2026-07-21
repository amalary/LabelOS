import { StatusIndicator } from "../components/status-indicator";

export default function HomePage() {
  return (
    <main className="min-h-screen px-6 py-10">
      <div className="mx-auto flex max-w-3xl flex-col gap-6">
        <div>
          <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Label OS</p>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950">Frontend starter</h1>
          <p className="mt-3 max-w-2xl text-base text-slate-600">
            Minimal Next.js application placeholder.
          </p>
        </div>
        <StatusIndicator />
      </div>
    </main>
  );
}
