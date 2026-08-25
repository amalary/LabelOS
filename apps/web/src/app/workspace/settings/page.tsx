import { redirect } from "next/navigation";

import { AppShell } from "../../../components/app-shell";
import { requireDashboardSession } from "../../../lib/dashboard-session";
import { getOrganizationSelection } from "../../../lib/organizations";
import { InviteTemplateForm } from "./invite-template-form";

type WorkspaceSettingsPageProps = {
  searchParams?: Promise<{
    invite?: string;
    inviteError?: string;
  }>;
};

function joinUrl(token: string): string {
  const baseUrl = process.env.WEB_BASE_URL ?? "http://localhost:3000";
  return new URL(`/join/${token}`, baseUrl).toString();
}

export default async function WorkspaceSettingsPage({ searchParams }: WorkspaceSettingsPageProps) {
  await requireDashboardSession();
  const params = await searchParams;
  const organizationSelection = await getOrganizationSelection();
  const activeOrganization = organizationSelection.activeOrganization;

  if (!activeOrganization && organizationSelection.organizations.length === 0) {
    redirect("/onboarding/workspace");
  }

  const inviteLink = params?.invite ? joinUrl(params.invite) : null;

  return (
    <AppShell>
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
        <header className="flex flex-col gap-2 border-b border-slate-200 pb-5">
          <p className="text-sm font-medium text-slate-500">Workspace Settings</p>
          <h1 className="text-3xl font-semibold tracking-normal text-slate-950">Invite People</h1>
          <p className="max-w-2xl text-sm leading-6 text-slate-600">
            Create a general workspace invitation link for{" "}
            {activeOrganization?.name ?? "this workspace"}.
          </p>
        </header>

        {!activeOrganization ? (
          <section
            className="border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"
            role="alert"
          >
            Choose an active workspace before creating an invitation link.
          </section>
        ) : (
          <section className="grid gap-5 border border-slate-200 bg-white p-5 shadow-sm">
            <div>
              <h2 className="text-lg font-semibold text-slate-950">Invite Person</h2>
              <p className="mt-1 text-sm leading-6 text-slate-600">
                Assign professional roles now. The accepted membership inherits these roles.
              </p>
            </div>

            <InviteTemplateForm organizationId={activeOrganization.id} />

            {inviteLink ? (
              <div className="grid gap-2 border border-emerald-200 bg-emerald-50 p-4">
                <div className="text-sm font-semibold text-emerald-950">Invite link created</div>
                <div className="break-all font-mono text-sm text-emerald-900">{inviteLink}</div>
              </div>
            ) : null}

            {params?.inviteError ? (
              <div
                className="border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
                role="alert"
              >
                We could not create the invite link. Check your workspace permissions and try again.
              </div>
            ) : null}
          </section>
        )}
      </div>
    </AppShell>
  );
}
