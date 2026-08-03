import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useOrganizationRealtime } from "./use-organization-realtime";

const navigation = vi.hoisted(() => ({
  refresh: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
}));

type Listener = (message: MessageEvent<string>) => void;

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  listeners = new Map<string, Listener[]>();
  closed = false;
  onerror: ((event: Event) => void) | null = null;

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener) {
    const current = this.listeners.get(type) ?? [];
    current.push(listener);
    this.listeners.set(type, current);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, data: unknown) {
    for (const listener of this.listeners.get(type) ?? []) {
      listener(new MessageEvent(type, { data: JSON.stringify(data) }));
    }
  }
}

function RealtimeProbe() {
  const { connectionState, lastUpdatedBy, presence } = useOrganizationRealtime("org_01");
  return (
    <div>
      <span>{connectionState}</span>
      <span>{lastUpdatedBy ?? "none"}</span>
      <span>{presence.length}</span>
    </div>
  );
}

describe("useOrganizationRealtime", () => {
  beforeEach(() => {
    navigation.refresh.mockReset();
    FakeEventSource.instances = [];
    window.sessionStorage.clear();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("deduplicates events, refreshes cacheable data, and tracks presence", async () => {
    window.sessionStorage.setItem("labelos:artists", "cached");
    render(<RealtimeProbe />);
    const source = FakeEventSource.instances[0]!;

    act(() => {
      source.emit("connected", { channel: "organization:org_01" });
    });

    await screen.findByText("connected");

    const event = {
      id: "event_01",
      type: "artist.updated",
      version: 1,
      channel: "organization:org_01",
      organization_id: "org_01",
      entity_type: "artist",
      entity_id: "artist_01",
      operation_id: "operation_01",
      actor: { user_id: "user_01", display_name: "Mara Chen" },
      payload: {},
      created_at: new Date().toISOString(),
    };

    act(() => {
      source.emit("message", {
        ...event,
        id: "presence_01",
        type: "presence.joined",
      });
      source.emit("message", event);
      source.emit("message", event);
    });

    await waitFor(() => expect(navigation.refresh).toHaveBeenCalledTimes(1));
    expect(window.sessionStorage.getItem("labelos:artists")).toBeNull();
    expect(screen.getByText("Mara Chen")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("reconnects with the last processed cursor", () => {
    vi.useFakeTimers();
    render(<RealtimeProbe />);
    const source = FakeEventSource.instances[0]!;

    act(() => {
      source.emit("message", {
        id: "event_02",
        type: "organization.updated",
        version: 1,
        channel: "organization:org_01",
        organization_id: "org_01",
        entity_type: "organization",
        entity_id: "org_01",
        operation_id: "operation_02",
        actor: null,
        payload: {},
        created_at: new Date().toISOString(),
      });
      source.onerror?.(new Event("error"));
      vi.advanceTimersByTime(2000);
    });

    const reconnectedSource = FakeEventSource.instances[1]!;
    expect(reconnectedSource.url).toBe(
      "/api/realtime/organizations/org_01/events?lastEventId=event_02",
    );
  });
});
