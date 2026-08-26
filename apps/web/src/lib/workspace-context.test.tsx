import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ActiveWorkspaceProvider,
  useActiveWorkspaceProfile,
  toWorkspaceSelection,
  useActiveWorkspace,
} from "./workspace-context";
import type { OrganizationSelection } from "./organizations";
import { clearProfileCache } from "./profiles";
import type { UniversalProfile, WorkspaceProfileMembership } from "./profiles.types";

const selection: OrganizationSelection = {
  activeOrganization: {
    id: "local_org_01LABEL",
    name: "Northstar Audio",
    slug: "northstar-audio",
    role: "owner",
    can_switch: true,
  },
  organizations: [
    {
      id: "local_org_01LABEL",
      name: "Northstar Audio",
      slug: "northstar-audio",
      role: "owner",
      can_switch: true,
    },
    {
      id: "local_org_02LABEL",
      name: "Backup Label",
      slug: "backup-label",
      role: "member",
      can_switch: true,
    },
  ],
};

const profile: UniversalProfile = {
  id: "profile_01",
  user_id: "user_01",
  slug: "mira-stone",
  first_name: "Mira",
  last_name: "Stone",
  display_name: "Mira Stone",
  headline: "Artist manager",
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
    default_workspace_id: "local_org_01LABEL",
    email_notifications_enabled: true,
    push_notifications_enabled: true,
    sms_notifications_enabled: false,
    marketing_notifications_enabled: false,
    interface_theme: "system",
    interface_density: "comfortable",
    notification_preferences: {},
    interface_preferences: {},
    integration_preferences: {},
  },
};

function workspaceMembership(
  workspaceId: string,
  overrides: Partial<WorkspaceProfileMembership>,
): WorkspaceProfileMembership {
  return {
    id: `${workspaceId}_membership`,
    workspace_id: workspaceId,
    profile,
    status: "active",
    joined_at: "2026-08-24T12:00:00+00:00",
    role: "member",
    professional_roles: [],
    department_access: [],
    workspace_roles: [],
    capability_permissions: [],
    ...overrides,
  };
}

describe("workspace context", () => {
  beforeEach(() => {
    clearProfileCache();
    vi.stubGlobal("fetch", vi.fn());
  });

  it("maps WorkOS-backed organizations into LabelOS workspaces", () => {
    expect(toWorkspaceSelection(selection)).toEqual({
      activeWorkspace: selection.activeOrganization,
      workspaces: selection.organizations,
    });
  });

  it("exposes the active workspace to client components", () => {
    const { result } = renderHook(() => useActiveWorkspace(), {
      wrapper: ({ children }) => (
        <ActiveWorkspaceProvider selection={selection}>{children}</ActiveWorkspaceProvider>
      ),
    });

    expect(result.current.activeWorkspace?.name).toBe("Northstar Audio");
    expect(result.current.workspaces).toHaveLength(2);
    expect(result.current.hasActiveWorkspace).toBe(true);
  });

  it("resolves roles, departments, capabilities, and actions for the active workspace", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json(profile))
      .mockResolvedValueOnce(
        Response.json(
          workspaceMembership("local_org_01LABEL", {
            role: "member",
            professional_roles: ["Artist"],
            workspace_roles: ["artist"],
            department_access: ["creative"],
            capability_permissions: ["artist.profile.view", "profile.edit"],
          }),
        ),
      );

    const { result } = renderHook(() => useActiveWorkspaceProfile(), {
      wrapper: ({ children }) => (
        <ActiveWorkspaceProvider selection={selection}>{children}</ActiveWorkspaceProvider>
      ),
    });

    await waitFor(() => expect(result.current.roles).toEqual(["Artist", "artist", "member"]));
    expect(result.current.departmentAccess).toEqual(["creative"]);
    expect(result.current.capabilities).toEqual(["artist.profile.view", "profile.edit"]);
    expect(result.current.canEditProfile).toBe(true);
  });

  it("updates profile interpretation when the active workspace changes", async () => {
    const betaSelection: OrganizationSelection = {
      ...selection,
      activeOrganization: selection.organizations[1] ?? null,
    };
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json(profile))
      .mockResolvedValueOnce(
        Response.json(
          workspaceMembership("local_org_01LABEL", {
            role: "member",
            professional_roles: ["Artist"],
            workspace_roles: ["artist"],
            department_access: ["creative"],
            capability_permissions: ["artist.profile.view", "profile.edit"],
          }),
        ),
      )
      .mockResolvedValueOnce(
        Response.json(
          workspaceMembership("local_org_02LABEL", {
            role: "member",
            professional_roles: ["Legal"],
            workspace_roles: ["legal"],
            department_access: ["contracts"],
            capability_permissions: ["contract.view"],
          }),
        ),
      );

    let currentSelection = selection;
    const { result, rerender } = renderHook(() => useActiveWorkspaceProfile(), {
      wrapper: ({ children }) => (
        <ActiveWorkspaceProvider selection={currentSelection}>{children}</ActiveWorkspaceProvider>
      ),
    });

    await waitFor(() => expect(result.current.roles).toContain("Artist"));

    currentSelection = betaSelection;
    rerender();

    await waitFor(() => expect(result.current.roles).toEqual(["Legal", "legal", "member"]));
    expect(result.current.departmentAccess).toEqual(["contracts"]);
    expect(result.current.capabilities).toEqual(["contract.view"]);
    expect(result.current.canEditProfile).toBe(false);
  });
});
