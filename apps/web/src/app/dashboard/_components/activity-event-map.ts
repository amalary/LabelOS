import type { ActivityEvent, ActivityEventPayload, ActivityEventType } from "./dashboard.types";

export type ActivityEventTone =
  "organization" | "team" | "artist" | "release" | "campaign" | "approval" | "agent" | "default";

export type ActivityEventViewModel = {
  id: string;
  title: string;
  description: string;
  timestamp: string;
  tone: ActivityEventTone;
  rawType: string;
};

type ActivityEventMapper = (
  event: ActivityEvent,
) => Omit<ActivityEventViewModel, "id" | "timestamp" | "rawType">;

const fallbackActor = "Someone";

function textValue(payload: ActivityEventPayload | undefined, keys: string[], fallback: string) {
  for (const key of keys) {
    const value = payload?.[key];
    if (typeof value === "string" && value.trim().length > 0) {
      return value;
    }
  }

  return fallback;
}

function actorName(event: ActivityEvent) {
  return event.actor?.displayName || fallbackActor;
}

function entityName(event: ActivityEvent, fallback: string) {
  return textValue(
    event.payload,
    ["name", "displayName", "title", "artistName", "organizationName"],
    fallback,
  );
}

function humanizeType(type: string) {
  return type.replace(/[._-]+/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

export function formatActivityTimestamp(createdAt: string, now: Date = new Date()) {
  const created = new Date(createdAt);

  if (Number.isNaN(created.getTime())) {
    return "Time unavailable";
  }

  const elapsedMs = Math.max(0, now.getTime() - created.getTime());
  const elapsedMinutes = Math.floor(elapsedMs / 60000);

  if (elapsedMinutes < 1) {
    return "Just now";
  }

  if (elapsedMinutes < 60) {
    return `${elapsedMinutes} minute${elapsedMinutes === 1 ? "" : "s"} ago`;
  }

  const elapsedHours = Math.floor(elapsedMinutes / 60);
  if (elapsedHours < 24) {
    return `${elapsedHours} hour${elapsedHours === 1 ? "" : "s"} ago`;
  }

  const elapsedDays = Math.floor(elapsedHours / 24);
  if (elapsedDays < 7) {
    return `${elapsedDays} day${elapsedDays === 1 ? "" : "s"} ago`;
  }

  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
  }).format(created);
}

const activityEventMappers: Partial<Record<ActivityEventType, ActivityEventMapper>> = {
  "organization.created": (event) => ({
    title: "Organization created",
    description: `${entityName(event, "A workspace")} was created`,
    tone: "organization",
  }),
  "organization.updated": (event) => ({
    title: "Organization updated",
    description: `${actorName(event)} updated ${entityName(event, "the organization")}`,
    tone: "organization",
  }),
  "organization.switched": (event) => ({
    title: "Organization switched",
    description: `${actorName(event)} switched to ${entityName(event, "another organization")}`,
    tone: "organization",
  }),
  "profile.created": (event) => ({
    title: "Profile created",
    description: `${actorName(event)} created a profile`,
    tone: "team",
  }),
  "profile.updated": (event) => ({
    title: "Profile updated",
    description: `${actorName(event)} updated a profile`,
    tone: "team",
  }),
  "profile.roles_updated": (event) => ({
    title: "Profile roles updated",
    description: `${actorName(event)} updated profile roles`,
    tone: "team",
  }),
  "profile.membership_updated": (event) => ({
    title: "Profile membership updated",
    description: `${actorName(event)} updated workspace membership`,
    tone: "team",
  }),
  "profile.artist_updated": (event) => ({
    title: "Artist profile updated",
    description: `${entityName(event, "An artist profile")} was updated`,
    tone: "artist",
  }),
  "profile.role_added": (event) => ({
    title: "Profile role added",
    description: `${actorName(event)} added ${textValue(event.payload, ["role", "roleKey"], "a role")} to a profile`,
    tone: "team",
  }),
  "profile.role_removed": (event) => ({
    title: "Profile role removed",
    description: `${actorName(event)} removed ${textValue(event.payload, ["role", "roleKey"], "a role")} from a profile`,
    tone: "team",
  }),
  "profile.workspace_joined": (event) => ({
    title: "Profile joined workspace",
    description: `${actorName(event)} joined the workspace`,
    tone: "team",
  }),
  "profile.workspace_left": (event) => ({
    title: "Profile left workspace",
    description: `${actorName(event)} left the workspace`,
    tone: "team",
  }),
  "profile.artist_profile_created": (event) => ({
    title: "Artist profile created",
    description: `${entityName(event, "An artist profile")} was created`,
    tone: "artist",
  }),
  "profile.artist_profile_updated": (event) => ({
    title: "Artist profile updated",
    description: `${entityName(event, "An artist profile")} was updated`,
    tone: "artist",
  }),
  "invitation.sent": (event) => ({
    title: "Invitation sent",
    description: `${actorName(event)} sent a workspace invitation`,
    tone: "team",
  }),
  "invitation.accepted": (event) => ({
    title: "Invitation accepted",
    description: `${actorName(event)} accepted a workspace invitation`,
    tone: "team",
  }),
  "member.invited": (event) => ({
    title: "Member invited",
    description: `${textValue(event.payload, ["email", "memberEmail", "displayName"], "A teammate")} was invited`,
    tone: "team",
  }),
  "member.updated": (event) => ({
    title: "Member updated",
    description: `${entityName(event, "A member")} was updated`,
    tone: "team",
  }),
  "member.joined": (event) => ({
    title: "Member joined",
    description: `${entityName(event, actorName(event))} joined the organization`,
    tone: "team",
  }),
  "member.role_changed": (event) => ({
    title: "Member role changed",
    description: `${entityName(event, "A member")} is now ${textValue(event.payload, ["role", "newRole"], "in a new role")}`,
    tone: "team",
  }),
  "member.removed": (event) => ({
    title: "Member removed",
    description: `${entityName(event, "A member")} was removed from the organization`,
    tone: "team",
  }),
  "artist.created": (event) => ({
    title: "Artist created",
    description: `${entityName(event, "An artist")} was added`,
    tone: "artist",
  }),
  "artist.updated": (event) => ({
    title: "Artist updated",
    description: `${entityName(event, "An artist")} was updated`,
    tone: "artist",
  }),
  "artist.status_changed": (event) => ({
    title: "Artist status changed",
    description: `${entityName(event, "An artist")} changed to ${textValue(event.payload, ["status", "newStatus"], "a new status")}`,
    tone: "artist",
  }),
  "release.updated": (event) => ({
    title: "Release updated",
    description: `${entityName(event, "A release")} was updated`,
    tone: "release",
  }),
  "campaign.updated": (event) => ({
    title: "Campaign updated",
    description: `${entityName(event, "A campaign")} was updated`,
    tone: "campaign",
  }),
  "approval.updated": (event) => ({
    title: "Approval updated",
    description: `${entityName(event, "An approval")} was updated`,
    tone: "approval",
  }),
  "agent.started": (event) => ({
    title: "AI agent started",
    description: `${entityName(event, "An AI agent")} started working`,
    tone: "agent",
  }),
  "agent.completed": (event) => ({
    title: "AI agent completed",
    description: `${entityName(event, "An AI agent")} completed its run`,
    tone: "agent",
  }),
  "agent.failed": (event) => ({
    title: "AI agent failed",
    description: `${entityName(event, "An AI agent")} needs attention`,
    tone: "agent",
  }),
};

export function mapActivityEvent(event: ActivityEvent, now?: Date): ActivityEventViewModel {
  const mapped = activityEventMappers[event.type]?.(event) ?? {
    title: humanizeType(event.type),
    description: `${actorName(event)} made an update${event.entityType ? ` to ${event.entityType}` : ""}`,
    tone: "default" as const,
  };

  return {
    id: event.id,
    rawType: event.type,
    timestamp: formatActivityTimestamp(event.createdAt, now),
    ...mapped,
  };
}

export function mapActivityEvents(events: ActivityEvent[], now?: Date) {
  return events.map((event) => mapActivityEvent(event, now));
}
