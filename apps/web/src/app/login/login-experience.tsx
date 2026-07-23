"use client";

import {
  AuthenticationErrorState,
  UnauthenticatedState,
} from "../../components/auth/auth-components";
import { StatusIndicator } from "../../components/status-indicator";

export type LoginExperienceProps = {
  hasAuthError: boolean;
};

export function LoginExperience({ hasAuthError }: LoginExperienceProps) {
  return (
    <div className="mx-auto flex min-h-[calc(100vh-5rem)] max-w-5xl flex-col justify-center gap-6">
      {hasAuthError ? (
        <AuthenticationErrorState
          headline="We could not complete sign-in"
          onRetry={() => {
            window.location.assign("/api/auth/login");
          }}
          onReturnHome={() => {
            window.location.assign("/");
          }}
          supportingText="WorkOS AuthKit returned an error before a secure Label OS session could be established."
        />
      ) : null}
      <UnauthenticatedState
        onSignIn={() => {
          window.location.assign("/api/auth/login");
        }}
      />
      <div className="rounded-[24px] border border-white/65 bg-white/55 p-4 shadow-[0_16px_50px_rgba(15,23,42,0.08)] backdrop-blur-2xl">
        <StatusIndicator />
      </div>
    </div>
  );
}
