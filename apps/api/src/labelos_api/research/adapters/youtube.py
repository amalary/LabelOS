"""Public channel candidates and counters, not YouTube Music or Analytics."""

import asyncio
import math
import random

import httpx

from labelos_api.research.adapters.common import (
    Code,
    HTTPAdapter,
    identifier,
    object_data,
    records,
    source_id,
)
from labelos_api.research.contracts import (
    ArtistLookupResponse,
    ArtistSearchResponse,
    AuthenticationRequirements,
    NormalizedArtist,
    ProviderDescriptor,
)
from labelos_api.research.errors import AdapterFailure, _retry_after, normalize_failure
from labelos_api.research.youtube_quota import reset_time

CHANNEL_ID = r"UC[A-Za-z0-9_-]{22}"


class YouTubeAdapter(HTTPAdapter):
    base_url = "https://www.googleapis.com/youtube/v3/"
    license_url = "https://developers.google.com/youtube/terms/developer-policies"
    retention_days = 30
    metrics = {
        "youtube.channel.views": "viewCount",
        "youtube.channel.subscribers": "subscriberCount",
        "youtube.channel.videos": "videoCount",
    }
    descriptor = ProviderDescriptor(
        key="youtube",
        display_name="YouTube",
        adapter_version="1.0.0",
        capabilities=frozenset({"search_artists", "lookup_artist", "observations"}),
        resources=frozenset({"artist", "observation"}),
        authentication=AuthenticationRequirements(
            method="api_key", required_fields=("api_key",)
        ),
        max_page_size=50,
    )

    # Assigned only by the authorized research service. Adapter contract callers
    # retain the original single-attempt behavior unless a budget is injected.
    quota = None

    async def get(self, path, params, credentials):
        if self.quota is None:
            return await super().get(path, params, credentials)
        attempts = 1 if path == "search" else 2
        for attempt in range(attempts):
            # A rejected reservation must not itself extend the cooldown.
            await self.quota.reserve(path)
            try:
                async with asyncio.timeout(5):
                    return await super().get(path, params, credentials)
            except Exception as error:
                failure = normalize_failure(error)
            transient = failure.code in {Code.timeout, Code.provider_unavailable}
            delay = max(failure.retry_after_seconds or 0, 2**attempt + random.random())
            if failure.code == Code.quota_exceeded:
                delay = max(
                    1, (reset_time(self.clock()) - self.clock()).total_seconds()
                )
            elif failure.code == Code.authentication_failed:
                delay = 60
            if transient or failure.code in {
                Code.quota_exceeded,
                Code.rate_limited,
                Code.authentication_failed,
            }:
                await self.quota.defer(path, math.ceil(delay))
            if not transient or attempt + 1 == attempts or delay > 5:
                break
            await asyncio.sleep(math.ceil(delay))
        # Do not retain upstream exceptions (which can contain a key-bearing URL).
        raise AdapterFailure(
            failure.code,
            retry_after_seconds=(
                math.ceil(delay)
                if failure.code
                in {Code.quota_exceeded, Code.rate_limited, Code.provider_unavailable}
                else None
            ),
        ) from None

    def http_error(self, response: httpx.Response) -> None:
        if response.status_code not in {400, 403}:
            return
        try:
            reasons = {
                row.get("reason")
                for row in response.json().get("error", {}).get("errors", [])
            }
        except (ValueError, TypeError, AttributeError):
            return
        if reasons & {"quotaExceeded", "dailyLimitExceeded", "dailyLimitExceededUnreg"}:
            raise AdapterFailure(Code.quota_exceeded)
        if reasons & {"rateLimitExceeded", "userRateLimitExceeded"}:
            retry = _retry_after(response)
            self.gate.defer(self.descriptor.key, retry or 1)
            raise AdapterFailure(Code.rate_limited, retry_after_seconds=retry)
        if reasons & {"keyInvalid", "accessNotConfigured", "ipRefererBlocked"}:
            raise AdapterFailure(Code.authentication_failed)

    def artist(self, row, context, *, search=False):
        statistics = row.get("statistics")
        stats = object_data({} if statistics is None else statistics)
        channel_id = source_id(
            row["id"]["channelId"] if search else row["id"], CHANNEL_ID
        )
        return NormalizedArtist(
            external_id=channel_id,
            name=row["snippet"]["title"],
            provenance=self.provenance(
                context,
                f"https://www.youtube.com/channel/{channel_id}",
                entity_type="channel_candidate",
                artist_identity="unverified",
                country=row["snippet"].get("country"),
                subscriber_count_precision="three_significant_figures",
                usage="display_only_no_derived_metrics_or_cross_owner_aggregation",
                subscriber_count_status=(
                    "hidden"
                    if stats.get("hiddenSubscriberCount") is True
                    else (
                        "rounded"
                        if stats.get("hiddenSubscriberCount") is False
                        and stats.get("subscriberCount") is not None
                        else "unavailable"
                    )
                ),
            ),
        )

    async def search_artists(self, request, *, context, credentials):
        params = {
            "part": "snippet",
            "type": "channel",
            "q": request.query,
            "maxResults": request.limit,
        }
        if request.cursor:
            identifier(request.cursor, r"[A-Za-z0-9_=-]{1,500}")
            params["pageToken"] = request.cursor
        data = await self.get("search", params, credentials)
        cursor = data.get("nextPageToken")
        if cursor is not None:
            identifier(cursor, r"[A-Za-z0-9_=-]{1,500}")
        return ArtistSearchResponse(
            context=context,
            items=tuple(
                self.artist(row, context, search=True) for row in records(data["items"])
            ),
            next_cursor=cursor,
        )

    async def channel(self, artist_id, credentials):
        identifier(artist_id, CHANNEL_ID)
        cached = getattr(self, "_request_channel", None)
        if self.quota is not None and cached and cached["id"] == artist_id:
            return cached
        data = await self.get(
            "channels", {"part": "snippet,statistics", "id": artist_id}, credentials
        )
        rows = records(data["items"])
        if not rows:
            raise AdapterFailure(Code.data_unavailable)
        if len(rows) != 1 or rows[0]["id"] != artist_id:
            raise ValueError("Channel mismatch")
        if self.quota is not None:
            self._request_channel = rows[0]
        return rows[0]

    async def lookup_artist(self, request, *, context, credentials):
        return ArtistLookupResponse(
            context=context,
            artist=self.artist(
                await self.channel(request.artist_id, credentials), context
            ),
        )

    async def observations(self, request, *, context, credentials):
        self.check_observations(request)
        row = await self.channel(request.subject.external_id, credentials)
        statistics = row.get("statistics")
        stats = dict(object_data({} if statistics is None else statistics))
        if (
            "hiddenSubscriberCount" in stats
            and type(stats["hiddenSubscriberCount"]) is not bool
        ):
            raise ValueError("Invalid subscriber visibility flag")
        if stats.get("hiddenSubscriberCount") is not False:
            stats.pop("subscriberCount", None)
        return self.snapshot(
            request, context, stats, self.artist(row, context).provenance
        )
