"""Uploads and source-scoped resolution use real authorization and persistence."""

import asyncio
import hashlib
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from labelos_database.models import MarketingMediaAsset, WorkspacePermission
from sqlalchemy import func, select, update
from sqlalchemy.exc import StatementError

from labelos_api.scheduling.payload import MAX_ASSET_BYTES, InvalidHandoffPayload
from labelos_api.services.marketing_media import load_approved_assets
from test_marketing_content_api import (
    _base,
    _draft_payload,
    _set_context,
)
from test_marketing_content_api import (
    marketing_content_client as marketing_content_client,
)

MEDIA = b"approved-video-bytes\x00\xff"


def draft(client, seeded):
    _set_context(client, seeded)
    response = client.post(
        _base(seeded), json={**_draft_payload(seeded), "asset_refs": []}
    )
    assert response.status_code == 201, response.text
    item = response.json()
    path = (
        f"/api/v1/workspaces/{seeded.workspace_id}"
        f"/marketing-content/{item['id']}/assets"
    )
    return item, path


def upload(client, path, data=MEDIA, **headers):
    return client.post(
        path, content=data, headers={"content-type": "video/mp4", **headers}
    )


def test_upload_persists_exact_bytes_idempotently_without_editing_draft(
    marketing_content_client,
):
    client, sessions, seeded = marketing_content_client
    item, path = draft(client, seeded)
    reference = upload(client, path).json()
    assert reference == {
        "sha256": hashlib.sha256(MEDIA).hexdigest(),
        "size_bytes": len(MEDIA),
        "media_type": "video/mp4",
    }
    assert upload(client, path).json() == reference
    current = client.get(f"{_base(seeded)}/{item['id']}").json()
    assert current["content_revision"] == item["content_revision"]
    assert current["asset_refs"] == []

    async def verify():
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(MarketingMediaAsset)
                )
                == 1
            )
            stored = await session.get(
                MarketingMediaAsset,
                (seeded.workspace_id, UUID(item["id"]), reference["sha256"]),
            )
            assert stored.data == MEDIA
            source = SimpleNamespace(id=UUID(item["id"]), asset_refs=[reference])
            assert await load_approved_assets(
                session, seeded.workspace_id, source, SimpleNamespace(asset_refs=[])
            ) == {reference["sha256"]: MEDIA}
            with pytest.raises(InvalidHandoffPayload):
                await load_approved_assets(
                    session, uuid4(), source, SimpleNamespace(asset_refs=[])
                )
            source.id = uuid4()
            with pytest.raises(InvalidHandoffPayload):
                await load_approved_assets(
                    session, seeded.workspace_id, source, SimpleNamespace(asset_refs=[])
                )

    asyncio.run(verify())


@pytest.mark.parametrize(
    "headers,data,status",
    [
        ({"content-type": "text/html"}, MEDIA, 415),
        ({"content-length": str(MAX_ASSET_BYTES + 1)}, MEDIA, 413),
        ({"content-length": "nonsense"}, MEDIA, 400),
        ({}, b"", 413),
        ({"content-length": "1"}, b"x" * (MAX_ASSET_BYTES + 1), 413),
    ],
    ids=["mime", "declared-large", "invalid-length", "empty", "stream-large"],
)
def test_upload_rejects_invalid_or_oversized_bodies(
    marketing_content_client, headers, data, status
):
    client, _, seeded = marketing_content_client
    _, path = draft(client, seeded)
    assert upload(client, path, data, **headers).status_code == status


def test_upload_enforces_edit_permission_and_workspace_content_scope(
    marketing_content_client,
):
    client, _, seeded = marketing_content_client
    _, path = draft(client, seeded)
    _set_context(
        client,
        seeded,
        user_id=seeded.viewer_user_id,
        workspace_permission=WorkspacePermission.guest,
    )
    assert upload(client, path).status_code == 403
    _set_context(client, seeded)
    assert (
        upload(
            client,
            path.replace(str(seeded.workspace_id), str(seeded.outside_workspace_id)),
        ).status_code
        == 404
    )
    assert (
        upload(client, path.replace(path.split("/")[-2], str(uuid4()))).status_code
        == 404
    )


def test_storage_failure_does_not_expose_media(
    marketing_content_client, monkeypatch, caplog
):
    from labelos_api.api.v1 import marketing_media

    client, _, seeded = marketing_content_client
    _, path = draft(client, seeded)

    async def unavailable(*args):
        raise StatementError(
            "PRIVATE_MEDIA_SENTINEL", "INSERT", {"data": MEDIA}, ValueError()
        )

    monkeypatch.setattr(marketing_media, "store_asset", unavailable)
    response = upload(client, path)
    assert response.status_code == 503
    assert "PRIVATE_MEDIA_SENTINEL" not in response.text + caplog.text
    assert MEDIA.decode("latin1") not in response.text + caplog.text


@pytest.mark.parametrize(
    "mutation", ["missing", "size", "mime", "digest", "corrupt", "extra", "aggregate"]
)
def test_resolution_fails_closed_and_channel_refs_override_shared(
    marketing_content_client, mutation
):
    client, sessions, seeded = marketing_content_client
    item, path = draft(client, seeded)
    reference = upload(client, path).json()

    async def verify():
        async with sessions.begin() as session:
            changed = dict(reference)
            if mutation == "missing":
                changed["sha256"] = "0" * 64
            if mutation == "size":
                changed["size_bytes"] = 1
            if mutation == "mime":
                changed["media_type"] = "image/png"
            if mutation == "digest":
                changed["sha256"] = "../arbitrary-file"
            if mutation == "extra":
                changed["url"] = "https://example.com/private"
            if mutation == "aggregate":
                changed["size_bytes"] = MAX_ASSET_BYTES
            if mutation == "corrupt":
                await session.execute(
                    update(MarketingMediaAsset).values(data=b"x" * len(MEDIA))
                )
            source = SimpleNamespace(id=UUID(item["id"]), asset_refs=[reference])
            channel = SimpleNamespace(
                asset_refs=[changed] * (2 if mutation == "aggregate" else 1)
            )
            with pytest.raises(InvalidHandoffPayload):
                await load_approved_assets(
                    session, seeded.workspace_id, source, channel
                )

    asyncio.run(verify())
