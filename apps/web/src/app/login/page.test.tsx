import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LoginPage from "./page";

describe("LoginPage", () => {
  it("renders the login form without enabling external auth calls", () => {
    render(<LoginPage />);

    expect(screen.getByRole("heading", { level: 1, name: "Login" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Continue with SSO" })).toHaveAttribute(
      "href",
      "/api/auth/login",
    );
    expect(screen.getByText("API URL: not configured")).toBeInTheDocument();
  });
});
