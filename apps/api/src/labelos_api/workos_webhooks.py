from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from labelos_database.models import (
    AuthIdentity,
    MembershipRole,
    Organization,
    OrganizationMembership,
    User,
    WebhookEvent,
)
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from labelos_api.api.v1.onboarding import slugify_organization_name

SUPPORTED_WORKOS_EVENT_TYPES = frozenset(
    {
        "user.created",
        "user.updated",
        "user.deleted",
        "organization.created",
        "organization.updated",
        "organization.deleted",
        "organization_membership.created",
        "organization_membership.updated",
        "organization_membership.deleted",
    }
)

WORKOS_WEBHOOK_PROVIDER = "workos"
WORKOS_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS = 300
WEBHOOK_OWNER_EMAIL = "workos-webhook-sync@labelos.local"


class WorkOSWebhookError(Exception):
    pass


class WorkOSWebhookSignatureError(WorkOSWebhookError):
    pass


class WorkOSWebhookPayloadError(WorkOSWebhookError):
    pass


@dataclass(frozen=True)
class WorkOSWebhookResult:
    event_id: str
    event_type: str
    status: str


def verify_workos_webhook_signature(
    *,
    raw_body: bytes,
    signature_header: str | None,
    secret: str,
    now: datetime | None = None,
) -> None:
    if not signature_header:
        raise WorkOSWebhookSignatureError("Missing WorkOS signature")

    timestamp: str | None = None
    signatures: list[str] = []
    for part in signature_header.split(","):
        key, separator, value = part.strip().partition("=")
        if not separator:
            continue
        if key == "t":
            timestamp = value
        elif key == "v1":
            signatures.append(value)

    if timestamp is None or not signatures:
        raise WorkOSWebhookSignatureError("Malformed WorkOS signature")

    try:
        issued_ms = int(timestamp)
    except ValueError as exc:
        raise WorkOSWebhookSignatureError("Invalid WorkOS signature timestamp") from exc

    current = now or datetime.now(UTC)
    issued_seconds = issued_ms / 1000
    if abs(current.timestamp() - issued_seconds) > (
        WORKOS_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS
    ):
        raise WorkOSWebhookSignatureError("Expired WorkOS signature")

    try:
        payload = raw_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkOSWebhookSignatureError("Webhook body must be UTF-8") from exc

    signed_payload = f"{timestamp}.{payload}".encode()
    expected = hmac.new(
        secret.encode("utf-8"),
        signed_payload,
        sha256,
    ).hexdigest()
    if not any(hmac.compare_digest(expected, signature) for signature in signatures):
        raise WorkOSWebhookSignatureError("Invalid WorkOS signature")


async def process_workos_webhook_event(
    *,
    session: AsyncSession,
    raw_body: bytes,
) -> WorkOSWebhookResult:
    event = _parse_workos_event(raw_body)
    event_id = event["id"]
    event_type = event["event"]
    event_created_at = _parse_datetime(event.get("created_at"))
    data = event["data"]
    resource_type, resource_id = _resource_identity(event_type, data)

    existing_event = await session.scalar(
        select(WebhookEvent)
        .where(WebhookEvent.provider == WORKOS_WEBHOOK_PROVIDER)
        .where(WebhookEvent.event_id == event_id)
    )
    if existing_event is not None:
        return WorkOSWebhookResult(
            event_id=event_id,
            event_type=event_type,
            status="duplicate",
        )

    if event_type not in SUPPORTED_WORKOS_EVENT_TYPES:
        session.add(
            WebhookEvent(
                provider=WORKOS_WEBHOOK_PROVIDER,
                event_id=event_id,
                event_type=event_type,
                resource_type=resource_type,
                resource_id=resource_id,
                workos_event_created_at=event_created_at,
                processing_status="ignored",
            )
        )
        await session.commit()
        return WorkOSWebhookResult(
            event_id=event_id,
            event_type=event_type,
            status="ignored",
        )

    status = "processed"
    if await _is_out_of_order_event(
        session=session,
        resource_type=resource_type,
        resource_id=resource_id,
        event_created_at=event_created_at,
    ):
        status = "skipped_out_of_order"
    else:
        await _synchronize_supported_event(session, event_type, data)

    session.add(
        WebhookEvent(
            provider=WORKOS_WEBHOOK_PROVIDER,
            event_id=event_id,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            workos_event_created_at=event_created_at,
            processing_status=status,
        )
    )
    await session.commit()
    return WorkOSWebhookResult(event_id=event_id, event_type=event_type, status=status)


def _parse_workos_event(raw_body: bytes) -> dict[str, Any]:
    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise WorkOSWebhookPayloadError("Webhook body must be valid JSON") from exc

    if not isinstance(event, dict):
        raise WorkOSWebhookPayloadError("Webhook event must be an object")
    event_id = event.get("id")
    event_type = event.get("event")
    data = event.get("data")
    if not isinstance(event_id, str) or not event_id:
        raise WorkOSWebhookPayloadError("Webhook event is missing id")
    if not isinstance(event_type, str) or not event_type:
        raise WorkOSWebhookPayloadError("Webhook event is missing event type")
    if not isinstance(data, dict):
        raise WorkOSWebhookPayloadError("Webhook event data must be an object")
    return event


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _ensure_timezone(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _resource_identity(
    event_type: str,
    data: dict[str, Any],
) -> tuple[str | None, str | None]:
    resource_id = _str_or_none(data.get("id"))
    if event_type.startswith("user."):
        return "user", resource_id
    if event_type.startswith("organization_membership."):
        return "organization_membership", resource_id
    if event_type.startswith("organization."):
        return "organization", resource_id
    return _str_or_none(data.get("object")), resource_id


async def _is_out_of_order_event(
    *,
    session: AsyncSession,
    resource_type: str | None,
    resource_id: str | None,
    event_created_at: datetime | None,
) -> bool:
    if resource_type is None or resource_id is None or event_created_at is None:
        return False

    latest = await session.scalar(
        select(WebhookEvent)
        .where(WebhookEvent.provider == WORKOS_WEBHOOK_PROVIDER)
        .where(WebhookEvent.resource_type == resource_type)
        .where(WebhookEvent.resource_id == resource_id)
        .where(WebhookEvent.workos_event_created_at.is_not(None))
        .order_by(desc(WebhookEvent.workos_event_created_at))
        .limit(1)
    )
    if latest is None or latest.workos_event_created_at is None:
        return False
    latest_created_at = _ensure_timezone(latest.workos_event_created_at)
    return latest_created_at > event_created_at


async def _synchronize_supported_event(
    session: AsyncSession,
    event_type: str,
    data: dict[str, Any],
) -> None:
    if event_type.startswith("user."):
        await _synchronize_user_event(session, event_type, data)
    elif event_type.startswith("organization_membership."):
        await _synchronize_membership_event(session, event_type, data)
    elif event_type.startswith("organization."):
        await _synchronize_organization_event(session, event_type, data)


async def _synchronize_user_event(
    session: AsyncSession,
    event_type: str,
    data: dict[str, Any],
) -> None:
    workos_user_id = _required_string(data, "id")
    user = await _get_user_by_workos_id(session, workos_user_id)
    if event_type == "user.deleted":
        if user is not None:
            await session.execute(
                delete(AuthIdentity)
                .where(AuthIdentity.provider == WORKOS_WEBHOOK_PROVIDER)
                .where(AuthIdentity.subject == workos_user_id)
            )
            user.workos_user_id = None
        return

    if user is None:
        user = User(
            workos_user_id=workos_user_id,
            email=_required_string(data, "email"),
        )
        session.add(user)
    _update_user_from_workos_data(user, data)
    await session.flush()
    await _ensure_workos_identity(session, user, workos_user_id)


async def _synchronize_organization_event(
    session: AsyncSession,
    event_type: str,
    data: dict[str, Any],
) -> None:
    workos_organization_id = _required_string(data, "id")
    organization = await _get_organization_by_workos_id(session, workos_organization_id)
    if event_type == "organization.deleted":
        if organization is not None:
            organization.workos_organization_id = None
        return

    if organization is None:
        owner = await _get_or_create_webhook_owner(session)
        name = _organization_name(data, workos_organization_id)
        organization = Organization(
            name=name,
            slug=await _unique_slug(session, name, workos_organization_id),
            workos_organization_id=workos_organization_id,
            owner_user_id=owner.id,
        )
        session.add(organization)
    else:
        organization.name = _organization_name(data, organization.name)


async def _synchronize_membership_event(
    session: AsyncSession,
    event_type: str,
    data: dict[str, Any],
) -> None:
    workos_membership_id = _required_string(data, "id")
    membership = await session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.workos_membership_id == workos_membership_id
        )
    )
    if event_type == "organization_membership.deleted":
        if membership is not None:
            await session.delete(membership)
        return

    workos_user_id = _required_string(data, "user_id")
    workos_organization_id = _required_string(data, "organization_id")
    user = await _get_user_by_workos_id(session, workos_user_id)
    if user is None:
        embedded_user = data.get("user")
        if isinstance(embedded_user, dict):
            user = User(
                workos_user_id=workos_user_id,
                email=_required_string(embedded_user, "email"),
            )
            _update_user_from_workos_data(user, embedded_user)
        else:
            user = User(
                workos_user_id=workos_user_id,
                email=f"{workos_user_id}@workos.local",
                display_name=workos_user_id,
            )
        session.add(user)
        await session.flush()
        await _ensure_workos_identity(session, user, workos_user_id)

    organization = await _get_organization_by_workos_id(session, workos_organization_id)
    if organization is None:
        name = _organization_name(data, workos_organization_id)
        organization = Organization(
            name=name,
            slug=await _unique_slug(session, name, workos_organization_id),
            workos_organization_id=workos_organization_id,
            owner_user_id=user.id,
        )
        session.add(organization)
        await session.flush()

    if membership is None:
        membership = await session.scalar(
            select(OrganizationMembership)
            .where(OrganizationMembership.organization_id == organization.id)
            .where(OrganizationMembership.user_id == user.id)
        )

    role = _membership_role(data)
    status = _str_or_none(data.get("status")) or "active"
    if membership is None:
        membership = OrganizationMembership(
            workos_membership_id=workos_membership_id,
            organization_id=organization.id,
            user_id=user.id,
            role=role,
            status=status,
        )
        session.add(membership)
    else:
        membership.workos_membership_id = workos_membership_id
        membership.organization_id = organization.id
        membership.user_id = user.id
        membership.role = role
        membership.status = status


def _update_user_from_workos_data(user: User, data: dict[str, Any]) -> None:
    user.workos_user_id = _required_string(data, "id")
    user.email = _required_string(data, "email")
    user.first_name = _str_or_none(data.get("first_name"))
    user.last_name = _str_or_none(data.get("last_name"))
    user.display_name = _str_or_none(data.get("name")) or user.email
    user.profile_image_url = _str_or_none(data.get("profile_picture_url"))


async def _ensure_workos_identity(
    session: AsyncSession,
    user: User,
    workos_user_id: str,
) -> None:
    identity = await session.scalar(
        select(AuthIdentity)
        .where(AuthIdentity.provider == WORKOS_WEBHOOK_PROVIDER)
        .where(AuthIdentity.subject == workos_user_id)
    )
    if identity is None:
        session.add(
            AuthIdentity(
                user_id=user.id,
                provider=WORKOS_WEBHOOK_PROVIDER,
                subject=workos_user_id,
                email=user.email,
            )
        )
    else:
        identity.user_id = user.id
        identity.email = user.email


async def _get_user_by_workos_id(
    session: AsyncSession,
    workos_user_id: str,
) -> User | None:
    return await session.scalar(
        select(User).where(User.workos_user_id == workos_user_id)
    )


async def _get_organization_by_workos_id(
    session: AsyncSession,
    workos_organization_id: str,
) -> Organization | None:
    return await session.scalar(
        select(Organization).where(
            Organization.workos_organization_id == workos_organization_id
        )
    )


async def _get_or_create_webhook_owner(session: AsyncSession) -> User:
    owner = await session.scalar(
        select(User)
        .where(User.email == WEBHOOK_OWNER_EMAIL)
        .where(User.workos_user_id.is_(None))
    )
    if owner is None:
        owner = User(email=WEBHOOK_OWNER_EMAIL, display_name="WorkOS Webhook Sync")
        session.add(owner)
        await session.flush()
    return owner


async def _unique_slug(
    session: AsyncSession,
    name: str,
    workos_organization_id: str,
) -> str:
    base_slug = slugify_organization_name(name)
    suffix = workos_organization_id.lower().replace("_", "-")[-12:]
    candidate = base_slug[:120]
    index = 1
    while True:
        existing = await session.scalar(
            select(Organization).where(Organization.slug == candidate)
        )
        if (
            existing is None
            or existing.workos_organization_id == workos_organization_id
        ):
            return candidate
        index += 1
        suffix_text = f"-{suffix}" if index == 2 else f"-{suffix}-{index}"
        candidate = f"{base_slug[: 120 - len(suffix_text)]}{suffix_text}"


def _membership_role(data: dict[str, Any]) -> MembershipRole:
    role = data.get("role")
    if isinstance(role, dict):
        slug = _str_or_none(role.get("slug"))
        if slug:
            return MembershipRole._value2member_map_.get(slug, MembershipRole.member)

    roles = data.get("roles")
    if isinstance(roles, list):
        for role_item in roles:
            if isinstance(role_item, dict):
                slug = _str_or_none(role_item.get("slug"))
                if slug in MembershipRole._value2member_map_:
                    return MembershipRole(slug)
    return MembershipRole.member


def _organization_name(data: dict[str, Any], fallback: str) -> str:
    return (
        _str_or_none(data.get("name"))
        or _str_or_none(data.get("organization_name"))
        or fallback
    )


def _str_or_none(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _required_string(data: dict[str, Any], key: str) -> str:
    value = _str_or_none(data.get(key))
    if value is None:
        raise WorkOSWebhookPayloadError(f"Webhook data is missing {key}")
    return value
