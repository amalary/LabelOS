"""Bounded Publishing sweeps for a trusted, workspace-scoped worker host.

Reuses delivery preparation, adapters, normalization, retry policy and journal.
Scheduling ownership ends at acceptance and is never extended by this worker.
"""

import asyncio
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID, uuid4, uuid5

from labelos_database.models import PublicationLease

from labelos_api.repositories.publication_leases import (
    PublicationLeaseLost,
    PublicationLeaseRepository,
)
from labelos_api.repositories.publishing import (
    PublicationConflict,
    PublicationRepository,
)
from labelos_api.services.delivery_orchestrator import (
    DeliveryIneligible,
    DeliveryOrchestrator,
)


@dataclass
class PublishingBatchResult:
    claimed: int = 0
    recovered: int = 0
    outcomes: Counter = field(default_factory=Counter)


class PublishingProcessor:
    def __init__(
        self,
        sessions,
        *,
        workspace_id: UUID,
        registry,
        owner_id: UUID | None = None,
        batch_size: int = 100,
        lease_duration: timedelta = timedelta(minutes=2),
        execution_timeout: float = 300,
    ):
        if not isinstance(workspace_id, UUID) or not workspace_id.int:
            raise ValueError("invalid_publication_workspace")
        if type(batch_size) is not int or not 1 <= batch_size <= 1000:
            raise ValueError("invalid_publication_batch_size")
        if not timedelta(seconds=1) <= lease_duration <= timedelta(hours=1):
            raise ValueError("invalid_publication_lease_duration")
        if not 0 < execution_timeout <= 3600:
            raise ValueError("invalid_publication_execution_timeout")
        self.sessions, self.workspace_id, self.registry = (
            sessions,
            workspace_id,
            registry,
        )
        self.owner_id = owner_id or uuid4()
        self.batch_size, self.lease_duration = batch_size, lease_duration
        self.execution_timeout = execution_timeout
        self.delivery = DeliveryOrchestrator()

    async def claim_next(self, *, exclude=()):
        # T1: commit ownership before source preparation; never prelease a batch
        # that could expire while earlier requests are running.
        async with self.sessions.begin() as session:
            return await PublicationLeaseRepository(
                session, self.workspace_id
            ).claim_next(
                owner_id=self.owner_id, duration=self.lease_duration, exclude=exclude
            )

    async def _heartbeat(self, claim):
        while True:
            await asyncio.sleep(self.lease_duration.total_seconds() / 3)
            async with self.sessions.begin() as session:
                await PublicationLeaseRepository(session, self.workspace_id).renew(
                    claim, self.lease_duration
                )

    async def _execute(self, claim):
        if claim.recovering:
            async with self.sessions() as session:
                row = await PublicationRepository(session, self.workspace_id).get(
                    claim.publication_id
                )
                if row is None or not row.attempts:
                    raise PublicationLeaseLost("publication_recovery_missing")
                execution_id = row.attempts[-1].execution_id
            # Recovery never invokes publish (or trusts an absence read while the
            # old executor might resume). The journal records uncertain delivery.
            return await self.delivery.recover_interrupted(
                self.sessions,
                workspace_id=self.workspace_id,
                publication_id=claim.publication_id,
                execution_id=execution_id,
                expected_version=claim.transition_version,
                claim=claim,
            )
        return await self.delivery.execute(
            self.sessions,
            workspace_id=self.workspace_id,
            publication_id=claim.publication_id,
            registry=self.registry,
            execution_id=uuid5(
                claim.publication_id,
                f"labelos:publication:worker:v1:{claim.transition_version}",
            ),
            expected_version=claim.transition_version,
            claim=claim,
        )

    async def process_claim(self, claim):
        if claim.workspace_id != self.workspace_id or claim.owner_id != self.owner_id:
            raise PublicationLeaseLost("publication_worker_scope_mismatch")
        execution = asyncio.create_task(self._execute(claim))
        heartbeat = asyncio.create_task(self._heartbeat(claim))
        try:
            async with asyncio.timeout(self.execution_timeout):
                done, _ = await asyncio.wait(
                    (execution, heartbeat), return_when=asyncio.FIRST_COMPLETED
                )
                if execution in done:
                    return await execution
                # Renewal failure means stop local work. Cancellation cannot undo
                # a network write; the durable start remains leased for recovery.
                await heartbeat
                raise PublicationLeaseLost("publication_heartbeat_stopped")
        finally:
            execution.cancel()
            heartbeat.cancel()
            for task in (execution, heartbeat):
                with suppress(asyncio.CancelledError, Exception):
                    await task

    async def _release_waiting(self, claim):
        # Completed evidence releases atomically. This path handles preflight
        # refusal/unsupported providers only; never release an interrupted start.
        async with self.sessions.begin() as session:
            row = await PublicationRepository(session, self.workspace_id).get(
                claim.publication_id, lock=True
            )
            if row is not None and row.status in ("pending", "retryable_failure"):
                lease = await session.get(PublicationLease, row.id)
                if lease is not None and lease.owner_id is not None:
                    await PublicationLeaseRepository(
                        session, self.workspace_id
                    ).release(claim)

    async def run(self, *, stop: asyncio.Event | None = None):
        """Stop drains current work; task cancellation leaves durable recovery work."""
        result, seen = PublishingBatchResult(), set()
        for _ in range(self.batch_size):
            if stop is not None and stop.is_set():
                break
            claim = await self.claim_next(exclude=seen)
            if claim is None:
                break
            seen.add(claim.publication_id)
            result.claimed += 1
            try:
                outcome = await self.process_claim(claim)
                result.outcomes[outcome.reason_code or outcome.status] += 1
                result.recovered += int(claim.recovering)
                await self._release_waiting(claim)
            except (DeliveryIneligible, PublicationConflict):
                result.outcomes["ineligible"] += 1
                with suppress(PublicationLeaseLost):
                    await self._release_waiting(claim)
            except PublicationLeaseLost:
                result.outcomes["claim_lost"] += 1
            except TimeoutError:
                result.outcomes["timed_out"] += 1
            except Exception:
                # Unknown commit acknowledgements stay leased for readback/recovery.
                # Never expose provider payloads, exception text or credentials.
                result.outcomes["failed"] += 1
        return result
