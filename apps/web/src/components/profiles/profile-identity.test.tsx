import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type {
  UniversalProfile,
  WorkspacePeopleDirectoryEntry,
  WorkspaceProfileMembership,
} from "../../lib/profiles.types";
import {
  ProfileAvatar,
  ProfileCard,
  ProfileMultiSelect,
  ProfileSelector,
  profileIdentityFromDirectoryEntry,
  profileIdentityFromMembership,
  profileIdentityFromUniversalProfile,
} from "./profile-identity";

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
  timezone: null,
  primary_email: "mira@example.com",
  profile_status: "active",
  onboarding_status: "complete",
  links: [],
  attributes: [],
  preferences: {
    locale: null,
    timezone: null,
    default_workspace_id: null,
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

const membership: WorkspaceProfileMembership = {
  id: "membership_01",
  workspace_id: "workspace_01",
  profile,
  status: "active",
  joined_at: null,
  role: "member",
  professional_roles: ["Artist Manager"],
  department_access: ["Marketing"],
  workspace_roles: ["Approver"],
  capability_permissions: [],
};

const directoryEntry: WorkspacePeopleDirectoryEntry = {
  id: "membership_01",
  workspace_id: "workspace_01",
  profile_id: "profile_01",
  avatar_url: null,
  display_name: "Mira Stone",
  headline: "Artist manager",
  roles: ["Artist Manager"],
  departments: ["Marketing"],
  profile_modules: ["artist"],
  artist_profile_id: "artist_profile_01",
  membership_status: "active",
};

const miraIdentity = profileIdentityFromMembership(membership);
const noahIdentity = {
  id: "profile_02",
  displayName: "Noah Kim",
  headline: "Release coordinator",
  avatarUrl: null,
  roles: ["Coordinator"],
  departments: ["Operations"],
};

describe("profile identity components", () => {
  it("normalizes Universal Profile and workspace records around Universal Profile IDs", () => {
    expect(profileIdentityFromUniversalProfile(profile)).toMatchObject({
      id: "profile_01",
      displayName: "Mira Stone",
    });
    expect(profileIdentityFromMembership(membership)).toMatchObject({
      id: "profile_01",
      roles: ["Artist Manager", "Approver"],
      departments: ["Marketing"],
    });
    expect(profileIdentityFromDirectoryEntry(directoryEntry)).toMatchObject({
      id: "profile_01",
      displayName: "Mira Stone",
    });
  });

  it("renders profile cards and initials without exposing raw WorkOS user IDs", () => {
    render(<ProfileCard profile={miraIdentity} />);

    expect(screen.getByRole("img", { name: "Mira Stone avatar" })).toHaveTextContent("MS");
    expect(screen.getByText("Mira Stone")).toBeInTheDocument();
    expect(screen.getByText("Artist Manager")).toBeInTheDocument();
    expect(screen.queryByText("user_01")).not.toBeInTheDocument();
  });

  it("uses avatar URLs when available", () => {
    const { container } = render(
      <ProfileAvatar
        profile={{
          ...miraIdentity,
          avatarUrl: "https://cdn.example.test/mira.png",
        }}
      />,
    );

    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      "https://cdn.example.test/mira.png",
    );
  });

  it("selects a single profile by Universal Profile ID", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(
      <ProfileSelector onChange={onChange} profiles={[miraIdentity, noahIdentity]} value={null} />,
    );

    await user.click(screen.getByRole("button", { name: /select profile/i }));
    await user.click(screen.getByRole("option", { name: /Noah Kim/i }));

    expect(onChange).toHaveBeenCalledWith("profile_02");
  });

  it("selects multiple profiles by Universal Profile ID", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(
      <ProfileMultiSelect
        onChange={onChange}
        profiles={[miraIdentity, noahIdentity]}
        values={["profile_01"]}
      />,
    );

    await user.click(screen.getByRole("checkbox", { name: /Noah Kim/i }));

    expect(onChange).toHaveBeenCalledWith(["profile_01", "profile_02"]);
  });
});
