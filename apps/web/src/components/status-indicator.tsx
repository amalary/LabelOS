const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "not configured";

export function StatusIndicator() {
  return (
    <section className="border border-slate-200 bg-white p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-sm font-semibold text-slate-950">Frontend status</h2>
          <p className="text-sm text-slate-600">Next.js frontend is running.</p>
        </div>
        <p className="text-xs text-slate-500">API URL: {apiUrl}</p>
      </div>
    </section>
  );
}
