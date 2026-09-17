"""YouTube Data API delivery. OAuth and secrets remain in Social Accounts.

One multipart videos.insert request creates the video; no automatic write retry.
An authoritative final resource ID establishes creation, not playback readiness.
No upload URLs, tokens, raw errors or response metadata cross this boundary.
"""

import hashlib
import json
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import ceil
from uuid import uuid4

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labelos_api.publishing.providers import (
    ProviderCapabilities,
    ProviderOutcome,
    ProviderResult,
    PublicationRequest,
)
from labelos_api.publishing.retries import FailureCategory as Category
from labelos_api.scheduling.payload import MAX_ASSET_BYTES
from labelos_api.services.social_account_execution import (
    ExecutionCredentialError,
    SocialAccountExecution,
)
from labelos_api.services.social_account_service import ExecutionConnectionError
from labelos_api.social_accounts.providers import (
    SocialAccountProviderErrorCode as Code,
)
from labelos_api.social_accounts.providers import (
    YouTubeDirectSocialAccountConnectionProvider,
)

_UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
_CHANNELS = "https://www.googleapis.com/youtube/v3/channels"
_REQUIRED_SCOPES = frozenset(
    {
        YouTubeDirectSocialAccountConnectionProvider.SCOPE_YOUTUBE_READONLY,
        YouTubeDirectSocialAccountConnectionProvider.SCOPE_YOUTUBE_UPLOAD,
    }
)


def _failure(
    outcome: ProviderOutcome, category: Category | None = None
) -> ProviderResult:
    return ProviderResult(
        outcome=outcome, confirmed_absent=True, failure_category=category
    )


class YouTubePublishingAdapter:
    capabilities = ProviderCapabilities(publish=True, reconcile=False)

    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        connection_provider: YouTubeDirectSocialAccountConnectionProvider,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if connection_provider.credential_store is None:
            raise ValueError("youtube_credential_store_required")
        self._sessions = sessions
        self._connection_provider = connection_provider
        self._store = connection_provider.credential_store
        self._http_client = http_client
        self._accounts = SocialAccountExecution(
            sessions=sessions,
            provider=connection_provider,
            credential_store=self._store,
            required_scopes=_REQUIRED_SCOPES,
        )

    def validate(self, request: PublicationRequest) -> ProviderResult | None:
        if (
            request.provider != "youtube"
            or request.channel != "youtube"
            or request.placement not in {"video", "shorts"}
        ):
            return ProviderResult(outcome=ProviderOutcome.unsupported)
        caption = request.caption or ""
        title = caption.split("\n", 1)[0]
        description = _description(request)
        if (
            not title.strip()
            or len(title) > 100
            or any(c in description for c in "<>")
            or any(ord(c) < 32 and c not in "\n\t" for c in description)
            or len(description.encode("utf-8")) > 5000
            or len(request.media) != 1
        ):
            return _failure(
                ProviderOutcome.permanent_failure, Category.invalid_content_media
            )
        media = request.media[0]
        if (
            not re.fullmatch(r"video/[a-z0-9][a-z0-9.+-]{0,63}", media.media_type)
            or not 0 < len(media.data) <= MAX_ASSET_BYTES
            or hashlib.sha256(media.data).hexdigest() != media.sha256
        ):
            return _failure(
                ProviderOutcome.permanent_failure, Category.invalid_content_media
            )
        return None

    async def _connection(self, request: PublicationRequest):
        return await self._accounts.connection(
            workspace_id=request.workspace_id,
            destination_id=request.destination_id,
            destination_identity=request.destination_identity,
        )

    async def publish(self, request: PublicationRequest) -> ProviderResult:
        rejection = self.validate(request)
        if rejection is not None:
            return rejection
        write_started = False
        try:
            connection = await self._connection(request)
            connection, credentials = await self._accounts.credentials(connection)
            # Check again after refresh/store I/O before using the token externally.
            if await self._connection(request) != connection:
                return _failure(ProviderOutcome.authorization_required)
            token = credentials.expose()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            # Bind this exact access token to the retained channel, never cached
            # provider_metadata (the connection provider can return cached identity).
            identity = await self._request(
                "GET",
                _CHANNELS,
                headers=headers,
                params={"part": "id", "mine": "true", "maxResults": "2"},
            )
            if identity.status_code != 200:
                result = _http_failure(identity, write_started=False)
                await self._observe_http(connection, identity, result)
                return result
            body = _json_object(identity)
            items = body.get("items")
            if (
                not isinstance(items, list)
                or len(items) != 1
                or not isinstance(items[0], dict)
                or items[0].get("id") != connection.external_account_id
                or body.get("nextPageToken")
            ):
                await self._accounts.observe(connection, Code.authorization_failed)
                return _failure(ProviderOutcome.authorization_required)
            # Detect reconnect/disconnect/replacement during credential I/O.
            if await self._connection(request) != connection:
                return _failure(ProviderOutcome.authorization_required)
            content_type, content = _multipart(request)
            write_started = True
            response = await self._request(
                "POST",
                _UPLOAD,
                headers={**headers, "Content-Type": content_type},
                params={"uploadType": "multipart", "part": "snippet,status"},
                content=content,
            )
            if response.status_code not in {200, 201}:
                result = _http_failure(response, write_started=True)
                await self._observe_http(connection, response, result)
                return result
            body = _json_object(response)
            video_id = body.get("id")
            snippet = body.get("snippet")
            status = body.get("status")
            if (
                body.get("kind") != "youtube#video"
                or "error" in body
                or not isinstance(video_id, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id)
                or not isinstance(snippet, dict)
                or snippet.get("channelId") != connection.external_account_id
                or not isinstance(status, dict)
                or status.get("uploadStatus") not in ("uploaded", "processed")
                or status.get("privacyStatus") not in ("public", "private", "unlisted")
            ):
                return ProviderResult(outcome=ProviderOutcome.ambiguous)
            await self._accounts.observe(connection, None)
            return ProviderResult(
                outcome=ProviderOutcome.published, external_post_id=video_id
            )
        except ExecutionConnectionError:
            return _failure(ProviderOutcome.authorization_required)
        except ExecutionCredentialError as exc:
            if exc.code == Code.rate_limited:
                return _failure(ProviderOutcome.rate_limited)
            if exc.code in {
                Code.provider_unavailable,
                Code.third_party_service_unavailable,
            }:
                return _failure(ProviderOutcome.retryable_failure)
            return _failure(
                ProviderOutcome.authorization_required,
                (
                    Category.authorization
                    if exc.code == Code.insufficient_scope
                    else Category.authentication
                ),
            )
        except (httpx.HTTPError, ValueError, SQLAlchemyError) as exc:
            # A timeout/invalid response after sending media cannot prove absence.
            if write_started:
                return ProviderResult(outcome=ProviderOutcome.ambiguous)
            return _failure(
                ProviderOutcome.retryable_failure,
                (
                    Category.transient_network
                    if isinstance(exc, httpx.HTTPError)
                    else (
                        Category.internal_failure
                        if isinstance(exc, SQLAlchemyError)
                        else Category.provider_unavailable
                    )
                ),
            )

    async def _observe_http(self, connection, response, result):
        # Only normalized, authoritative authentication failures affect health.
        # Unknown post-write errors retain ambiguous delivery evidence.
        if result.outcome == ProviderOutcome.authorization_required:
            code = (
                Code.insufficient_scope
                if "insufficientPermissions" in _error_reasons(response)
                else Code.authorization_failed
            )
            await self._accounts.observe(connection, code)

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        # No redirects and no transport retries. Use MockTransport in tests.
        if self._http_client is not None:
            return await self._http_client.request(
                method, url, follow_redirects=False, **kwargs
            )
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120, connect=10), follow_redirects=False
        ) as client:
            return await client.request(method, url, **kwargs)

    async def reconcile(self, request: PublicationRequest) -> ProviderResult:
        # YouTube cannot look up a video by LabelOS's idempotency key. Searching
        # by caption/time is not authoritative and could authorize a duplicate.
        return ProviderResult(outcome=ProviderOutcome.unsupported)


def _description(request: PublicationRequest) -> str:
    return (request.caption or "") + (
        "\n\n" + " ".join(request.hashtags) if request.hashtags else ""
    )


def _multipart(request: PublicationRequest) -> tuple[str, bytes]:
    media = request.media[0]
    metadata = json.dumps(
        {
            "snippet": {
                "title": (request.caption or "").split("\n", 1)[0],
                "description": _description(request),
            },
            "status": {"privacyStatus": "public"},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    boundary = uuid4().hex
    while boundary.encode() in media.data or boundary.encode() in metadata:
        boundary = uuid4().hex
    body = (
        f"--{boundary}\r\n".encode()
        + b"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        + metadata
        + f"\r\n--{boundary}\r\nContent-Type: {media.media_type}\r\n\r\n".encode()
        + media.data
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return f"multipart/related; boundary={boundary}", body


def _json_object(response: httpx.Response) -> dict:
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError("invalid_youtube_response")
    return value


def _error_reasons(response: httpx.Response) -> set:
    # Never retain Google's messages/details, including malformed error bodies.
    try:
        error = _json_object(response).get("error")
        return (
            {entry.get("reason") for entry in error.get("errors", [])}
            if isinstance(error, dict) and error.get("code") == response.status_code
            else set()
        )
    except (ValueError, TypeError, AttributeError):
        return set()


def _http_failure(response: httpx.Response, *, write_started: bool) -> ProviderResult:
    # Only structured Google rejections establish noncreation after upload starts.
    reasons = _error_reasons(response)
    outcome = None
    category = None
    if response.status_code in {400, 403, 429} and reasons & {
        "quotaExceeded",
        "dailyLimitExceeded",
        "rateLimitExceeded",
        "userRateLimitExceeded",
        "uploadLimitExceeded",
    }:
        outcome = ProviderOutcome.rate_limited
    elif response.status_code in {401, 403} and reasons & {
        "authError",
        "unauthorized",
        "insufficientPermissions",
        "forbidden",
        "youtubeSignupRequired",
        "accountSuspended",
        "authenticatedUserAccountSuspended",
    }:
        outcome = ProviderOutcome.authorization_required
    elif response.status_code == 400 and reasons & {
        "invalidTitle",
        "invalidDescription",
        "invalidTags",
        "invalidCategoryId",
        "invalidVideoMetadata",
        "mediaBodyRequired",
        "invalidFilename",
    }:
        outcome = ProviderOutcome.permanent_failure
        category = Category.invalid_content_media
    if outcome is None:
        if write_started:
            return ProviderResult(outcome=ProviderOutcome.ambiguous)
        if response.status_code in {401, 403}:
            outcome = ProviderOutcome.authorization_required
        elif response.status_code == 429:
            outcome = ProviderOutcome.rate_limited
        elif response.status_code >= 500:
            outcome = ProviderOutcome.retryable_failure
        else:
            outcome = ProviderOutcome.permanent_failure
    if outcome == ProviderOutcome.authorization_required:
        category = (
            Category.authorization
            if "insufficientPermissions" in reasons
            or (
                response.status_code == 403
                and not reasons & {"authError", "unauthorized"}
            )
            else Category.authentication
        )
    return ProviderResult(
        outcome=outcome,
        confirmed_absent=True,
        failure_category=category,
        retry_after_seconds=(
            parse_retry_after(response.headers.get("Retry-After"))
            if outcome
            in {ProviderOutcome.rate_limited, ProviderOutcome.retryable_failure}
            else None
        ),
    )


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> int | None:
    """Accept bounded delta seconds or an aware HTTP date; never store raw headers."""
    if not value or len(value) > 128 or not value.isascii():
        return None
    try:
        if value.isdigit():
            delay = int(value)
        else:
            target = parsedate_to_datetime(value)
            if target.utcoffset() is None:
                return None
            delay = max(0, ceil((target - (now or datetime.now(UTC))).total_seconds()))
        return delay if 0 <= delay <= 604800 else None
    except (ValueError, TypeError, OverflowError):
        return None
