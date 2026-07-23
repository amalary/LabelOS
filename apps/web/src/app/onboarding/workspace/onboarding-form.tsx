"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { onboardWorkspace, type WorkspaceOnboardingState } from "./actions";

const initialState: WorkspaceOnboardingState = {
  error: null,
};

function SubmitButton() {
  const { pending } = useFormStatus();

  return (
    <button
      className="inline-flex h-11 items-center justify-center rounded-md bg-slate-950 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
      disabled={pending}
      type="submit"
    >
      {pending ? "Creating workspace..." : "Create workspace"}
    </button>
  );
}

export function WorkspaceOnboardingForm() {
  const [state, formAction] = useActionState(onboardWorkspace, initialState);

  return (
    <form action={formAction} className="mt-6 flex flex-col gap-4">
      <label className="flex flex-col gap-2 text-sm font-medium text-slate-800">
        Label or company name
        <input
          autoComplete="organization"
          className="h-11 rounded-md border border-slate-300 bg-white px-3 text-base text-slate-950 outline-none transition placeholder:text-slate-400 focus:border-sky-500 focus:ring-2 focus:ring-sky-100"
          maxLength={120}
          name="organizationName"
          placeholder="Example Records"
          required
        />
      </label>
      {state.error ? (
        <div
          aria-live="polite"
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-900"
          role="alert"
        >
          {state.error}
        </div>
      ) : null}
      <div>
        <SubmitButton />
      </div>
    </form>
  );
}
