import type { ProfileCompletion, UniversalProfile } from "./profiles.types";

export type ProfileCompletionViewModel = {
  isVisible: boolean;
  title: string;
  missingSummary: string;
  href: string;
};

export function profileCompletionFor(profile: UniversalProfile | null): ProfileCompletion | null {
  return profile?.profile_completion ?? null;
}

export function profileCompletionViewModel(
  profile: UniversalProfile | null,
): ProfileCompletionViewModel | null {
  const completion = profileCompletionFor(profile);
  if (!completion || completion.is_complete) {
    return null;
  }

  return {
    isVisible: true,
    title: completion.guidance ?? "Add your professional information",
    missingSummary: completion.missing_fields.length
      ? `Missing: ${completion.missing_fields.join(", ")}`
      : "Add the profile details that match your current responsibilities.",
    href: "/profile",
  };
}
