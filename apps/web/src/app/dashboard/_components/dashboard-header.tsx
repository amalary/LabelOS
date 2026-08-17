type DashboardHeaderProps = {
  organizationName: string;
};

export function DashboardHeader({ organizationName }: DashboardHeaderProps) {
  return (
    <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div className="min-w-0">
        <h1
          className="dashboard-gradient-text text-3xl font-semibold leading-tight sm:text-5xl"
          id="dashboard-page-title"
        >
          Dashboard
        </h1>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-300">
          Operational view for {organizationName}. Workspace-scoped metrics stay isolated until
          production dashboard APIs are ready.
        </p>
      </div>
      <div className="dashboard-panel-soft w-full rounded-[16px] px-4 py-3 lg:w-auto lg:min-w-64">
        <p className="text-xs font-medium uppercase tracking-[0.16em] text-slate-400">
          Command center
        </p>
        <p className="mt-1 text-sm font-semibold text-slate-100">Label intelligence online</p>
      </div>
    </header>
  );
}
