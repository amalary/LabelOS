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

export type AnalyticsQueryOptions = {
  metric_definition_id?: string | null;
  provider_id?: string | null;
  target_type?: string | null;
  target_id?: string | null;
  campaign_id?: string | null;
  artist_profile_id?: string | null;
  campaign_object_type?: string | null;
  campaign_object_id?: string | null;
  observed_start?: string | null;
  observed_end?: string | null;
  aggregation?: AnalyticsAggregation | null;
  limit?: number;
  offset?: number;
};

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

export const analyticsQueryKeys = {
  metricDefinitions: (workspaceId: string) => `analytics:metrics:${workspaceId}`,
  observations: (workspaceId: string, options?: AnalyticsQueryOptions) =>
    `analytics:observations:${workspaceId}:${stableQueryKey(options)}`,
  latest: (workspaceId: string, options?: AnalyticsQueryOptions) =>
    `analytics:latest:${workspaceId}:${stableQueryKey(options)}`,
  series: (workspaceId: string, options?: AnalyticsQueryOptions) =>
    `analytics:series:${workspaceId}:${stableQueryKey(options)}`,
  comparison: (workspaceId: string, options: AnalyticsComparisonOptions) =>
    `analytics:comparison:${workspaceId}:${stableQueryKey(options)}`,
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

function analyticsQuery(options?: AnalyticsQueryOptions | AnalyticsComparisonOptions): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(options ?? {})) {
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

export function clearAnalyticsCache() {
  cache.clear();
}

export function getAnalyticsMetricDefinitions(
  workspaceId: string,
): Promise<AnalyticsMetricDefinitionsList> {
  return analyticsJson<AnalyticsMetricDefinitionsList>(
    `/api/workspaces/${workspaceId}/analytics/metric-definitions`,
  );
}

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

export function getAnalyticsObservations(
  workspaceId: string,
  options?: AnalyticsQueryOptions,
): Promise<AnalyticsObservationsList> {
  return analyticsJson<AnalyticsObservationsList>(
    `/api/workspaces/${workspaceId}/analytics/observations${analyticsQuery(options)}`,
  );
}

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

export function getLatestAnalyticsObservation(
  workspaceId: string,
  options?: AnalyticsQueryOptions,
): Promise<AnalyticsObservation | null> {
  return analyticsJson<AnalyticsObservation | null>(
    `/api/workspaces/${workspaceId}/analytics/observations/latest${analyticsQuery(options)}`,
  );
}

export function getAnalyticsHistoricalSeries(
  workspaceId: string,
  options?: AnalyticsQueryOptions,
): Promise<AnalyticsHistoricalSeries> {
  return analyticsJson<AnalyticsHistoricalSeries>(
    `/api/workspaces/${workspaceId}/analytics/series${analyticsQuery(options)}`,
  );
}

export function getAnalyticsPreviousPeriodComparison(
  workspaceId: string,
  options: AnalyticsComparisonOptions,
): Promise<AnalyticsPreviousPeriodComparison> {
  return analyticsJson<AnalyticsPreviousPeriodComparison>(
    `/api/workspaces/${workspaceId}/analytics/comparison${analyticsQuery(options)}`,
  );
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
