"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

type CacheEntry<T, E> = {
  data: T | null;
  error: E | null;
  fetcher: (() => Promise<T>) | null;
  isLoading: boolean;
  listeners: Set<() => void>;
  promise: Promise<T> | null;
  version: number;
  generation: number;
};

/** Each domain owns an isolated cache and supplies its existing error contract. */
export function createResourceCache<E extends Error>(options: {
  toError: (error: unknown) => E;
  missingKeyError: () => E;
}) {
  const entries = new Map<string, CacheEntry<unknown, E>>();

  function entryFor<T>(key: string): CacheEntry<T, E> {
    let entry = entries.get(key) as CacheEntry<T, E> | undefined;
    if (!entry) {
      entry = {
        data: null,
        error: null,
        fetcher: null,
        isLoading: false,
        listeners: new Set(),
        promise: null,
        version: 0,
        generation: 0,
      };
      entries.set(key, entry as CacheEntry<unknown, E>);
    }
    return entry;
  }

  function emit(entry: CacheEntry<unknown, E>) {
    entry.version += 1;
    for (const listener of entry.listeners) listener();
  }

  function load<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
    const entry = entryFor<T>(key);
    entry.fetcher = fetcher;
    if (entry.promise) return entry.promise;

    const generation = entry.generation;
    const isCurrent = () => entries.get(key) === entry && entry.generation === generation;
    entry.error = null;
    entry.isLoading = true;
    entry.promise = Promise.resolve()
      .then(fetcher)
      .then((data) => {
        if (isCurrent()) {
          entry.data = data;
          entry.error = null;
        }
        return data;
      })
      .catch((error: unknown) => {
        const typedError = options.toError(error);
        if (isCurrent()) entry.error = typedError;
        throw typedError;
      })
      .finally(() => {
        entry.promise = null;
        entry.isLoading = false;
        if (entries.get(key) !== entry) return;
        if (entry.generation !== generation && entry.fetcher) {
          // Coalesce invalidations during a request into one fresh read, even
          // when the old request fails. Never expose its superseded response.
          void load(key, entry.fetcher).catch(() => undefined);
        } else {
          emit(entry);
        }
      });
    emit(entry);
    return entry.promise;
  }

  function invalidate(predicate?: (key: string) => boolean) {
    for (const [key, entry] of entries) {
      if (predicate && !predicate(key)) continue;
      entry.generation += 1;
      entry.data = null;
      entry.error = null;
      if (entry.fetcher && !entry.promise) {
        void load(key, entry.fetcher).catch(() => undefined);
      } else {
        emit(entry);
      }
    }
  }

  return {
    entryFor,
    emit,
    load,
    invalidate,
    clear: () => entries.clear(),
    missingKeyError: options.missingKeyError,
  };
}

export function useCachedResource<T, E extends Error>(
  cache: ReturnType<typeof createResourceCache<E>>,
  key: string | null,
  fetcher: (() => Promise<T>) | null,
) {
  const subscribe = useCallback(
    (listener: () => void) => {
      if (!key) return () => undefined;
      const entry = cache.entryFor<T>(key);
      entry.listeners.add(listener);
      return () => {
        entry.listeners.delete(listener);
      };
    },
    [cache, key],
  );
  const getSnapshot = useCallback(() => (key ? cache.entryFor<T>(key).version : 0), [cache, key]);
  useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  useEffect(() => {
    if (!key || !fetcher) return;
    const entry = cache.entryFor<T>(key);
    entry.fetcher = fetcher;
    if (entry.data === null && !entry.isLoading && !entry.error) {
      void cache.load(key, fetcher).catch(() => undefined);
    }
  }, [cache, key, fetcher]);

  const reload = useCallback(async () => {
    if (!key || !fetcher) throw cache.missingKeyError();
    return cache.load(key, fetcher);
  }, [cache, key, fetcher]);
  const entry = key ? cache.entryFor<T>(key) : null;
  return {
    data: entry?.data ?? null,
    error: entry?.error ?? null,
    isLoading: entry?.isLoading ?? false,
    reload,
  };
}
