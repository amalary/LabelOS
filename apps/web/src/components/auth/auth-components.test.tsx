import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  AuthenticationErrorState,
  AuthenticationLoadingState,
  SignInButton,
  SignOutButton,
  SignedInUserSummary,
  UnauthenticatedState,
  UserAccountMenu,
} from "./auth-components";

const fullUser = {
  email: "mara@example.com",
  imageUrl: "https://example.com/mara.png",
  name: "Mara Chen",
  organization: "Northstar Audio",
  role: "Admin",
  status: "online" as const,
};

describe("authentication components", () => {
  it("renders sign in and sign out controls with loading and disabled states", async () => {
    const user = userEvent.setup();
    const onSignIn = vi.fn();
    const onSignOut = vi.fn();

    render(
      <div>
        <SignInButton onClick={onSignIn} />
        <SignOutButton disabled onClick={onSignOut} />
        <SignInButton isLoading />
      </div>,
    );

    await user.click(screen.getByRole("button", { name: "Sign In" }));

    expect(onSignIn).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Sign Out" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Signing In" })).toBeDisabled();
  });

  it("renders a signed-in summary and handles missing profile fields", () => {
    render(
      <div>
        <SignedInUserSummary user={fullUser} />
        <SignedInUserSummary user={{ email: "unnamed@example.com" }} />
      </div>,
    );

    expect(screen.getByText("Mara Chen")).toBeInTheDocument();
    expect(screen.getByText("Admin · Northstar Audio")).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: "online status" })).toHaveLength(2);
    expect(screen.getByText("User")).toBeInTheDocument();
    expect(screen.getByText("Member · Personal Workspace")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "User profile" })).toHaveTextContent("U");
  });

  it("opens and closes the account menu with click outside and Escape", async () => {
    const user = userEvent.setup();
    const onSignOut = vi.fn();

    render(
      <div>
        <UserAccountMenu onSignIn={vi.fn()} onSignOut={onSignOut} user={fullUser} />
        <button type="button">Outside</button>
      </div>,
    );

    await user.click(screen.getByRole("button", { name: "Open account menu" }));

    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /Settings/ })).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open account menu" })).toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Open account menu" }));
    await user.click(screen.getByRole("button", { name: "Outside" }));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("supports arrow navigation, tab trapping, and enter selection in the account menu", async () => {
    const user = userEvent.setup();
    const onTheme = vi.fn();
    const onSignOut = vi.fn();

    render(
      <UserAccountMenu
        onSignIn={vi.fn()}
        onSignOut={onSignOut}
        onTheme={onTheme}
        user={fullUser}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Open account menu" }));
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: /Theme/ })).toHaveFocus();

    await user.keyboard("{Enter}");
    expect(onTheme).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open account menu" }));
    await user.keyboard("{ArrowUp}");
    expect(screen.getByRole("menuitem", { name: /Sign Out/ })).toHaveFocus();

    await user.tab();
    expect(screen.getByRole("menuitem", { name: /Settings/ })).toHaveFocus();
  });

  it("renders loading, error, and unauthenticated states", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const onHome = vi.fn();
    const onSignIn = vi.fn();

    render(
      <div>
        <AuthenticationLoadingState />
        <AuthenticationErrorState onRetry={onRetry} onReturnHome={onHome} />
        <UnauthenticatedState onSignIn={onSignIn} showIllustration={false} />
      </div>,
    );

    expect(screen.getByRole("status", { name: "Loading authentication" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Authentication needs attention" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Welcome to your labeling workspace" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));
    await user.click(screen.getByRole("button", { name: "Return Home" }));
    await user.click(
      within(screen.getByText("Label OS").closest("section")!).getByRole("button", {
        name: "Sign In",
      }),
    );

    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(onHome).toHaveBeenCalledTimes(1);
    expect(onSignIn).toHaveBeenCalledTimes(1);
  });
});
