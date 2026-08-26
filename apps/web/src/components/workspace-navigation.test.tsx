import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { clearProfileCache } from "../lib/profiles";
import type { UniversalProfile, WorkspaceProfileMembership } from "../lib/profiles.types";
import { ActiveWorkspaceProvider } from "../lib/workspace-context";
import type { OrganizationSelection } from "../lib/organizations";
import { WorkspaceNavigation } from "./workspace-navigation";

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
}));

const profile: UniversalProfile = {
  id: "profile_01",
  user_id: "user_01",
  slug: "mira-stone",
  first_name: "Mira",
  last_name: "Stone",
  display_name: "Mira Stone",
  headline: null,
  biography: null,
  avatar_url: null,
  location: null,
  timezone: "America/Los_Angeles",
  primary_email: "mira@example.com",
  profile_status: "active",
  onboarding_status: "complete",
  links: [],
  attributes: [],
  preferences: {
    locale: "en-US",
    timezone: "America/Los_Angeles",
    default_workspace_id: "workspace_member",
    email_notifications_enabled: true,
    push_notifications_enabled: true,
    sms_notifications_enabled: false,
    marketing_notifications_enabled: false,
    interface_theme: null,
    interface_density: null,
    notification_preferences: {},
    interface_preferences: {},
    integration_preferences: {},
  },
};

function selection(activeId: string): OrganizationSelection {
  const organizations = [
    {
      id: "workspace_member",
      name: "Member Workspace",
      slug: "member-workspace",
      role: "member" as const,
      can_switch: true,
    },
    {
      id: "workspace_admin",
      name: "Admin Workspace",
      slug: "admin-workspace",
      role: "member" as const,
      can_switch: true,
    },
  ];

  return {
    activeOrganization: organizations.find((organization) => organization.id === activeId) ?? null,
    organizations,
  };
}

function membership(
  workspaceId: string,
  capability_permissions: string[],
  department_access: string[] = [],
): WorkspaceProfileMembership {
  return {
    id: `${workspaceId}_membership`,
    workspace_id: workspaceId,
    profile,
    status: "active",
    joined_at: "2026-08-24T12:00:00+00:00",
    role: "member",
    professional_roles: [],
    department_access,
    workspace_roles: [],
    capability_permissions,
  };
}

describe("WorkspaceNavigation", () => {
  beforeEach(() => {
    clearProfileCache();
    vi.stubGlobal("fetch", vi.fn());
  });

  it("updates available navigation when the active workspace role context changes", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json(profile))
      .mockResolvedValueOnce(
        Response.json(membership("workspace_member", ["artist.view"], ["artist"])),
      )
      .mockResolvedValueOnce(
        Response.json(
          membership(
            "workspace_admin",
            ["workspace.manage", "member.invite", "role.assign"],
            ["administration"],
          ),
        ),
      );
    let currentSelection = selection("workspace_member");

    const { rerender } = render(
      <ActiveWorkspaceProvider selection={currentSelection}>
        <WorkspaceNavigation />
      </ActiveWorkspaceProvider>,
    );

    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Profile" })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "Artist Profile" })).toHaveAttribute(
        "href",
        "/artists",
      ),
    );
    await waitFor(() =>
      expect(screen.queryByRole("link", { name: "Workspace Settings" })).not.toBeInTheDocument(),
    );

    currentSelection = selection("workspace_admin");
    rerender(
      <ActiveWorkspaceProvider selection={currentSelection}>
        <WorkspaceNavigation />
      </ActiveWorkspaceProvider>,
    );

    await waitFor(() =>
      expect(screen.getByRole("link", { name: "Workspace Settings" })).toHaveAttribute(
        "href",
        "/workspace/settings",
      ),
    );
    expect(screen.getByRole("link", { name: "Member Management" })).toHaveAttribute(
      "href",
      "/workspace/members",
    );
    expect(screen.getByRole("link", { name: "Roles" })).toHaveAttribute("href", "/workspace/roles");
  });
});
