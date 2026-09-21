"""Internal delivery context and application result; no provider SDK objects."""

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True, kw_only=True)
class PublicationClaim:
    workspace_id: UUID
    publication_id: UUID
    owner_id: UUID
    fencing_token: int
    transition_version: int
    recovering: bool = False


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
    readiness_reason: str | None = None


@dataclass(frozen=True, kw_only=True)
class DeliveryResult:
    publication_id: UUID
    status: str
    reason_code: str | None = None
    retry_after_seconds: int | None = None
