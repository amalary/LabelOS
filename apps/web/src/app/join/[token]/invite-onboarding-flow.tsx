"use client";

import { useMemo, useState } from "react";
import { useFormStatus } from "react-dom";

import type { WorkspaceInvite } from "../../../lib/organizations";
import { acceptWorkspaceInviteAction } from "./actions";

type InviteOnboardingStep = "intro" | "account" | "accept" | "roles";

type InviteOnboardingFlowProps = {
  invite: WorkspaceInvite;
  hasInviteError: boolean;
  initialStep?: InviteOnboardingStep;
};

function AcceptButton({ disabled }: { disabled: boolean }) {
  const { pending } = useFormStatus();

  return (
    <button
      className="h-11 w-full bg-slate-950 px-4 text-sm font-semibold text-white outline-none transition hover:bg-slate-800 focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-slate-300"
      disabled={disabled || pending}
      type="submit"
    >
      {pending ? "Accepting invitation..." : "Accept Workspace Invitation"}
    </button>
  );
}

export function InviteOnboardingFlow({
  invite,
  hasInviteError,
  initialStep = "intro",
}: InviteOnboardingFlowProps) {
  const [step, setStep] = useState<InviteOnboardingStep>(initialStep);
  const joinPath = useMemo(() => `/join/${invite.token}`, [invite.token]);
  const loginPath = useMemo(
    () => `/api/auth/login?next=${encodeURIComponent(`${joinPath}?step=accept`)}`,
    [joinPath],
  );
  const signupPath = useMemo(
    () => `/api/auth/signup?next=${encodeURIComponent(`${joinPath}?step=accept`)}`,
    [joinPath],
  );
  const isActive = invite.status === "active";
  const showsAccountChoice = step === "account" || step === "accept" || step === "roles";
  const showsAcceptStep = step === "accept" || step === "roles";

  return (
    <section className="w-full border border-slate-200 bg-white p-6 shadow-sm">
      <div className="border-b border-slate-200 pb-6 text-center">
        <p className="text-lg font-medium text-slate-600">You&apos;ve been invited to</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-normal text-slate-950">
          {invite.workspace.name}
        </h1>
        {invite.professional_roles.length > 0 ? (
          <div className="mt-5 grid gap-2">
            <div className="text-sm font-semibold text-slate-700">Roles</div>
            <div className="flex flex-wrap justify-center gap-2">
              {invite.professional_roles.map((role) => (
                <span
                  className="border border-slate-200 bg-slate-50 px-3 py-1 text-sm font-medium text-slate-800"
                  key={role}
                >
                  {role}
                </span>
              ))}
            </div>
          </div>
        ) : null}
        {invite.proposed_department_access.length > 0 ? (
          <div className="mt-5 grid gap-2">
            <div className="text-sm font-semibold text-slate-700">Department Access</div>
            <div className="flex flex-wrap justify-center gap-2">
              {invite.proposed_department_access.map((department) => (
                <span
                  className="border border-cyan-100 bg-cyan-50 px-3 py-1 text-sm font-medium capitalize text-slate-800"
                  key={department}
                >
                  {department.replaceAll("_", " ")}
                </span>
              ))}
            </div>
          </div>
        ) : null}
        <button
          className="mt-6 h-11 bg-slate-950 px-5 text-sm font-semibold text-white outline-none transition hover:bg-slate-800 focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-slate-300"
          disabled={!isActive}
          onClick={() => setStep("account")}
          type="button"
        >
          Join Workspace
        </button>
      </div>

      {hasInviteError ? (
        <div
          className="mt-5 border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
          role="alert"
        >
          We could not accept this invite. It may have expired or reached its usage limit.
        </div>
      ) : null}

      {!showsAccountChoice ? null : (
        <div className="mt-6 grid gap-6">
          <div className="grid gap-4 text-center">
            <h2 className="text-xl font-semibold text-slate-950">Existing LabelOS account?</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              <a
                className="flex h-11 items-center justify-center border border-slate-300 bg-white px-4 text-sm font-semibold text-slate-950 transition hover:border-slate-950"
                href={loginPath}
              >
                Sign in
              </a>
              <a
                className="flex h-11 items-center justify-center border border-slate-300 bg-white px-4 text-sm font-semibold text-slate-950 transition hover:border-slate-950"
                href={signupPath}
              >
                Sign up
              </a>
            </div>
          </div>

          {!showsAcceptStep ? null : !isActive ? (
            <p className="border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              This invitation is not accepting new members.
            </p>
          ) : (
            <form action={acceptWorkspaceInviteAction} className="grid gap-5">
              <input name="token" type="hidden" value={invite.token} />
              <AcceptButton disabled={!isActive} />
            </form>
          )}
        </div>
      )}
    </section>
  );
}
