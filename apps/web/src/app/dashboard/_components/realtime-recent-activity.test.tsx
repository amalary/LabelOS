import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OrganizationRealtimeProvider } from "../../../lib/realtime/use-organization-realtime";
import { RealtimeRecentActivity } from "./realtime-recent-activity";

const navigation = vi.hoisted(() => ({
  refresh: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
  usePathname: () => "/dashboard",
}));

type Listener = (message: MessageEvent<string>) => void;

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  listeners = new Map<string, Listener[]>();
  onerror: ((event: Event) => void) | null = null;

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener) {
    const current = this.listeners.get(type) ?? [];
    current.push(listener);
    this.listeners.set(type, current);
  }

  close() {}

  emit(type: string, data: unknown) {
    for (const listener of this.listeners.get(type) ?? []) {
      listener(new MessageEvent(type, { data: JSON.stringify(data) }));
    }
  }
}

describe("RealtimeRecentActivity", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("prepends organization realtime activity without duplicating initial events", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    FakeEventSource.instances = [];
    navigation.refresh.mockReset();

    render(
      <OrganizationRealtimeProvider organizationId="org_01">
        <RealtimeRecentActivity
          activity={{
            events: [
              {
                id: "event_01",
                type: "artist.created",
                payload: { name: "NOVA" },
                createdAt: "2026-08-12T17:56:00.000Z",
              },
            ],
          }}
        />
      </OrganizationRealtimeProvider>,
    );

    const source = FakeEventSource.instances[0]!;

    act(() => {
      source.emit("message", {
        id: "event_02",
        type: "member.updated",
        version: 1,
        channel: "organization:org_01",
        organization_id: "org_01",
        entity_type: "member",
        entity_id: "member_01",
        operation_id: "operation_02",
        actor: { user_id: "user_01", display_name: "Mara Chen" },
        payload: { displayName: "Sarah Jones" },
        created_at: "2026-08-12T18:00:00.000Z",
      });
      source.emit("message", {
        id: "event_02",
        type: "member.updated",
        version: 1,
        channel: "organization:org_01",
        organization_id: "org_01",
        entity_type: "member",
        entity_id: "member_01",
        operation_id: "operation_02",
        actor: { user_id: "user_01", display_name: "Mara Chen" },
        payload: { displayName: "Sarah Jones" },
        created_at: "2026-08-12T18:00:00.000Z",
      });
    });

    expect(await screen.findByText("Member updated")).toBeInTheDocument();
    expect(screen.getByText("Sarah Jones was updated")).toBeInTheDocument();
    expect(screen.getByText("Artist created")).toBeInTheDocument();
    expect(screen.getAllByText("member.updated")).toHaveLength(1);
    expect(navigation.refresh).not.toHaveBeenCalled();
  });
});
