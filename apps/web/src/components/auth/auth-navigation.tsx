"use client";

import { AuthUiProvider, useAuthUi } from "./auth-ui-context";
import { SignInButton, SignedInUserSummary, UserAccountMenu } from "./auth-components";
import type { AuthUiState } from "./auth-types";

function submitPost(url: string) {
  const form = document.createElement("form");
  form.action = url;
  form.method = "post";
  form.style.display = "none";
  document.body.appendChild(form);
  form.submit();
}

function AuthNavigationContent() {
  const {
    isAuthenticated,
    isLoading,
    onKeyboardShortcuts,
    onSettings,
    onSignIn,
    onSignOut,
    onTheme,
    user,
  } = useAuthUi();

  return (
    <div className="flex h-14 min-w-[18rem] items-center justify-end">
      <div className="grid w-full justify-items-end [grid-template-areas:'stack']">
        <div
          aria-hidden={isAuthenticated || isLoading}
          className="transition duration-300 ease-out [grid-area:stack] data-[visible=false]:pointer-events-none data-[visible=false]:translate-y-1 data-[visible=false]:scale-[0.98] data-[visible=false]:opacity-0"
          data-visible={!isAuthenticated && !isLoading}
        >
          <SignInButton disabled={isLoading} isLoading={isLoading} onClick={onSignIn} />
        </div>
        <div
          aria-hidden={!isAuthenticated}
          className="flex items-center gap-3 transition duration-300 ease-out [grid-area:stack] data-[visible=false]:pointer-events-none data-[visible=false]:translate-y-1 data-[visible=false]:scale-[0.98] data-[visible=false]:opacity-0"
          data-visible={isAuthenticated}
        >
          <SignedInUserSummary className="hidden sm:grid" user={user} />
          <UserAccountMenu
            onKeyboardShortcuts={onKeyboardShortcuts}
            onSettings={onSettings}
            onSignIn={onSignIn}
            onSignOut={onSignOut}
            onTheme={onTheme}
            user={user}
          />
        </div>
      </div>
    </div>
  );
}

export type AuthNavigationProps = AuthUiState & {
  loginPath?: string;
  logoutPath?: string;
};

export function AuthNavigation({
  loginPath = "/api/auth/login",
  logoutPath = "/api/auth/logout",
  ...state
}: AuthNavigationProps) {
  return (
    <AuthUiProvider
      {...state}
      onKeyboardShortcuts={() => undefined}
      onSettings={() => undefined}
      onSignIn={() => window.location.assign(loginPath)}
      onSignOut={() => submitPost(logoutPath)}
      onTheme={() => undefined}
    >
      <AuthNavigationContent />
    </AuthUiProvider>
  );
}
