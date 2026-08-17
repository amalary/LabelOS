import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DashboardShellHeader, dashboardGreeting } from "./dashboard-shell-header";

const activeOrganization = {
  id: "local_org_01LABEL",
  name: "Northstar Audio",
  slug: "northstar-audio",
  role: "owner" as const,
  can_switch: true,
};

describe("DashboardShellHeader", () => {
  it("renders organization context and dashboard controls without sensitive values", () => {
    render(
      <DashboardShellHeader
        activeOrganization={activeOrganization}
        authNavigation={<button type="button">Account</button>}
        organizationSwitcher={<button type="button">Northstar Audio workspace</button>}
        realtimeStatus={<span>Realtime connected</span>}
        user={{
          email: "mara@example.com",
          firstName: "Mara",
          name: "Mara Chen",
          organization: "org_01SECRET",
        }}
      />,
    );

    expect(screen.getByRole("heading", { name: /good/i })).toHaveTextContent(/Mara/);
    expect(screen.getByText("Northstar Audio")).toBeInTheDocument();
    expect(screen.getByText("Here's what's happening across Northstar Audio.")).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open notifications" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Account" })).toBeInTheDocument();
    expect(screen.queryByText("org_01SECRET")).not.toBeInTheDocument();
  });

  it("supports neutral copy when no workspace is active", () => {
    render(
      <DashboardShellHeader
        activeOrganization={null}
        authNavigation={<button type="button">Account</button>}
        organizationSwitcher={<span>No workspaces</span>}
        user={null}
      />,
    );

    expect(screen.getByText("Label operations dashboard")).toBeInTheDocument();
    expect(screen.getByText("Choose a workspace to see label operations.")).toBeInTheDocument();
  });

  it("formats time-appropriate greetings from safe user display fields", () => {
    expect(dashboardGreeting(new Date("2026-08-12T08:00:00"), { firstName: "Mara" })).toBe(
      "Good morning, Mara",
    );
    expect(dashboardGreeting(new Date("2026-08-12T14:00:00"), { name: "Avery Stone" })).toBe(
      "Good afternoon, Avery",
    );
    expect(dashboardGreeting(new Date("2026-08-12T19:00:00"), null)).toBe("Good evening");
  });
});
