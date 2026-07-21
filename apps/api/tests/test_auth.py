import base64
import hashlib
import hmac
import json
import time
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from labelos_database.models import MembershipRole, User

from labelos_api.auth import (
    AuthenticatedPrincipal,
    CurrentUserContext,
    MembershipContext,
    has_role_at_least,
    principal_from_token,
    require_organization_role,
)
from labelos_api.config import Settings
from labelos_api.main import create_app


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def make_token(
    *,
    secret: str = "test-secret",
    subject: str = "provider-user-1",
    issuer: str = "https://issuer.example",
    audience: str = "label-os-api",
    expires_in: int = 300,
) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "email": "person@example.com",
        "name": "Test Person",
        "exp": int(time.time()) + expires_in,
    }
    token_head = ".".join(
        [
            _b64url(json.dumps(header).encode("utf-8")),
            _b64url(json.dumps(claims).encode("utf-8")),
        ]
    )
    signature = hmac.new(
        secret.encode("utf-8"),
        token_head.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{token_head}.{_b64url(signature)}"


def auth_settings() -> Settings:
    return Settings(
        environment="test",
        auth_provider="test-oidc",
        auth_issuer_url="https://issuer.example",
        auth_audience="label-os-api",
        auth_token_secret="test-secret",
    )


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_me_rejects_invalid_token(client: TestClient) -> None:
    response = client.get("/api/v1/me", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid authentication token"}


def test_valid_token_returns_authenticated_principal() -> None:
    principal = principal_from_token(make_token(), auth_settings())

    assert principal == AuthenticatedPrincipal(
        provider="test-oidc",
        subject="provider-user-1",
        email="person@example.com",
        display_name="Test Person",
    )


def test_authenticated_me_response_uses_current_user_context() -> None:
    app = create_app()
    organization_id = uuid4()
    user = User(email="person@example.com", display_name="Test Person")
    user.id = uuid4()

    async def fake_current_user_context() -> CurrentUserContext:
        return CurrentUserContext(
            user=user,
            principal=AuthenticatedPrincipal(
                provider="test-oidc",
                subject="provider-user-1",
                email="person@example.com",
                display_name="Test Person",
            ),
            memberships=(
                MembershipContext(
                    organization_id=organization_id,
                    organization_name="Example Label",
                    organization_slug="example-label",
                    role=MembershipRole.admin,
                ),
            ),
        )

    from labelos_api.auth import get_current_user_context

    app.dependency_overrides[get_current_user_context] = fake_current_user_context

    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user.id),
        "email": "person@example.com",
        "display_name": "Test Person",
        "auth_provider": "test-oidc",
        "auth_subject": "provider-user-1",
        "memberships": [
            {
                "organization_id": str(organization_id),
                "organization_name": "Example Label",
                "organization_slug": "example-label",
                "role": "admin",
            }
        ],
    }


def test_role_checks_follow_membership_hierarchy() -> None:
    assert has_role_at_least(MembershipRole.owner, MembershipRole.viewer)
    assert has_role_at_least(MembershipRole.admin, MembershipRole.member)
    assert not has_role_at_least(MembershipRole.viewer, MembershipRole.member)


def test_require_organization_role_rejects_insufficient_role() -> None:
    organization_id = uuid4()
    context = CurrentUserContext(
        user=User(email="person@example.com"),
        principal=AuthenticatedPrincipal(provider="test-oidc", subject="user-1"),
        memberships=(
            MembershipContext(
                organization_id=organization_id,
                organization_name="Example Label",
                organization_slug="example-label",
                role=MembershipRole.viewer,
            ),
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        require_organization_role(organization_id, MembershipRole.admin, context)

    assert exc_info.value.status_code == 403
