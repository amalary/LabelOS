import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from labelos_database.models import MarketingContentItem, MarketingContentItemChannel

from labelos_api.config import Settings
from labelos_api.scheduling.contracts import (
    RetryableUnavailable,
    ScheduleSnapshot,
)
from labelos_api.scheduling.payload import (
    InvalidHandoffPayload,
    canonical_json,
    envelope,
    fingerprint,
    normalize_content,
    prepare_request,
    validate_request,
)
from labelos_api.scheduling.receivers import configured_receiver


@pytest.fixture
def content_source():
    item = MarketingContentItem(
        id=UUID(int=1),
        organization_id=UUID(int=2),
        content_revision=3,
        copy_text="Parent",
        asset_refs=[],
        metadata_json={"hashtags": [" music ", "MUSIC"]},
    )
    channel = MarketingContentItemChannel(
        id=UUID(int=4),
        marketing_content_item_id=item.id,
        channel="instagram",
        placement="feed",
        copy_text_override="Cafe\u0301\r\nLaunch",
        social_account_connection_id=UUID(int=5),
        scheduled_at=datetime(2026, 9, 15, tzinfo=UTC),
        schedule_timezone="UTC",
        schedule_generation=6,
        asset_refs=[],
        metadata_json={"hashtags": ["#New", "music"], "access_token": "SECRET"},
    )
    return item, channel


def request_for(item, channel, assets=None):
    return prepare_request(
        snapshot=ScheduleSnapshot(
            workspace_id=item.organization_id,
            content_item_id=item.id,
            channel_id=channel.id,
            content_revision=item.content_revision,
            approval_request_id=UUID(int=7),
            schedule_generation=channel.schedule_generation,
            scheduled_for=channel.scheduled_at,
        ),
        job_id=UUID(int=8),
        destination_id=channel.social_account_connection_id,
        artist_profile_id=None,
        authoring_timezone=channel.schedule_timezone,
        correlation_id=UUID(int=9),
        item=item,
        channel=channel,
        asset_bytes=assets or {},
    )


def test_normalization_golden_fixture_and_envelope(content_source):
    item, channel = content_source
    request = request_for(item, channel)
    assert (
        request.canonical_payload
        == (
            '{"asset_refs":[],"caption":"Caf\u00e9\\nLaunch","channel":"instagram",'
            '"hashtags":["#music","#New"],"metadata":{},"placement":"feed"}'
        ).encode()
    )
    expected = {
        "payload_schema_version": 1,
        "scheduling_job_id": str(UUID(int=8)),
        "workspace_id": str(UUID(int=2)),
        "content_item_id": str(UUID(int=1)),
        "content_channel_id": str(UUID(int=4)),
        "social_account_connection_id": str(UUID(int=5)),
        "approval_request_id": str(UUID(int=7)),
        "authorized_content_revision": 3,
        "schedule_generation": 6,
        "scheduled_for": "2026-09-15T00:00:00.000000Z",
        "execution_mode": "automatic",
        "correlation_id": str(UUID(int=9)),
        "artist_profile_id": None,
        "authoring_timezone": "UTC",
        "idempotency_key": f"labelos:scheduling:v1:{UUID(int=2)}:{UUID(int=8)}",
        "content": json.loads(request.canonical_payload),
    }
    assert envelope(request) == expected
    assert (
        request.payload_fingerprint
        == hashlib.sha256(canonical_json(expected)).hexdigest()
    )
    channel.metadata_json = {"access_token": "DIFFERENT", "hashtags": ["#New", "music"]}
    channel.copy_text_override = "Caf\u00e9\nLaunch"
    assert request_for(item, channel) == request
    assert validate_request(request) == {}


def test_fallback_order_and_no_hashtag_inference(content_source):
    item, channel = content_source
    channel.copy_text_override = None
    item.copy_text = "Caption #NotStructured"
    item.metadata_json = channel.metadata_json = {}
    result = json.loads(normalize_content(item, channel, {}))
    assert result["caption"] == "Caption #NotStructured"
    assert result["hashtags"] == []


def asset_ref(data):
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "media_type": "image/png",
    }


def test_assets_are_copied_and_bound_to_approved_digest(content_source):
    item, channel = content_source
    data = b"immutable approved image"
    ref = asset_ref(data)
    item.asset_refs = [ref]
    assets = {ref["sha256"]: data}
    request = request_for(item, channel, assets)
    original = request.canonical_payload
    assets[ref["sha256"]] = b"changed after approval"
    with pytest.raises(InvalidHandoffPayload):
        request_for(item, channel, assets)
    item.asset_refs[0]["sha256"] = "0" * 64
    channel.copy_text_override = "edited later"
    assert request.canonical_payload == original
    assert validate_request(request) == {hashlib.sha256(data).hexdigest(): data}


def test_asset_order_and_channel_precedence(content_source):
    item, channel = content_source
    parent, first, second = b"parent", b"first", b"second"
    item.asset_refs = [asset_ref(parent)]
    channel.asset_refs = [asset_ref(first), asset_ref(second)]
    assets = {hashlib.sha256(data).hexdigest(): data for data in (first, second)}
    request = request_for(item, channel, assets)
    refs = json.loads(request.canonical_payload)["asset_refs"]
    assert [ref["sha256"] for ref in refs] == list(assets)
    channel.asset_refs.reverse()
    assert (
        request_for(item, channel, assets).payload_fingerprint
        != request.payload_fingerprint
    )


def test_receiver_rechecks_asset_bytes_even_when_envelope_is_rehashed(content_source):
    item, channel = content_source
    ref = asset_ref(b"original")
    channel.asset_refs = [ref]
    request = request_for(item, channel, {ref["sha256"]: b"original"})
    content = json.loads(request.canonical_payload)
    content["asset_refs"][0]["content_base64"] = "dGFtcGVyZWQ="
    request = replace(request, canonical_payload=canonical_json(content))
    request = replace(request, payload_fingerprint=fingerprint(request))
    with pytest.raises(InvalidHandoffPayload):
        validate_request(request)


@pytest.mark.parametrize(
    "ref",
    [
        "https://mutable/image.png",
        {"asset_id": "mutable"},
        {"url": "https://example/image?token=SECRET"},
        {"sha256": "0" * 64, "size_bytes": 3, "media_type": "image/png"},
        {
            "sha256": "0" * 64,
            "size_bytes": 3,
            "media_type": "image/png",
            "token": "SECRET",
        },
    ],
)
def test_unverifiable_assets_rejected_without_echoing_input(content_source, ref):
    item, channel = content_source
    channel.asset_refs = [ref]
    with pytest.raises(InvalidHandoffPayload, match="^invalid_handoff_payload$"):
        request_for(item, channel)


@pytest.mark.parametrize(
    "change",
    [
        {"execution_mode": "manual"},
        {"payload_schema_version": 2},
        {"correlation_id": None},
        {"canonical_payload": b"{}"},
        {"payload_fingerprint": "0" * 64},
        {"destination_id": UUID(int=123)},
        {"correlation_id": UUID(int=123)},
    ],
)
def test_receiver_rechecks_schema_and_full_fingerprint(content_source, change):
    with pytest.raises(InvalidHandoffPayload):
        validate_request(replace(request_for(*content_source), **change))


def test_noncanonical_and_unknown_fields_rejected_even_with_valid_hash(content_source):
    request = request_for(*content_source)
    for content in [
        {**json.loads(request.canonical_payload), "credentials": "SECRET"},
        {
            **json.loads(request.canonical_payload),
            "metadata": {"refresh_token": "SECRET"},
        },
    ]:
        changed = replace(request, canonical_payload=canonical_json(content))
        changed = replace(changed, payload_fingerprint=fingerprint(changed))
        with pytest.raises(InvalidHandoffPayload):
            validate_request(changed)
    changed = replace(
        request,
        canonical_payload=json.dumps(json.loads(request.canonical_payload)).encode(),
    )
    with pytest.raises(InvalidHandoffPayload):
        validate_request(changed)
    assert "Launch" not in repr(request)
    assert "SECRET" not in repr(request)


@pytest.mark.parametrize(
    "field,value",
    [
        ("content_revision", 4),
        ("organization_id", UUID(int=55)),
    ],
)
def test_source_revision_and_scope_are_checked(content_source, field, value):
    item, channel = content_source
    request = request_for(item, channel)
    setattr(item, field, value)
    with pytest.raises(InvalidHandoffPayload):
        prepare_request(
            snapshot=request.snapshot,
            job_id=request.job_id,
            destination_id=request.destination_id,
            artist_profile_id=None,
            authoring_timezone="UTC",
            correlation_id=uuid4(),
            item=item,
            channel=channel,
            asset_bytes={},
        )


@pytest.mark.parametrize(
    "environment", ["production", "staging", "preview", "local", "test"]
)
@pytest.mark.parametrize("backend", ["fake", "memory", "noop-success", "typo"])
def test_successful_fakes_cannot_be_deployed(environment, backend):
    settings = Settings(environment=environment, delivery_receiver_backend=backend)
    with pytest.raises(RuntimeError, match="successful fake"):
        settings.validate_startup_environment()
    with pytest.raises(RuntimeError, match="successful fake"):
        configured_receiver(settings)


def test_development_receiver_never_accepts(content_source):
    receiver = configured_receiver(Settings(environment="local"))
    assert isinstance(
        asyncio.run(receiver.accept(None, request_for(*content_source))),
        RetryableUnavailable,
    )


def test_production_may_remain_unavailable():
    Settings(environment="production").validate_delivery_receiver()
