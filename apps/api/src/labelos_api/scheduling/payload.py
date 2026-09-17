"""Version 1 deterministic, self-contained, credential-free delivery snapshots.

Asset bytes must be prepared locally before entering the acceptance transaction.
An approved SHA-256 reference binds those bytes; this module never resolves URLs.
"""

import base64
import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import replace
from uuid import UUID

from labelos_database.models import MarketingContentItem, MarketingContentItemChannel

from labelos_api.scheduling.contracts import DeliveryAcceptanceRequest, ScheduleSnapshot
from labelos_api.scheduling.timezones import authoring_zone

MAX_ASSET_BYTES = 16 * 1024 * 1024
MAX_PAYLOAD_BYTES = 24 * 1024 * 1024
_DIGEST = re.compile(r"[0-9a-f]{64}")
_MEDIA_TYPE = re.compile(r"(?:image|video|audio)/[a-z0-9][a-z0-9.+-]{0,63}")


class InvalidHandoffPayload(ValueError):
    def __init__(self):
        # Never echo input, URLs, metadata, content or decoding errors.
        super().__init__("invalid_handoff_payload")


def _text(value: object, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise InvalidHandoffPayload()
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError):
        raise InvalidHandoffPayload() from None


def _asset(ref: object, data: object) -> dict:
    if not isinstance(ref, dict) or set(ref) != {"sha256", "size_bytes", "media_type"}:
        raise InvalidHandoffPayload()
    digest, size, media_type = ref["sha256"], ref["size_bytes"], ref["media_type"]
    if (
        not isinstance(digest, str)
        or not _DIGEST.fullmatch(digest)
        or type(size) is not int
        or not 0 < size <= MAX_ASSET_BYTES
        or not isinstance(media_type, str)
        or not _MEDIA_TYPE.fullmatch(media_type)
        or not isinstance(data, bytes)
        or len(data) != size
        or hashlib.sha256(data).hexdigest() != digest
    ):
        raise InvalidHandoffPayload()
    return {**ref, "content_base64": base64.b64encode(data).decode("ascii")}


def normalize_content(
    item: MarketingContentItem,
    channel: MarketingContentItemChannel,
    asset_bytes: Mapping[str, bytes],
) -> bytes:
    """Whitelist output fields; mutable JSON and arbitrary metadata never escape."""
    tags: list[str] = []
    seen: set[str] = set()
    for metadata in (item.metadata_json or {}, channel.metadata_json or {}):
        raw = metadata.get("hashtags", [])
        if not isinstance(raw, list):
            continue
        for value in raw:
            if not isinstance(value, str):
                continue
            tag = str(_text(value)).strip()
            if not tag:
                continue
            tag = tag if tag.startswith("#") else "#" + tag
            if tag.lower() not in seen:
                tags.append(tag)
                seen.add(tag.lower())
    assets = []
    for ref in channel.asset_refs or item.asset_refs or []:
        if not isinstance(ref, dict) or not isinstance(ref.get("sha256"), str):
            raise InvalidHandoffPayload()
        assets.append(_asset(ref, asset_bytes.get(ref["sha256"])))
    payload = canonical_json(
        {
            "caption": _text(
                channel.copy_text_override or item.copy_text, nullable=True
            ),
            "channel": _text(channel.channel),
            "placement": _text(channel.placement),
            "hashtags": tags,
            "asset_refs": assets,
            "metadata": {},
        }
    )
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise InvalidHandoffPayload()
    return payload


def envelope(request: DeliveryAcceptanceRequest) -> dict:
    snapshot = request.snapshot
    return {
        "payload_schema_version": request.payload_schema_version,
        "scheduling_job_id": str(request.job_id),
        "workspace_id": str(snapshot.workspace_id),
        "content_item_id": str(snapshot.content_item_id),
        "content_channel_id": str(snapshot.channel_id),
        "social_account_connection_id": str(request.destination_id),
        "approval_request_id": str(snapshot.approval_request_id),
        "authorized_content_revision": snapshot.content_revision,
        "schedule_generation": snapshot.schedule_generation,
        "scheduled_for": snapshot.scheduled_for.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z"),
        "execution_mode": request.execution_mode,
        "idempotency_key": request.idempotency_key,
        "correlation_id": str(request.correlation_id),
        "artist_profile_id": (
            str(request.artist_profile_id) if request.artist_profile_id else None
        ),
        "authoring_timezone": request.authoring_timezone,
        "content": json.loads(request.canonical_payload),
    }


def fingerprint(request: DeliveryAcceptanceRequest) -> str:
    return hashlib.sha256(canonical_json(envelope(request))).hexdigest()


def validate_request(request: DeliveryAcceptanceRequest) -> dict[str, bytes]:
    """Receiver-side strict schema, canonical encoding and content binding check."""
    try:
        if (
            type(request.canonical_payload) is not bytes
            or type(request.payload_schema_version) is not int
            or request.payload_schema_version != 1
            or request.execution_mode != "automatic"
            or not isinstance(request.correlation_id, UUID)
            or not isinstance(request.job_id, UUID)
            or not isinstance(request.destination_id, UUID)
            or any(
                not isinstance(value, UUID)
                for value in (
                    request.snapshot.workspace_id,
                    request.snapshot.content_item_id,
                    request.snapshot.channel_id,
                    request.snapshot.approval_request_id,
                )
            )
            or any(
                type(value) is not int or value < 1
                for value in (
                    request.snapshot.content_revision,
                    request.snapshot.schedule_generation,
                )
            )
            or (
                request.artist_profile_id is not None
                and not isinstance(request.artist_profile_id, UUID)
            )
            or len(request.canonical_payload) > MAX_PAYLOAD_BYTES
        ):
            raise InvalidHandoffPayload()
        authoring_zone(request.authoring_timezone)
        content = json.loads(request.canonical_payload)
        if (
            set(content)
            != {"caption", "channel", "placement", "hashtags", "asset_refs", "metadata"}
            or content["metadata"] != {}
        ):
            raise InvalidHandoffPayload()
        for key in ("caption", "channel", "placement"):
            if _text(content[key], nullable=key == "caption") != content[key]:
                raise InvalidHandoffPayload()
        if not isinstance(content["hashtags"], list):
            raise InvalidHandoffPayload()
        tags = content["hashtags"]
        if any(
            not isinstance(tag, str)
            or not tag.startswith("#")
            or len(tag) < 2
            or _text(tag) != tag
            or tag.strip() != tag
            for tag in tags
        ) or len({tag.lower() for tag in tags}) != len(tags):
            raise InvalidHandoffPayload()
        assets: dict[str, bytes] = {}
        if not isinstance(content["asset_refs"], list):
            raise InvalidHandoffPayload()
        for asset in content["asset_refs"]:
            if not isinstance(asset, dict) or set(asset) != {
                "sha256",
                "size_bytes",
                "media_type",
                "content_base64",
            }:
                raise InvalidHandoffPayload()
            ref = {
                key: value for key, value in asset.items() if key != "content_base64"
            }
            data = base64.b64decode(asset["content_base64"], validate=True)
            if _asset(ref, data) != asset:
                raise InvalidHandoffPayload()
            assets[asset["sha256"]] = data
        if (
            canonical_json(content) != request.canonical_payload
            or fingerprint(request) != request.payload_fingerprint
        ):
            raise InvalidHandoffPayload()
        return assets
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise InvalidHandoffPayload() from None


def prepare_request(
    *,
    snapshot: ScheduleSnapshot,
    job_id: UUID,
    destination_id: UUID,
    artist_profile_id: UUID | None,
    authoring_timezone: str,
    correlation_id: UUID,
    item: MarketingContentItem,
    channel: MarketingContentItemChannel,
    asset_bytes: Mapping[str, bytes],
) -> DeliveryAcceptanceRequest:
    """Prepare from server source records; acceptance reloads/validates under locks."""
    if (
        item.organization_id != snapshot.workspace_id
        or item.id != snapshot.content_item_id
        or channel.id != snapshot.channel_id
        or channel.marketing_content_item_id != item.id
        or item.content_revision != snapshot.content_revision
        or channel.schedule_generation != snapshot.schedule_generation
        or channel.scheduled_at != snapshot.scheduled_for
        or channel.social_account_connection_id != destination_id
        or channel.schedule_timezone != authoring_timezone
    ):
        raise InvalidHandoffPayload()
    request = DeliveryAcceptanceRequest(
        snapshot=snapshot,
        job_id=job_id,
        destination_id=destination_id,
        artist_profile_id=artist_profile_id,
        authoring_timezone=authoring_timezone,
        correlation_id=correlation_id,
        payload_schema_version=1,
        canonical_payload=normalize_content(item, channel, asset_bytes),
        payload_fingerprint="",
    )
    request = replace(request, payload_fingerprint=fingerprint(request))
    validate_request(request)
    return request
