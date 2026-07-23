import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LoginPage from "./page";

describe("LoginPage", () => {
  it("renders the WorkOS-only unauthenticated state without external auth calls", async () => {
    render(await LoginPage({}));

    expect(
      screen.getByRole("heading", { level: 1, name: "Welcome to your labeling workspace" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign In" })).toBeInTheDocument();
    expect(screen.getByText("API URL: not configured")).toBeInTheDocument();
  });

  it("shows a safe message after authentication errors", async () => {
    render(
      await LoginPage({
        searchParams: Promise.resolve({ auth_error: "sign_in_failed" }),
      }),
    );

    expect(
      screen.getByRole("heading", { name: "We could not complete sign-in" }),
    ).toBeInTheDocument();
  });
});
