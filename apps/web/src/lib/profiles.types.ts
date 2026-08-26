export type JsonObject = Record<string, unknown>;

export type ProfileLink = {
  id: string;
  link_type: string;
  label: string | null;
  url: string;
  username: string | null;
  external_id: string | null;
  status: string;
  is_primary: boolean;
  sort_order: number;
  metadata: JsonObject;
};

export type ProfileAttribute = {
  id: string;
  attribute_type: string;
  label: string | null;
  value: string;
  source: string;
  is_primary: boolean;
  sort_order: number;
  metadata: JsonObject;
};

export type ProfilePreferences = {
  locale: string | null;
  timezone: string | null;
  default_workspace_id: string | null;
  email_notifications_enabled: boolean;
  push_notifications_enabled: boolean;
  sms_notifications_enabled: boolean;
  marketing_notifications_enabled: boolean;
  interface_theme: string | null;
  interface_density: string | null;
  notification_preferences: JsonObject;
  interface_preferences: JsonObject;
  integration_preferences: JsonObject;
};

export type ProfileCompletion = {
  ruleset: string;
  is_complete: boolean;
  percent: number;
  completed_fields: string[];
  missing_fields: string[];
  guidance: string | null;
  is_blocking: boolean;
};

export type UniversalProfile = {
  id: string;
  user_id: string | null;
  slug: string | null;
  first_name: string | null;
  last_name: string | null;
  display_name: string | null;
  headline: string | null;
  biography: string | null;
  avatar_url: string | null;
  location: string | null;
  timezone: string | null;
  primary_email: string | null;
  profile_status: string | null;
  onboarding_status: string | null;
  links: ProfileLink[];
  attributes: ProfileAttribute[];
  preferences: ProfilePreferences;
  profile_completion?: ProfileCompletion | null;
};

export type ProfileLinkInput = Omit<ProfileLink, "id">;

export type ProfileAttributeInput = Omit<ProfileAttribute, "id">;

export type ProfilePreferencesUpdate = Partial<ProfilePreferences>;

export type UniversalProfileUpdate = {
  slug?: string | null;
  display_name?: string | null;
  headline?: string | null;
  biography?: string | null;
  avatar_url?: string | null;
  location?: string | null;
  timezone?: string | null;
  onboarding_status?: "not_started" | "in_progress" | "complete";
  links?: ProfileLinkInput[];
  attributes?: ProfileAttributeInput[];
  preferences?: ProfilePreferencesUpdate;
};

export type WorkspaceProfileMembership = {
  id: string;
  workspace_id: string;
  profile: UniversalProfile;
  status: string;
  joined_at: string | null;
  role: string | null;
  professional_roles: string[];
  department_access: string[];
  workspace_roles: string[];
  capability_permissions: string[];
};

export type WorkspaceProfilesList = {
  profiles: WorkspaceProfileMembership[];
  limit: number;
  offset: number;
  total: number;
};

export type WorkspacePeopleDirectoryEntry = {
  id: string;
  workspace_id: string;
  profile_id: string;
  avatar_url: string | null;
  display_name: string | null;
  headline: string | null;
  roles: string[];
  departments: string[];
  profile_modules: string[];
  artist_profile_id: string | null;
  membership_status: string;
};

export type WorkspacePeopleDirectory = {
  people: WorkspacePeopleDirectoryEntry[];
  limit: number;
  offset: number;
  total: number;
  query: string | null;
};

export type ArtistProfileDetail = {
  id: string;
  artist_id: string;
  workspace_id: string;
  universal_profile_id: string | null;
  artist_name: string;
  stage_name: string | null;
  genres: string[];
  influences: string[];
  imagery: JsonObject;
  dsp_links: JsonObject;
  catalog_references: JsonObject[];
  creative_metadata: JsonObject;
  career_stage: string | null;
  audience: JsonObject;
  preferences: JsonObject;
};

export type ArtistProfileCreate = {
  artist_id: string;
  universal_profile_id: string;
  stage_name?: string | null;
  genres?: string[];
  influences?: string[];
  imagery?: JsonObject;
  dsp_links?: JsonObject;
  catalog_references?: string[];
  creative_metadata?: JsonObject;
  career_stage?: string | null;
  audience?: JsonObject;
  preferences?: JsonObject;
};

export type ArtistProfileUpdate = {
  universal_profile_id?: string | null;
  stage_name?: string | null;
  genres?: string[];
  influences?: string[];
  imagery?: JsonObject;
  dsp_links?: JsonObject;
  catalog_references?: JsonObject[];
  creative_metadata?: JsonObject;
  career_stage?: string | null;
  audience?: JsonObject;
  preferences?: JsonObject;
};
