import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { createResourceCache, useCachedResource } from "./resource-cache";

function createCache() {
  return createResourceCache({
    toError: (error) => (error instanceof Error ? error : new Error(String(error))),
    missingKeyError: () => new Error("Missing key"),
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

describe("resource cache", () => {
  it.each([false, true])(
    "coalesces invalidations and discards obsolete responses (failure: %s)",
    async (fail) => {
      const cache = createCache();
      const old = deferred<string>();
      const fresh = deferred<string>();
      const fetcher = vi.fn().mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
      const first = cache.load("one", fetcher);
      expect(cache.load("one", fetcher)).toBe(first);
      cache.invalidate();
      cache.invalidate();
      const handled = first.catch(() => undefined);
      if (fail) old.reject(new Error("Old failure"));
      else old.resolve("Old snapshot");
      await handled;
      expect(fetcher).toHaveBeenCalledTimes(2);
      expect(cache.entryFor("one")).toMatchObject({ data: null, error: null, isLoading: true });
      const current = cache.load("one", fetcher);
      fresh.resolve("Fresh snapshot");
      await current;
      expect(cache.entryFor("one")).toMatchObject({ data: "Fresh snapshot", isLoading: false });
    },
  );

  it("honors key filters and does not revive cleared entries", async () => {
    const cache = createCache();
    const pending = deferred<string>();
    const fetcher = vi.fn(() => pending.promise);
    await cache.load("other-workspace", async () => "Keep");
    const first = cache.load("workspace", fetcher);
    cache.invalidate((key) => key === "workspace");
    expect(cache.entryFor("other-workspace").data).toBe("Keep");
    cache.clear();
    await cache.load("workspace", async () => "New session");
    pending.resolve("Old session");
    await first;
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(cache.entryFor("workspace").data).toBe("New session");
  });

  it("allows a failed resource to be retried explicitly without looping on rerender", async () => {
    const cache = createCache();
    const error = new Error("Offline");
    const fetcher = vi.fn().mockRejectedValueOnce(error).mockResolvedValueOnce("Recovered");
    const { result, rerender } = renderHook(() => useCachedResource(cache, "key", () => fetcher()));
    await waitFor(() => expect(result.current.error).toBe(error));
    rerender();
    expect(fetcher).toHaveBeenCalledTimes(1);
    await act(async () => {
      await result.current.reload();
    });
    expect(result.current.data).toBe("Recovered");
    expect(result.current.error).toBeNull();
  });

  it("reports synchronous fetch failures and supports a later retry", async () => {
    const cache = createCache();
    await expect(
      cache.load("key", () => {
        throw new Error("Synchronous");
      }),
    ).rejects.toThrow("Synchronous");
    expect(cache.entryFor("key").isLoading).toBe(false);
    await expect(cache.load("key", async () => "Recovered")).resolves.toBe("Recovered");
  });
});
