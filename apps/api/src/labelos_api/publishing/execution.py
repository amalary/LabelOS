"""Trusted provider seam. No deployable provider execution is supplied in Stage 3."""

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from labelos_api.publishing.contracts import PublicationAttempt, PublicationEvidence


@dataclass(frozen=True, kw_only=True)
class DeliveryContext:
    workspace_id: UUID
    publication_id: UUID
    scheduling_job_id: UUID
    destination_id: UUID
    provider: str
    destination_identity: str = field(repr=False)
    canonical_envelope: bytes = field(repr=False)
    transition_version: int


class PublicationProvider(Protocol):
    """Internal injection only, never constructed from public request data.

    Adapters must bind credentials to destination_identity before I/O and produce
    normalized evidence. The internal publication ID is not proof of provider
    idempotency. An exception or ambiguous response cannot establish nonpublication.
    """

    @property
    def enabled(self) -> bool: ...

    async def deliver(
        self, context: DeliveryContext, attempt: PublicationAttempt
    ) -> PublicationEvidence: ...


class DisabledPublicationProvider:
    enabled = False

    async def deliver(
        self, context: DeliveryContext, attempt: PublicationAttempt
    ) -> PublicationEvidence:
        raise RuntimeError("provider_execution_disabled")


@dataclass(frozen=True, kw_only=True)
class DeliveryResult:
    publication_id: UUID
    status: str
    reason_code: str | None = None
