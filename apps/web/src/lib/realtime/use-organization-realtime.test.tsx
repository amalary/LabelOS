import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearAnalyticsCache,
  shouldInvalidateAnalyticsRealtimeCacheKey,
  useAnalyticsHistoricalSeries,
} from "../analytics";
import {
  clearMarketingContentCache,
  shouldInvalidateMarketingContentRealtimeCacheKey,
  useWorkspaceMarketingContent,
} from "../marketing-content";
import { activityEventTypes, refetchEventTypes } from "./events";
import {
  shouldInvalidateProfileRealtimeCacheKey,
  useOrganizationRealtime,
} from "./use-organization-realtime";

const navigation = vi.hoisted(() => ({
  refresh: vi.fn(),
}));

const routeState = vi.hoisted(() => ({
  pathname: "/artists",
}));

vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
  usePathname: () => routeState.pathname,
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

const analyticsSeriesOptions = {
  aggregation: "sum" as const,
  metric_definition_id: "metric_01",
};
const marketingContentCalendarOptions = {
  start: "2026-09-01T00:00:00Z",
  end: "2026-09-30T23:59:59Z",
};

function RealtimeProbe() {
  const { connectionState, lastUpdatedBy, presence, recentActivityEvents } =
    useOrganizationRealtime("org_01");
  return (
    <div>
      <span>{connectionState}</span>
      <span>{lastUpdatedBy ?? "none"}</span>
      <span>{presence.length}</span>
      <span>{recentActivityEvents.length}</span>
      <span>{recentActivityEvents[0]?.type ?? "no activity"}</span>
    </div>
  );
}

function RealtimeAnalyticsProbe() {
  const { recentActivityEvents } = useOrganizationRealtime("org_01");
  const series = useAnalyticsHistoricalSeries("org_01", analyticsSeriesOptions);
  return (
    <div>
      <span>{series.data?.observation_count ?? "no series"}</span>
      <span>{recentActivityEvents[0]?.type ?? "no activity"}</span>
    </div>
  );
}

function RealtimeMarketingContentProbe() {
  const { recentActivityEvents } = useOrganizationRealtime("org_01");
  const content = useWorkspaceMarketingContent("org_01", marketingContentCalendarOptions);
  return (
    <div>
      <span>{content.data?.total ?? "no content"}</span>
      <span>{recentActivityEvents[0]?.type ?? "no activity"}</span>
    </div>
  );
}

describe("useOrganizationRealtime", () => {
  beforeEach(() => {
    clearAnalyticsCache();
    clearMarketingContentCache();
    navigation.refresh.mockReset();
    routeState.pathname = "/artists";
    FakeEventSource.instances = [];
    window.sessionStorage.clear();
    vi.stubGlobal("fetch", vi.fn());
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
    expect(screen.getAllByText("1")).toHaveLength(2);
    expect(screen.getByText("artist.updated")).toBeInTheDocument();
  });

  it("keeps dashboard activity local without a full dashboard refresh", async () => {
    routeState.pathname = "/dashboard";
    window.sessionStorage.setItem("labelos:artists", "cached");
    render(<RealtimeProbe />);
    const source = FakeEventSource.instances[0]!;

    act(() => {
      source.emit("message", {
        id: "event_03",
        type: "member.updated",
        version: 1,
        channel: "organization:org_01",
        organization_id: "org_01",
        entity_type: "member",
        entity_id: "member_01",
        operation_id: "operation_03",
        actor: { user_id: "user_01", display_name: "Mara Chen" },
        payload: { displayName: "Sarah Jones" },
        created_at: new Date().toISOString(),
      });
    });

    expect(await screen.findByText("member.updated")).toBeInTheDocument();
    expect(navigation.refresh).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem("labelos:artists")).toBe("cached");
  });

  it("handles campaign realtime activity on campaign pages without a route refresh", async () => {
    routeState.pathname = "/campaigns";
    window.sessionStorage.setItem("labelos:artists", "cached");
    render(<RealtimeProbe />);
    const source = FakeEventSource.instances[0]!;

    act(() => {
      source.emit("message", {
        id: "event_campaign_01",
        type: "campaign.goal_completed",
        version: 1,
        channel: "organization:org_01",
        organization_id: "org_01",
        entity_type: "campaign",
        entity_id: "campaign_01",
        operation_id: "operation_campaign_01",
        actor: { user_id: "user_01", display_name: "Mara Chen" },
        payload: {
          campaignId: "campaign_01",
          campaignName: "Single Launch",
          goalId: "goal_01",
          goalTitle: "Reach fans",
        },
        created_at: new Date().toISOString(),
      });
    });

    expect(await screen.findByText("campaign.goal_completed")).toBeInTheDocument();
    expect(navigation.refresh).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem("labelos:artists")).toBe("cached");
  });

  it("invalidates analytics queries for workspace scoped analytics events", async () => {
    routeState.pathname = "/analytics";
    vi.mocked(fetch).mockResolvedValue(
      Response.json({
        aggregation: "sum",
        points: [],
        value_type: "integer",
        unit: "count",
        provider_id: "provider_01",
        metric_definition_id: "metric_01",
        observation_count: 1,
      }),
    );
    render(<RealtimeAnalyticsProbe />);
    const source = FakeEventSource.instances[0]!;

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    act(() => {
      source.emit("message", {
        id: "analytics_event_01",
        type: "analytics.observations.ingested",
        version: 1,
        channel: "organization:org_01",
        organization_id: "org_01",
        entity_type: "analytics_observation_batch",
        entity_id: "org_01",
        operation_id: "operation_analytics_01",
        actor: { user_id: "user_01", display_name: "Mara Chen" },
        payload: {
          workspace_id: "org_01",
          created_count: 2,
          existing_count: 0,
          observation_count: 2,
          observations: [
            {
              workspace_id: "org_01",
              observation_id: "observation_01",
              metric_definition_id: "metric_01",
              artist_profile_id: null,
              campaign_id: "campaign_01",
              campaign_object_type: null,
              campaign_object_id: null,
              observed_at: "2026-08-29T12:00:00+00:00",
            },
          ],
        },
        created_at: new Date().toISOString(),
      });
    });

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/workspaces/org_01/analytics/series?aggregation=sum&metric_definition_id=metric_01",
      expect.any(Object),
    );
    expect(navigation.refresh).not.toHaveBeenCalled();
    expect(screen.getByText("no activity")).toBeInTheDocument();
  });

  it("recognizes marketing content events as realtime refetch and activity events", () => {
    expect(refetchEventTypes.has("marketing.content.created")).toBe(true);
    expect(refetchEventTypes.has("marketing.content.updated")).toBe(true);
    expect(refetchEventTypes.has("marketing.content.status_changed")).toBe(true);
    expect(refetchEventTypes.has("marketing.content.approval_requested")).toBe(true);
    expect(refetchEventTypes.has("marketing.content.approved")).toBe(true);
    expect(refetchEventTypes.has("marketing.content.published")).toBe(true);
    expect(activityEventTypes.has("marketing.content.created")).toBe(true);
  });

  it("invalidates marketing content cache for workspace scoped content events", async () => {
    routeState.pathname = "/marketing";
    vi.mocked(fetch).mockResolvedValue(
      Response.json({
        marketing_content: [],
        total: 1,
        limit: 100,
        offset: 0,
      }),
    );
    render(<RealtimeMarketingContentProbe />);
    const source = FakeEventSource.instances[0]!;

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    act(() => {
      source.emit("message", {
        id: "marketing_content_event_01",
        type: "marketing.content.approval_requested",
        version: 1,
        channel: "organization:org_01",
        organization_id: "org_01",
        entity_type: "marketing_content_item",
        entity_id: "content_01",
        operation_id: "operation_marketing_content_01",
        actor: { user_id: "user_01", display_name: "Mara Chen" },
        payload: {
          contentItemId: "content_01",
          campaignId: "campaign_01",
          status: "in_review",
        },
        created_at: new Date().toISOString(),
      });
    });

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/workspaces/org_01/marketing-content?start=2026-09-01T00%3A00%3A00Z&end=2026-09-30T23%3A59%3A59Z",
      expect.any(Object),
    );
    expect(navigation.refresh).not.toHaveBeenCalled();
    expect(screen.getByText("marketing.content.approval_requested")).toBeInTheDocument();
  });

  it("ignores events for a different organization", () => {
    render(<RealtimeProbe />);
    const source = FakeEventSource.instances[0]!;

    act(() => {
      source.emit("message", {
        id: "event_other_org",
        type: "artist.updated",
        version: 1,
        channel: "organization:org_02",
        organization_id: "org_02",
        entity_type: "artist",
        entity_id: "artist_02",
        operation_id: "operation_other_org",
        actor: { user_id: "user_02", display_name: "Other User" },
        payload: {},
        created_at: new Date().toISOString(),
      });
    });

    expect(navigation.refresh).not.toHaveBeenCalled();
    expect(screen.getByText("no activity")).toBeInTheDocument();
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

  it("invalidates workspace people and targeted artist profile caches for profile realtime events", () => {
    const shouldInvalidate = (key: string) =>
      shouldInvalidateProfileRealtimeCacheKey({
        artistProfileId: "artist_profile_01",
        eventType: "profile.artist_profile_updated",
        key,
        organizationId: "org_01",
        profileId: "profile_01",
      });

    expect(shouldInvalidate("profiles:workspace-people:org_01::25:0")).toBe(true);
    expect(shouldInvalidate("profiles:artist-profile:org_01:artist_profile_01")).toBe(true);
    expect(shouldInvalidate("profiles:artist-profile:org_01:artist_profile_02")).toBe(false);
    expect(shouldInvalidate("profiles:workspace-people:org_02::25:0")).toBe(false);
  });

  it("invalidates workspace scoped artist profile caches when artist profile events lack an id", () => {
    expect(
      shouldInvalidateProfileRealtimeCacheKey({
        artistProfileId: null,
        eventType: "profile.artist_profile_updated",
        key: "profiles:artist-profile:org_01:artist_profile_01",
        organizationId: "org_01",
        profileId: "profile_01",
      }),
    ).toBe(true);
    expect(
      shouldInvalidateProfileRealtimeCacheKey({
        artistProfileId: null,
        eventType: "profile.updated",
        key: "profiles:artist-profile:org_01:artist_profile_01",
        organizationId: "org_01",
        profileId: "profile_01",
      }),
    ).toBe(false);
  });

  it("matches only analytics query cache keys for the event workspace", () => {
    expect(
      shouldInvalidateAnalyticsRealtimeCacheKey({
        key: "analytics:series:org_01:aggregation:sum|metric_definition_id:metric_01",
        workspaceId: "org_01",
      }),
    ).toBe(true);
    expect(
      shouldInvalidateAnalyticsRealtimeCacheKey({
        key: "analytics:series:org_02:aggregation:sum|metric_definition_id:metric_01",
        workspaceId: "org_01",
      }),
    ).toBe(false);
    expect(
      shouldInvalidateAnalyticsRealtimeCacheKey({
        key: "analytics:mutation:create-observation:org_01",
        workspaceId: "org_01",
      }),
    ).toBe(false);
  });

  it("matches only marketing content cache keys for the event workspace", () => {
    const shouldInvalidate = (key: string) =>
      shouldInvalidateMarketingContentRealtimeCacheKey({
        campaignId: "campaign_01",
        contentItemId: "content_01",
        key,
        workspaceId: "org_01",
      });

    expect(shouldInvalidate("marketing-content:workspace-list:org_01:default")).toBe(true);
    expect(shouldInvalidate("marketing-content:campaign-list:org_01:campaign_01")).toBe(true);
    expect(shouldInvalidate("marketing-content:detail:org_01:campaign_01:content_01")).toBe(true);
    expect(shouldInvalidate("marketing-content:workspace-list:org_02:default")).toBe(false);
    expect(shouldInvalidate("marketing-content:campaign-list:org_01:campaign_02")).toBe(false);
    expect(shouldInvalidate("marketing-content:detail:org_01:campaign_01:content_02")).toBe(false);
  });
});
