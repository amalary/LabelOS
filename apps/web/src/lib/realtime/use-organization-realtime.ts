"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { clearOrganizationScopedBrowserCaches } from "../browser-cache";
import { refetchEventTypes, type RealtimeEventEnvelope } from "./events";

export type RealtimeConnectionState =
  "idle" | "connecting" | "connected" | "reconnecting" | "closed";

export type PresenceMember = {
  userId: string;
  displayName: string | null;
  status: "active" | "offline";
};

export function useOrganizationRealtime(organizationId: string | null) {
  const router = useRouter();
  const seenEventIds = useRef<Set<string>>(new Set());
  const lastEventId = useRef<string | null>(null);
  const retryAttempt = useRef(0);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sourceRef = useRef<EventSource | null>(null);
  const [connectionState, setConnectionState] = useState<RealtimeConnectionState>("idle");
  const [presence, setPresence] = useState<Map<string, PresenceMember>>(new Map());
  const [lastUpdatedBy, setLastUpdatedBy] = useState<string | null>(null);

  useEffect(() => {
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
        const event = JSON.parse(message.data) as RealtimeEventEnvelope;
        if (event.version !== 1 || seenEventIds.current.has(event.id)) {
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

        if (refetchEventTypes.has(event.type)) {
          clearOrganizationScopedBrowserCaches();
          router.refresh();
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
  }, [organizationId, router]);

  return {
    connectionState,
    lastUpdatedBy,
    presence: Array.from(presence.values()).filter((member) => member.status === "active"),
  };
}
