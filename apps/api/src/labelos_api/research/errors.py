"""Safe failures shared by adapters and consumers. Never retain raw responses."""

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum

import httpx
from pydantic import Field, ValidationError, model_validator

from labelos_api.research.contracts import CollectionContext, Contract, Operation
from labelos_api.services.credential_store import (
    CredentialNotFoundError,
    CredentialStoreError,
    InvalidCredentialReferenceError,
)


class ProviderErrorCode(StrEnum):
    authentication_failed = "authentication_failed"
    quota_exceeded = "quota_exceeded"
    rate_limited = "rate_limited"
    timeout = "timeout"
    data_unavailable = "data_unavailable"
    provider_unavailable = "provider_unavailable"
    malformed_data = "malformed_data"
    unsupported_operation = "unsupported_operation"
    invalid_request = "invalid_request"
    internal_error = "internal_error"


class FailureDetails(Contract):
    code: ProviderErrorCode
    retry_after_seconds: int | None = Field(default=None, ge=0, le=86400 * 365)

    @model_validator(mode="after")
    def retry_hint(self):
        if self.retry_after_seconds is not None and self.code not in {
            ProviderErrorCode.rate_limited,
            ProviderErrorCode.quota_exceeded,
            ProviderErrorCode.provider_unavailable,
        }:
            raise ValueError("Failure does not support a retry hint")
        return self

    @property
    def retryable(self) -> bool:
        return self.code in {
            ProviderErrorCode.rate_limited,
            ProviderErrorCode.timeout,
            ProviderErrorCode.provider_unavailable,
        }


class AdapterFailure(Exception):
    """Adapters translate SDK-specific failures using only these safe fields."""

    def __init__(
        self, code: ProviderErrorCode, *, retry_after_seconds: int | None = None
    ) -> None:
        self.details = FailureDetails(
            code=code, retry_after_seconds=retry_after_seconds
        )
        super().__init__(self.details.code.value)


class ProviderFailure(Contract):
    context: CollectionContext
    operation: Operation
    details: FailureDetails


class ProviderError(Exception):
    def __init__(self, failure: ProviderFailure) -> None:
        self.failure = failure
        super().__init__(failure.details.code.value)


def _retry_after(response: httpx.Response) -> int | None:
    value = response.headers.get("Retry-After", "")
    try:
        seconds = int(value) if value.isascii() and value.isdigit() else None
        if seconds is None:
            deadline = parsedate_to_datetime(value)
            if deadline.tzinfo is None:
                return None
            seconds = max(0, int((deadline - datetime.now(UTC)).total_seconds()) + 1)
        return seconds if 0 <= seconds <= 86400 * 365 else None
    except (ValueError, TypeError, OverflowError):
        return None


def normalize_failure(error: Exception) -> FailureDetails:
    """Map read-only HTTP failures; discard bodies, URLs, headers and messages."""
    code = ProviderErrorCode
    if isinstance(error, AdapterFailure):
        try:
            return FailureDetails.model_validate(error.details)
        except ValidationError:
            return FailureDetails(code=code.malformed_data)
    if isinstance(error, (CredentialNotFoundError, InvalidCredentialReferenceError)):
        return FailureDetails(code=code.authentication_failed)
    if isinstance(error, CredentialStoreError):
        return FailureDetails(code=code.provider_unavailable)
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return FailureDetails(code=code.timeout)
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        mapped = {
            401: code.authentication_failed,
            403: code.authentication_failed,
            402: code.quota_exceeded,
            404: code.data_unavailable,
            410: code.data_unavailable,
            408: code.timeout,
            429: code.rate_limited,
        }.get(
            status, code.provider_unavailable if status >= 500 else code.invalid_request
        )
        retry_after = (
            _retry_after(error.response)
            if mapped
            in {code.rate_limited, code.quota_exceeded, code.provider_unavailable}
            else None
        )
        return FailureDetails(code=mapped, retry_after_seconds=retry_after)
    if isinstance(error, httpx.RequestError):
        return FailureDetails(code=code.provider_unavailable)
    if isinstance(error, (ValidationError, ValueError, TypeError, KeyError)):
        return FailureDetails(code=code.malformed_data)
    return FailureDetails(code=code.internal_error)
