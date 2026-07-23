import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LoginPage from "./page";

describe("LoginPage", () => {
  it("renders the login form without enabling external auth calls", async () => {
    render(await LoginPage({}));

    expect(screen.getByRole("heading", { level: 1, name: "Login" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Continue with WorkOS" })).toHaveAttribute(
      "href",
      "/api/auth/login",
    );
    expect(screen.getByText("API URL: not configured")).toBeInTheDocument();
  });

  it("shows a safe message after authentication errors", async () => {
    render(
      await LoginPage({
        searchParams: Promise.resolve({ auth_error: "sign_in_failed" }),
      }),
    );

    expect(
      screen.getByText("We could not complete sign-in. Please try again."),
    ).toBeInTheDocument();
  });
});
