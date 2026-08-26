import time
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from labelos_database.models import MembershipRole, User, WorkspacePermission

from labelos_api.auth import (
    AuthenticatedPrincipal,
    CurrentUserContext,
    MembershipContext,
    has_role_at_least,
    principal_from_token,
    require_active_workspace_id,
    require_organization_role,
    require_permission,
)
from labelos_api.authorization import (
    INITIAL_ROLE_CAPABILITIES,
    INITIAL_ROLE_PERMISSIONS,
    AuthorizationResource,
    Capability,
    Permission,
    authorization_service,
    effective_capabilities,
    has_capability,
    has_department_access,
)
from labelos_api.config import Settings
from labelos_api.main import create_app

PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_KEY = PRIVATE_KEY.public_key()
OTHER_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeSigningKey:
    key = PUBLIC_KEY


class FakeJwkClient:
    init_count = 0

    def __init__(self, url: str, **kwargs: object) -> None:
        FakeJwkClient.init_count += 1
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
    role: str | None = "admin",
    roles: list[str] | None = None,
    permissions: list[str] | None = None,
    expires_in: int = 300,
    signing_key=PRIVATE_KEY,
    algorithm: str = "RS256",
    omit_claims: set[str] | None = None,
) -> str:
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "sid": session_id,
        "email": "person@example.com",
        "name": "Test Person",
        "permissions": permissions or ["artists:read"],
        "exp": int(time.time()) + expires_in,
    }
    if role is not None:
        claims["role"] = role
    if roles is not None:
        claims["roles"] = roles
    if organization_id is not None:
        claims["org_id"] = organization_id
    for claim in omit_claims or set():
        claims.pop(claim, None)
    return jwt.encode(
        claims, signing_key, algorithm=algorithm, headers={"kid": "test-key"}
    )


def auth_settings() -> Settings:
    return Settings(
        environment="test",
        auth_provider="workos",
        workos_client_id="client_01TEST",
        workos_issuer_url="https://api.workos.com",
        workos_jwks_url="https://example.test/jwks",
    )


@pytest.fixture(autouse=True)
def clear_workos_jwks_cache() -> None:
    from labelos_api.workos_jwt import _cached_jwks_client

    _cached_jwks_client.cache_clear()
    FakeJwkClient.init_count = 0


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_me_rejects_invalid_token(client: TestClient) -> None:
    response = client.get("/api/v1/me", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid authentication token"}


def test_me_rejects_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("WORKOS_CLIENT_ID", "client_01TEST")
    monkeypatch.setenv("WORKOS_JWKS_URL", "https://example.test/jwks")
    monkeypatch.setattr("labelos_api.workos_jwt.PyJWKClient", FakeJwkClient)

    with TestClient(create_app()) as test_client:
        response = test_client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {make_token(expires_in=-1)}"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid authentication token"}


def test_me_returns_safe_workos_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("WORKOS_CLIENT_ID", "client_01TEST")
    monkeypatch.setenv("WORKOS_JWKS_URL", "https://example.test/jwks")
    monkeypatch.setattr("labelos_api.workos_jwt.PyJWKClient", FakeJwkClient)
    token = make_token(permissions=["artists:read", "albums:write"])

    with TestClient(create_app()) as test_client:
        response = test_client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "workos_user_id": "user_01TEST",
        "organization_id": "org_01TEST",
        "role": "admin",
        "permissions": ["artists:read", "albums:write"],
    }
    serialized_response = response.text
    assert "session_01TEST" not in serialized_response
    assert "person@example.com" not in serialized_response
    assert "Test Person" not in serialized_response


def test_me_allows_valid_token_without_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("WORKOS_CLIENT_ID", "client_01TEST")
    monkeypatch.setenv("WORKOS_JWKS_URL", "https://example.test/jwks")
    monkeypatch.setattr("labelos_api.workos_jwt.PyJWKClient", FakeJwkClient)
    token = make_token(organization_id=None, role="member")

    with TestClient(create_app()) as test_client:
        response = test_client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "workos_user_id": "user_01TEST",
        "organization_id": None,
        "role": "member",
        "permissions": ["artists:read"],
    }


def test_valid_token_returns_authenticated_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("labelos_api.workos_jwt.PyJWKClient", FakeJwkClient)

    principal = principal_from_token(make_token(), auth_settings())

    assert principal == AuthenticatedPrincipal(
        provider="workos",
        subject="user_01TEST",
        session_id="session_01TEST",
        email="person@example.com",
        display_name="Test Person",
        organization_id="org_01TEST",
        role="admin",
        roles=("admin",),
        permissions=("artists:read",),
    )


def test_valid_token_accepts_multiple_workos_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("labelos_api.workos_jwt.PyJWKClient", FakeJwkClient)

    principal = principal_from_token(
        make_token(role=None, roles=["member", "admin"]),
        auth_settings(),
    )

    assert principal.role is None
    assert principal.roles == ("member", "admin")
    assert principal.membership_roles == (MembershipRole.member, MembershipRole.admin)


def test_workos_jwt_rejects_unsigned_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("labelos_api.workos_jwt.PyJWKClient", FakeJwkClient)
    unsigned_token = make_token(signing_key="", algorithm="none")

    with pytest.raises(Exception, match="Token is invalid"):
        principal_from_token(unsigned_token, auth_settings())


def test_workos_jwt_rejects_wrong_algorithm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("labelos_api.workos_jwt.PyJWKClient", FakeJwkClient)
    token = make_token(
        signing_key="a-test-secret-with-enough-entropy-for-hs256",
        algorithm="HS256",
    )

    with pytest.raises(Exception, match="Token is invalid"):
        principal_from_token(token, auth_settings())


def test_workos_jwt_rejects_incorrect_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("labelos_api.workos_jwt.PyJWKClient", FakeJwkClient)
    token = make_token(signing_key=OTHER_PRIVATE_KEY)

    with pytest.raises(Exception, match="Token is invalid"):
        principal_from_token(token, auth_settings())


@pytest.mark.parametrize("claim", ["exp", "iss", "sub", "sid"])
def test_workos_jwt_rejects_missing_required_claims(
    monkeypatch: pytest.MonkeyPatch,
    claim: str,
) -> None:
    monkeypatch.setattr("labelos_api.workos_jwt.PyJWKClient", FakeJwkClient)
    token = make_token(omit_claims={claim})

    with pytest.raises(Exception, match="Token is invalid"):
        principal_from_token(token, auth_settings())


def test_workos_jwt_rejects_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("labelos_api.workos_jwt.PyJWKClient", FakeJwkClient)
    token = make_token(expires_in=-1)

    with pytest.raises(Exception, match="Token is invalid"):
        principal_from_token(token, auth_settings())


def test_workos_jwt_rejects_wrong_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("labelos_api.workos_jwt.PyJWKClient", FakeJwkClient)
    token = make_token(issuer="https://issuer.example.test")

    with pytest.raises(Exception, match="Token is invalid"):
        principal_from_token(token, auth_settings())


def test_workos_jwt_does_not_require_audience_unless_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("labelos_api.workos_jwt.PyJWKClient", FakeJwkClient)

    principal = principal_from_token(
        make_token(audience="unexpected_audience"),
        auth_settings(),
    )

    assert principal.subject == "user_01TEST"


def test_workos_jwt_validates_configured_audience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("labelos_api.workos_jwt.PyJWKClient", FakeJwkClient)
    settings = auth_settings()
    settings.workos_audience = "client_01TEST"

    principal = principal_from_token(make_token(), settings)

    assert principal.subject == "user_01TEST"


def test_workos_jwt_rejects_wrong_configured_audience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("labelos_api.workos_jwt.PyJWKClient", FakeJwkClient)
    settings = auth_settings()
    settings.workos_audience = "client_expected"

    with pytest.raises(Exception, match="Token is invalid"):
        principal_from_token(make_token(audience="client_other"), settings)


def test_workos_jwks_client_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("labelos_api.workos_jwt.PyJWKClient", FakeJwkClient)
    settings = auth_settings()

    principal_from_token(make_token(session_id="session_01A"), settings)
    principal_from_token(make_token(session_id="session_01B"), settings)

    assert FakeJwkClient.init_count == 1


def test_authenticated_me_response_uses_current_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    app = create_app()

    async def fake_current_principal() -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            provider="workos",
            subject="user_01TEST",
            session_id="session_01SECRET",
            email="person@example.com",
            display_name="Test Person",
            organization_id="org_01TEST",
            role="admin",
            roles=("admin",),
            permissions=("artists:read",),
        )

    from labelos_api.auth import get_current_principal

    app.dependency_overrides[get_current_principal] = fake_current_principal

    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/me")

    assert response.status_code == 200
    assert response.json() == {
        "workos_user_id": "user_01TEST",
        "organization_id": "org_01TEST",
        "role": "admin",
        "permissions": ["artists:read"],
    }


def test_role_checks_follow_membership_hierarchy() -> None:
    assert has_role_at_least(MembershipRole.owner, MembershipRole.guest)
    assert has_role_at_least(MembershipRole.admin, MembershipRole.member)
    assert not has_role_at_least(MembershipRole.guest, MembershipRole.member)


def test_initial_role_permission_mapping() -> None:
    owner_permissions = INITIAL_ROLE_PERMISSIONS[MembershipRole.owner]
    admin_permissions = INITIAL_ROLE_PERMISSIONS[MembershipRole.admin]
    member_permissions = INITIAL_ROLE_PERMISSIONS[MembershipRole.member]

    assert Permission.organization_manage in owner_permissions
    assert Permission.royalties_manage in owner_permissions
    assert Permission.artists_manage in admin_permissions
    assert Permission.royalties_manage not in admin_permissions
    assert Permission.artists_view in member_permissions
    assert Permission.artists_manage not in member_permissions


def test_initial_role_capability_mapping() -> None:
    owner_capabilities = INITIAL_ROLE_CAPABILITIES[MembershipRole.owner]
    admin_capabilities = INITIAL_ROLE_CAPABILITIES[MembershipRole.admin]
    member_capabilities = INITIAL_ROLE_CAPABILITIES[MembershipRole.member]

    assert Capability.workspace_manage in owner_capabilities
    assert Capability.contract_approve in admin_capabilities
    assert Capability.role_assign in admin_capabilities
    assert Capability.artist_view in member_capabilities
    assert Capability.contract_approve not in member_capabilities


def test_capability_authorization_combines_workspace_department_and_capability() -> (
    None
):
    context = CurrentUserContext(
        user=User(email="person@example.com"),
        principal=AuthenticatedPrincipal(
            provider="workos",
            subject="user_01TEST",
            session_id="session_01TEST",
            organization_id="org_ACTIVE",
        ),
        memberships=(
            MembershipContext(
                organization_id=uuid4(),
                organization_name="Example Label",
                organization_slug="example-label",
                workos_organization_id="org_ACTIVE",
                workspace_permission=WorkspacePermission.member,
                department_access=("legal",),
                capability_permissions=("contract.approve",),
            ),
        ),
    )

    assert has_department_access(context, "legal")
    assert has_capability(context, Capability.contract_approve)
    assert Capability.contract_approve in effective_capabilities(context)
    assert not has_capability(context, Capability.contract_sign_request)


def test_authorization_service_can_resolves_workspace_capability_resource() -> None:
    workspace_id = uuid4()
    context = CurrentUserContext(
        user=User(email="person@example.com"),
        principal=AuthenticatedPrincipal(
            provider="workos",
            subject="user_01TEST",
            session_id="session_01TEST",
            organization_id="org_ACTIVE",
        ),
        memberships=(
            MembershipContext(
                organization_id=workspace_id,
                organization_name="Malary Records",
                organization_slug="malary-records",
                workos_organization_id="org_ACTIVE",
                workspace_permission=WorkspacePermission.member,
                department_access=("legal",),
                capability_permissions=("contract.upload",),
            ),
        ),
    )

    assert authorization_service.can(
        context,
        workspace_id,
        Capability.contract_upload,
        AuthorizationResource(department="legal"),
    )
    assert not authorization_service.can(
        context,
        workspace_id,
        Capability.contract_upload,
        AuthorizationResource(department="finance"),
    )
    assert not authorization_service.can(
        context,
        workspace_id,
        Capability.contract_sign_request,
        AuthorizationResource(department="legal"),
    )


def test_owner_has_all_capabilities_and_department_access() -> None:
    context = CurrentUserContext(
        user=User(email="person@example.com"),
        principal=AuthenticatedPrincipal(
            provider="workos",
            subject="user_01TEST",
            session_id="session_01TEST",
            organization_id="org_ACTIVE",
        ),
        memberships=(
            MembershipContext(
                organization_id=uuid4(),
                organization_name="Example Label",
                organization_slug="example-label",
                workos_organization_id="org_ACTIVE",
                workspace_permission=WorkspacePermission.owner,
            ),
        ),
    )

    assert has_department_access(context, "legal")
    assert has_capability(context, Capability.workspace_manage)


def test_role_derived_capability_authorizes_without_direct_membership_grant() -> None:
    context = CurrentUserContext(
        user=User(email="person@example.com"),
        principal=AuthenticatedPrincipal(
            provider="workos",
            subject="user_01TEST",
            session_id="session_01TEST",
            organization_id="org_ACTIVE",
        ),
        memberships=(
            MembershipContext(
                organization_id=uuid4(),
                organization_name="Example Label",
                organization_slug="example-label",
                workos_organization_id="org_ACTIVE",
                workspace_permission=WorkspacePermission.guest,
                department_access=("legal",),
                role_capabilities=("contract.approve",),
            ),
        ),
    )

    assert Capability.contract_approve in effective_capabilities(context)
    assert has_capability(context, Capability.contract_approve)


def test_authorization_service_denies_unknown_actions_by_default() -> None:
    context = CurrentUserContext(
        user=User(email="person@example.com"),
        principal=AuthenticatedPrincipal(
            provider="workos",
            subject="user_01TEST",
            session_id="session_01TEST",
            organization_id="org_ACTIVE",
        ),
        memberships=(
            MembershipContext(
                organization_id=uuid4(),
                organization_name="Example Label",
                organization_slug="example-label",
                workos_organization_id="org_ACTIVE",
                workspace_permission=WorkspacePermission.owner,
            ),
        ),
    )

    assert not authorization_service.can(context, None, "unregistered.action")
    assert not authorization_service.can_capability(context, "unregistered.action")
    assert not authorization_service.can_permission(context, "unregistered:permission")
    assert not authorization_service.can_role(context, "unregistered-role")


def test_authorization_service_requires_active_workspace_membership() -> None:
    workspace_id = uuid4()
    inactive_membership = MembershipContext(
        organization_id=workspace_id,
        organization_name="Example Label",
        organization_slug="example-label",
        workos_organization_id="org_ACTIVE",
        workspace_permission=WorkspacePermission.owner,
        status="removed",
    )
    context = CurrentUserContext(
        user=User(email="person@example.com"),
        principal=AuthenticatedPrincipal(
            provider="workos",
            subject="user_01TEST",
            session_id="session_01TEST",
            organization_id="org_ACTIVE",
        ),
        memberships=(inactive_membership,),
    )

    assert context.active_membership is None
    assert not authorization_service.can(
        context,
        inactive_membership,
        Capability.workspace_manage,
    )
    assert not authorization_service.can(
        context, workspace_id, Capability.workspace_manage
    )


def test_authorization_service_combines_capabilities_across_multiple_roles() -> None:
    context = CurrentUserContext(
        user=User(email="person@example.com"),
        principal=AuthenticatedPrincipal(
            provider="workos",
            subject="user_01TEST",
            session_id="session_01TEST",
            organization_id="org_ACTIVE",
        ),
        memberships=(
            MembershipContext(
                organization_id=uuid4(),
                organization_name="Example Label",
                organization_slug="example-label",
                workos_organization_id="org_ACTIVE",
                workspace_permission=WorkspacePermission.guest,
                department_access=("legal", "marketing"),
                role_capabilities=("contract.view", "campaign.approve"),
            ),
        ),
    )

    capabilities = effective_capabilities(context)

    assert Capability.contract_view in capabilities
    assert Capability.campaign_approve in capabilities
    assert authorization_service.can(
        context,
        None,
        Capability.contract_view,
        AuthorizationResource(department="legal"),
    )
    assert authorization_service.can(
        context,
        None,
        Capability.campaign_approve,
        AuthorizationResource(department="marketing"),
    )
    assert not authorization_service.can(
        context,
        None,
        Capability.member_invite,
        AuthorizationResource(department="administration"),
    )


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
                workos_organization_id="org_01TEST",
                role=MembershipRole.guest,
            ),
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        require_organization_role(organization_id, MembershipRole.admin, context)

    assert exc_info.value.status_code == 403


def test_active_workspace_uses_workos_organization_membership() -> None:
    active_organization_id = uuid4()
    secondary_organization_id = uuid4()
    context = CurrentUserContext(
        user=User(email="person@example.com"),
        principal=AuthenticatedPrincipal(
            provider="workos",
            subject="user_01TEST",
            session_id="session_01TEST",
            organization_id="org_ACTIVE",
        ),
        memberships=(
            MembershipContext(
                organization_id=secondary_organization_id,
                organization_name="Secondary Label",
                organization_slug="secondary-label",
                workos_organization_id="org_SECONDARY",
                role=MembershipRole.member,
            ),
            MembershipContext(
                organization_id=active_organization_id,
                organization_name="Active Label",
                organization_slug="active-label",
                workos_organization_id="org_ACTIVE",
                role=MembershipRole.admin,
            ),
        ),
    )

    assert context.active_workspace_id == active_organization_id
    assert context.active_membership is not None
    assert context.active_membership.workspace_id == active_organization_id
    assert context.workspace_memberships == context.memberships
    assert require_active_workspace_id(context) == active_organization_id


def test_active_workspace_requires_matching_active_membership() -> None:
    context = CurrentUserContext(
        user=User(email="person@example.com"),
        principal=AuthenticatedPrincipal(
            provider="workos",
            subject="user_01TEST",
            session_id="session_01TEST",
            organization_id="org_MISSING",
        ),
        memberships=(
            MembershipContext(
                organization_id=uuid4(),
                organization_name="Inactive Label",
                organization_slug="inactive-label",
                workos_organization_id="org_MISSING",
                role=MembershipRole.admin,
                status="inactive",
            ),
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        require_active_workspace_id(context)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Workspace context required"


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


def _override_current_user_context(
    app,
    *,
    role: str | None = "member",
    roles: tuple[str, ...] = (),
    permissions: tuple[str, ...] = (),
    organization_id: str | None = "org_01TEST",
    workspace_permission: WorkspacePermission = WorkspacePermission.admin,
    department_access: tuple[str, ...] = (),
    capability_permissions: tuple[str, ...] = (),
) -> None:
    from labelos_api.auth import get_current_user_context

    active_organization_id = uuid4()

    async def fake_current_user_context() -> CurrentUserContext:
        return CurrentUserContext(
            user=User(email="person@example.com"),
            principal=AuthenticatedPrincipal(
                provider="workos",
                subject="user_01TEST",
                session_id="session_01TEST",
                organization_id=organization_id,
                role=role,
                roles=roles or ((role,) if role else ()),
                permissions=permissions,
            ),
            memberships=(
                (
                    MembershipContext(
                        organization_id=active_organization_id,
                        organization_name="Example Label",
                        organization_slug="example-label",
                        workos_organization_id=organization_id,
                        workspace_permission=workspace_permission,
                        department_access=department_access,
                        capability_permissions=capability_permissions,
                    ),
                )
                if organization_id is not None
                else ()
            ),
        )

    app.dependency_overrides[get_current_user_context] = fake_current_user_context


def test_protected_route_allows_owner_with_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    app = create_app()
    _override_current_user_context(
        app,
        role="owner",
        permissions=("artists:view", "artists:manage", "settings:manage"),
    )

    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/authorization/examples/artists-manage")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "guard": "artists:manage"}


def test_protected_route_allows_admin_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    app = create_app()
    _override_current_user_context(app, role="admin")

    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/authorization/examples/admin")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "guard": "admin"}


def test_protected_route_rejects_member_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    app = create_app()
    _override_current_user_context(app, role="member")

    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/authorization/examples/admin")

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient role"}


def test_protected_route_rejects_missing_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    app = create_app()
    _override_current_user_context(app, role=None, roles=())

    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/authorization/examples/admin")

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient role"}


def test_protected_route_rejects_missing_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    app = create_app()
    _override_current_user_context(app, role="admin", permissions=("artists:view",))

    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/authorization/examples/artists-manage")

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient permission"}


def test_capability_route_allows_department_and_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    app = create_app()
    _override_current_user_context(
        app,
        workspace_permission=WorkspacePermission.member,
        department_access=("legal",),
        capability_permissions=("contract.upload",),
    )

    with TestClient(app) as test_client:
        response = test_client.post("/api/v1/authorization/examples/contracts")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "guard": "contract.upload"}


def test_capability_route_rejects_missing_department(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    app = create_app()
    _override_current_user_context(
        app,
        workspace_permission=WorkspacePermission.member,
        capability_permissions=("contract.upload",),
    )

    with TestClient(app) as test_client:
        response = test_client.post("/api/v1/authorization/examples/contracts")

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient department access"}


def test_capability_route_rejects_missing_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    app = create_app()
    _override_current_user_context(
        app,
        workspace_permission=WorkspacePermission.guest,
        department_access=("legal",),
    )

    with TestClient(app) as test_client:
        response = test_client.post("/api/v1/authorization/examples/contracts")

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient capability permission"}


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
        workos_webhook_secret="whsec_01TEST",
    )

    settings.validate_startup_environment()

    assert settings.resolved_workos_jwks_url == (
        "https://api.workos.com/sso/jwks/client_01TEST"
    )
