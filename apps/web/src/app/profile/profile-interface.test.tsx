import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { clearProfileCache } from "../../lib/profiles";
import type { UniversalProfile, WorkspaceProfileMembership } from "../../lib/profiles.types";
import { ActiveWorkspaceProvider } from "../../lib/workspace-context";
import { UniversalProfileInterface } from "./profile-interface";

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
      id: "link_spotify",
      link_type: "spotify",
      label: "Spotify",
      url: "https://open.spotify.com/artist/mira",
      username: "mira",
      external_id: null,
      status: "active",
      is_primary: false,
      sort_order: 1,
      metadata: {},
    },
  ],
  attributes: [],
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
    completed_fields: ["Display name", "Professional headline", "Contact or website link"],
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
  capability_permissions: ["profiles.write"],
};

function renderProfileInterface() {
  return render(
    <ActiveWorkspaceProvider
      selection={{
        activeOrganization: {
          id: "workspace_01",
          name: "Northstar Audio",
          slug: "northstar-audio",
          role: "owner",
          can_switch: true,
        },
        organizations: [],
      }}
    >
      <UniversalProfileInterface />
    </ActiveWorkspaceProvider>,
  );
}

describe("UniversalProfileInterface", () => {
  beforeEach(() => {
    clearProfileCache();
    vi.stubGlobal("fetch", vi.fn());
  });

  it("renders universal profile identity, workspace context, and supported links", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json(profile))
      .mockResolvedValueOnce(Response.json(membership));

    renderProfileInterface();

    expect(await screen.findByRole("heading", { name: "Mira Stone" })).toBeInTheDocument();
    expect(screen.getByText("Artist manager and catalog strategist")).toBeInTheDocument();
    expect(screen.getByText("Building release systems for independent artists.")).toBeInTheDocument();
    expect(screen.getByText("Los Angeles, CA")).toBeInTheDocument();
    expect(screen.getByText("Artist Manager")).toBeInTheDocument();
    expect(screen.getByText("Workspace Admin")).toBeInTheDocument();
    expect(screen.getByText("A&R")).toBeInTheDocument();
    expect(screen.getByText("Marketing")).toBeInTheDocument();
    expect(screen.getByText("Northstar Audio")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Website/i })).toHaveAttribute(
      "href",
      "https://mirastone.example",
    );
    expect(screen.getByRole("link", { name: /Spotify/i })).toHaveAttribute(
      "href",
      "https://open.spotify.com/artist/mira",
    );
    expect(screen.queryByText("Add your professional information")).not.toBeInTheDocument();
  });

  it("shows advisory completion guidance when important profile details are missing", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        Response.json({
          ...profile,
          profile_completion: {
            ruleset: "manager",
            is_complete: false,
            percent: 67,
            completed_fields: ["Display name", "Professional headline"],
            missing_fields: ["Contact or website link"],
            guidance: "Add your professional information",
            is_blocking: false,
          },
        }),
      )
      .mockResolvedValueOnce(Response.json(membership));

    renderProfileInterface();

    expect(await screen.findByText("Add your professional information")).toBeInTheDocument();
    expect(screen.getByText("Missing: Contact or website link")).toBeInTheDocument();
    expect(screen.getByText("67% complete")).toBeInTheDocument();
  });

  it("lets the profile owner edit core fields and supported links", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json(profile))
      .mockResolvedValueOnce(Response.json(membership))
      .mockResolvedValueOnce(Response.json({ ...profile, display_name: "Mira S." }))
      .mockResolvedValueOnce(Response.json(membership));

    renderProfileInterface();

    await screen.findByRole("heading", { name: "Mira Stone" });
    await user.click(screen.getByRole("button", { name: "Edit Profile" }));
    await user.clear(screen.getByLabelText("Display name"));
    await user.type(screen.getByLabelText("Display name"), "Mira S.");
    await user.clear(screen.getByLabelText("GitHub"));
    await user.type(screen.getByLabelText("GitHub"), "github.com/mirastone");

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Save" }));
    });

    await waitFor(() => expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument());
    const patchCall = vi.mocked(fetch).mock.calls.find(([url, init]) => {
      return url === "/api/profiles/me" && init?.method === "PATCH";
    });
    expect(patchCall).toBeDefined();
    expect(JSON.parse(String(patchCall?.[1]?.body))).toMatchObject({
      display_name: "Mira S.",
      links: expect.arrayContaining([
        expect.objectContaining({
          link_type: "github",
          url: "https://github.com/mirastone",
        }),
      ]),
    });
  });
});
