import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { clearProfileCache } from "../../../lib/profiles";
import type {
  ArtistProfileDetail,
  UniversalProfile,
  WorkspaceProfileMembership,
} from "../../../lib/profiles.types";
import { ActiveWorkspaceProvider } from "../../../lib/workspace-context";
import { ArtistProfileEditor } from "./artist-profile-editor";

vi.mock("../../../components/analytics/analytics-read-surface", () => ({
  AnalyticsReadSurface: ({
    artistProfileId,
    title,
    workspaceId,
  }: {
    artistProfileId: string;
    title: string;
    workspaceId: string;
  }) => (
    <section
      aria-label={title}
      data-artist-profile-id={artistProfileId}
      data-workspace-id={workspaceId}
    >
      {title}
    </section>
  ),
}));

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
};

const baseMembership: WorkspaceProfileMembership = {
  id: "membership_01",
  workspace_id: "workspace_01",
  profile,
  status: "active",
  joined_at: "2026-08-24T12:00:00+00:00",
  role: "member",
  professional_roles: ["Artist Manager"],
  department_access: [],
  workspace_roles: [],
  capability_permissions: [],
};

const artistProfile: ArtistProfileDetail = {
  id: "artist_profile_01",
  artist_id: "artist_01",
  workspace_id: "workspace_01",
  universal_profile_id: "profile_01",
  artist_name: "Mira Stone",
  stage_name: "Mira",
  genres: ["Alternative"],
  influences: ["Downtown scenes"],
  imagery: {},
  dsp_links: {},
  catalog_references: [],
  creative_metadata: {},
  career_stage: "Emerging",
  audience: {},
  preferences: {},
};

function renderArtistProfileEditor() {
  return render(
    <ActiveWorkspaceProvider
      selection={{
        activeOrganization: {
          id: "workspace_01",
          name: "Northstar Audio",
          slug: "northstar-audio",
          role: "member",
          can_switch: true,
        },
        organizations: [],
      }}
    >
      <ArtistProfileEditor artistProfileId="artist_profile_01" />
    </ActiveWorkspaceProvider>,
  );
}

describe("ArtistProfileEditor", () => {
  let membership: WorkspaceProfileMembership;

  beforeEach(() => {
    clearProfileCache();
    membership = { ...baseMembership, capability_permissions: [], department_access: [] };
    vi.stubGlobal(
      "fetch",
      vi.fn((url) => {
        if (url === "/api/profiles/me") {
          return Promise.resolve(Response.json(profile));
        }
        if (url === "/api/profiles/workspaces/workspace_01/profiles/profile_01") {
          return Promise.resolve(Response.json(membership));
        }
        if (url === "/api/profiles/workspaces/workspace_01/artist-profiles/artist_profile_01") {
          return Promise.resolve(Response.json(artistProfile));
        }
        return Promise.resolve(Response.json({}, { status: 404 }));
      }),
    );
  });

  it("disables artist profile editing without artist profile edit capability", async () => {
    renderArtistProfileEditor();

    expect(await screen.findByRole("heading", { name: "Mira Stone" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Artist stage name")).toBeDisabled();
    expect(screen.getByPlaceholderText("Emerging, developing, established")).toBeDisabled();
    expect(screen.getByPlaceholderText("Pop, R&B, Alternative")).toBeDisabled();
    expect(
      screen.getByPlaceholderText("Reference artists, scenes, or creative influences"),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save artist profile" })).toBeDisabled();
    expect(
      screen.getByText("Analytics are unavailable without analytics view access."),
    ).toBeInTheDocument();
  });

  it("mounts artist analytics when the workspace subject has analytics view capability", async () => {
    membership = {
      ...baseMembership,
      capability_permissions: ["analytics.view"],
      department_access: ["analytics"],
    };

    renderArtistProfileEditor();

    expect(await screen.findByRole("heading", { name: "Mira Stone" })).toBeInTheDocument();
    const analyticsSurface = screen.getByRole("region", { name: "Artist analytics" });
    expect(analyticsSurface).toHaveAttribute("data-artist-profile-id", "artist_profile_01");
    expect(analyticsSurface).toHaveAttribute("data-workspace-id", "workspace_01");
  });
});
