"""Provider-neutral, versioned retry policy. Pure calculations; no sleeps or I/O."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from math import isfinite


class FailureCategory(StrEnum):
    transient_network = "transient_network"
    provider_unavailable = "provider_unavailable"
    rate_limited = "rate_limited"
    authentication = "authentication"
    authorization = "authorization"
    invalid_content_media = "invalid_content_media"
    unsupported_operation = "unsupported_operation"
    ambiguous_outcome = "ambiguous_outcome"
    permanent_rejection = "permanent_rejection"
    internal_failure = "internal_failure"


class RetryDisposition(StrEnum):
    automatic = "automatic"
    provider_delay = "provider_delay"
    blocked_reconnection = "blocked_reconnection"
    reconciliation_required = "reconciliation_required"
    permanent = "permanent"
    manual_action = "manual_action"
    exhausted = "exhausted"


AUTOMATIC = frozenset(
    {
        FailureCategory.transient_network,
        FailureCategory.provider_unavailable,
        FailureCategory.rate_limited,
    }
)
# Version 1 is deliberately fixed, so restarts/configuration changes cannot reset
# a publication's budget. Attempts include the initial execution and preflight.
POLICY_VERSION = 1
MAX_ATTEMPTS = 5
MAX_ELAPSED = timedelta(hours=24)
BASE_DELAY_SECONDS = 30
MAX_DELAY_SECONDS = 1800
MAX_PROVIDER_DELAY_SECONDS = 604800


@dataclass(frozen=True)
class RetryDecision:
    disposition: RetryDisposition
    next_retry_at: datetime | None = None
    deadline_at: datetime | None = None
    policy_version: int = POLICY_VERSION


def retry_decision(
    category: FailureCategory,
    *,
    attempt_number: int,
    first_started_at: datetime,
    observed_at: datetime,
    retry_after_seconds: int | None = None,
    jitter: float = 0.5,
) -> RetryDecision:
    """Equal jitter in [half the exponential cap, cap]; provider delay is a floor.

    A delay beyond the elapsed budget exhausts the policy; it is never shortened.
    Only adapters with authoritative final nonpublication may select AUTOMATIC.
    """
    if (
        not isinstance(category, FailureCategory)
        or type(attempt_number) is not int
        or attempt_number < 1
        or first_started_at.utcoffset() != timedelta(0)
        or observed_at.utcoffset() != timedelta(0)
        or observed_at < first_started_at
        or not isfinite(jitter)
        or not 0 <= jitter <= 1
        or (
            retry_after_seconds is not None
            and (
                type(retry_after_seconds) is not int
                or not 0 <= retry_after_seconds <= MAX_PROVIDER_DELAY_SECONDS
            )
        )
    ):
        raise ValueError("invalid_retry_inputs")
    if category not in AUTOMATIC:
        disposition = {
            FailureCategory.authentication: RetryDisposition.blocked_reconnection,
            FailureCategory.authorization: RetryDisposition.blocked_reconnection,
            FailureCategory.ambiguous_outcome: RetryDisposition.reconciliation_required,
            FailureCategory.internal_failure: RetryDisposition.manual_action,
        }.get(category, RetryDisposition.permanent)
        return RetryDecision(disposition)
    deadline = first_started_at + MAX_ELAPSED
    if attempt_number >= MAX_ATTEMPTS or observed_at >= deadline:
        return RetryDecision(RetryDisposition.exhausted, deadline_at=deadline)
    cap = min(MAX_DELAY_SECONDS, BASE_DELAY_SECONDS * 2 ** (attempt_number - 1))
    delay = max(cap * (0.5 + jitter / 2), retry_after_seconds or 0)
    eligible = observed_at + timedelta(seconds=delay)
    if eligible >= deadline:
        return RetryDecision(RetryDisposition.exhausted, deadline_at=deadline)
    return RetryDecision(
        (
            RetryDisposition.provider_delay
            if retry_after_seconds is not None
            else RetryDisposition.automatic
        ),
        eligible,
        deadline,
    )


def manual_action_candidate(disposition: RetryDisposition) -> bool:
    return disposition not in {
        RetryDisposition.automatic,
        RetryDisposition.provider_delay,
    }
