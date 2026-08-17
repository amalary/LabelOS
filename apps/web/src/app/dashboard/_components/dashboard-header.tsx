type DashboardHeaderProps = {
  organizationName: string;
};

export function DashboardHeader({ organizationName }: DashboardHeaderProps) {
  return (
    <header className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
      <div className="min-w-0">
        <h1 className="dashboard-gradient-text text-4xl font-semibold sm:text-5xl">Dashboard</h1>
        <p className="mt-4 max-w-3xl text-sm leading-6 text-slate-300">
          Operational view for {organizationName}. Workspace-scoped metrics stay isolated until
          production dashboard APIs are ready.
        </p>
      </div>
      <div className="dashboard-panel-soft w-full rounded-[18px] px-4 py-3 lg:w-auto lg:min-w-64">
        <p className="text-xs font-medium uppercase tracking-[0.16em] text-slate-500">
          Command center
        </p>
        <p className="mt-1 text-sm font-semibold text-slate-100">Label intelligence online</p>
      </div>
    </header>
  );
}
