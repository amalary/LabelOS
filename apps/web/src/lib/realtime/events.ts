export type RealtimeEventType =
  | "organization.updated"
  | "member.joined"
  | "member.removed"
  | "artist.created"
  | "artist.updated"
  | "artist.status_changed"
  | "release.updated"
  | "campaign.updated"
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

export const refetchEventTypes = new Set<RealtimeEventType>([
  "organization.updated",
  "member.joined",
  "member.removed",
  "artist.created",
  "artist.updated",
  "artist.status_changed",
  "release.updated",
  "campaign.updated",
  "approval.updated",
  "agent.started",
  "agent.completed",
  "agent.failed",
]);
