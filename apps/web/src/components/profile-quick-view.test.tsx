import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { clearProfileCache } from "../lib/profiles";
import type { UniversalProfile, WorkspaceProfileMembership } from "../lib/profiles.types";
import { ProfileQuickViewDrawer } from "./profile-quick-view";

const profile: UniversalProfile = {
  id: "profile_01",
  user_id: "user_01",
  slug: "mira-stone",
  first_name: "Mira",
  last_name: "Stone",
  display_name: "Mira Stone",
  headline: "Artist manager and catalog strategist",
  biography: "Building release systems for independent artists.",
  avatar_url: null,
  location: "Los Angeles, CA",
  timezone: "America/Los_Angeles",
  primary_email: "mira@example.com",
  profile_status: "active",
  onboarding_status: "complete",
  links: [
    {
      id: "link_website",
      link_type: "website",
      label: "Website",
      url: "https://mirastone.example",
      username: null,
      external_id: null,
      status: "active",
      is_primary: true,
      sort_order: 0,
      metadata: {},
    },
    {
      id: "link_private",
      link_type: "internal_notes",
      label: "Internal notes",
      url: "https://internal.example",
      username: null,
      external_id: null,
      status: "active",
      is_primary: false,
      sort_order: 1,
      metadata: {},
    },
  ],
  attributes: [
    {
      id: "attribute_01",
      attribute_type: "career_stage",
      label: "Career stage",
      value: "Developing roster lead",
      source: "artist_profile",
      is_primary: true,
      sort_order: 0,
      metadata: {},
    },
  ],
  preferences: {
    locale: "en-US",
    timezone: "America/Los_Angeles",
    default_workspace_id: "workspace_01",
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
  profile_completion: {
    ruleset: "manager",
    is_complete: true,
    percent: 100,
    completed_fields: ["Display name"],
    missing_fields: [],
    guidance: null,
    is_blocking: false,
  },
};

const membership: WorkspaceProfileMembership = {
  id: "membership_01",
  workspace_id: "workspace_01",
  profile,
  status: "active",
  joined_at: "2026-08-24T12:00:00+00:00",
  role: "admin",
  professional_roles: ["Artist Manager"],
  department_access: ["A&R", "Marketing"],
  workspace_roles: ["Workspace Admin"],
  capability_permissions: ["profile.edit"],
};

describe("ProfileQuickViewDrawer", () => {
  beforeEach(() => {
    clearProfileCache();
    vi.stubGlobal("fetch", vi.fn());
  });

  it("renders workspace-scoped profile details without exposing non-public links", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json(membership));

    render(
      <ProfileQuickViewDrawer
        isOpen
        onClose={vi.fn()}
        profileId="profile_01"
        workspaceId="workspace_01"
      />,
    );

    expect(await screen.findByRole("heading", { name: "Mira Stone" })).toBeInTheDocument();
    expect(screen.getByText("Artist manager and catalog strategist")).toBeInTheDocument();
    expect(screen.getByText("Artist Manager")).toBeInTheDocument();
    expect(screen.getByText("Workspace Admin")).toBeInTheDocument();
    expect(screen.getByText("A&R")).toBeInTheDocument();
    expect(screen.getByText("Career stage")).toBeInTheDocument();
    expect(screen.getByText("Developing roster lead")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Website/i })).toHaveAttribute(
      "href",
      "https://mirastone.example",
    );
    expect(screen.queryByText("Internal notes")).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "/api/profiles/workspaces/workspace_01/profiles/profile_01",
      expect.any(Object),
    );
  });

  it("shows a capability-aware access message when detail is denied", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ detail: "No access" }, { status: 403 }));

    render(
      <ProfileQuickViewDrawer
        isOpen
        onClose={vi.fn()}
        profileId="profile_01"
        workspaceId="workspace_01"
      />,
    );

    expect(
      await screen.findByText(
        "You do not have access to view this profile in the current workspace.",
      ),
    ).toBeInTheDocument();
  });

  it("closes from the drawer close control", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    vi.mocked(fetch).mockResolvedValue(Response.json(membership));

    render(
      <ProfileQuickViewDrawer
        isOpen
        onClose={onClose}
        profileId="profile_01"
        workspaceId="workspace_01"
      />,
    );

    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Close profile" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
