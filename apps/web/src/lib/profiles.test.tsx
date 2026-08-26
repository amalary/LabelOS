import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ProfileApiError,
  clearProfileCache,
  createArtistProfile,
  getArtistProfile,
  getCurrentProfile,
  getProfile,
  getWorkspaceMembers,
  updateArtistProfile,
  updateCurrentProfile,
  useArtistProfile,
  useCurrentProfile,
  useProfileCapabilities,
  useProfileRoles,
  useCreateArtistProfile,
  useUpdateArtistProfile,
  useUpdateCurrentProfile,
} from "./profiles";
import type {
  ArtistProfileDetail,
  UniversalProfile,
  WorkspaceProfileMembership,
} from "./profiles.types";

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
  location: "Los Angeles, CA",
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

const workspaceProfile: WorkspaceProfileMembership = {
  id: "membership_01",
  workspace_id: "workspace_01",
  profile,
  status: "active",
  joined_at: "2026-08-24T12:00:00+00:00",
  role: "admin",
  professional_roles: ["Artist"],
  department_access: ["creative"],
  workspace_roles: ["manager"],
  capability_permissions: ["catalog.read", "members.manage"],
};

const artistProfile: ArtistProfileDetail = {
  id: "artist_profile_01",
  artist_id: "artist_01",
  workspace_id: "workspace_01",
  universal_profile_id: "profile_01",
  artist_name: "Mira Stone",
  stage_name: "Mira",
  genres: ["R&B", "Pop"],
  influences: ["Aaliyah"],
  imagery: {},
  dsp_links: {
    spotify: "https://open.spotify.com/artist/example",
  },
  catalog_references: [],
  creative_metadata: {},
  career_stage: "developing",
  audience: {},
  preferences: {},
};

describe("profile data layer", () => {
  beforeEach(() => {
    clearProfileCache();
    vi.stubGlobal("fetch", vi.fn());
  });

  it("fetches the current universal profile through the frontend API proxy", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json(profile));

    await expect(getCurrentProfile()).resolves.toEqual(profile);

    expect(fetch).toHaveBeenCalledWith(
      "/api/profiles/me",
      expect.objectContaining({
        cache: "no-store",
        headers: expect.any(Headers),
      }),
    );
    const headers = vi.mocked(fetch).mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("Accept")).toBe("application/json");
  });

  it("updates the current profile with JSON and returns the saved profile", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ ...profile, display_name: "Mira S." }));

    await expect(updateCurrentProfile({ display_name: "Mira S." })).resolves.toMatchObject({
      display_name: "Mira S.",
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/profiles/me",
      expect.objectContaining({
        body: JSON.stringify({ display_name: "Mira S." }),
        method: "PATCH",
      }),
    );
    const headers = vi.mocked(fetch).mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("fetches workspace members with pagination parameters", async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({ profiles: [workspaceProfile], limit: 25, offset: 50, total: 80 }),
    );

    await expect(getWorkspaceMembers("workspace_01", { limit: 25, offset: 50 })).resolves.toEqual({
      profiles: [workspaceProfile],
      limit: 25,
      offset: 50,
      total: 80,
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/profiles/workspaces/workspace_01/profiles?limit=25&offset=50",
      expect.any(Object),
    );
  });

  it("fetches a profile by ID through the frontend API proxy", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json(profile));

    await expect(getProfile("profile_01")).resolves.toEqual(profile);

    expect(fetch).toHaveBeenCalledWith("/api/profiles/profile_01", expect.any(Object));
  });

  it("fetches an artist profile through the workspace API proxy", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json(artistProfile));

    await expect(getArtistProfile("workspace_01", "artist_profile_01")).resolves.toEqual(
      artistProfile,
    );

    expect(fetch).toHaveBeenCalledWith(
      "/api/profiles/workspaces/workspace_01/artist-profiles/artist_profile_01",
      expect.any(Object),
    );
  });

  it("creates an artist profile link with JSON through the workspace API proxy", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json(artistProfile, { status: 201 }));

    await expect(
      createArtistProfile("workspace_01", {
        artist_id: "artist_01",
        universal_profile_id: "profile_01",
        genres: ["Soul"],
      }),
    ).resolves.toEqual(artistProfile);

    expect(fetch).toHaveBeenCalledWith(
      "/api/profiles/workspaces/workspace_01/artist-profiles",
      expect.objectContaining({
        body: JSON.stringify({
          artist_id: "artist_01",
          universal_profile_id: "profile_01",
          genres: ["Soul"],
        }),
        method: "POST",
      }),
    );
  });

  it("updates an artist profile with JSON through the workspace API proxy", async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({ ...artistProfile, stage_name: "Mira S." }),
    );

    await expect(
      updateArtistProfile("workspace_01", "artist_profile_01", {
        genres: ["Soul"],
        stage_name: "Mira S.",
      }),
    ).resolves.toMatchObject({ stage_name: "Mira S." });

    expect(fetch).toHaveBeenCalledWith(
      "/api/profiles/workspaces/workspace_01/artist-profiles/artist_profile_01",
      expect.objectContaining({
        body: JSON.stringify({ genres: ["Soul"], stage_name: "Mira S." }),
        method: "PATCH",
      }),
    );
  });

  it("maps failed responses to typed profile API errors", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json({ detail: "No access" }, { status: 403 }));

    await expect(getCurrentProfile()).rejects.toBeInstanceOf(ProfileApiError);
    await expect(getCurrentProfile()).rejects.toMatchObject({
      code: "forbidden",
      status: 403,
    });
  });

  it("loads current profile state and reuses the cached request", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json(profile));

    const first = renderHook(() => useCurrentProfile());
    const second = renderHook(() => useCurrentProfile());

    await waitFor(() => expect(first.result.current.data?.id).toBe("profile_01"));
    expect(second.result.current.data?.id).toBe("profile_01");
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("updates current profile cache after a mutation", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json(profile))
      .mockResolvedValueOnce(Response.json({ ...profile, display_name: "Mira S." }));

    const current = renderHook(() => useCurrentProfile());
    const mutation = renderHook(() => useUpdateCurrentProfile());

    await waitFor(() => expect(current.result.current.data?.display_name).toBe("Mira Stone"));

    await act(async () => {
      await mutation.result.current.mutate({ display_name: "Mira S." });
    });

    expect(current.result.current.data?.display_name).toBe("Mira S.");
    expect(mutation.result.current.isMutating).toBe(false);
  });

  it("derives roles and capabilities from workspace profile membership data", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json(workspaceProfile));

    const roles = renderHook(() => useProfileRoles("workspace_01", "profile_01"));
    const capabilities = renderHook(() => useProfileCapabilities("workspace_01", "profile_01"));

    await waitFor(() => expect(roles.result.current.data).toEqual(["Artist", "manager"]));
    expect(capabilities.result.current.data).toEqual(["catalog.read", "members.manage"]);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("updates artist profile cache after a mutation", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(Response.json(artistProfile))
      .mockResolvedValueOnce(Response.json({ ...artistProfile, stage_name: "Mira S." }));

    const current = renderHook(() => useArtistProfile("workspace_01", "artist_profile_01"));
    const mutation = renderHook(() =>
      useUpdateArtistProfile("workspace_01", "artist_profile_01"),
    );

    await waitFor(() => expect(current.result.current.data?.stage_name).toBe("Mira"));

    await act(async () => {
      await mutation.result.current.mutate({ stage_name: "Mira S." });
    });

    expect(current.result.current.data?.stage_name).toBe("Mira S.");
    expect(mutation.result.current.isMutating).toBe(false);
  });

  it("caches newly created artist profiles for detail lookups", async () => {
    vi.mocked(fetch).mockResolvedValue(Response.json(artistProfile, { status: 201 }));

    const mutation = renderHook(() => useCreateArtistProfile("workspace_01"));

    await act(async () => {
      await mutation.result.current.mutate({
        artist_id: "artist_01",
        universal_profile_id: "profile_01",
      });
    });

    const current = renderHook(() => useArtistProfile("workspace_01", "artist_profile_01"));

    expect(current.result.current.data?.id).toBe("artist_profile_01");
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
