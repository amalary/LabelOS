"""Test-only durable receiver: no production inbox or fake success configuration."""

import asyncio
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from labelos_database.models import (
    MarketingContentItem,
    SchedulingJob,
    SocialAccountConnection,
)
from sqlalchemy import Column, LargeBinary, MetaData, String, Table, select, update
from sqlalchemy.dialects.postgresql import insert

from labelos_api.logging import JsonFormatter
from labelos_api.repositories.scheduling import snapshot_for
from labelos_api.scheduling.contracts import (
    DeliveryAcceptanceReceipt,
    DurableAccepted,
    DurableDeliveryReceiverUnavailable,
    RetryableUnavailable,
    SchedulingFeatureControls,
    TerminalRejected,
)
from labelos_api.scheduling.payload import (
    canonical_json,
    envelope,
    fingerprint,
    prepare_request,
    validate_request,
)
from labelos_api.services.scheduling_handoff import accept_scheduling_handoff
from test_scheduling_repository import claim, repo, seed
from test_scheduling_repository import sessions as repository_sessions  # noqa: F401

inbox = Table(
    "fake_durable_handoff_inbox",
    MetaData(),
    Column("key", String, primary_key=True),
    Column("fingerprint", String, nullable=False),
    Column("receipt", String, nullable=False),
    Column("envelope", LargeBinary, nullable=False),
)


class FakeDurableReceiver:
    async def accept(self, session, request):
        validate_request(request)
        await session.execute(
            insert(inbox)
            .values(
                key=request.idempotency_key,
                fingerprint=request.payload_fingerprint,
                receipt=str(uuid4()),
                envelope=canonical_json(envelope(request)),
            )
            .on_conflict_do_nothing(index_elements=[inbox.c.key])
        )
        row = (
            await session.execute(
                select(inbox).where(inbox.c.key == request.idempotency_key)
            )
        ).one()
        if row.fingerprint != request.payload_fingerprint:
            return TerminalRejected()
        return DurableAccepted(
            receipt=DeliveryAcceptanceReceipt(
                delivery_request_id=UUID(row.receipt),
                idempotency_key=row.key,
                payload_fingerprint=row.fingerprint,
            )
        )


@pytest.fixture
def sessions(repository_sessions):  # noqa: F811
    async def create():
        async with repository_sessions.begin() as session:
            connection = await session.connection()
            await connection.run_sync(inbox.metadata.create_all)

    asyncio.run(create())
    return repository_sessions


async def prepared(sessions):
    async with sessions.begin() as session:
        workspace, _, _ = await seed(session)
        await session.execute(
            update(SocialAccountConnection).values(
                status="connected", capabilities=["content_publish"]
            )
        )
        job = (await claim(session, workspace.id))[0]
        repository = repo(session, workspace.id)
        source = await repository.lock_activation_source(
            job.marketing_content_item_id, job.marketing_content_item_channel_id
        )
        source.channel.schedule_local_time = job.scheduled_for.replace(
            tzinfo=None
        ).isoformat()
        source.channel.schedule_offset_seconds = 0
        source.item.copy_text = "APPROVED_PRIVATE_COPY"
        source.item.metadata_json = {"access_token": "SECRET_TOKEN"}
        request = prepare_request(
            snapshot=snapshot_for(job),
            job_id=job.id,
            destination_id=job.social_account_connection_id,
            artist_profile_id=job.effective_artist_id,
            authoring_timezone=job.schedule_timezone,
            correlation_id=uuid4(),
            item=source.item,
            channel=source.channel,
            asset_bytes={},
        )
        return request, job.fencing_token


async def accept(session, request, fence, receiver=None, **kwargs):
    return await accept_scheduling_handoff(
        repo(session, request.snapshot.workspace_id),
        receiver=receiver or FakeDurableReceiver(),
        request=request,
        expected_worker="worker:a",
        expected_fencing_token=fence,
        controls=SchedulingFeatureControls(
            execution_enabled=True, delivery_receiver_configured=True
        ),
        **kwargs,
    )


def test_commit_idempotent_readback_and_later_edits(sessions, caplog):
    async def run():
        request, fence = await prepared(sessions)
        async with sessions.begin() as session:
            first = await accept(session, request, fence)
            assert isinstance(first, DurableAccepted)
        async with sessions.begin() as session:
            await session.execute(
                update(MarketingContentItem).values(
                    copy_text="changed", content_revision=2
                )
            )
        async with sessions.begin() as session:
            assert await accept(session, request, fence) == first
            job = await session.get(SchedulingJob, request.job_id)
            assert job.status == "handed_off"
            assert job.handoff_receipt_id == first.receipt_id
            row = (await session.execute(select(inbox))).one()
            assert row.envelope == canonical_json(envelope(request))
            assert b"SECRET_TOKEN" not in row.envelope
        return request

    with caplog.at_level("INFO"):
        request = asyncio.run(run())
    assert "APPROVED_PRIVATE_COPY" not in caplog.text
    assert "SECRET_TOKEN" not in caplog.text
    records = [r for r in caplog.records if r.msg == "scheduling_handoff_result"]
    assert len(records) == 2
    assert all(r.correlation_id == str(request.correlation_id) for r in records)
    assert all(r.handoff_outcome == "DurableAccepted" for r in records)


def test_concurrent_acceptance_and_key_conflict(sessions):
    async def run():
        request, fence = await prepared(sessions)

        async def attempt():
            async with sessions.begin() as session:
                return await accept(session, request, fence)

        results = await asyncio.gather(attempt(), attempt())
        assert isinstance(results[0], DurableAccepted)
        assert results[0] == results[1]
        changed = replace(request, correlation_id=uuid4())
        changed = replace(changed, payload_fingerprint=fingerprint(changed))
        async with sessions.begin() as session:
            assert isinstance(await accept(session, changed, fence), TerminalRejected)
            assert len((await session.execute(select(inbox))).all()) == 1

    asyncio.run(run())


@pytest.mark.parametrize("outcome", [RetryableUnavailable(), TerminalRejected()])
def test_nonacceptance_rolls_back_partial_receiver_writes(sessions, outcome):
    class PartialReceiver(FakeDurableReceiver):
        async def accept(self, session, request):
            await super().accept(session, request)
            return outcome

    async def run():
        request, fence = await prepared(sessions)
        async with sessions.begin() as session:
            assert await accept(session, request, fence, PartialReceiver()) == outcome
        async with sessions.begin() as session:
            assert not (await session.execute(select(inbox))).all()
            assert (
                await session.get(SchedulingJob, request.job_id)
            ).status == "claimed"
            assert isinstance(await accept(session, request, fence), DurableAccepted)

    asyncio.run(run())


def test_outer_rollback_and_receipt_mismatch_are_atomic(sessions):
    class WrongReceipt(FakeDurableReceiver):
        async def accept(self, session, request):
            result = await super().accept(session, request)
            return DurableAccepted(
                receipt=replace(result.receipt, payload_fingerprint="wrong")
            )

    async def run():
        request, fence = await prepared(sessions)
        async with sessions() as session:
            assert isinstance(await accept(session, request, fence), DurableAccepted)
            await session.rollback()
        async with sessions.begin() as session:
            assert not (await session.execute(select(inbox))).all()
            assert isinstance(
                await accept(session, request, fence, WrongReceipt()), TerminalRejected
            )
        async with sessions.begin() as session:
            assert not (await session.execute(select(inbox))).all()
            assert (
                await session.get(SchedulingJob, request.job_id)
            ).status == "claimed"

    asyncio.run(run())


def test_unavailable_exception_has_safe_structured_logs(sessions, caplog):
    class Unavailable:
        async def accept(self, session, request):
            raise DurableDeliveryReceiverUnavailable(
                "SECRET_TOKEN https://secret?token=abc"
            )

    async def run():
        request, fence = await prepared(sessions)
        async with sessions.begin() as session:
            assert isinstance(
                await accept(session, request, fence, Unavailable()),
                RetryableUnavailable,
            )
            assert (
                await session.get(SchedulingJob, request.job_id)
            ).status == "claimed"
            assert not (await session.execute(select(inbox))).all()

    with caplog.at_level("INFO"):
        asyncio.run(run())
    formatter = JsonFormatter(
        service_name="test", service_version="1", environment="test"
    )
    logs = "\n".join(formatter.format(record) for record in caplog.records)
    assert "SECRET_TOKEN" not in logs
    assert "APPROVED_PRIVATE_COPY" not in logs
    assert "https://secret" not in logs
    assert "RetryableUnavailable" in logs


@pytest.mark.parametrize("drift", ["revision", "payload", "fence", "destination"])
def test_final_validation_prevents_receiver_call(sessions, drift):
    class NeverCalled:
        async def accept(self, session, request):
            pytest.fail("Receiver must not be called before validation")

    async def run():
        request, fence = await prepared(sessions)
        async with sessions.begin() as session:
            if drift == "revision":
                await session.execute(
                    update(MarketingContentItem).values(content_revision=2)
                )
            elif drift == "payload":
                await session.execute(
                    update(MarketingContentItem).values(copy_text="unauthorized drift")
                )
            elif drift == "destination":
                await session.execute(
                    update(SocialAccountConnection).values(status="disconnected")
                )
        async with sessions.begin() as session:
            result = await accept(
                session, request, fence + (drift == "fence"), NeverCalled()
            )
            assert isinstance(result, TerminalRejected)
            assert not (await session.execute(select(inbox))).all()
            assert (
                await session.get(SchedulingJob, request.job_id)
            ).status == "claimed"

    asyncio.run(run())
