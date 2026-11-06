"""Small volatile display cache; no disk, payload logging, or TTL extension on reads."""

import hashlib
import threading
import time
from uuid import uuid4

from labelos_api.research.errors import (
    FailureDetails,
    ProviderError,
    ProviderFailure,
)
from labelos_api.research.errors import (
    ProviderErrorCode as Code,
)


class DisplayCache:
    def __init__(self, *, ttl=60, capacity=128, clock=time.monotonic):
        self.ttl = ttl
        self.capacity = capacity
        self.clock = clock
        self.entries = {}
        self.pending = {}
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            entry = self.entries.get(key)
            if entry and entry[0] > self.clock():
                return entry[2]
            self.entries.pop(key, None)

    def put(self, key, value, *, pending_token=None):
        token = uuid4()
        with self.lock:
            if pending_token is not None and self.pending.get(key) != pending_token:
                return
            if len(self.entries) >= self.capacity:
                self.entries.pop(next(iter(self.entries)))
            self.entries[key] = (self.clock() + self.ttl, token, value)
        # Evict even when no further requests arrive. Timer captures only key and
        # random generation, never a response or credential. A read cannot renew it.
        timer = threading.Timer(self.ttl, self._expire, args=(key, token))
        timer.daemon = True
        timer.start()

    def _expire(self, key, token):
        with self.lock:
            entry = self.entries.get(key)
            if entry and entry[1] == token:
                self.entries.pop(key, None)

    def clear_workspace(self, workspace_id):
        with self.lock:
            for key in list(self.entries):
                if key[0] == workspace_id:
                    self.entries.pop(key)
            for key in list(self.pending):
                if key[0] == workspace_id:
                    self.pending.pop(key)


DISPLAY_CACHE = DisplayCache()


class CachedYouTubeClient:
    def __init__(self, client, cache=DISPLAY_CACHE):
        self.client = client
        self.cache = cache

    async def _call(self, operation, request, context):
        key = (
            context.workspace_id,
            context.collection_run_id,
            operation,
            hashlib.sha256(request.model_dump_json().encode()).hexdigest(),
        )
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        with self.cache.lock:
            if (
                key in self.cache.pending
                or len(self.cache.pending) >= self.cache.capacity
            ):
                raise ProviderError(
                    ProviderFailure(
                        context=context,
                        operation=operation,
                        details=FailureDetails(
                            code=Code.rate_limited, retry_after_seconds=1
                        ),
                    )
                )
            pending_token = uuid4()
            self.cache.pending[key] = pending_token
        try:
            result = await getattr(self.client, operation)(request, context=context)
            self.cache.put(key, result, pending_token=pending_token)
            return result
        except ProviderError as error:
            if error.failure.details.code == Code.data_unavailable:
                self.cache.clear_workspace(context.workspace_id)
            raise
        finally:
            with self.cache.lock:
                if self.cache.pending.get(key) == pending_token:
                    self.cache.pending.pop(key)

    async def search_artists(self, request, *, context):
        return await self._call("search_artists", request, context)

    async def lookup_artist(self, request, *, context):
        return await self._call("lookup_artist", request, context)

    async def observations(self, request, *, context):
        # Time-window contracts must be checked against a new fetch. Never stamp
        # old observations with today's time to make a cache hit appear fresh.
        try:
            return await self.client.observations(request, context=context)
        except ProviderError as error:
            if error.failure.details.code == Code.data_unavailable:
                self.cache.clear_workspace(context.workspace_id)
            raise
