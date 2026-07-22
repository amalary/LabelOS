import time
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
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
    require_permission,
)
from labelos_api.config import Settings
from labelos_api.main import create_app

PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_KEY = PRIVATE_KEY.public_key()


class FakeSigningKey:
    key = PUBLIC_KEY


class FakeJwkClient:
    def __init__(self, url: str) -> None:
        self.url = url

    def get_signing_key_from_jwt(self, token: str) -> FakeSigningKey:
        return FakeSigningKey()


def make_token(
    *,
    subject: str = "user_01TEST",
    session_id: str = "session_01TEST",
    issuer: str = "https://api.workos.com",
    audience: str = "client_01TEST",
    organization_id: str | None = "org_01TEST",
    role: str = "admin",
    permissions: list[str] | None = None,
    expires_in: int = 300,
) -> str:
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "sid": session_id,
        "email": "person@example.com",
        "name": "Test Person",
        "role": role,
        "permissions": permissions or ["artists:read"],
        "exp": int(time.time()) + expires_in,
    }
    if organization_id is not None:
        claims["org_id"] = organization_id
    return jwt.encode(
        claims, PRIVATE_KEY, algorithm="RS256", headers={"kid": "test-key"}
    )


def auth_settings() -> Settings:
    return Settings(
        environment="test",
        auth_provider="workos",
        workos_client_id="client_01TEST",
        workos_issuer_url="https://api.workos.com",
        workos_jwks_url="https://example.test/jwks",
    )


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_me_rejects_invalid_token(client: TestClient) -> None:
    response = client.get("/api/v1/me", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid authentication token"}


def test_valid_token_returns_authenticated_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("labelos_api.auth.PyJWKClient", FakeJwkClient)

    principal = principal_from_token(make_token(), auth_settings())

    assert principal == AuthenticatedPrincipal(
        provider="workos",
        subject="user_01TEST",
        session_id="session_01TEST",
        email="person@example.com",
        display_name="Test Person",
        organization_id="org_01TEST",
        role="admin",
        permissions=("artists:read",),
    )


def test_authenticated_me_response_uses_current_user_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    app = create_app()
    organization_id = uuid4()
    user = User(email="person@example.com", display_name="Test Person")
    user.id = uuid4()

    async def fake_current_user_context() -> CurrentUserContext:
        return CurrentUserContext(
            user=user,
            principal=AuthenticatedPrincipal(
                provider="workos",
                subject="user_01TEST",
                session_id="session_01TEST",
                email="person@example.com",
                display_name="Test Person",
                organization_id="org_01TEST",
                role="admin",
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
        "auth_provider": "workos",
        "auth_subject": "user_01TEST",
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
        principal=AuthenticatedPrincipal(
            provider="workos",
            subject="user_01TEST",
            session_id="session_01TEST",
        ),
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


def test_require_permission_rejects_missing_permission() -> None:
    context = CurrentUserContext(
        user=User(email="person@example.com"),
        principal=AuthenticatedPrincipal(
            provider="workos",
            subject="user_01TEST",
            session_id="session_01TEST",
            permissions=("artists:read",),
        ),
        memberships=(),
    )

    with pytest.raises(HTTPException) as exc_info:
        require_permission("artists:write", context)

    assert exc_info.value.status_code == 403


def test_workos_startup_validation_requires_client_id() -> None:
    settings = Settings(
        environment="production",
        auth_provider="workos",
        workos_client_id=None,
        workos_issuer_url="https://api.workos.com",
    )

    with pytest.raises(RuntimeError, match="WORKOS_CLIENT_ID"):
        settings.validate_startup_environment()


def test_workos_jwks_url_defaults_to_client_id() -> None:
    settings = Settings(
        environment="production",
        auth_provider="workos",
        workos_client_id="client_01TEST",
        workos_issuer_url="https://api.workos.com",
        workos_jwks_url=None,
    )

    settings.validate_startup_environment()

    assert settings.resolved_workos_jwks_url == (
        "https://api.workos.com/sso/jwks/client_01TEST"
    )
