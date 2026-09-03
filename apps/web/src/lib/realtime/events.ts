export type RealtimeEventType =
  | "organization.updated"
  | "profile.created"
  | "profile.updated"
  | "profile.roles_updated"
  | "profile.membership_updated"
  | "profile.artist_updated"
  | "profile.role_added"
  | "profile.role_removed"
  | "profile.workspace_joined"
  | "profile.workspace_left"
  | "profile.artist_profile_created"
  | "profile.artist_profile_updated"
  | "member.updated"
  | "member.role_changed"
  | "member.joined"
  | "member.removed"
  | "artist.created"
  | "artist.updated"
  | "artist.status_changed"
  | "release.updated"
  | "campaign.created"
  | "campaign.updated"
  | "campaign.status_changed"
  | "campaign.member_added"
  | "campaign.member_updated"
  | "campaign.member_removed"
  | "campaign.artist_associated"
  | "campaign.artist_removed"
  | "campaign.release_associated"
  | "campaign.release_removed"
  | "campaign.goal_created"
  | "campaign.goal_updated"
  | "campaign.goal_completed"
  | "campaign.milestone_created"
  | "campaign.milestone_updated"
  | "campaign.milestone_completed"
  | "analytics.observation.created"
  | "analytics.observations.ingested"
  | "marketing.content.created"
  | "marketing.content.updated"
  | "marketing.content.status_changed"
  | "marketing.content.approval_requested"
  | "marketing.content.approved"
  | "marketing.content.published"
  | "approval.updated"
  | "agent.started"
  | "agent.completed"
  | "agent.failed"
  | "presence.joined"
  | "presence.left";

export type RealtimeEventEnvelope = {
  id: string;
  type: RealtimeEventType;
  version: 1;
  channel: string;
  organization_id: string;
  entity_type: string | null;
  entity_id: string | null;
  operation_id: string;
  actor: {
    user_id: string;
    display_name: string | null;
  } | null;
  payload: Record<string, unknown>;
  created_at: string;
};

export const activityEventTypes = new Set<RealtimeEventType>([
  "organization.updated",
  "profile.created",
  "profile.updated",
  "profile.roles_updated",
  "profile.membership_updated",
  "profile.artist_updated",
  "profile.role_added",
  "profile.role_removed",
  "profile.workspace_joined",
  "profile.workspace_left",
  "profile.artist_profile_created",
  "profile.artist_profile_updated",
  "member.updated",
  "member.role_changed",
  "member.joined",
  "member.removed",
  "artist.created",
  "artist.updated",
  "artist.status_changed",
  "release.updated",
  "campaign.created",
  "campaign.updated",
  "campaign.status_changed",
  "campaign.member_added",
  "campaign.member_updated",
  "campaign.member_removed",
  "campaign.artist_associated",
  "campaign.artist_removed",
  "campaign.release_associated",
  "campaign.release_removed",
  "campaign.goal_created",
  "campaign.goal_updated",
  "campaign.goal_completed",
  "campaign.milestone_created",
  "campaign.milestone_updated",
  "campaign.milestone_completed",
  "marketing.content.created",
  "marketing.content.updated",
  "marketing.content.status_changed",
  "marketing.content.approval_requested",
  "marketing.content.approved",
  "marketing.content.published",
  "approval.updated",
  "agent.started",
  "agent.completed",
  "agent.failed",
]);

export const refetchEventTypes = new Set<RealtimeEventType>([
  "organization.updated",
  "profile.created",
  "profile.updated",
  "profile.roles_updated",
  "profile.membership_updated",
  "profile.artist_updated",
  "profile.role_added",
  "profile.role_removed",
  "profile.workspace_joined",
  "profile.workspace_left",
  "profile.artist_profile_created",
  "profile.artist_profile_updated",
  "member.updated",
  "member.role_changed",
  "member.joined",
  "member.removed",
  "artist.created",
  "artist.updated",
  "artist.status_changed",
  "release.updated",
  "campaign.created",
  "campaign.updated",
  "campaign.status_changed",
  "campaign.member_added",
  "campaign.member_updated",
  "campaign.member_removed",
  "campaign.artist_associated",
  "campaign.artist_removed",
  "campaign.release_associated",
  "campaign.release_removed",
  "campaign.goal_created",
  "campaign.goal_updated",
  "campaign.goal_completed",
  "campaign.milestone_created",
  "campaign.milestone_updated",
  "campaign.milestone_completed",
  "analytics.observation.created",
  "analytics.observations.ingested",
  "marketing.content.created",
  "marketing.content.updated",
  "marketing.content.status_changed",
  "marketing.content.approval_requested",
  "marketing.content.approved",
  "marketing.content.published",
  "approval.updated",
  "agent.started",
  "agent.completed",
  "agent.failed",
]);
