import { AppShell } from "../../components/app-shell";
import { StatusIndicator } from "../../components/status-indicator";

export default function DashboardPage() {
  return (
    <AppShell>
      <div className="flex flex-col gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-950">Dashboard</h1>
          <p className="mt-2 text-sm text-slate-600">Placeholder dashboard route.</p>
        </div>
        <StatusIndicator />
      </div>
    </AppShell>
  );
}
