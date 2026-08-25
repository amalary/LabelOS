import { AppShell } from "../../../components/app-shell";
import { ApiClientError } from "../../../lib/api-client";
import { getWorkspaceInvite } from "../../../lib/organizations";
import { InviteOnboardingFlow } from "./invite-onboarding-flow";

type InviteOnboardingStep = "intro" | "account" | "accept" | "roles";

type JoinWorkspacePageProps = {
  params: Promise<{
    token: string;
  }>;
  searchParams?: Promise<{
    inviteError?: string;
    step?: string;
  }>;
};

function inviteStepFromQuery(step: string | undefined): InviteOnboardingStep {
  if (step === "account" || step === "accept" || step === "roles") {
    return step;
  }

  return "intro";
}

export default async function JoinWorkspacePage({ params, searchParams }: JoinWorkspacePageProps) {
  const { token } = await params;
  const query = await searchParams;
  const initialStep = inviteStepFromQuery(query?.step);

  try {
    const invite = await getWorkspaceInvite(token);

    return (
      <AppShell>
        <div className="mx-auto flex min-h-[60vh] w-full max-w-2xl items-center">
          <InviteOnboardingFlow
            hasInviteError={Boolean(query?.inviteError)}
            initialStep={initialStep}
            invite={invite}
          />
        </div>
      </AppShell>
    );
  } catch (error) {
    if (!(error instanceof ApiClientError) || (error.status !== 404 && error.status !== 410)) {
      throw error;
    }

    return (
      <AppShell>
        <div className="mx-auto flex min-h-[60vh] w-full max-w-2xl items-center">
          <section className="w-full border border-slate-200 bg-white p-6 shadow-sm">
            <p className="text-sm font-medium text-slate-500">Workspace Invite</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-normal text-slate-950">
              Invite unavailable
            </h1>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              This invite link is invalid, expired, or no longer available.
            </p>
          </section>
        </div>
      </AppShell>
    );
  }
}
