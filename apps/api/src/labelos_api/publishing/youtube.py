"""YouTube Data API delivery. OAuth and secrets remain in Social Accounts.

One multipart videos.insert request creates the video; no automatic write retry.
An authoritative final resource ID establishes creation, not playback readiness.
No upload URLs, tokens, raw errors or response metadata cross this boundary.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from labelos_database.models import SocialAccountConnection
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labelos_api.publishing.providers import (
    ProviderCapabilities,
    ProviderOutcome,
    ProviderResult,
    PublicationRequest,
)
from labelos_api.scheduling.payload import MAX_ASSET_BYTES, canonical_json
from labelos_api.services.credential_store import (
    CredentialNotFoundError,
    CredentialStoreError,
    InvalidCredentialReferenceError,
)
from labelos_api.social_accounts.providers import (
    SocialAccountProviderError,
    SocialAccountProviderErrorCode,
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


def _failure(outcome: ProviderOutcome) -> ProviderResult:
    return ProviderResult(outcome=outcome, confirmed_absent=True)


class _NotReady(Exception):
    def __init__(self, outcome: ProviderOutcome):
        super().__init__("youtube_connection_not_ready")
        self.outcome = outcome


@dataclass(frozen=True, repr=False)
class _Connection:
    credential_ref: str
    external_account_id: str
    token_expires_at: datetime | None
    updated_at: datetime


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
            return _failure(ProviderOutcome.permanent_failure)
        media = request.media[0]
        if (
            not re.fullmatch(r"video/[a-z0-9][a-z0-9.+-]{0,63}", media.media_type)
            or not 0 < len(media.data) <= MAX_ASSET_BYTES
            or hashlib.sha256(media.data).hexdigest() != media.sha256
        ):
            return _failure(ProviderOutcome.permanent_failure)
        return None

    async def _connection(self, request: PublicationRequest) -> _Connection:
        # Deliberately select only connection fields, without relationship loads.
        # Close the transaction before any credential-store or provider I/O.
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(
                        SocialAccountConnection.provider,
                        SocialAccountConnection.connection_method,
                        SocialAccountConnection.status,
                        SocialAccountConnection.capabilities,
                        SocialAccountConnection.credential_ref,
                        SocialAccountConnection.external_account_id,
                        SocialAccountConnection.token_expires_at,
                        SocialAccountConnection.updated_at,
                    ).where(
                        SocialAccountConnection.organization_id == request.workspace_id,
                        SocialAccountConnection.id == request.destination_id,
                    )
                )
            ).one_or_none()
        if (
            row is None
            or row.provider != "youtube"
            or row.connection_method != "direct_api"
            or row.status not in {"connected", "limited"}
            or "content_publish" not in (row.capabilities or [])
            or not row.credential_ref
            or not row.external_account_id
            or hashlib.sha256(
                canonical_json([row.provider, row.external_account_id])
            ).hexdigest()
            != request.destination_identity
        ):
            raise _NotReady(ProviderOutcome.authorization_required)
        return _Connection(
            row.credential_ref,
            row.external_account_id,
            row.token_expires_at,
            row.updated_at,
        )

    async def _credentials(self, connection: _Connection) -> dict:
        values = (await self._store.get(connection.credential_ref)).expose()
        scope = values.get("scope")
        if (
            not isinstance(scope, str)
            or not _REQUIRED_SCOPES.issubset(scope.split())
            or str(values.get("token_type", "Bearer")).lower() != "bearer"
        ):
            raise _NotReady(ProviderOutcome.authorization_required)
        return values

    async def _refresh(
        self, request: PublicationRequest, connection: _Connection
    ) -> _Connection:
        # Use the existing token endpoint, refresh semantics and secret replacement.
        refreshed = await self._connection_provider.refresh_credentials(
            credential_ref=connection.credential_ref
        )
        if refreshed.credential_ref != connection.credential_ref:
            raise _NotReady(ProviderOutcome.authorization_required)
        async with self._sessions.begin() as session:
            updated = await session.scalar(
                update(SocialAccountConnection)
                .where(
                    SocialAccountConnection.organization_id == request.workspace_id,
                    SocialAccountConnection.id == request.destination_id,
                    SocialAccountConnection.updated_at == connection.updated_at,
                    SocialAccountConnection.credential_ref == connection.credential_ref,
                    SocialAccountConnection.external_account_id
                    == connection.external_account_id,
                )
                .values(
                    token_expires_at=refreshed.token_expires_at,
                    capabilities=self._connection_provider.capabilities_for_scopes(
                        refreshed.granted_scopes
                    ),
                )
                .returning(SocialAccountConnection.id)
            )
            if updated is None:
                raise _NotReady(ProviderOutcome.authorization_required)
        return await self._connection(request)

    async def publish(self, request: PublicationRequest) -> ProviderResult:
        rejection = self.validate(request)
        if rejection is not None:
            return rejection
        write_started = False
        try:
            connection = await self._connection(request)
            values = await self._credentials(connection)
            expiry = connection.token_expires_at
            if expiry is not None and expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            if expiry is None or expiry <= datetime.now(UTC) + timedelta(seconds=60):
                connection = await self._refresh(request, connection)
                values = await self._credentials(connection)
            token = values.get("access_token")
            if not isinstance(token, str) or not token.strip():
                return _failure(ProviderOutcome.authorization_required)
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
                return _http_failure(identity, write_started=False)
            body = _json_object(identity)
            items = body.get("items")
            if (
                not isinstance(items, list)
                or len(items) != 1
                or not isinstance(items[0], dict)
                or items[0].get("id") != connection.external_account_id
                or body.get("nextPageToken")
            ):
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
                return _http_failure(response, write_started=True)
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
            return ProviderResult(
                outcome=ProviderOutcome.published, external_post_id=video_id
            )
        except _NotReady as exc:
            return _failure(exc.outcome)
        except (CredentialNotFoundError, InvalidCredentialReferenceError):
            return _failure(ProviderOutcome.authorization_required)
        except SocialAccountProviderError as exc:
            if exc.code == SocialAccountProviderErrorCode.rate_limited:
                return _failure(ProviderOutcome.rate_limited)
            if exc.code in {
                SocialAccountProviderErrorCode.provider_unavailable,
                SocialAccountProviderErrorCode.malformed_provider_response,
            }:
                return _failure(ProviderOutcome.retryable_failure)
            return _failure(ProviderOutcome.authorization_required)
        except (CredentialStoreError, httpx.HTTPError, ValueError):
            # A timeout/invalid response after sending media cannot prove absence.
            if write_started:
                return ProviderResult(outcome=ProviderOutcome.ambiguous)
            return _failure(ProviderOutcome.retryable_failure)

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


def _http_failure(response: httpx.Response, *, write_started: bool) -> ProviderResult:
    # Only documented, structured Google rejection reasons prove no video was
    # created by the sole insert request. Never retain Google's message/details.
    try:
        error = _json_object(response).get("error")
        reasons = (
            {entry.get("reason") for entry in error.get("errors", [])}
            if isinstance(error, dict) and error.get("code") == response.status_code
            else set()
        )
    except (ValueError, TypeError, AttributeError):
        reasons = set()
    outcome = None
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
    if outcome is not None:
        hint = response.headers.get("Retry-After", "")
        return ProviderResult(
            outcome=outcome,
            confirmed_absent=True,
            retry_after_seconds=(
                int(hint)
                if outcome == ProviderOutcome.rate_limited
                and hint.isascii()
                and hint.isdigit()
                and len(hint) <= 6
                and int(hint) <= 604800
                else None
            ),
        )
    if write_started:
        return ProviderResult(outcome=ProviderOutcome.ambiguous)
    if response.status_code in {401, 403}:
        return _failure(ProviderOutcome.authorization_required)
    if response.status_code == 429:
        return _failure(ProviderOutcome.rate_limited)
    return _failure(ProviderOutcome.retryable_failure)
