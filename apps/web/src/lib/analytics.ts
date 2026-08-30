"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

export type AnalyticsApiErrorCode =
  "unauthorized" | "forbidden" | "not_found" | "conflict" | "network_failure";

export class AnalyticsApiError extends Error {
  constructor(
    readonly code: AnalyticsApiErrorCode,
    message: string,
    readonly status?: number,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "AnalyticsApiError";
  }
}

export type AnalyticsAggregation = "sum" | "average" | "min" | "max" | "latest" | "count";
export type AnalyticsMetricValueType = "integer" | "decimal" | "string" | "boolean" | "json";
export type AnalyticsComparisonStatus =
  "compared" | "no_current_data" | "no_previous_period" | "zero_previous_value";

export type AnalyticsProvider = {
  id: string;
  workspace_id: string;
  key: string;
  display_name: string;
  provider_type: string;
  external_account_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type AnalyticsTargetType = "workspace" | "artist_profile" | "campaign" | "campaign_object";
export type AnalyticsCampaignObjectType = "goal" | "milestone" | (string & {});

export type AnalyticsMetricDefinition = {
  id: string;
  workspace_id: string;
  provider: AnalyticsProvider;
  key: string;
  display_name: string;
  description: string | null;
  value_type: AnalyticsMetricValueType;
  default_unit: string | null;
  aggregation: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type AnalyticsMetricDefinitionsList = {
  metric_definitions: AnalyticsMetricDefinition[];
};

export type AnalyticsProvidersList = {
  providers: AnalyticsProvider[];
};

export type AnalyticsObservation = {
  id: string;
  workspace_id: string;
  metric_definition_id: string;
  metric_key: string;
  provider_id: string;
  provider_key: string;
  target_type: string;
  target_id: string | null;
  artist_profile_id: string | null;
  campaign_id: string | null;
  campaign_name: string | null;
  campaign_object_type: string | null;
  campaign_object_id: string | null;
  value_numeric: string | null;
  value_text: string | null;
  value_boolean: boolean | null;
  value_json: Record<string, unknown> | null;
  unit: string | null;
  observed_at: string;
  source_record_id: string | null;
  idempotency_key: string | null;
  dimensions: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type AnalyticsObservationsList = {
  observations: AnalyticsObservation[];
  total: number;
  limit: number;
  offset: number;
};

export type AnalyticsSeriesPoint = {
  bucket_date: string;
  value: string | boolean | Record<string, unknown> | null;
  observation_count: number;
};

export type AnalyticsHistoricalSeries = {
  aggregation: AnalyticsAggregation;
  points: AnalyticsSeriesPoint[];
  value_type: AnalyticsMetricValueType | null;
  unit: string | null;
  provider_id: string | null;
  metric_definition_id: string | null;
  observation_count: number;
};

export type AnalyticsPreviousPeriodComparison = {
  aggregation: AnalyticsAggregation;
  current_start: string;
  current_end: string;
  previous_start: string;
  previous_end: string;
  current_value: string | boolean | Record<string, unknown> | null;
  previous_value: string | boolean | Record<string, unknown> | null;
  current_observation_count: number;
  previous_observation_count: number;
  absolute_change: string | null;
  percentage_change: string | null;
  status: AnalyticsComparisonStatus;
};

export type AnalyticsSummaryResult = AnalyticsHistoricalSeries;

export type AnalyticsQueryOptions = {
  metric?: string | null;
  provider?: string | null;
  artist?: string | null;
  campaign?: string | null;
  metric_definition_id?: string | null;
  provider_id?: string | null;
  target_type?: AnalyticsTargetType | string | null;
  target_id?: string | null;
  campaign_id?: string | null;
  artist_profile_id?: string | null;
  campaign_object_type?: string | null;
  campaign_object_id?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  observed_start?: string | null;
  observed_end?: string | null;
  aggregation?: AnalyticsAggregation | null;
  limit?: number;
  offset?: number;
};

export type AnalyticsObservationFilters = Omit<AnalyticsQueryOptions, "aggregation">;

export type AnalyticsMetricDefinitionCreate = {
  key: string;
  display_name: string;
  provider: {
    key: string;
    display_name?: string | null;
    provider_type?: string;
    external_account_id?: string | null;
    metadata?: Record<string, unknown> | null;
  };
  description?: string | null;
  value_type: AnalyticsMetricValueType;
  default_unit?: string | null;
  aggregation?: string | null;
  metadata?: Record<string, unknown> | null;
};

export type AnalyticsObservationCreate = {
  metric_definition_id: string;
  target_type: string;
  observed_at: string;
  target_id?: string | null;
  artist_profile_id?: string | null;
  campaign_id?: string | null;
  campaign_object_type?: string | null;
  campaign_object_id?: string | null;
  value_numeric?: string | number | null;
  value_text?: string | null;
  value_boolean?: boolean | null;
  value_json?: Record<string, unknown> | null;
  unit?: string | null;
  source_record_id?: string | null;
  idempotency_key?: string | null;
  dimensions?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
};

export type AnalyticsComparisonOptions = AnalyticsQueryOptions & {
  current_start: string;
  current_end: string;
};

export type AnalyticsResourceState<T> = {
  data: T | null;
  error: AnalyticsApiError | null;
  isLoading: boolean;
  reload: () => Promise<T>;
};

export type AnalyticsMutationState<TData, TVariables> = {
  data: TData | null;
  error: AnalyticsApiError | null;
  isMutating: boolean;
  mutate: (variables: TVariables) => Promise<TData>;
  reset: () => void;
};

type CacheEntry<T> = {
  data: T | null;
  error: AnalyticsApiError | null;
  fetcher: (() => Promise<T>) | null;
  isLoading: boolean;
  listeners: Set<() => void>;
  promise: Promise<T> | null;
  version: number;
};

const cache = new Map<string, CacheEntry<unknown>>();
const mutationListeners = new Set<() => void>();
let mutationVersion = 0;
let activeMutationCount = 0;

export const analyticsQueryKeys = {
  metricDefinitions: (workspaceId: string) => `analytics:metrics:${workspaceId}`,
  providers: (workspaceId: string) => `analytics:providers:${workspaceId}`,
  observations: (workspaceId: string, options?: AnalyticsQueryOptions) =>
    `analytics:observations:${workspaceId}:${stableQueryKey(normalizeAnalyticsQueryOptions(options))}`,
  latest: (workspaceId: string, options?: AnalyticsQueryOptions) =>
    `analytics:latest:${workspaceId}:${stableQueryKey(normalizeAnalyticsQueryOptions(options))}`,
  series: (workspaceId: string, options?: AnalyticsQueryOptions) =>
    `analytics:series:${workspaceId}:${stableQueryKey(normalizeAnalyticsQueryOptions(options))}`,
  summary: (workspaceId: string, options?: AnalyticsQueryOptions) =>
    `analytics:summary:${workspaceId}:${stableQueryKey(normalizeAnalyticsQueryOptions(options))}`,
  comparison: (workspaceId: string, options: AnalyticsComparisonOptions) =>
    `analytics:comparison:${workspaceId}:${stableQueryKey(normalizeAnalyticsQueryOptions(options))}`,
};

function entryFor<T>(key: string): CacheEntry<T> {
  let entry = cache.get(key) as CacheEntry<T> | undefined;
  if (!entry) {
    entry = {
      data: null,
      error: null,
      fetcher: null,
      isLoading: false,
      listeners: new Set(),
      promise: null,
      version: 0,
    };
    cache.set(key, entry as CacheEntry<unknown>);
  }
  return entry;
}

function emit(entry: CacheEntry<unknown>) {
  entry.version += 1;
  for (const listener of entry.listeners) {
    listener();
  }
}

function emitMutationChange() {
  mutationVersion += 1;
  for (const listener of mutationListeners) {
    listener();
  }
}

function stableQueryKey(options?: Record<string, unknown> | null): string {
  if (!options) {
    return "default";
  }
  return Object.entries(options)
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}:${String(value)}`)
    .join("|");
}

function normalizeAnalyticsQueryOptions(
  options?: AnalyticsQueryOptions | AnalyticsComparisonOptions,
): Record<string, string | number | boolean | null | undefined> {
  if (!options) {
    return {};
  }
  const normalized: Record<string, string | number | boolean | null | undefined> = {
    ...options,
  };
  if (normalized.metric_definition_id === undefined && options.metric !== undefined) {
    normalized.metric_definition_id = options.metric;
  }
  if (normalized.provider_id === undefined && options.provider !== undefined) {
    normalized.provider_id = options.provider;
  }
  if (normalized.artist_profile_id === undefined && options.artist !== undefined) {
    normalized.artist_profile_id = options.artist;
  }
  if (normalized.campaign_id === undefined && options.campaign !== undefined) {
    normalized.campaign_id = options.campaign;
  }
  if (normalized.observed_start === undefined && options.start_date !== undefined) {
    normalized.observed_start = options.start_date;
  }
  if (normalized.observed_end === undefined && options.end_date !== undefined) {
    normalized.observed_end = options.end_date;
  }
  delete normalized.metric;
  delete normalized.provider;
  delete normalized.artist;
  delete normalized.campaign;
  delete normalized.start_date;
  delete normalized.end_date;
  return normalized;
}

function analyticsQuery(options?: AnalyticsQueryOptions | AnalyticsComparisonOptions): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(normalizeAnalyticsQueryOptions(options))) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

function toAnalyticsApiError(status: number): AnalyticsApiError {
  if (status === 401) {
    return new AnalyticsApiError("unauthorized", "Sign in again to load analytics.", status);
  }
  if (status === 403) {
    return new AnalyticsApiError("forbidden", "You do not have access to analytics.", status);
  }
  if (status === 404) {
    return new AnalyticsApiError("not_found", "Analytics data was not found.", status);
  }
  if (status === 409) {
    return new AnalyticsApiError("conflict", "Analytics data could not be changed.", status);
  }
  if (status === 400 || status === 422) {
    return new AnalyticsApiError("conflict", "Analytics query parameters are invalid.", status);
  }
  return new AnalyticsApiError("network_failure", "Analytics data could not be loaded.", status);
}

async function analyticsJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      cache: "no-store",
      headers,
    });
  } catch (error) {
    throw new AnalyticsApiError(
      "network_failure",
      "Unable to reach the analytics API.",
      undefined,
      {
        cause: error,
      },
    );
  }

  if (!response.ok) {
    throw toAnalyticsApiError(response.status);
  }

  return (await response.json()) as T;
}

async function loadResource<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
  const entry = entryFor<T>(key);
  entry.fetcher = fetcher;
  if (entry.promise) {
    return entry.promise;
  }

  entry.error = null;
  entry.isLoading = true;
  emit(entry);

  entry.promise = fetcher()
    .then((data) => {
      entry.data = data;
      entry.error = null;
      return data;
    })
    .catch((error) => {
      entry.error =
        error instanceof AnalyticsApiError
          ? error
          : new AnalyticsApiError(
              "network_failure",
              "Analytics data could not be loaded.",
              undefined,
              { cause: error },
            );
      throw entry.error;
    })
    .finally(() => {
      entry.isLoading = false;
      entry.promise = null;
      emit(entry);
    });

  emit(entry);
  return entry.promise;
}

function useAnalyticsResource<T>(
  key: string | null,
  fetcher: (() => Promise<T>) | null,
): AnalyticsResourceState<T> {
  const subscribe = useCallback(
    (listener: () => void) => {
      if (!key) {
        return () => undefined;
      }
      const entry = entryFor<T>(key);
      entry.listeners.add(listener);
      return () => {
        entry.listeners.delete(listener);
      };
    },
    [key],
  );

  const getSnapshot = useCallback(() => {
    if (!key) {
      return 0;
    }
    return entryFor<T>(key).version;
  }, [key]);

  useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  useEffect(() => {
    if (!key || !fetcher) {
      return;
    }
    const entry = entryFor<T>(key);
    entry.fetcher = fetcher;
    if (entry.data === null && !entry.isLoading) {
      void loadResource(key, fetcher).catch(() => undefined);
    }
  }, [fetcher, key]);

  const reload = useCallback(async () => {
    if (!key || !fetcher) {
      throw new AnalyticsApiError("not_found", "An analytics resource key is required.");
    }
    return loadResource(key, fetcher);
  }, [fetcher, key]);

  const entry = key ? entryFor<T>(key) : null;
  return {
    data: entry?.data ?? null,
    error: entry?.error ?? null,
    isLoading: entry?.isLoading ?? false,
    reload,
  };
}

export function invalidateAnalyticsCache(predicate?: (key: string) => boolean) {
  for (const [key, entry] of cache.entries()) {
    if (predicate && !predicate(key)) {
      continue;
    }
    entry.data = null;
    entry.error = null;
    if (entry.fetcher) {
      void loadResource(key, entry.fetcher).catch(() => undefined);
    } else {
      emit(entry);
    }
  }
}

export function shouldInvalidateAnalyticsRealtimeCacheKey({
  key,
  workspaceId,
}: {
  key: string;
  workspaceId: string;
}) {
  return (
    key === analyticsQueryKeys.metricDefinitions(workspaceId) ||
    key === analyticsQueryKeys.providers(workspaceId) ||
    key.startsWith(`analytics:observations:${workspaceId}:`) ||
    key.startsWith(`analytics:latest:${workspaceId}:`) ||
    key.startsWith(`analytics:series:${workspaceId}:`) ||
    key.startsWith(`analytics:summary:${workspaceId}:`) ||
    key.startsWith(`analytics:comparison:${workspaceId}:`)
  );
}

export function invalidateAnalyticsWorkspaceCache(workspaceId: string) {
  invalidateAnalyticsCache((key) =>
    shouldInvalidateAnalyticsRealtimeCacheKey({ key, workspaceId }),
  );
}

export function clearAnalyticsCache() {
  cache.clear();
  activeMutationCount = 0;
  mutationVersion = 0;
}

export function listAnalyticsMetricDefinitions(
  workspaceId: string,
): Promise<AnalyticsMetricDefinitionsList> {
  return analyticsJson<AnalyticsMetricDefinitionsList>(
    `/api/workspaces/${workspaceId}/analytics/metric-definitions`,
  );
}

export const getAnalyticsMetricDefinitions = listAnalyticsMetricDefinitions;

export function listAnalyticsProviders(workspaceId: string): Promise<AnalyticsProvidersList> {
  return analyticsJson<AnalyticsProvidersList>(
    `/api/workspaces/${workspaceId}/analytics/providers`,
  );
}

export const getAnalyticsProviders = listAnalyticsProviders;

export function createAnalyticsMetricDefinition(
  workspaceId: string,
  payload: AnalyticsMetricDefinitionCreate,
): Promise<AnalyticsMetricDefinition> {
  return analyticsJson<AnalyticsMetricDefinition>(
    `/api/workspaces/${workspaceId}/analytics/metric-definitions`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function listAnalyticsObservations(
  workspaceId: string,
  options?: AnalyticsQueryOptions,
): Promise<AnalyticsObservationsList> {
  return analyticsJson<AnalyticsObservationsList>(
    `/api/workspaces/${workspaceId}/analytics/observations${analyticsQuery(options)}`,
  );
}

export const getAnalyticsObservations = listAnalyticsObservations;

export function createAnalyticsObservation(
  workspaceId: string,
  payload: AnalyticsObservationCreate,
): Promise<AnalyticsObservation> {
  return analyticsJson<AnalyticsObservation>(
    `/api/workspaces/${workspaceId}/analytics/observations`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function queryLatestAnalyticsObservation(
  workspaceId: string,
  options?: AnalyticsQueryOptions,
): Promise<AnalyticsObservation | null> {
  return analyticsJson<AnalyticsObservation | null>(
    `/api/workspaces/${workspaceId}/analytics/observations/latest${analyticsQuery(options)}`,
  );
}

export const getLatestAnalyticsObservation = queryLatestAnalyticsObservation;

export function queryMetricHistory(
  workspaceId: string,
  options?: AnalyticsQueryOptions,
): Promise<AnalyticsHistoricalSeries> {
  return analyticsJson<AnalyticsHistoricalSeries>(
    `/api/workspaces/${workspaceId}/analytics/series${analyticsQuery(options)}`,
  );
}

export const getAnalyticsHistoricalSeries = queryMetricHistory;

export function queryAnalyticsSummary(
  workspaceId: string,
  options?: AnalyticsQueryOptions,
): Promise<AnalyticsSummaryResult> {
  return analyticsJson<AnalyticsSummaryResult>(
    `/api/workspaces/${workspaceId}/analytics/summary${analyticsQuery(options)}`,
  );
}

export function queryAnalyticsPreviousPeriodComparison(
  workspaceId: string,
  options: AnalyticsComparisonOptions,
): Promise<AnalyticsPreviousPeriodComparison> {
  return analyticsJson<AnalyticsPreviousPeriodComparison>(
    `/api/workspaces/${workspaceId}/analytics/comparison${analyticsQuery(options)}`,
  );
}

export const getAnalyticsPreviousPeriodComparison = queryAnalyticsPreviousPeriodComparison;

export function queryObservationsByArtist(
  workspaceId: string,
  artistProfileId: string,
  options?: AnalyticsObservationFilters,
): Promise<AnalyticsObservationsList> {
  return listAnalyticsObservations(workspaceId, {
    ...options,
    artist_profile_id: artistProfileId,
  });
}

export function queryObservationsByCampaign(
  workspaceId: string,
  campaignId: string,
  options?: AnalyticsObservationFilters & { include_child_objects?: boolean },
): Promise<AnalyticsObservationsList> {
  const { include_child_objects = true, ...filters } = options ?? {};
  return listAnalyticsObservations(workspaceId, {
    ...filters,
    campaign_id: campaignId,
    ...(include_child_objects
      ? {}
      : {
          target_id: campaignId,
          target_type: "campaign",
        }),
  });
}

export function queryObservationsByCampaignChildObject(
  workspaceId: string,
  campaignId: string,
  campaignObjectType: AnalyticsCampaignObjectType,
  campaignObjectId: string,
  options?: AnalyticsObservationFilters,
): Promise<AnalyticsObservationsList> {
  return listAnalyticsObservations(workspaceId, {
    ...options,
    campaign_id: campaignId,
    campaign_object_id: campaignObjectId,
    campaign_object_type: campaignObjectType,
    target_id: campaignObjectId,
    target_type: "campaign_object",
  });
}

export function useAnalyticsMetricDefinitions(
  workspaceId: string | null,
): AnalyticsResourceState<AnalyticsMetricDefinitionsList> {
  const key = workspaceId ? analyticsQueryKeys.metricDefinitions(workspaceId) : null;
  const fetcher = useCallback(
    () => getAnalyticsMetricDefinitions(workspaceId ?? ""),
    [workspaceId],
  );
  return useAnalyticsResource(key, workspaceId ? fetcher : null);
}

export function useAnalyticsObservations(
  workspaceId: string | null,
  options: AnalyticsQueryOptions | null,
): AnalyticsResourceState<AnalyticsObservationsList> {
  const key = workspaceId && options ? analyticsQueryKeys.observations(workspaceId, options) : null;
  const fetcher = useCallback(
    () => listAnalyticsObservations(workspaceId ?? "", options as AnalyticsQueryOptions),
    [options, workspaceId],
  );
  return useAnalyticsResource(key, workspaceId && options ? fetcher : null);
}

export function useAnalyticsObservationsByArtist(
  workspaceId: string | null,
  artistProfileId: string | null,
  options?: AnalyticsObservationFilters,
): AnalyticsResourceState<AnalyticsObservationsList> {
  const queryOptions =
    artistProfileId === null
      ? null
      : {
          ...options,
          artist_profile_id: artistProfileId,
        };
  const key =
    workspaceId && queryOptions ? analyticsQueryKeys.observations(workspaceId, queryOptions) : null;
  const fetcher = useCallback(
    () => queryObservationsByArtist(workspaceId ?? "", artistProfileId ?? "", options),
    [artistProfileId, options, workspaceId],
  );
  return useAnalyticsResource(key, workspaceId && artistProfileId ? fetcher : null);
}

export function useAnalyticsObservationsByCampaign(
  workspaceId: string | null,
  campaignId: string | null,
  options?: AnalyticsObservationFilters & { include_child_objects?: boolean },
): AnalyticsResourceState<AnalyticsObservationsList> {
  const includeChildObjects = options?.include_child_objects ?? true;
  const queryOptions =
    campaignId === null
      ? null
      : {
          ...options,
          campaign_id: campaignId,
          ...(includeChildObjects
            ? {}
            : {
                target_id: campaignId,
                target_type: "campaign",
              }),
        };
  const key =
    workspaceId && queryOptions ? analyticsQueryKeys.observations(workspaceId, queryOptions) : null;
  const fetcher = useCallback(
    () => queryObservationsByCampaign(workspaceId ?? "", campaignId ?? "", options),
    [campaignId, options, workspaceId],
  );
  return useAnalyticsResource(key, workspaceId && campaignId ? fetcher : null);
}

export function useAnalyticsObservationsByCampaignChildObject(
  workspaceId: string | null,
  campaignId: string | null,
  campaignObjectType: AnalyticsCampaignObjectType | null,
  campaignObjectId: string | null,
  options?: AnalyticsObservationFilters,
): AnalyticsResourceState<AnalyticsObservationsList> {
  const queryOptions =
    campaignId && campaignObjectType && campaignObjectId
      ? {
          ...options,
          campaign_id: campaignId,
          campaign_object_id: campaignObjectId,
          campaign_object_type: campaignObjectType,
          target_id: campaignObjectId,
          target_type: "campaign_object",
        }
      : null;
  const key =
    workspaceId && queryOptions ? analyticsQueryKeys.observations(workspaceId, queryOptions) : null;
  const fetcher = useCallback(
    () =>
      queryObservationsByCampaignChildObject(
        workspaceId ?? "",
        campaignId ?? "",
        campaignObjectType ?? "",
        campaignObjectId ?? "",
        options,
      ),
    [campaignId, campaignObjectId, campaignObjectType, options, workspaceId],
  );
  return useAnalyticsResource(
    key,
    workspaceId && campaignId && campaignObjectType && campaignObjectId ? fetcher : null,
  );
}

export function useLatestAnalyticsObservation(
  workspaceId: string | null,
  options: AnalyticsQueryOptions | null,
): AnalyticsResourceState<AnalyticsObservation | null> {
  const key = workspaceId && options ? analyticsQueryKeys.latest(workspaceId, options) : null;
  const fetcher = useCallback(
    () => queryLatestAnalyticsObservation(workspaceId ?? "", options as AnalyticsQueryOptions),
    [options, workspaceId],
  );
  return useAnalyticsResource(key, workspaceId && options ? fetcher : null);
}

export function useAnalyticsHistoricalSeries(
  workspaceId: string | null,
  options: AnalyticsQueryOptions | null,
): AnalyticsResourceState<AnalyticsHistoricalSeries> {
  const key = workspaceId && options ? analyticsQueryKeys.series(workspaceId, options) : null;
  const fetcher = useCallback(
    () => getAnalyticsHistoricalSeries(workspaceId ?? "", options as AnalyticsQueryOptions),
    [options, workspaceId],
  );
  return useAnalyticsResource(key, workspaceId && options ? fetcher : null);
}

export function useAnalyticsSummary(
  workspaceId: string | null,
  options: AnalyticsQueryOptions | null,
): AnalyticsResourceState<AnalyticsSummaryResult> {
  const key = workspaceId && options ? analyticsQueryKeys.summary(workspaceId, options) : null;
  const fetcher = useCallback(
    () => queryAnalyticsSummary(workspaceId ?? "", options as AnalyticsQueryOptions),
    [options, workspaceId],
  );
  return useAnalyticsResource(key, workspaceId && options ? fetcher : null);
}

export function useAnalyticsPreviousPeriodComparison(
  workspaceId: string | null,
  options: AnalyticsComparisonOptions | null,
): AnalyticsResourceState<AnalyticsPreviousPeriodComparison> {
  const key = workspaceId && options ? analyticsQueryKeys.comparison(workspaceId, options) : null;
  const fetcher = useCallback(
    () =>
      getAnalyticsPreviousPeriodComparison(
        workspaceId ?? "",
        options as AnalyticsComparisonOptions,
      ),
    [options, workspaceId],
  );
  return useAnalyticsResource(key, workspaceId && options ? fetcher : null);
}

export function useCreateAnalyticsMetricDefinition(
  workspaceId: string | null,
): AnalyticsMutationState<AnalyticsMetricDefinition, AnalyticsMetricDefinitionCreate> {
  const getVersion = useCallback(() => mutationVersion, []);
  const subscribe = useCallback((listener: () => void) => {
    mutationListeners.add(listener);
    return () => {
      mutationListeners.delete(listener);
    };
  }, []);
  useSyncExternalStore(subscribe, getVersion, getVersion);

  const entry = entryFor<AnalyticsMetricDefinition>(
    `analytics:mutation:create-metric:${workspaceId ?? "none"}`,
  );
  const mutate = useCallback(
    async (payload: AnalyticsMetricDefinitionCreate) => {
      if (!workspaceId) {
        throw new AnalyticsApiError("not_found", "A workspace resource key is required.");
      }
      activeMutationCount += 1;
      entry.isLoading = true;
      entry.error = null;
      emitMutationChange();
      try {
        const metricDefinition = await createAnalyticsMetricDefinition(workspaceId, payload);
        entry.data = metricDefinition;
        entry.error = null;
        invalidateAnalyticsCache(
          (key) =>
            key === analyticsQueryKeys.metricDefinitions(workspaceId) ||
            key === analyticsQueryKeys.providers(workspaceId),
        );
        return metricDefinition;
      } catch (error) {
        entry.error =
          error instanceof AnalyticsApiError
            ? error
            : new AnalyticsApiError(
                "network_failure",
                "Analytics metric creation failed.",
                undefined,
                {
                  cause: error,
                },
              );
        throw entry.error;
      } finally {
        activeMutationCount = Math.max(0, activeMutationCount - 1);
        entry.isLoading = false;
        emitMutationChange();
      }
    },
    [entry, workspaceId],
  );

  const reset = useCallback(() => {
    entry.data = null;
    entry.error = null;
    entry.isLoading = false;
    emitMutationChange();
  }, [entry]);

  return {
    data: entry.data,
    error: entry.error,
    isMutating: entry.isLoading || activeMutationCount > 0,
    mutate,
    reset,
  };
}

export function useAnalyticsProviders(
  workspaceId: string | null,
): AnalyticsResourceState<AnalyticsProvidersList> {
  const key = workspaceId ? analyticsQueryKeys.providers(workspaceId) : null;
  const fetcher = useCallback(() => getAnalyticsProviders(workspaceId ?? ""), [workspaceId]);
  return useAnalyticsResource(key, workspaceId ? fetcher : null);
}

export function useCreateAnalyticsObservation(
  workspaceId: string | null,
): AnalyticsMutationState<AnalyticsObservation, AnalyticsObservationCreate> {
  const getVersion = useCallback(() => mutationVersion, []);
  const subscribe = useCallback((listener: () => void) => {
    mutationListeners.add(listener);
    return () => {
      mutationListeners.delete(listener);
    };
  }, []);
  useSyncExternalStore(subscribe, getVersion, getVersion);

  const entry = entryFor<AnalyticsObservation>(
    `analytics:mutation:create-observation:${workspaceId ?? "none"}`,
  );
  const mutate = useCallback(
    async (payload: AnalyticsObservationCreate) => {
      if (!workspaceId) {
        throw new AnalyticsApiError("not_found", "A workspace resource key is required.");
      }
      activeMutationCount += 1;
      entry.isLoading = true;
      entry.error = null;
      emitMutationChange();
      try {
        const observation = await createAnalyticsObservation(workspaceId, payload);
        entry.data = observation;
        entry.error = null;
        invalidateAnalyticsCache(
          (key) => key.startsWith(`analytics:`) && key.includes(workspaceId),
        );
        return observation;
      } catch (error) {
        entry.error =
          error instanceof AnalyticsApiError
            ? error
            : new AnalyticsApiError(
                "network_failure",
                "Analytics observation creation failed.",
                undefined,
                {
                  cause: error,
                },
              );
        throw entry.error;
      } finally {
        activeMutationCount = Math.max(0, activeMutationCount - 1);
        entry.isLoading = false;
        emitMutationChange();
      }
    },
    [entry, workspaceId],
  );

  const reset = useCallback(() => {
    entry.data = null;
    entry.error = null;
    entry.isLoading = false;
    emitMutationChange();
  }, [entry]);

  return {
    data: entry.data,
    error: entry.error,
    isMutating: entry.isLoading || activeMutationCount > 0,
    mutate,
    reset,
  };
}
