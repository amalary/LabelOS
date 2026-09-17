"""Minimal trusted adapter contract. No SDKs, credentials, I/O or auto-discovery.

Adapters normalize their own responses/errors. Unhandled errors are ambiguous;
HTTP status alone (including 429/401) never proves absence of a side effect.
"""

import base64
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from labelos_api.publishing import contracts as domain
from labelos_api.publishing.execution import DeliveryContext
from labelos_api.publishing.retries import FailureCategory as Category


class AdapterContractError(ValueError):
    def __init__(self):
        super().__init__("invalid_adapter_result")


@dataclass(frozen=True, kw_only=True)
class ProviderCapabilities:
    publish: bool = True
    reconcile: bool = False

    def __post_init__(self) -> None:
        if type(self.publish) is not bool or type(self.reconcile) is not bool:
            raise AdapterContractError()


@dataclass(frozen=True, kw_only=True)
class PublicationMedia:
    sha256: str
    media_type: str
    data: bytes = field(repr=False)


@dataclass(frozen=True, kw_only=True)
class PublicationRequest:
    """Immutable projection of validated, accepted LabelOS content.

    destination_id is workspace-scoped. Before I/O the adapter must resolve its
    own credentials and verify SHA-256(canonical [provider, external_account_id])
    against destination_identity. No credentials or opaque provider data cross
    this boundary. Keys stay stable across retries; they are NOT an exactly-once
    guarantee. Reconciliation looks up the same attempt without publishing again.
    """

    workspace_id: UUID
    publication_id: UUID
    destination_id: UUID
    provider: str
    destination_identity: str = field(repr=False)
    idempotency_key: str
    attempt: domain.PublicationAttempt
    channel: str
    placement: str
    caption: str | None = field(repr=False)
    hashtags: tuple[str, ...] = field(repr=False)
    media: tuple[PublicationMedia, ...] = field(repr=False)


def publication_request(
    context: DeliveryContext, attempt: domain.PublicationAttempt
) -> PublicationRequest:
    """Only called with an accepted envelope already validated by Delivery."""
    if (
        attempt.workspace_id != context.workspace_id
        or attempt.publication_id != context.publication_id
    ):
        raise AdapterContractError()
    content = json.loads(context.canonical_envelope)["content"]
    return PublicationRequest(
        workspace_id=context.workspace_id,
        publication_id=context.publication_id,
        destination_id=context.destination_id,
        provider=context.provider,
        destination_identity=context.destination_identity,
        idempotency_key=f"labelos:publication:v1:{context.workspace_id}:{context.publication_id}",
        attempt=attempt,
        channel=content["channel"],
        placement=content["placement"],
        caption=content["caption"],
        hashtags=tuple(content["hashtags"]),
        media=tuple(
            PublicationMedia(
                sha256=asset["sha256"],
                media_type=asset["media_type"],
                data=base64.b64decode(asset["content_base64"], validate=True),
            )
            for asset in content["asset_refs"]
        ),
    )


class ProviderOutcome(StrEnum):
    published = "published"
    accepted = "accepted"
    retryable_failure = "retryable_failure"
    permanent_failure = "permanent_failure"
    authorization_required = "authorization_required"
    rate_limited = "rate_limited"
    ambiguous = "ambiguous"
    unsupported = "unsupported"


_FAILURES = frozenset(
    {
        ProviderOutcome.retryable_failure,
        ProviderOutcome.permanent_failure,
        ProviderOutcome.authorization_required,
        ProviderOutcome.rate_limited,
    }
)


_CATEGORIES = {
    ProviderOutcome.published: {None},
    ProviderOutcome.accepted: {Category.ambiguous_outcome},
    ProviderOutcome.ambiguous: {Category.ambiguous_outcome},
    ProviderOutcome.retryable_failure: {
        Category.provider_unavailable,
        Category.transient_network,
        Category.internal_failure,
    },
    ProviderOutcome.rate_limited: {Category.rate_limited},
    ProviderOutcome.authorization_required: {
        Category.authentication,
        Category.authorization,
    },
    ProviderOutcome.permanent_failure: {
        Category.permanent_rejection,
        Category.invalid_content_media,
    },
    ProviderOutcome.unsupported: {Category.unsupported_operation},
}
_DEFAULT_CATEGORY = {
    ProviderOutcome.retryable_failure: Category.provider_unavailable,
    ProviderOutcome.authorization_required: Category.authentication,
    ProviderOutcome.permanent_failure: Category.permanent_rejection,
}


@dataclass(frozen=True, kw_only=True)
class ProviderResult:
    """No raw response, exception message, arbitrary metadata or credentials.

    Failures require authoritative FINAL nonpublication: the original request
    cannot later create a resource. A transient lookup miss, eventual-consistency
    gap, expired receipt, or still-running request is not confirmed_absent.
    unsupported describes only the
    requested operation and makes no claim about an earlier publication.
    If a request might have had a
    side effect, return ambiguous instead. accepted means unfinished external work,
    never success. External IDs must be sanitized non-secret identifiers.
    retry_after_seconds is advisory only; this contract schedules no retry.
    """

    outcome: ProviderOutcome
    external_post_id: str | None = field(default=None, repr=False)
    confirmed_absent: bool = False
    retry_after_seconds: int | None = None
    failure_category: Category | None = None

    def __post_init__(self) -> None:
        if self.failure_category is None and isinstance(self.outcome, ProviderOutcome):
            category = _DEFAULT_CATEGORY.get(self.outcome)
            if category is None:
                category = next(iter(_CATEGORIES[self.outcome]))
            object.__setattr__(self, "failure_category", category)
        validate_result(self)


def validate_result(value: object) -> ProviderResult:
    """Runtime boundary check, including incorrectly typed or mutated adapters."""
    if type(value) is not ProviderResult:
        raise AdapterContractError()
    if (
        not isinstance(value.outcome, ProviderOutcome)
        or type(value.confirmed_absent) is not bool
        or value.confirmed_absent != (value.outcome in _FAILURES)
    ):
        raise AdapterContractError()
    if value.failure_category not in _CATEGORIES[value.outcome] or (
        value.failure_category is not None
        and not isinstance(value.failure_category, Category)
    ):
        raise AdapterContractError()
    if value.outcome == ProviderOutcome.published:
        identifier = value.external_post_id
        if (
            not isinstance(identifier, str)
            or not identifier.strip()
            or identifier != identifier.strip()
            or len(identifier) > 512
            or any(ord(c) < 32 or ord(c) == 127 for c in identifier)
        ):
            raise AdapterContractError()
    elif value.external_post_id is not None:
        raise AdapterContractError()
    if value.retry_after_seconds is not None and (
        value.outcome
        not in {ProviderOutcome.rate_limited, ProviderOutcome.retryable_failure}
        or type(value.retry_after_seconds) is not int
        or not 0 <= value.retry_after_seconds <= 604800
    ):
        raise AdapterContractError()
    return value


def validate_preflight(value: object) -> ProviderResult | None:
    if value is None:
        return None
    result = validate_result(value)
    if result.outcome not in _FAILURES | {ProviderOutcome.unsupported}:
        raise AdapterContractError()
    return result


class PublishingProviderAdapter(Protocol):
    """Trusted server wiring only. Implementations contain all platform behavior.

    validate is synchronous, local and side-effect-free. It returns None when ready
    or a normalized rejection. It cannot transform approved content. publish and
    reconcile run outside database transactions. reconcile is read-only externally
    and must return unsupported when unavailable. It must never invoke publish.
    Error normalization belongs inside these methods, not in the core domain.
    """

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def validate(self, request: PublicationRequest) -> ProviderResult | None: ...

    async def publish(self, request: PublicationRequest) -> ProviderResult: ...

    async def reconcile(self, request: PublicationRequest) -> ProviderResult: ...


class ProviderResolutionError(ValueError):
    """Fixed safe reason; never echoes the supplied provider/destination."""


class ProviderRegistry:
    """Immutable explicit canonical-key registrations; empty by default.

    No aliases, guessed platform mapping, fallback adapter or plugin loading.
    Resolve the provider from the locked canonical destination, never user input.
    Account-specific support is checked by adapter validation/credential binding.
    """

    def __init__(
        self, adapters: Mapping[str, PublishingProviderAdapter] | None = None
    ) -> None:
        entries = dict(adapters or {})
        for key, adapter in entries.items():
            if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", key):
                raise ProviderResolutionError("invalid_provider_registration")
            capabilities = adapter.capabilities
            if type(capabilities) is not ProviderCapabilities:
                raise ProviderResolutionError("invalid_provider_registration")
            capabilities.__post_init__()
            if any(
                not callable(getattr(adapter, method, None))
                for method in ("validate", "publish", "reconcile")
            ):
                raise ProviderResolutionError("invalid_provider_registration")
        self._adapters = MappingProxyType(entries)

    def resolve(self, provider: str) -> PublishingProviderAdapter:
        adapter = self._adapters.get(provider) if isinstance(provider, str) else None
        if adapter is None:
            raise ProviderResolutionError("unsupported_provider")
        return adapter


def result_evidence(
    request: PublicationRequest,
    result: ProviderResult,
    *,
    source: domain.EvidenceSource = domain.EvidenceSource.provider_response,
    observed_at: datetime | None = None,
) -> domain.PublicationEvidence:
    """Bind evidence in the core: adapters cannot choose another tenant/attempt."""
    validate_result(result)
    outcome, reason = {
        ProviderOutcome.published: (domain.DeliveryOutcome.published, None),
        ProviderOutcome.accepted: (
            domain.DeliveryOutcome.unknown,
            domain.PublicationFailureReason.outcome_unknown,
        ),
        ProviderOutcome.ambiguous: (
            domain.DeliveryOutcome.unknown,
            domain.PublicationFailureReason.outcome_unknown,
        ),
        ProviderOutcome.retryable_failure: (
            domain.DeliveryOutcome.retryable_failure,
            domain.PublicationFailureReason.temporary_unavailability,
        ),
        ProviderOutcome.rate_limited: (
            domain.DeliveryOutcome.retryable_failure,
            domain.PublicationFailureReason.rate_limited,
        ),
        ProviderOutcome.permanent_failure: (
            domain.DeliveryOutcome.permanent_failure,
            domain.PublicationFailureReason.invalid_content,
        ),
        ProviderOutcome.authorization_required: (
            domain.DeliveryOutcome.retryable_failure,
            domain.PublicationFailureReason.authorization_required,
        ),
        ProviderOutcome.unsupported: (
            domain.DeliveryOutcome.permanent_failure,
            domain.PublicationFailureReason.destination_unavailable,
        ),
    }[result.outcome]
    return domain.PublicationEvidence(
        workspace_id=request.workspace_id,
        publication_id=request.publication_id,
        attempt_id=request.attempt.id,
        destination_id=request.destination_id,
        outcome=outcome,
        source=source,
        observed_at=observed_at or datetime.now(UTC),
        failure_category=result.failure_category,
        retry_after_seconds=result.retry_after_seconds,
        external_post_id=result.external_post_id,
        reason=reason,
    )
