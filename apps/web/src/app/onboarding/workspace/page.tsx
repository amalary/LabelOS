import { redirect } from "next/navigation";

import { AppShell } from "../../../components/app-shell";
import { requireDashboardSession } from "../../../lib/dashboard-session";
import { WorkspaceOnboardingForm } from "./onboarding-form";

export default async function WorkspaceOnboardingPage() {
  const session = await requireDashboardSession();

  if (session.organizationId) {
    redirect("/dashboard");
  }

  return (
    <AppShell>
      <main className="mx-auto flex min-h-[calc(100vh-9rem)] w-full max-w-xl flex-col justify-center">
        <section className="rounded-md border border-white/70 bg-white/70 p-6 shadow-sm backdrop-blur-2xl">
          <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">
            Workspace setup
          </p>
          <h1 className="mt-2 text-2xl font-semibold text-slate-950">
            Create your label workspace
          </h1>
          <p className="mt-3 text-sm leading-6 text-slate-600">
            Start with the label or company name. You can add teammates and configure workspace
            details after setup.
          </p>
          <WorkspaceOnboardingForm />
        </section>
      </main>
    </AppShell>
  );
}
