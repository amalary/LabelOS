"""Production hosts and receiver on PostgreSQL; provider I/O is a test adapter."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from labelos_database.models import (
    MarketingContentItem,
    MarketingContentItemChannel,
    Publication,
    PublicationAttempt,
    PublicationLease,
    RealtimeEvent,
    SchedulingExecutionControl,
    SchedulingJob,
    SchedulingJobTransition,
    SocialAccountConnection,
)
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSessionTransaction

from labelos_api import publishing_worker, scheduling_worker
from labelos_api.api.v1 import scheduling as scheduling_api
from labelos_api.publishing.providers import ProviderRegistry
from labelos_api.repositories.publishing import PublicationRepository
from labelos_api.repositories.scheduling import SchedulingRepository
from labelos_api.scheduling.contracts import DurableAccepted, TerminalRejected
from labelos_api.scheduling.payload import fingerprint
from labelos_api.scheduling.receivers import configured_receiver
from labelos_api.services.credential_store import InMemoryCredentialStore
from labelos_api.services.delivery_orchestrator import DeliveryOrchestrator
from labelos_api.services.scheduling_activation import SchedulingActivationService
from labelos_api.services.scheduling_handoff import accept_scheduling_handoff
from test_delivery_orchestrator import CONTROLS, prepared
from test_publishing_idempotency_postgres import Provider
from test_scheduling_activation import prepare
from test_scheduling_repository import expire, repo
from test_scheduling_repository import sessions as sessions  # noqa: F401
from test_scheduling_worker import ASYNC_CLIENT, tokens, worker_settings  # noqa: F401


@pytest.fixture
def composition(monkeypatch, sessions, worker_settings, tokens):  # noqa: F811
    settings = worker_settings.model_copy(
        update={
            "delivery_receiver_backend": "publishing",
            "scheduling_execution_enabled": True,
            "publishing_execution_enabled": True,
            "credential_store_backend": "gcp-secret-manager",
            "credential_store_gcp_project_id": "test-project",
        }
    )
    provider = Provider()
    monkeypatch.setattr(scheduling_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(scheduling_api, "get_settings", lambda: settings)
    for host in (scheduling_worker, publishing_worker):
        monkeypatch.setattr(host, "get_sessionmaker", lambda _: sessions)
    # External infrastructure only. Keep both hosts, controls, receiver,
    # repositories, leases, orchestrator and transactions unchanged.
    monkeypatch.setattr(
        publishing_worker, "build_credential_store", lambda _: InMemoryCredentialStore()
    )
    monkeypatch.setattr(
        publishing_worker,
        "publishing_provider_registry",
        lambda **_: ProviderRegistry({"instagram": provider}),
    )
    return settings, provider, tokens()


async def scheduled(sessions, settings):
    async with sessions.begin() as session:
        workspace, actor, command, activation = await prepare(session, seconds_ago=-1)
        settings.scheduling_worker_workspace_id = workspace.id
        settings.publishing_worker_workspace_id = workspace.id
        session.add(
            SchedulingExecutionControl(
                workspace_id=workspace.id, execution_enabled=True
            )
        )
        item = await session.get(MarketingContentItem, command.content_item_id)
        item.copy_text = "Approved production composition test"
        connection = await session.get(
            SocialAccountConnection, activation.destination_id
        )
        connection.external_account_id = f"account-{connection.id}"
        await session.flush()
        controls = await scheduling_api.scheduling_controls(workspace.id, session)
        assert controls.can_execute
        job = await SchedulingActivationService(
            session,
            workspace.id,
            actor=actor,
            controls=controls,
            lateness_window_seconds=300,
        ).activate(command)
        now = await session.scalar(select(func.clock_timestamp()))
        wait_seconds = max(0, (job.scheduled_for - now).total_seconds())
    # Let a genuinely future, activated schedule become due without rewriting
    # immutable scheduling intent or replacing the database clock.
    await asyncio.sleep(wait_seconds + 0.01)
    return job


async def sweep(token, *, body=None):
    # Recreate the production app on every call to exercise startup and replay.
    async with ASYNC_CLIENT(
        transport=httpx.ASGITransport(app=scheduling_worker.create_worker_app()),
        base_url="https://worker.test",
    ) as client:
        return await client.post(
            scheduling_worker.WORKER_PATH,
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )


async def publication(sessions, job):
    async with sessions() as session:
        return await PublicationRepository(session, job.workspace_id).get_by_job(job.id)


async def assert_no_acceptance(sessions, job):
    async with sessions() as session:
        saved = await session.get(SchedulingJob, job.id)
        assert saved.status != "handed_off" and saved.handoff_receipt_id is None
        for model in (Publication, PublicationLease, PublicationAttempt):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
        assert (
            await session.scalar(
                select(func.count())
                .select_from(SchedulingJobTransition)
                .where(SchedulingJobTransition.operation == "accept_delivery")
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(RealtimeEvent)
                .where(RealtimeEvent.event_type == "marketing.publication.changed")
            )
            == 0
        )


def test_production_schedule_handoff_and_separate_worker(sessions, composition):
    async def run():
        settings, provider, token = composition
        job = await scheduled(sessions, settings)
        result = await sweep(token)
        assert result.status_code == 200
        assert result.json()["outcomes"] == {"handed_off": 1}
        row = await publication(sessions, job)
        assert row.status == "pending" and not row.attempts and not provider.calls
        async with sessions() as session:
            saved = await session.get(SchedulingJob, job.id)
            assert saved.handoff_receipt_id == row.receipt_id
            assert await session.get(PublicationLease, row.id) is not None
        # A stopped/disabled Publishing process leaves durable pending work.
        settings.publishing_execution_enabled = False
        assert await publishing_worker.run_sweep(settings) == {
            "status": "execution_disabled"
        }
        assert (await sweep(token)).json()["claimed"] == 0
        settings.publishing_execution_enabled = True
        # New processor/owner at every host invocation: no in-memory handoff.
        assert (await publishing_worker.run_sweep(settings))["outcomes"] == {
            "published": 1
        }
        assert (await publication(sessions, job)).status == "published"
        assert (await publishing_worker.run_sweep(settings))["claimed"] == 0
        assert len(provider.calls) == 1

    asyncio.run(run())


def test_enabled_handoff_rejects_human_authority(
    sessions, composition, tokens  # noqa: F811
):
    async def run():
        settings, provider, _ = composition
        job = await scheduled(sessions, settings)
        # Even a correctly signed token must have the dedicated workload issuer
        # and identity; ordinary API authority cannot run the enabled composition.
        response = await sweep(tokens(iss="https://api.workos.com", sub="human-user"))
        assert response.status_code == 401
        await assert_no_acceptance(sessions, job)
        assert not provider.calls

    asyncio.run(run())


def test_configured_receiver_concurrent_duplicate_and_conflicting_replay(
    sessions, composition
):
    async def run():
        settings, _, _ = composition
        request, fence = await prepared(sessions)
        settings.scheduling_worker_workspace_id = request.snapshot.workspace_id

        async def accept(value=request):
            async with sessions.begin() as session:
                return await accept_scheduling_handoff(
                    repo(session, request.snapshot.workspace_id),
                    receiver=configured_receiver(settings),
                    request=value,
                    expected_worker="worker:a",
                    expected_fencing_token=fence,
                    controls=CONTROLS,
                )

        results = await asyncio.gather(accept(), accept(), accept())
        assert isinstance(results[0], DurableAccepted)
        assert results[0] == results[1] == results[2] == await accept()
        changed = replace(request, correlation_id=uuid4())
        changed = replace(changed, payload_fingerprint=fingerprint(changed))
        assert isinstance(await accept(changed), TerminalRejected)
        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(Publication)) == 1
            )
            assert (
                await session.scalar(select(func.count()).select_from(PublicationLease))
                == 1
            )

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["cancel", "supersede"])
def test_cancelled_or_superseded_schedule_cannot_handoff(
    sessions, composition, operation
):
    async def run():
        settings, provider, token = composition
        job = await scheduled(sessions, settings)
        async with sessions.begin() as session:
            await repo(session, job.workspace_id).apply_user_transition(
                job.id, operation=operation, operation_id=uuid4(), actor_key="test:user"
            )
        assert (await sweep(token)).json()["claimed"] == 0
        await assert_no_acceptance(sessions, job)
        assert (await publishing_worker.run_sweep(settings))["claimed"] == 0
        assert not provider.calls

    asyncio.run(run())


@pytest.mark.parametrize("change", ["cancel_publication", "supersede_source"])
def test_cancel_or_source_change_after_handoff_prevents_execution(
    sessions, composition, change
):
    async def run():
        settings, provider, token = composition
        job = await scheduled(sessions, settings)
        assert (await sweep(token)).json()["outcomes"] == {"handed_off": 1}
        row = await publication(sessions, job)
        if change == "cancel_publication":
            await DeliveryOrchestrator().cancel_waiting(
                sessions,
                workspace_id=job.workspace_id,
                publication_id=row.id,
                expected_version=row.transition_version,
            )
        else:
            async with sessions.begin() as session:
                channel = await session.get(
                    MarketingContentItemChannel, job.marketing_content_item_channel_id
                )
                channel.schedule_generation += 1
        await publishing_worker.run_sweep(settings)
        assert not provider.calls
        assert not (await publication(sessions, job)).attempts

    asyncio.run(run())


def test_unavailable_publishing_storage_rolls_back_and_recovers(sessions, composition):
    async def run():
        settings, provider, token = composition
        job = await scheduled(sessions, settings)
        # Real PostgreSQL failure late in Publication creation, after row flush:
        # simulate missing lease infrastructure without replacing the receiver.
        async with sessions.begin() as session:
            await session.execute(
                text("ALTER TABLE publication_leases RENAME TO unavailable_leases")
            )
        try:
            response = await sweep(token)
            assert response.json()["outcomes"] == {"job_failed": 1}
            assert "unavailable_leases" not in response.text
            assert not provider.calls
        finally:
            async with sessions.begin() as session:
                await session.execute(
                    text("ALTER TABLE unavailable_leases RENAME TO publication_leases")
                )
        await assert_no_acceptance(sessions, job)
        async with sessions.begin() as session:
            await expire(session, job.id)
        assert (await sweep(token)).json()["outcomes"] == {"handed_off": 1}
        assert (await publishing_worker.run_sweep(settings))["outcomes"] == {
            "published": 1
        }
        assert len(provider.calls) == 1

    asyncio.run(run())


@pytest.mark.parametrize("committed", [False, True])
def test_restart_before_or_after_acceptance_commit(
    sessions, composition, monkeypatch, committed
):
    async def run():
        settings, provider, token = composition
        job = await scheduled(sessions, settings)
        original_record = SchedulingRepository.record_handoff_acceptance
        original_exit = AsyncSessionTransaction.__aexit__

        async def record(self, *args, **kwargs):
            result = await original_record(self, *args, **kwargs)
            self.session.info["interrupt_acceptance"] = True
            return result

        async def interrupted_exit(self, *args):
            if not self.nested and self.session.info.pop("interrupt_acceptance", False):
                if committed:
                    await original_exit(self, *args)
                else:
                    await self.rollback()
                raise RuntimeError("injected process interruption")
            return await original_exit(self, *args)

        with monkeypatch.context() as patch:
            patch.setattr(SchedulingRepository, "record_handoff_acceptance", record)
            patch.setattr(AsyncSessionTransaction, "__aexit__", interrupted_exit)
            assert (await sweep(token)).json()["outcomes"] == {"job_failed": 1}
        assert not provider.calls
        if not committed:
            await assert_no_acceptance(sessions, job)
            async with sessions.begin() as session:
                await expire(session, job.id)
        response = await sweep(token)
        assert response.json()["claimed"] == (0 if committed else 1)
        assert (await publication(sessions, job)).status == "pending"
        assert (await publishing_worker.run_sweep(settings))["outcomes"] == {
            "published": 1
        }
        assert (await publishing_worker.run_sweep(settings))["claimed"] == 0
        assert len(provider.calls) == 1

    asyncio.run(run())


def test_hosts_and_receiver_preserve_workspace_isolation(sessions, composition):
    async def run():
        settings, provider, token = composition
        first = await scheduled(sessions, settings)
        second = await scheduled(sessions, settings)
        response = await sweep(
            token,
            body={
                "workspace_id": str(first.workspace_id),
                "delivery_receiver_backend": "unavailable",
                "actor": "human-admin",
            },
        )
        assert response.json()["outcomes"] == {"handed_off": 1}
        assert await publication(sessions, first) is None
        second_publication = await publication(sessions, second)
        settings.publishing_worker_workspace_id = first.workspace_id
        assert (await publishing_worker.run_sweep(settings))["claimed"] == 0
        assert not provider.calls
        async with sessions() as session:
            assert (
                await PublicationRepository(session, first.workspace_id).get(
                    second_publication.id
                )
                is None
            )
        request, _ = await prepared(sessions)
        async with sessions.begin() as session:
            result = await configured_receiver(
                settings, workspace_id=first.workspace_id
            ).accept(session, request)
            assert isinstance(result, TerminalRejected)
        settings.publishing_worker_workspace_id = second.workspace_id
        assert (await publishing_worker.run_sweep(settings))["outcomes"] == {
            "published": 1
        }
        assert len(provider.calls) == 1
        assert provider.calls[0].workspace_id == second.workspace_id

    asyncio.run(run())
