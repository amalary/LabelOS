"use client";

import {
  createContext,
  createElement,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { usePathname, useRouter } from "next/navigation";

import { clearOrganizationScopedBrowserCaches } from "../browser-cache";
import { invalidateProfileCache } from "../profiles";
import {
  invalidateWorkspaceCapabilityCache,
  shouldInvalidateWorkspaceCapabilityRealtimeCacheKey,
} from "../workspace-capabilities";
import { activityEventTypes, refetchEventTypes, type RealtimeEventEnvelope } from "./events";
import type {
  ActivityEvent,
  ActivityEventPayload,
} from "../../app/dashboard/_components/dashboard.types";

export type RealtimeConnectionState =
  "idle" | "connecting" | "connected" | "reconnecting" | "closed";

export type PresenceMember = {
  userId: string;
  displayName: string | null;
  status: "active" | "offline";
};

export type OrganizationRealtimeState = {
  connectionState: RealtimeConnectionState;
  lastUpdatedBy: string | null;
  presence: PresenceMember[];
  recentActivityEvents: ActivityEvent[];
};

type OrganizationRealtimeContextValue = OrganizationRealtimeState & {
  organizationId: string | null;
};

const OrganizationRealtimeContext = createContext<OrganizationRealtimeContextValue | null>(null);

const maxRecentActivityEvents = 25;
const profileEventPrefix = "profile.";
const artistProfileEventTypes = new Set<string>([
  "profile.artist_updated",
  "profile.artist_profile_created",
  "profile.artist_profile_updated",
]);

export function shouldInvalidateProfileRealtimeCacheKey({
  artistProfileId,
  eventType,
  key,
  organizationId,
  profileId,
}: {
  artistProfileId: string | null;
  eventType: string;
  key: string;
  organizationId: string;
  profileId: string | null;
}) {
  if (key === "profiles:current") {
    return true;
  }
  if (key.startsWith(`profiles:workspace-members:${organizationId}:`)) {
    return true;
  }
  if (key.startsWith(`profiles:workspace-people:${organizationId}:`)) {
    return true;
  }
  if (profileId) {
    if (key === `profiles:workspace-profile:${organizationId}:${profileId}`) {
      return true;
    }
  } else if (key.startsWith(`profiles:workspace-profile:${organizationId}:`)) {
    return true;
  }
  if (artistProfileId) {
    return key === `profiles:artist-profile:${organizationId}:${artistProfileId}`;
  }
  return (
    artistProfileEventTypes.has(eventType) &&
    key.startsWith(`profiles:artist-profile:${organizationId}:`)
  );
}

function payloadForActivity(event: RealtimeEventEnvelope): ActivityEventPayload {
  const payload: ActivityEventPayload = {};
  for (const [key, value] of Object.entries(event.payload)) {
    if (
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean" ||
      value === null ||
      value === undefined
    ) {
      payload[key] = value;
    }
  }

  const entityPayload = event.entity_type ? event.payload[event.entity_type] : null;
  if (entityPayload && typeof entityPayload === "object" && !Array.isArray(entityPayload)) {
    for (const [key, value] of Object.entries(entityPayload)) {
      if (
        typeof value === "string" ||
        typeof value === "number" ||
        typeof value === "boolean" ||
        value === null ||
        value === undefined
      ) {
        payload[key] = value;
      }
    }
  }

  return payload;
}

function toActivityEvent(event: RealtimeEventEnvelope): ActivityEvent {
  return {
    id: event.id,
    type: event.type,
    createdAt: event.created_at,
    actor: event.actor
      ? {
          userId: event.actor.user_id,
          displayName: event.actor.display_name,
        }
      : null,
    entityType: event.entity_type,
    entityId: event.entity_id,
    payload: payloadForActivity(event),
  };
}

export function useOrganizationRealtime(organizationId: string | null): OrganizationRealtimeState {
  const router = useRouter();
  const pathname = usePathname();
  const seenEventIds = useRef<Set<string>>(new Set());
  const lastEventId = useRef<string | null>(null);
  const retryAttempt = useRef(0);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sourceRef = useRef<EventSource | null>(null);
  const [connectionState, setConnectionState] = useState<RealtimeConnectionState>("idle");
  const [presence, setPresence] = useState<Map<string, PresenceMember>>(new Map());
  const [lastUpdatedBy, setLastUpdatedBy] = useState<string | null>(null);
  const [recentActivityEvents, setRecentActivityEvents] = useState<ActivityEvent[]>([]);

  useEffect(() => {
    seenEventIds.current.clear();
    lastEventId.current = null;
    retryAttempt.current = 0;
    setPresence(new Map());
    setLastUpdatedBy(null);
    setRecentActivityEvents([]);

    if (!organizationId) {
      setConnectionState("idle");
      return;
    }

    let closed = false;

    function closeSource() {
      sourceRef.current?.close();
      sourceRef.current = null;
      if (retryTimer.current) {
        clearTimeout(retryTimer.current);
        retryTimer.current = null;
      }
    }

    function connect() {
      closeSource();
      setConnectionState(retryAttempt.current === 0 ? "connecting" : "reconnecting");
      const params = new URLSearchParams();
      if (lastEventId.current) {
        params.set("lastEventId", lastEventId.current);
      }
      const url = `/api/realtime/organizations/${organizationId}/events${
        params.size > 0 ? `?${params.toString()}` : ""
      }`;
      const source = new EventSource(url);
      sourceRef.current = source;

      source.addEventListener("connected", () => {
        retryAttempt.current = 0;
        setConnectionState("connected");
      });

      source.addEventListener("message", (message) => {
        let event: RealtimeEventEnvelope;
        try {
          event = JSON.parse(message.data) as RealtimeEventEnvelope;
        } catch {
          return;
        }
        if (
          event.version !== 1 ||
          event.organization_id !== organizationId ||
          seenEventIds.current.has(event.id)
        ) {
          return;
        }
        seenEventIds.current.add(event.id);
        lastEventId.current = event.id;

        if (event.type === "presence.joined" || event.type === "presence.left") {
          const userId = event.actor?.user_id;
          if (userId) {
            setPresence((current) => {
              const next = new Map(current);
              next.set(userId, {
                userId,
                displayName: event.actor?.display_name ?? null,
                status: event.type === "presence.joined" ? "active" : "offline",
              });
              return next;
            });
          }
        }

        if (event.actor?.display_name && refetchEventTypes.has(event.type)) {
          setLastUpdatedBy(event.actor.display_name);
        }

        if (activityEventTypes.has(event.type)) {
          const activityEvent = toActivityEvent(event);
          setRecentActivityEvents((current) => {
            if (current.some((item) => item.id === activityEvent.id)) {
              return current;
            }
            return [activityEvent, ...current].slice(0, maxRecentActivityEvents);
          });
        }

        if (refetchEventTypes.has(event.type)) {
          if (event.type.startsWith(profileEventPrefix)) {
            const profileId =
              typeof event.payload.profileId === "string"
                ? event.payload.profileId
                : event.entity_id;
            const artistProfileId =
              typeof event.payload.artistProfileId === "string"
                ? event.payload.artistProfileId
                : null;
            invalidateProfileCache((key) =>
              shouldInvalidateProfileRealtimeCacheKey({
                artistProfileId,
                eventType: event.type,
                key,
                organizationId,
                profileId,
              }),
            );
          }
          if (
            event.type === "member.updated" ||
            event.type === "member.role_changed" ||
            event.type === "member.joined" ||
            event.type === "member.removed" ||
            event.type === "profile.roles_updated" ||
            event.type === "profile.role_added" ||
            event.type === "profile.role_removed" ||
            event.type === "profile.membership_updated" ||
            event.type === "profile.workspace_joined" ||
            event.type === "profile.workspace_left"
          ) {
            invalidateWorkspaceCapabilityCache((key) =>
              shouldInvalidateWorkspaceCapabilityRealtimeCacheKey({
                key,
                organizationId,
              }),
            );
          }
          const isDashboardActivityRefresh =
            pathname === "/dashboard" && activityEventTypes.has(event.type);
          if (!isDashboardActivityRefresh) {
            clearOrganizationScopedBrowserCaches();
            router.refresh();
          }
        }
      });

      source.addEventListener("membership_revoked", () => {
        closeSource();
        clearOrganizationScopedBrowserCaches();
        router.refresh();
        setConnectionState("closed");
      });

      source.onerror = () => {
        closeSource();
        if (closed) {
          return;
        }
        retryAttempt.current += 1;
        const delay = Math.min(30000, 1000 * 2 ** Math.min(retryAttempt.current, 5));
        retryTimer.current = setTimeout(connect, delay);
      };
    }

    connect();

    return () => {
      closed = true;
      closeSource();
      setConnectionState("closed");
    };
  }, [organizationId, pathname, router]);

  return {
    connectionState,
    lastUpdatedBy,
    recentActivityEvents,
    presence: Array.from(presence.values()).filter((member) => member.status === "active"),
  };
}

export function OrganizationRealtimeProvider({
  children,
  organizationId,
}: {
  children: ReactNode;
  organizationId: string | null;
}) {
  const realtime = useOrganizationRealtime(organizationId);
  const { connectionState, lastUpdatedBy, presence, recentActivityEvents } = realtime;
  const value = useMemo(
    () => ({
      connectionState,
      lastUpdatedBy,
      organizationId,
      presence,
      recentActivityEvents,
    }),
    [connectionState, lastUpdatedBy, organizationId, presence, recentActivityEvents],
  );

  return createElement(OrganizationRealtimeContext.Provider, { value }, children);
}

export function useOrganizationRealtimeContext() {
  return useContext(OrganizationRealtimeContext);
}
