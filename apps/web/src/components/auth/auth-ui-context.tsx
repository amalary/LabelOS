"use client";

import { createContext, type ReactNode, useContext } from "react";

import type { AuthActions, AuthUiState } from "./auth-types";

type AuthUiContextValue = AuthUiState & AuthActions;

const AuthUiContext = createContext<AuthUiContextValue | null>(null);

export type AuthUiProviderProps = AuthUiContextValue & {
  children: ReactNode;
};

export function AuthUiProvider({ children, ...value }: AuthUiProviderProps) {
  return <AuthUiContext.Provider value={value}>{children}</AuthUiContext.Provider>;
}

export function useAuthUi() {
  const value = useContext(AuthUiContext);

  if (!value) {
    throw new Error("useAuthUi must be used within AuthUiProvider");
  }

  return value;
}
