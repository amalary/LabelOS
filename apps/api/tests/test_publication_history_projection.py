"""Real database query/load regression with media-bearing accepted publications."""

import asyncio
import base64
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi.encoders import jsonable_encoder
from labelos_database.models import (
    ApprovalRequest,
    MarketingContentItem,
    MarketingContentItemChannel,
    Publication,
    PublicationListMetadata,
    SchedulingJob,
    SocialAccountConnection,
)
from sqlalchemy import event, inspect, select, update

from labelos_api.repositories.publishing import PublicationRepository
from labelos_api.repositories.scheduling import snapshot_for
from labelos_api.scheduling.contracts import DeliveryAcceptanceRequest
from labelos_api.scheduling.payload import canonical_json, fingerprint
from labelos_api.services.publication_recovery import PublicationRecoveryService
from labelos_api.services.scheduling_commands import authorized_item
from test_publication_recovery import recovery_api as recovery_api  # noqa: F401
from test_publishing_persistence import append, result_entry, seed, start_entry
from test_publishing_persistence import sessions as sessions  # noqa: F401


@pytest.fixture
def history_dataset(recovery_api, sessions):
    client, state, scope, identifier, actor, viewer = recovery_api

    async def prepare():
        async with sessions.begin() as session:
            repo = PublicationRepository(session, scope)
            original = await repo.get(identifier)
            job = await session.get(SchedulingJob, original.scheduling_job_id)
            destinations = []
            for index in range(3):
                destination = SocialAccountConnection(
                    organization_id=scope,
                    provider="instagram",
                    connection_method="assisted",
                    external_account_id=f"account-{index}",
                    display_name=f"Artist {index}",
                )
                session.add(destination)
                destinations.append(destination)
            await session.flush()
            payload = json.loads(original.canonical_envelope)["content"]
            payload["asset_refs"] = []
            for index in range(2):
                data = bytes([index + 1]) * (128 * 1024)
                payload["asset_refs"].append(
                    {
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "size_bytes": len(data),
                        "media_type": "image/png",
                        "content_base64": base64.b64encode(data).decode(),
                    }
                )
            for index in range(24):
                destination = destinations[index % 3]
                channel = MarketingContentItemChannel(
                    marketing_content_item_id=original.marketing_content_item_id,
                    channel="instagram",
                    placement=f"slot-{index}",
                )
                session.add(channel)
                await session.flush()
                job_id = uuid4()
                values = {
                    c.key: getattr(job, c.key) for c in SchedulingJob.__table__.columns
                }
                values.update(
                    id=job_id,
                    schedule_generation=index + 2,
                    marketing_content_item_channel_id=channel.id,
                    activation_operation_id=uuid4(),
                    social_account_connection_id=destination.id,
                    idempotency_key=f"labelos:scheduling:v1:{scope}:{job_id}",
                )
                next_job = SchedulingJob(**values)
                session.add(next_job)
                await session.flush()
                request = DeliveryAcceptanceRequest(
                    snapshot=snapshot_for(next_job),
                    job_id=job_id,
                    destination_id=destination.id,
                    artist_profile_id=job.effective_artist_id,
                    authoring_timezone=job.schedule_timezone,
                    payload_fingerprint="",
                    payload_schema_version=1,
                    canonical_payload=canonical_json(payload),
                    correlation_id=uuid4(),
                )
                request = replace(request, payload_fingerprint=fingerprint(request))
                row = await repo.create(
                    request,
                    created_at=original.created_at,
                    destination_identity=hashlib.sha256(
                        canonical_json(["instagram", destination.external_account_id])
                    ).hexdigest(),
                )
                row = await append(repo, row, start_entry(row))
                row = await append(repo, row, result_entry(row, "retryable_failure"))
                if index % 2:
                    row = await append(repo, row, start_entry(row))
                    outcome = result_entry(row)
                    await append(
                        repo,
                        row,
                        replace(
                            outcome,
                            evidence=replace(
                                outcome.evidence, external_post_id=f"post-{index}"
                            ),
                        ),
                    )
            # Other workspace/content/destination records must never enter the page.
            await seed(session)
            other_item = MarketingContentItem(
                organization_id=scope,
                campaign_id=await session.scalar(
                    select(MarketingContentItem.campaign_id).where(
                        MarketingContentItem.id == original.marketing_content_item_id
                    )
                ),
                title="Other content",
                content_type="image",
                channels=[MarketingContentItemChannel(channel="instagram")],
            )
            session.add(other_item)
            await session.flush()
            approval = ApprovalRequest(
                organization_id=scope,
                resource_type="marketing_content_item",
                resource_id=other_item.id,
                resource_revision=1,
                title="Other approval",
                status="approved",
            )
            session.add(approval)
            await session.flush()
            other_job_id = uuid4()
            values.update(
                id=other_job_id,
                marketing_content_item_id=other_item.id,
                marketing_content_item_channel_id=other_item.channels[0].id,
                approval_request_id=approval.id,
                activation_operation_id=uuid4(),
                idempotency_key=f"labelos:scheduling:v1:{scope}:{other_job_id}",
            )
            other_job = SchedulingJob(**values)
            session.add(other_job)
            await session.flush()
            other_request = replace(
                request, snapshot=snapshot_for(other_job), job_id=other_job_id
            )
            other_request = replace(
                other_request, payload_fingerprint=fingerprint(other_request)
            )
            await repo.create(other_request, created_at=original.created_at)
            # Current draft fields differ from the accepted snapshot; these large
            # authoring fields and channels must not be loaded by list authorization.
            await session.execute(
                update(MarketingContentItem)
                .where(MarketingContentItem.id == original.marketing_content_item_id)
                .values(metadata_json={"unrelated": "x" * 262144})
            )
            await session.execute(
                update(MarketingContentItemChannel)
                .where(
                    MarketingContentItemChannel.id
                    == original.marketing_content_item_channel_id
                )
                .values(placement="story")
            )
            return original.marketing_content_item_id

    return (*recovery_api, asyncio.run(prepare()))


async def legacy_list(session, scope, item_id, actor, limit):
    """The pre-fix endpoint, retained only as a measurable baseline."""
    await authorized_item(session, scope, item_id, actor)
    ids = list(
        await session.scalars(
            select(Publication.id)
            .where(
                Publication.workspace_id == scope,
                Publication.marketing_content_item_id == item_id,
            )
            .order_by(Publication.id)
            .limit(limit + 1)
        )
    )
    service = PublicationRecoveryService(session, scope, actor=actor)
    return [
        await service.handoff(await service.get(identifier))
        for identifier in ids[:limit]
    ]


def test_bounded_history_query_count_and_no_media_load(
    history_dataset, sessions, capsys
):
    client, _, scope, _, actor, _, item_id = history_dataset
    engine = sessions.kw["bind"].sync_engine
    statements = []
    projection_queries = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            statements.append(statement)
            if "history_page" in statement:
                # Keep executed SQL and binds; cached compiled statements retain
                # the first request's limit as their literal default.
                projection_queries.append((statement, _parameters))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        counts = []
        for limit in (1, 5, 25):

            async def before(limit=limit):
                async with sessions() as session:
                    return await legacy_list(session, scope, item_id, actor, limit)

            statements.clear()
            old = jsonable_encoder(asyncio.run(before()))
            old_count = len(statements)
            old_envelopes = sum(
                "publications.canonical_envelope" in sql for sql in statements
            )
            assert old_envelopes == limit
            statements.clear()
            response = client.get(
                f"/api/v1/workspaces/{scope}/publications",
                params={"content_item_id": str(item_id), "limit": limit},
            )
            assert response.status_code == 200, response.text
            new_count = len(statements)
            counts.append((limit, old_count, new_count))
            assert not any(
                token in sql.lower()
                for sql in statements
                for token in (
                    "canonical_envelope",
                    "asset_refs",
                    "marketing_content_item_channels",
                    "marketing_content_items.metadata",
                    "credential_ref",
                )
            )
            assert sum("history_page" in sql for sql in statements) == 1
            summaries = response.json()["publications"]
            assert len(summaries) == limit
            for summary, detail in zip(summaries, old, strict=True):
                assert "attempts" not in summary and "asset_refs" not in summary
                assert all(value == detail[key] for key, value in summary.items())
            assert new_count < old_count
        assert len({new for _, _, new in counts}) == 1
        assert counts[-1][1] > counts[0][1] * 5

        async def explain():
            sql, parameters = projection_queries[-1]
            async with sessions() as session:
                connection = await session.connection()
                if engine.dialect.name == "sqlite":
                    plan = (
                        await connection.exec_driver_sql(
                            "EXPLAIN QUERY PLAN " + sql, parameters
                        )
                    ).all()
                    assert any("ix_publications_content" in row[3] for row in plan)
                else:
                    plan = (
                        await connection.exec_driver_sql(
                            "EXPLAIN (ANALYZE, FORMAT JSON) " + sql, parameters
                        )
                    ).scalar_one()
                    assert plan[0]["Plan"]["Actual Rows"] == 25

        asyncio.run(explain())
        with capsys.disabled():
            print(f"\nHistory queries (page size, before, after): {counts}")
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def test_history_metadata_backfill_preserves_snapshots(history_dataset, sessions):
    scripts = ScriptDirectory.from_config(
        Config(
            str(Path(__file__).resolve().parents[3] / "packages/database/alembic.ini")
        )
    )
    revision = scripts.get_revision("202609170500").module

    def verify(connection):
        query = select(PublicationListMetadata).order_by(
            PublicationListMetadata.publication_id
        )
        before = connection.execute(query).all()
        assert len(before) == 27
        with Operations.context(MigrationContext.configure(connection)):
            revision.downgrade()
            revision.upgrade()
        assert connection.execute(query).all() == before
        index = next(
            index
            for index in inspect(connection).get_indexes("publications")
            if index["name"] == "ix_publications_content"
        )
        assert index["column_names"] == [
            "workspace_id",
            "marketing_content_item_id",
            "id",
        ]

    async def run():
        async with sessions.kw["bind"].begin() as connection:
            await connection.run_sync(verify)

    asyncio.run(run())


def test_history_pages_scope_and_identity(history_dataset, sessions):
    client, state, scope, _, actor, viewer, item_id = history_dataset
    base = f"/api/v1/workspaces/{scope}/publications"
    params = {"content_item_id": str(item_id), "limit": 7}
    ids = []
    for _ in range(4):
        response = client.get(base, params=params)
        assert response.status_code == 200
        page = response.json()
        ids.extend(row["id"] for row in page["publications"])
        assert all(row["workspace_id"] == str(scope) for row in page["publications"])
        params["after_id"] = page["next_after_id"]
    assert params["after_id"] is None
    assert len(ids) == len(set(ids)) == 25
    assert ids == sorted(ids)
    state["actor"] = viewer
    response = client.get(base, params={"content_item_id": str(item_id)})
    assert response.status_code == 200
    assert all(
        not row["can_manage_recovery"] for row in response.json()["publications"]
    )

    async def retarget():
        async with sessions.begin() as session:
            await session.execute(
                update(SocialAccountConnection)
                .where(SocialAccountConnection.organization_id == scope)
                .values(
                    external_account_id=SocialAccountConnection.external_account_id
                    + "-replaced"
                )
            )

    asyncio.run(retarget())
    page = client.get(base, params={"content_item_id": str(item_id)}).json()
    assert all(row["destination_account"] is None for row in page["publications"])
    assert (
        client.get(
            base, params={"content_item_id": str(item_id), "limit": 101}
        ).status_code
        == 422
    )
    assert (
        client.get(
            base, params={"content_item_id": str(item_id), "limit": 0}
        ).status_code
        == 422
    )
