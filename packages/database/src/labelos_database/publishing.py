"""Publishing storage checks. Domain enums remain owned by Stage 1."""

from urllib.parse import urlsplit

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

STATES = (
    "pending",
    "processing",
    "published",
    "retryable_failure",
    "retrying",
    "permanent_failure",
    "manual_action_required",
    "cancelled",
)
OPERATIONS = (
    "start",
    "retry",
    "confirm_success",
    "fail_retryable",
    "fail_permanently",
    "require_manual_action",
    "cancel",
)
OUTCOMES = ("published", "retryable_failure", "permanent_failure", "unknown")
REASONS = (
    "temporary_unavailability",
    "rate_limited",
    "invalid_content",
    "destination_unavailable",
    "authorization_required",
    "outcome_unknown",
)
SOURCES = ("provider_response", "reconciliation", "execution_interrupted")


def choices(column, values):
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class PublicResourceURL(TypeDecorator[str]):
    """Public resource links only; adapters must additionally verify provider ownership."""

    impl = String(2048)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        message = "A public HTTPS resource URL without credentials or query is required"
        try:
            parsed = urlsplit(value)
            valid = (
                isinstance(value, str)
                and len(value) <= 2048
                and parsed.scheme == "https"
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and parsed.port in (None, 443)
                and not any(ord(c) <= 32 or ord(c) == 127 for c in value)
                and not any(c in value for c in ("\\", "?", "#", "@"))
            )
        except (TypeError, ValueError):
            raise ValueError(message) from None
        if not valid:
            raise ValueError(message)
        return value
