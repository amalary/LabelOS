import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { UniversalProfile } from "../../../lib/profiles.types";
import {
  profileOnboardingAttributes,
  resolveOnboardingRoleModule,
  UniversalProfileOnboarding,
} from "./profile-onboarding";

const navigation = vi.hoisted(() => ({
  push: vi.fn(),
}));

const profileMutation = vi.hoisted(() => ({
  mutate: vi.fn(),
}));

const workspaceContext = vi.hoisted(() => ({
  useActiveWorkspace: vi.fn(),
  useActiveWorkspaceProfile: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
}));

vi.mock("../../../lib/profiles", () => ({
  useUpdateCurrentProfile: () => ({
    isMutating: false,
    mutate: profileMutation.mutate,
  }),
}));

vi.mock("../../../lib/workspace-context", () => workspaceContext);

const baseProfile: UniversalProfile = {
  id: "profile_01",
  user_id: "user_01",
  slug: null,
  first_name: null,
  last_name: null,
  display_name: "",
  headline: null,
  biography: null,
  avatar_url: null,
  location: null,
  timezone: null,
  primary_email: null,
  profile_status: "active",
  onboarding_status: "not_started",
  links: [],
  attributes: [],
  preferences: {
    locale: null,
    timezone: "America/Los_Angeles",
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

describe("UniversalProfileOnboarding", () => {
  beforeEach(() => {
    navigation.push.mockReset();
    profileMutation.mutate.mockReset();
    profileMutation.mutate.mockResolvedValue({ ...baseProfile, onboarding_status: "complete" });
    workspaceContext.useActiveWorkspace.mockReturnValue({
      activeWorkspace: { id: "workspace_01", name: "Northstar Audio" },
      workspaces: [{ id: "workspace_01", name: "Northstar Audio" }],
    });
    workspaceContext.useActiveWorkspaceProfile.mockReturnValue({
      departmentAccess: ["marketing"],
      roles: ["Marketing"],
    });
  });

  it("resolves invite/workspace roles into a reusable role-aware module", () => {
    expect(resolveOnboardingRoleModule(["Artist"], [])).toMatchObject({
      key: "artist",
      title: "Creative setup",
    });
    expect(resolveOnboardingRoleModule([], ["marketing"])).toMatchObject({
      key: "marketing",
      title: "Marketing setup",
    });
  });

  it("completes the profile with essential details and role-aware interests", async () => {
    const user = userEvent.setup();

    render(<UniversalProfileOnboarding hasWorkspace initialProfile={baseProfile} />);

    expect(screen.getByRole("heading", { name: "Marketing setup" })).toBeInTheDocument();
    expect(screen.getByText("Northstar Audio")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Display name"), "Mira Stone");
    await user.type(screen.getByLabelText("Headline"), "Campaign strategist");
    await user.click(screen.getByRole("button", { name: "Campaign strategy" }));
    await user.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(profileMutation.mutate).toHaveBeenCalled());
    expect(profileMutation.mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        attributes: expect.arrayContaining([
          expect.objectContaining({
            attribute_type: "interest",
            value: "Campaign strategy",
          }),
        ]),
        display_name: "Mira Stone",
        headline: "Campaign strategist",
        onboarding_status: "complete",
        preferences: { timezone: "America/Los_Angeles" },
      }),
    );
    expect(navigation.push).toHaveBeenCalledWith("/dashboard");
  });

  it("preserves non-onboarding attributes while replacing interest selections", () => {
    const attributes = profileOnboardingAttributes(
      {
        ...baseProfile,
        attributes: [
          {
            id: "attribute_skill",
            attribute_type: "skill",
            label: "Skill",
            value: "A&R",
            source: "user",
            is_primary: true,
            sort_order: 0,
            metadata: {},
          },
          {
            id: "attribute_interest",
            attribute_type: "interest",
            label: "Interest",
            value: "Old",
            source: "onboarding",
            is_primary: false,
            sort_order: 1,
            metadata: {},
          },
        ],
      },
      ["Campaign strategy"],
    );

    expect(attributes).toEqual([
      expect.objectContaining({ attribute_type: "interest", value: "Campaign strategy" }),
      expect.objectContaining({ attribute_type: "skill", value: "A&R" }),
    ]);
  });
});
