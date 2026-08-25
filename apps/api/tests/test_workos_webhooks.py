import asyncio
import hmac
import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient
from labelos_database.base import Base
from labelos_database.models import (
    AuthIdentity,
    Department,
    MembershipDepartmentAccess,
    MembershipProfessionalRole,
    MembershipRole,
    Organization,
    OrganizationMembership,
    ProfessionalRole,
    UniversalProfile,
    User,
    WebhookEvent,
    WorkspaceMembership,
    WorkspacePermission,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import StaticPool

from labelos_api.auth import get_session
from labelos_api.main import create_app

WEBHOOK_SECRET = "whsec_test_secret"


@pytest.fixture
def webhook_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, async_sessionmaker[AsyncSession]]]:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("WORKOS_WEBHOOK_SECRET", WEBHOOK_SECRET)
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare_database())
    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session

    with TestClient(app) as client:
        yield client, sessionmaker

    asyncio.run(engine.dispose())


def _event(
    event_type: str,
    data: dict,
    *,
    event_id: str = "event_01TEST",
    created_at: str = "2026-07-23T20:00:00.000Z",
) -> bytes:
    return json.dumps(
        {
            "object": "event",
            "id": event_id,
            "event": event_type,
            "data": data,
            "created_at": created_at,
            "context": {},
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _signature(raw_body: bytes, *, secret: str = WEBHOOK_SECRET) -> str:
    timestamp = str(int(datetime.now(UTC).timestamp() * 1000))
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{raw_body.decode('utf-8')}".encode(),
        sha256,
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def _post_webhook(client: TestClient, raw_body: bytes, signature: str | None = None):
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["WorkOS-Signature"] = signature
    return client.post(
        "/api/v1/webhooks/workos",
        content=raw_body,
        headers=headers,
    )


async def _scalar(
    sessionmaker: async_sessionmaker[AsyncSession],
    statement,
):
    async with sessionmaker() as session:
        return await session.scalar(statement)


async def _membership_with_roles(
    sessionmaker: async_sessionmaker[AsyncSession],
    workos_membership_id: str,
) -> OrganizationMembership | None:
    async with sessionmaker() as session:
        return await session.scalar(
            select(OrganizationMembership)
            .options(
                selectinload(
                    OrganizationMembership.professional_role_links
                ).selectinload(MembershipProfessionalRole.professional_role),
                selectinload(OrganizationMembership.department_access_grants),
                selectinload(
                    OrganizationMembership.department_access_grants
                ).selectinload(MembershipDepartmentAccess.department),
            )
            .where(OrganizationMembership.workos_membership_id == workos_membership_id)
        )


async def _workspace_membership_for_profile_email(
    sessionmaker: async_sessionmaker[AsyncSession],
    email: str,
) -> WorkspaceMembership | None:
    async with sessionmaker() as session:
        return await session.scalar(
            select(WorkspaceMembership)
            .join(WorkspaceMembership.profile)
            .where(UniversalProfile.primary_email == email)
            .options(
                selectinload(WorkspaceMembership.profile),
                selectinload(WorkspaceMembership.organization_membership),
            )
        )


def test_workos_webhook_accepts_valid_signature(
    webhook_client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _sessionmaker = webhook_client
    raw_body = _event("user.created", _user_data(), event_id="event_valid")

    response = _post_webhook(client, raw_body, _signature(raw_body))

    assert response.status_code == 200
    assert response.json() == {"ok": True, "status": "processed"}


def test_workos_webhook_rejects_invalid_signature_before_payload_parsing(
    webhook_client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, _sessionmaker = webhook_client

    response = _post_webhook(client, b"{not-json", "t=1,v1=bad")

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid WorkOS webhook signature"}


def test_workos_webhook_duplicate_event_is_idempotent(
    webhook_client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, sessionmaker = webhook_client
    raw_body = _event("user.created", _user_data(), event_id="event_duplicate")

    first_response = _post_webhook(client, raw_body, _signature(raw_body))
    second_response = _post_webhook(client, raw_body, _signature(raw_body))

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json() == {"ok": True, "status": "duplicate"}
    event_count = asyncio.run(
        _scalar(
            sessionmaker,
            select(WebhookEvent).where(WebhookEvent.event_id == "event_duplicate"),
        )
    )
    assert event_count is not None


def test_workos_webhook_records_unsupported_event_without_sync(
    webhook_client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, sessionmaker = webhook_client
    raw_body = _event(
        "invitation.created",
        {"object": "invitation", "id": "invitation_01TEST"},
        event_id="event_unsupported",
    )

    response = _post_webhook(client, raw_body, _signature(raw_body))

    assert response.status_code == 200
    assert response.json() == {"ok": True, "status": "ignored"}
    stored_event = asyncio.run(
        _scalar(
            sessionmaker,
            select(WebhookEvent).where(WebhookEvent.event_id == "event_unsupported"),
        )
    )
    assert stored_event is not None
    assert stored_event.processing_status == "ignored"


def test_workos_webhook_synchronizes_user_event(
    webhook_client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, sessionmaker = webhook_client
    raw_body = _event(
        "user.created",
        _user_data(email="artist@example.com"),
        event_id="event_user",
    )

    response = _post_webhook(client, raw_body, _signature(raw_body))

    assert response.status_code == 200
    user = asyncio.run(
        _scalar(sessionmaker, select(User).where(User.workos_user_id == "user_01TEST"))
    )
    identity = asyncio.run(
        _scalar(
            sessionmaker,
            select(AuthIdentity).where(AuthIdentity.subject == "user_01TEST"),
        )
    )
    assert user is not None
    assert user.email == "artist@example.com"
    assert user.first_name == "Ada"
    assert user.profile_image_url == "https://workoscdn.example/avatar.png"
    assert identity is not None


def test_workos_webhook_synchronizes_organization_event(
    webhook_client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, sessionmaker = webhook_client
    raw_body = _event(
        "organization.created",
        {
            "object": "organization",
            "id": "org_01TEST",
            "name": "Test Label",
        },
        event_id="event_org",
    )

    response = _post_webhook(client, raw_body, _signature(raw_body))

    assert response.status_code == 200
    organization = asyncio.run(
        _scalar(
            sessionmaker,
            select(Organization).where(
                Organization.workos_organization_id == "org_01TEST"
            ),
        )
    )
    assert organization is not None
    assert organization.name == "Test Label"
    assert organization.slug == "test-label"


def test_workos_webhook_synchronizes_membership_event(
    webhook_client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, sessionmaker = webhook_client
    raw_body = _event(
        "organization_membership.created",
        {
            "object": "organization_membership",
            "id": "om_01TEST",
            "user_id": "user_01TEST",
            "organization_id": "org_01TEST",
            "organization_name": "Membership Label",
            "status": "active",
            "role": {"slug": "admin"},
            "metadata": {
                "professional_roles": ["A&R", "Product Manager", "A&R"],
                "department_access": ["artists", "marketing"],
            },
            "user": _user_data(),
        },
        event_id="event_membership",
    )

    response = _post_webhook(client, raw_body, _signature(raw_body))

    assert response.status_code == 200
    membership = asyncio.run(_membership_with_roles(sessionmaker, "om_01TEST"))
    product_manager = asyncio.run(
        _scalar(
            sessionmaker,
            select(ProfessionalRole).where(ProfessionalRole.slug == "product_manager"),
        )
    )
    assert membership is not None
    assert membership.role == MembershipRole.admin
    assert membership.workspace_permission == WorkspacePermission.admin
    assert list(membership.professional_roles) == ["A&R", "Product Manager"]
    assert product_manager is not None
    assert len(membership.professional_role_links) == 2
    assert membership.professional_role_links[0].is_primary
    assert membership.department_access == ["artists", "marketing"]
    assert membership.approved_department_access == (
        "artists",
        "marketing",
        "a&r",
        "discovery",
        "artist",
        "evaluations",
    )
    assert membership.pending_department_access == ()
    assert {
        grant.department_slug: grant.source
        for grant in membership.department_access_grants
    } == {
        "artists": "invitation",
        "marketing": "invitation",
        "a&r": "role_default",
        "discovery": "role_default",
        "artist": "role_default",
        "evaluations": "role_default",
    }
    assert membership.status == "active"
    workspace_membership = asyncio.run(
        _workspace_membership_for_profile_email(sessionmaker, "ada@example.com")
    )
    assert workspace_membership is not None
    assert workspace_membership.workspace_id == membership.organization_id
    assert workspace_membership.profile.primary_email == "ada@example.com"
    assert workspace_membership.organization_membership_id == membership.id
    assert workspace_membership.status == "active"


def test_workos_webhook_requests_department_access_from_professional_roles(
    webhook_client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, sessionmaker = webhook_client
    raw_body = _event(
        "organization_membership.created",
        {
            "object": "organization_membership",
            "id": "om_default_departments",
            "user_id": "user_01TEST",
            "organization_id": "org_01TEST",
            "organization_name": "Default Departments Label",
            "status": "active",
            "role": {"slug": "member"},
            "metadata": {
                "professional_roles": ["Artist", "Management"],
            },
            "user": _user_data(),
        },
        event_id="event_default_departments",
    )

    response = _post_webhook(client, raw_body, _signature(raw_body))

    assert response.status_code == 200
    membership = asyncio.run(
        _membership_with_roles(sessionmaker, "om_default_departments")
    )
    assert membership is not None
    assert list(membership.professional_roles) == ["Artist", "Management"]
    assert membership.department_access == []
    assert membership.approved_department_access == (
        "artist",
        "creative",
        "releases",
        "analytics",
        "management",
        "marketing",
    )
    assert membership.pending_department_access == ()


def test_workos_webhook_separates_requested_roles_from_granted_access(
    webhook_client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, sessionmaker = webhook_client
    raw_body = _event(
        "organization_membership.created",
        {
            "object": "organization_membership",
            "id": "om_sarah",
            "user_id": "user_01TEST",
            "organization_id": "org_01TEST",
            "organization_name": "Sarah Label",
            "status": "active",
            "role": {"slug": "member"},
            "metadata": {
                "professional_roles": ["Legal", "Management"],
                "department_access": ["management", "artist", "releases"],
                "requested_department_access": ["legal", "finance"],
            },
            "user": _user_data(email="sarah@example.com"),
        },
        event_id="event_sarah_access",
    )

    response = _post_webhook(client, raw_body, _signature(raw_body))

    assert response.status_code == 200
    membership = asyncio.run(_membership_with_roles(sessionmaker, "om_sarah"))
    assert membership is not None
    finance_grant = asyncio.run(
        _scalar(
            sessionmaker,
            select(MembershipDepartmentAccess)
            .join(Department, Department.id == MembershipDepartmentAccess.department_id)
            .where(MembershipDepartmentAccess.membership_id == membership.id)
            .where(Department.slug == "finance"),
        )
    )
    assert list(membership.professional_roles) == ["Legal", "Management"]
    assert membership.approved_department_access == (
        "management",
        "artist",
        "releases",
        "legal",
        "finance",
    )
    assert membership.pending_department_access == ()
    assert finance_grant is not None
    assert finance_grant.source == "role_default"


def test_workos_webhook_skips_out_of_order_resource_event(
    webhook_client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, sessionmaker = webhook_client
    newer_body = _event(
        "user.updated",
        _user_data(email="newer@example.com"),
        event_id="event_newer",
        created_at="2026-07-23T21:00:00.000Z",
    )
    older_body = _event(
        "user.updated",
        _user_data(email="older@example.com"),
        event_id="event_older",
        created_at="2026-07-23T20:00:00.000Z",
    )

    newer_response = _post_webhook(client, newer_body, _signature(newer_body))
    older_response = _post_webhook(client, older_body, _signature(older_body))

    assert newer_response.status_code == 200
    assert older_response.status_code == 200
    assert older_response.json() == {"ok": True, "status": "skipped_out_of_order"}
    user = asyncio.run(
        _scalar(sessionmaker, select(User).where(User.workos_user_id == "user_01TEST"))
    )
    assert user is not None
    assert user.email == "newer@example.com"


def _user_data(*, email: str = "ada@example.com") -> dict:
    return {
        "object": "user",
        "id": "user_01TEST",
        "email": email,
        "first_name": "Ada",
        "last_name": "Lovelace",
        "name": "Ada Lovelace",
        "profile_picture_url": "https://workoscdn.example/avatar.png",
        "created_at": "2026-07-23T19:00:00.000Z",
        "updated_at": "2026-07-23T19:00:00.000Z",
    }
