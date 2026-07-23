import { redirect } from "next/navigation";

import { AppShell } from "../../components/app-shell";
import { StatusIndicator } from "../../components/status-indicator";
import { ApiClientError, getCurrentApiUser, type CurrentApiUser } from "../../lib/api-client";
import { requireDashboardSession } from "../../lib/dashboard-session";

function displayName({
  email,
  firstName,
  lastName,
}: {
  email: string | null;
  firstName: string | null;
  lastName: string | null;
}) {
  return [firstName, lastName].filter(Boolean).join(" ") || email || "Label OS user";
}

export default async function DashboardPage() {
  const session = await requireDashboardSession();
  if (!session.organizationId) {
    redirect("/onboarding/workspace");
  }

  let backendUser: CurrentApiUser | null = null;
  let sessionError = false;

  try {
    backendUser = await getCurrentApiUser();
  } catch (error) {
    if (error instanceof ApiClientError) {
      sessionError = true;
    } else {
      throw error;
    }
  }

  const name = displayName(session.user);
  const organizationId = backendUser?.organization_id ?? session.organizationId;

  return (
    <AppShell>
      <div className="flex flex-col gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-950">Dashboard</h1>
          <p className="mt-2 text-sm text-slate-600">Placeholder dashboard route.</p>
        </div>
        <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,24rem)]">
          <div className="rounded-md border border-white/70 bg-white/60 p-5 shadow-sm backdrop-blur-2xl">
            <div className="flex items-center gap-4">
              {session.user.profileImageUrl ? (
                <span
                  aria-label={`${name} profile image`}
                  className="h-14 w-14 rounded-full bg-cover bg-center ring-1 ring-white/80"
                  role="img"
                  style={{ backgroundImage: `url("${session.user.profileImageUrl}")` }}
                />
              ) : (
                <span
                  aria-hidden="true"
                  className="flex h-14 w-14 items-center justify-center rounded-full bg-slate-950 text-sm font-semibold text-white"
                >
                  LO
                </span>
              )}
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">
                  Signed in
                </p>
                <h2 className="truncate text-lg font-semibold text-slate-950">{name}</h2>
                {session.user.email ? (
                  <p className="truncate text-sm text-slate-600">{session.user.email}</p>
                ) : null}
              </div>
            </div>
          </div>
          <div className="rounded-md border border-white/70 bg-white/60 p-5 shadow-sm backdrop-blur-2xl">
            <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">
              Active organization
            </p>
            {organizationId ? (
              <p className="mt-2 break-all font-mono text-sm text-slate-950">{organizationId}</p>
            ) : (
              <p className="mt-2 text-sm leading-6 text-slate-600">
                No active organization is selected. Complete workspace onboarding to attach this
                account to a label workspace.
              </p>
            )}
          </div>
        </section>
        {sessionError ? (
          <section
            aria-live="polite"
            className="rounded-md border border-amber-200 bg-amber-50 px-5 py-4 text-sm leading-6 text-amber-950"
            role="alert"
          >
            Your session is signed in with WorkOS, but the backend could not verify it. Sign out and
            sign in again to refresh access.
          </section>
        ) : null}
        {backendUser ? (
          <section className="grid gap-4 rounded-md border border-white/70 bg-white/60 p-5 shadow-sm backdrop-blur-2xl sm:grid-cols-2">
            <div>
              <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">Role</p>
              <p className="mt-2 text-sm font-medium text-slate-950">
                {backendUser.role ?? "No role assigned"}
              </p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-normal text-slate-500">
                Permissions
              </p>
              <p className="mt-2 text-sm text-slate-700">
                {backendUser.permissions.length > 0
                  ? backendUser.permissions.join(", ")
                  : "No permissions assigned"}
              </p>
            </div>
          </section>
        ) : null}
        {!organizationId ? (
          <section className="rounded-md border border-dashed border-slate-300 bg-white/70 px-6 py-10 text-center shadow-sm backdrop-blur-2xl">
            <h2 className="text-base font-semibold text-slate-950">No label workspace yet</h2>
            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-600">
              You are signed in, but this account does not belong to a label workspace yet. Once an
              administrator adds you to an organization, workspace data will appear here.
            </p>
          </section>
        ) : null}
        <StatusIndicator />
      </div>
    </AppShell>
  );
}
