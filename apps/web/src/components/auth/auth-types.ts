export type AuthUser = {
  id?: string;
  name?: string | null;
  firstName?: string | null;
  lastName?: string | null;
  email?: string | null;
  imageUrl?: string | null;
  role?: string | null;
  organization?: string | null;
  status?: "online" | "away" | "offline";
};

export type AuthUiState = {
  user: AuthUser | null;
  isAuthenticated: boolean;
  isLoading?: boolean;
};

export type AuthActions = {
  onSignIn: () => void;
  onSignOut: () => void;
  onSettings?: () => void;
  onTheme?: () => void;
  onKeyboardShortcuts?: () => void;
};
