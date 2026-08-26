import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OrganizationSwitcher } from "./organization-switcher";

vi.mock("../app/dashboard/actions", () => ({
  switchOrganization: vi.fn(async () => ({ error: null })),
}));

describe("OrganizationSwitcher", () => {
  it("renders the active organization without exposing internal ids in visible labels", async () => {
    const user = userEvent.setup();

    render(
      <OrganizationSwitcher
        activeOrganization={{
          id: "org-a",
          name: "Alpha Label",
          slug: "alpha-label",
          role: "owner",
          can_switch: true,
        }}
        organizations={[
          {
            id: "org-a",
            name: "Alpha Label",
            slug: "alpha-label",
            role: "owner",
            can_switch: true,
          },
          {
            id: "org-b",
            name: "Beta Label",
            slug: "beta-label",
            role: "member",
            can_switch: true,
          },
        ]}
      />,
    );

    expect(
      screen.getByRole("button", { name: /active workspace alpha label/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText("org-a")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /active workspace alpha label/i }));

    expect(screen.getByRole("listbox", { name: /alpha label/i })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /beta label/i })).toBeInTheDocument();
    expect(screen.queryByText("org-b")).not.toBeInTheDocument();
  });

  it("shows organization logos when available and initials when missing", async () => {
    const user = userEvent.setup();

    render(
      <OrganizationSwitcher
        activeOrganization={{
          id: "org-a",
          name: "Alpha Label",
          logoUrl: "https://cdn.example.test/alpha.png",
          slug: "alpha-label",
          role: "owner",
          can_switch: true,
        }}
        organizations={[
          {
            id: "org-a",
            name: "Alpha Label",
            logoUrl: "https://cdn.example.test/alpha.png",
            slug: "alpha-label",
            role: "owner",
            can_switch: true,
          },
          {
            id: "org-b",
            name: "Beta Label",
            slug: "beta-label",
            role: "member",
            can_switch: true,
          },
        ]}
      />,
    );

    expect(screen.getByRole("img", { name: "Alpha Label logo" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /active workspace alpha label/i }));

    expect(screen.getByText("BL")).toBeInTheDocument();
  });

  it("clears organization-scoped session cache before switching", async () => {
    const user = userEvent.setup();
    sessionStorage.setItem("labelos:artists:org-a", "cached");

    render(
      <OrganizationSwitcher
        activeOrganization={{
          id: "org-a",
          name: "Alpha Label",
          slug: "alpha-label",
          role: "owner",
          can_switch: true,
        }}
        organizations={[
          {
            id: "org-a",
            name: "Alpha Label",
            slug: "alpha-label",
            role: "owner",
            can_switch: true,
          },
          {
            id: "org-b",
            name: "Beta Label",
            slug: "beta-label",
            role: "member",
            can_switch: true,
          },
        ]}
      />,
    );

    await user.click(screen.getByRole("button", { name: /active workspace alpha label/i }));
    await user.click(screen.getByRole("option", { name: /beta label/i }));

    expect(sessionStorage.getItem("labelos:artists:org-a")).toBeNull();
  });

  it("does not switch or clear caches for the current workspace", async () => {
    const user = userEvent.setup();
    sessionStorage.setItem("labelos:artists:org-a", "cached");

    render(
      <OrganizationSwitcher
        activeOrganization={{
          id: "org-a",
          name: "Alpha Label",
          slug: "alpha-label",
          role: "owner",
          can_switch: true,
        }}
        organizations={[
          {
            id: "org-a",
            name: "Alpha Label",
            slug: "alpha-label",
            role: "owner",
            can_switch: true,
          },
          {
            id: "org-b",
            name: "Beta Label",
            slug: "beta-label",
            role: "member",
            can_switch: true,
          },
        ]}
      />,
    );

    await user.click(screen.getByRole("button", { name: /active workspace alpha label/i }));
    await user.click(screen.getByRole("option", { name: /alpha label/i }));

    expect(sessionStorage.getItem("labelos:artists:org-a")).toBe("cached");
  });

  it("does not switch to a workspace marked unavailable", async () => {
    const user = userEvent.setup();
    sessionStorage.setItem("labelos:artists:org-a", "cached");

    render(
      <OrganizationSwitcher
        activeOrganization={{
          id: "org-a",
          name: "Alpha Label",
          slug: "alpha-label",
          role: "owner",
          can_switch: true,
        }}
        organizations={[
          {
            id: "org-a",
            name: "Alpha Label",
            slug: "alpha-label",
            role: "owner",
            can_switch: true,
          },
          {
            id: "org-b",
            name: "Beta Label",
            slug: "beta-label",
            role: "member",
            can_switch: false,
          },
        ]}
      />,
    );

    await user.click(screen.getByRole("button", { name: /active workspace alpha label/i }));
    const unavailableWorkspace = screen.getByRole("option", { name: /beta label/i });

    expect(unavailableWorkspace).toHaveAttribute("aria-disabled", "true");

    await user.click(unavailableWorkspace);

    expect(sessionStorage.getItem("labelos:artists:org-a")).toBe("cached");
  });

  it("supports keyboard navigation through workspace options", async () => {
    const user = userEvent.setup();

    render(
      <OrganizationSwitcher
        activeOrganization={{
          id: "org-a",
          name: "Alpha Label",
          slug: "alpha-label",
          role: "owner",
          can_switch: true,
        }}
        organizations={[
          {
            id: "org-a",
            name: "Alpha Label",
            slug: "alpha-label",
            role: "owner",
            can_switch: true,
          },
          {
            id: "org-b",
            name: "Beta Label With An Extremely Long Workspace Name",
            slug: "beta-label",
            role: "member",
            can_switch: true,
          },
        ]}
      />,
    );

    screen.getByRole("button", { name: /active workspace alpha label/i }).focus();
    await user.keyboard("{ArrowDown}");

    expect(screen.getByRole("listbox")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /alpha label/i })).toHaveFocus();

    await user.keyboard("{ArrowDown}");

    expect(screen.getByRole("option", { name: /beta label/i })).toHaveFocus();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /active workspace alpha label/i })).toHaveFocus();
  });

  it("renders loading, empty, and error states", () => {
    const { rerender } = render(
      <OrganizationSwitcher activeOrganization={null} isLoading organizations={[]} />,
    );

    expect(screen.getByRole("status", { name: "Loading workspaces" })).toBeInTheDocument();

    rerender(<OrganizationSwitcher activeOrganization={null} organizations={[]} />);

    expect(screen.getByRole("status", { name: "No workspaces available" })).toHaveTextContent(
      "No workspaces",
    );

    rerender(
      <OrganizationSwitcher
        activeOrganization={null}
        error="Workspaces unavailable"
        organizations={[
          {
            id: "org-a",
            name: "Alpha Label",
            slug: "alpha-label",
            role: "owner",
            can_switch: true,
          },
        ]}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Workspaces unavailable");
    expect(screen.getByRole("status")).toHaveTextContent("Select a workspace");
  });
});
