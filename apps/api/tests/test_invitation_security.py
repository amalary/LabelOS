"""Invitation authorization regressions, using mocked auth and disposable SQLite."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from labelos_database.models import (
    Capability as CapabilityRow,
)
from labelos_database.models import (
    MembershipDepartmentAccess,
    MembershipRole,
    OrganizationMembership,
    Role,
    RoleCapability,
    WorkspaceInvite,
    WorkspaceMembership,
    WorkspaceMembershipRole,
    WorkspacePermission,
)
from sqlalchemy import delete, select

from labelos_api.auth import get_current_principal
from labelos_api.authorization import Capability, authorization_service
from test_onboarding_security import (
    onboarding_client as onboarding_client,
)
from test_onboarding_security import (
    seed_workspace,
    snapshot,
)
from test_organizations_api import (
    _membership_department_access,
    _membership_professional_roles,
    _set_context,
    _set_joiner_context,
    _workspace_role_keys,
)
from test_organizations_api import (
    organizations_client as organizations_client,
)


def create_invite(state, **payload):
    client, _, seeded = state
    _set_context(client, seeded)
    response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/invites", json=payload
    )
    assert response.status_code == 201, response.text
    _set_joiner_context(client, seeded)
    return response.json()["token"]


def accept(state, token, **payload):
    return state[0].post(f"/api/v1/organizations/invites/{token}/accept", json=payload)


def test_self_selected_job_title_cannot_grant_capabilities(organizations_client):
    state = organizations_client
    _, maker, seeded = state

    async def seed_capability():
        async with maker() as session:
            capability = CapabilityRow(
                key="governance.manage", display_name="Manage", description="Manage"
            )
            session.add(capability)
            await session.flush()
            session.add(
                RoleCapability(
                    role_id=seeded.legal_role_id, capability_id=capability.id
                )
            )
            await session.commit()

    asyncio.run(seed_capability())
    token = create_invite(state)
    response = accept(state, token, professional_roles=["Legal", "Management"])
    assert response.status_code == 200, response.text
    membership_id = UUID(response.json()["membership_id"])

    async def can_manage():
        async with maker() as session:
            return await authorization_service.has_capability(
                session, seeded.joiner_id, seeded.org_a_id, Capability.governance_manage
            )

    assert not asyncio.run(
        can_manage()
    ), "Self-selected title became an authorization role"
    assert asyncio.run(_workspace_role_keys(maker, membership_id)) == []
    assert asyncio.run(_membership_professional_roles(maker, membership_id)) == [
        "Legal",
        "Management",
    ]
    assert asyncio.run(_membership_department_access(maker, membership_id)) == []


def test_invite_only_actor_cannot_grant_departments(organizations_client):
    client, _, seeded = organizations_client
    _set_context(
        client,
        seeded,
        role_for_org_a=MembershipRole.member,
        capability_permissions=("workspace.member.invite",),
    )
    response = client.post(
        f"/api/v1/organizations/{seeded.org_a_id}/invites",
        json={"department_access": ["finance"]},
    )
    assert response.status_code == 403


def test_job_titles_on_creation_are_metadata_only(organizations_client):
    state = organizations_client
    token = create_invite(state, professional_roles=["Legal"])
    invite = state[0].get(f"/api/v1/organizations/invites/{token}").json()
    assert invite["workspace_roles"] == []
    assert invite["proposed_department_access"] == []


def test_replay_cannot_restore_removed_role(organizations_client):
    state = organizations_client
    token = create_invite(state, workspace_roles=["legal"], maximum_uses=2)
    response = accept(state, token)
    assert response.status_code == 200, response.text
    membership_id = UUID(response.json()["membership_id"])

    async def revoke_role():
        async with state[1]() as session:
            await session.execute(delete(WorkspaceMembershipRole))
            await session.commit()

    asyncio.run(revoke_role())
    assert accept(state, token).status_code == 200
    assert asyncio.run(_workspace_role_keys(state[1], membership_id)) == []


@pytest.mark.parametrize("status", ["revoked", "inactive", "exhausted", "expired"])
def test_unusable_invite_cannot_create_membership(organizations_client, status):
    state = organizations_client
    token = create_invite(state, workspace_roles=["legal"])

    async def invalidate():
        async with state[1]() as session:
            invite = await session.scalar(
                select(WorkspaceInvite).where(WorkspaceInvite.token == token)
            )
            invite.status = status
            await session.commit()

    asyncio.run(invalidate())
    assert accept(state, token).status_code == 410

    async def no_membership():
        async with state[1]() as session:
            return await session.scalar(
                select(OrganizationMembership.id).where(
                    OrganizationMembership.user_id == state[2].joiner_id
                )
            )

    assert asyncio.run(no_membership()) is None


def test_addressed_invite_requires_matching_user(organizations_client):
    state = organizations_client
    token = create_invite(
        state, email="someone-else@example.test", workspace_roles=["legal"]
    )
    assert accept(state, token).status_code == 403


@pytest.mark.parametrize("role", ["guest", "member", "owner"])
def test_active_members_keep_authorized_access_on_acceptance(
    organizations_client, role
):
    state = organizations_client
    token = create_invite(state, workspace_roles=["legal"], department_access=["legal"])

    async def seed_member():
        async with state[1]() as session:
            membership = OrganizationMembership(
                organization_id=state[2].org_a_id,
                user_id=state[2].joiner_id,
                role=MembershipRole(role),
                workspace_permission=WorkspacePermission(role),
            )
            session.add(membership)
            await session.commit()
            return membership.id

    membership_id = asyncio.run(seed_member())
    assert accept(state, token, professional_roles=["Management"]).status_code == 200
    assert asyncio.run(_workspace_role_keys(state[1], membership_id)) == []
    assert asyncio.run(_membership_department_access(state[1], membership_id)) == []

    async def mirror():
        async with state[1]() as session:
            membership = await session.get(OrganizationMembership, membership_id)
            assert membership.workspace_permission == WorkspacePermission(role)
            return await session.scalar(
                select(WorkspaceMembership.id).where(
                    WorkspaceMembership.organization_membership_id == membership_id
                )
            )

    assert asyncio.run(mirror()) is not None


@pytest.mark.parametrize("claim", ["admin", "member", "owner"])
def test_stale_workos_claim_cannot_promote_guest(onboarding_client, claim):
    client, _, _, _, principal = onboarding_client
    seed_workspace(onboarding_client, "guest")
    stale = replace(principal, role=claim, roles=(claim,))
    client.app.dependency_overrides[get_current_principal] = lambda: stale
    before = snapshot(onboarding_client)
    assert client.get("/api/v1/organizations").status_code == 200
    assert snapshot(onboarding_client) == before


@pytest.mark.parametrize("claim", ["admin", "member"])
def test_stale_workos_claim_cannot_recreate_removed_membership(
    onboarding_client, claim
):
    from labelos_database.workspace_memberships import (
        ensure_workspace_membership_for_organization_membership,
        mark_workspace_membership_removed,
    )

    client, maker, _, _, principal = onboarding_client
    org_id = seed_workspace(onboarding_client, "member")

    async def remove():
        async with maker() as session:
            membership = await session.scalar(select(OrganizationMembership))
            workspace_member = (
                await ensure_workspace_membership_for_organization_membership(
                    session, membership
                )
            )
            await mark_workspace_membership_removed(
                session, workspace_id=org_id, profile_id=workspace_member.profile_id
            )
            await session.commit()

    asyncio.run(remove())
    stale = replace(principal, role=claim, roles=(claim,))
    client.app.dependency_overrides[get_current_principal] = lambda: stale
    before = snapshot(onboarding_client)
    assert client.get("/api/v1/organizations").status_code in {200, 403}
    assert snapshot(onboarding_client) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("workspace_roles", ["owner"]),
        ("department_access", ["finance"]),
        ("workspace_permission", "owner"),
        ("organization_id", "other"),
    ],
)
def test_accept_rejects_caller_authorization_fields(organizations_client, field, value):
    token = create_invite(organizations_client)
    assert accept(organizations_client, token, **{field: value}).status_code == 422


@pytest.mark.parametrize(
    "change", ["expired", "consumed", "inviter_removed", "inviter_demoted"]
)
def test_invite_rechecks_persisted_authority(organizations_client, change):
    state = organizations_client
    token = create_invite(state, workspace_roles=["legal"], maximum_uses=1)

    async def change_authority():
        async with state[1]() as session:
            invite = await session.scalar(
                select(WorkspaceInvite).where(WorkspaceInvite.token == token)
            )
            if change == "expired":
                invite.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            elif change == "consumed":
                invite.use_count = 1
            else:
                membership = await session.scalar(
                    select(OrganizationMembership).where(
                        OrganizationMembership.organization_id == state[2].org_a_id,
                        OrganizationMembership.user_id == state[2].user_id,
                    )
                )
                if change == "inviter_removed":
                    membership.status = "removed"
                else:
                    membership.role = MembershipRole.member
                    membership.workspace_permission = WorkspacePermission.member
            await session.commit()

    asyncio.run(change_authority())
    assert accept(state, token).status_code == (
        410 if change in {"expired", "consumed"} else 403
    )


def test_replay_cannot_restore_department_access(organizations_client):
    state = organizations_client
    token = create_invite(state, department_access=["finance"])
    response = accept(state, token)
    assert response.status_code == 200, response.text
    membership_id = UUID(response.json()["membership_id"])

    async def revoke():
        async with state[1]() as session:
            await session.execute(
                delete(MembershipDepartmentAccess).where(
                    MembershipDepartmentAccess.membership_id == membership_id
                )
            )
            membership = await session.get(OrganizationMembership, membership_id)
            membership.department_access = []
            await session.commit()

    asyncio.run(revoke())
    assert accept(state, token).status_code == 200
    assert asyncio.run(_membership_department_access(state[1], membership_id)) == []


@pytest.mark.parametrize("retain_membership", [True, False])
def test_old_invite_cannot_reactivate_removed_member(
    organizations_client, retain_membership
):
    state = organizations_client
    token = create_invite(state, workspace_roles=["legal"])
    response = accept(state, token)
    membership_id = UUID(response.json()["membership_id"])

    async def revoke():
        async with state[1]() as session:
            membership = await session.get(OrganizationMembership, membership_id)
            workspace_member = await session.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.organization_membership_id == membership_id
                )
            )
            workspace_member.status = "removed"
            if retain_membership:
                membership.status = "removed"
            else:
                workspace_member.organization_membership_id = None
                await session.delete(membership)
            await session.commit()

    asyncio.run(revoke())
    assert accept(state, token).status_code == 403


def test_legacy_professional_roles_do_not_become_capability_roles(organizations_client):
    state = organizations_client
    token = create_invite(state, professional_roles=["Legal"])
    response = accept(state, token, professional_roles=["Management"])
    assert response.status_code == 200
    membership_id = UUID(response.json()["membership_id"])
    assert asyncio.run(_membership_professional_roles(state[1], membership_id)) == [
        "Legal"
    ]
    assert asyncio.run(_workspace_role_keys(state[1], membership_id)) == []


def test_authorized_grants_are_scoped_to_invited_workspace(organizations_client):
    state = organizations_client

    async def seed_capability():
        async with state[1]() as session:
            capability = CapabilityRow(
                key="contract.execute", display_name="Execute", description="Execute"
            )
            session.add(capability)
            await session.flush()
            session.add(
                RoleCapability(
                    role_id=state[2].legal_role_id, capability_id=capability.id
                )
            )
            await session.commit()

    asyncio.run(seed_capability())
    token = create_invite(state, workspace_roles=["legal"], department_access=["legal"])
    response = accept(state, token, professional_roles=["Management"])
    assert response.status_code == 200, response.text
    membership_id = UUID(response.json()["membership_id"])
    assert asyncio.run(_workspace_role_keys(state[1], membership_id)) == ["legal"]

    async def capabilities():
        async with state[1]() as session:
            return [
                await authorization_service.has_capability(
                    session,
                    state[2].joiner_id,
                    workspace_id,
                    Capability.contract_execute,
                )
                for workspace_id in [state[2].org_a_id, state[2].org_b_id]
            ]

    assert asyncio.run(capabilities()) == [True, False]


def test_foreign_workspace_role_cannot_be_assigned(organizations_client):
    state = organizations_client
    token = create_invite(state, workspace_roles=["legal"])

    async def move_role():
        async with state[1]() as session:
            role = await session.get(Role, state[2].legal_role_id)
            role.workspace_id = state[2].org_b_id
            await session.commit()

    asyncio.run(move_role())
    assert accept(state, token).status_code == 409


def test_cross_workspace_invite_creation_denied(organizations_client):
    client, _, seeded = organizations_client
    _set_context(client, seeded)
    assert (
        client.post(
            f"/api/v1/organizations/{seeded.org_c_id}/invites", json={}
        ).status_code
        == 403
    )


def test_concurrent_acceptance_cannot_exceed_use_limit(organizations_client):
    from fastapi import HTTPException
    from labelos_database.models import User

    from labelos_api.api.v1.organizations import accept_workspace_invite
    from labelos_api.auth import AuthenticatedPrincipal, CurrentUserContext

    state = organizations_client
    if state[1].kw["bind"].dialect.name != "postgresql":
        pytest.skip("Row-lock concurrency is exercised on disposable PostgreSQL")
    token = create_invite(state, maximum_uses=1, workspace_roles=["legal"])

    async def race():
        async with state[1]() as session:
            users = [User(email=f"racer{index}@example.test") for index in range(2)]
            session.add_all(users)
            await session.commit()

        async def join(user):
            async with state[1]() as session:
                context = CurrentUserContext(
                    user=user,
                    memberships=(),
                    principal=AuthenticatedPrincipal(
                        provider="workos",
                        subject=str(user.id),
                        session_id="test-session",
                    ),
                )
                try:
                    await accept_workspace_invite(token, session, context)
                    return 200
                except HTTPException as exc:
                    await session.rollback()
                    return exc.status_code

        results = await asyncio.gather(*(join(user) for user in users))
        async with state[1]() as session:
            invite = await session.scalar(
                select(WorkspaceInvite).where(WorkspaceInvite.token == token)
            )
            assert invite.use_count == 1
        return results

    assert sorted(asyncio.run(race())) == [200, 410]


@pytest.mark.parametrize("revoked", [False, True])
def test_acceptance_checks_invite_before_scoped_workos_claims(
    organizations_client, revoked
):
    from labelos_database.models import AuthIdentity

    from labelos_api.auth import (
        AuthenticatedPrincipal,
        get_invitation_acceptance_context,
    )

    state = organizations_client
    token = create_invite(state, workspace_roles=["legal"])

    async def identity():
        async with state[1]() as session:
            session.add(
                AuthIdentity(
                    user_id=state[2].joiner_id,
                    provider="workos",
                    subject="scoped-invitee",
                )
            )
            if revoked:
                invite = await session.scalar(
                    select(WorkspaceInvite).where(WorkspaceInvite.token == token)
                )
                invite.status = "revoked"
            await session.commit()

    asyncio.run(identity())
    principal = AuthenticatedPrincipal(
        provider="workos",
        subject="scoped-invitee",
        session_id="test-session",
        organization_id="org_ALPHA",
        role="admin",
        roles=("admin",),
    )
    state[0].app.dependency_overrides.pop(get_invitation_acceptance_context)
    state[0].app.dependency_overrides[get_current_principal] = lambda: principal
    response = accept(state, token)
    assert response.status_code == (410 if revoked else 200), response.text

    async def membership():
        async with state[1]() as session:
            return await session.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == state[2].org_a_id,
                    OrganizationMembership.user_id == state[2].joiner_id,
                )
            )

    stored = asyncio.run(membership())
    if revoked:
        assert stored is None
    else:
        assert stored.workspace_permission == WorkspacePermission.member
        assert asyncio.run(_workspace_role_keys(state[1], stored.id)) == ["legal"]


@pytest.mark.parametrize("role_key", ["member", "owner"])
def test_explicit_authorized_invitation_roles_remain_supported(
    organizations_client, role_key
):
    state = organizations_client

    async def seed_role():
        async with state[1]() as session:
            role = Role(
                key=role_key,
                display_name=role_key,
                description="Authorized invitation role",
                system_role=True,
            )
            capability = CapabilityRow(
                key="governance.manage" if role_key == "owner" else "governance.view",
                display_name="Governance",
                description="Governance",
            )
            session.add_all([role, capability])
            await session.flush()
            session.add(RoleCapability(role_id=role.id, capability_id=capability.id))
            await session.commit()

    asyncio.run(seed_role())
    token = create_invite(state, workspace_roles=[role_key])
    response = accept(state, token, professional_roles=["Management"])
    assert response.status_code == 200, response.text
    membership_id = UUID(response.json()["membership_id"])
    assert asyncio.run(_workspace_role_keys(state[1], membership_id)) == [role_key]

    async def can_manage(workspace_id):
        async with state[1]() as session:
            return await authorization_service.has_capability(
                session, state[2].joiner_id, workspace_id, Capability.governance_manage
            )

    assert asyncio.run(can_manage(state[2].org_a_id)) == (role_key == "owner")
    assert not asyncio.run(can_manage(state[2].org_b_id))


def test_inviter_cannot_assign_capabilities_they_do_not_have(organizations_client):
    state = organizations_client

    async def seed_capability():
        async with state[1]() as session:
            capability = CapabilityRow(
                key="finance.payment.approve",
                display_name="Approve",
                description="Approve payments",
            )
            session.add(capability)
            await session.flush()
            session.add(
                RoleCapability(
                    role_id=state[2].legal_role_id, capability_id=capability.id
                )
            )
            await session.commit()

    asyncio.run(seed_capability())
    _set_context(state[0], state[2], role_for_org_a=MembershipRole.admin)
    response = state[0].post(
        f"/api/v1/organizations/{state[2].org_a_id}/invites",
        json={"workspace_roles": ["legal"]},
    )
    assert response.status_code == 403


def test_department_grants_are_bounded_by_inviter_scope(organizations_client):
    state = organizations_client
    _set_context(state[0], state[2], role_for_org_a=MembershipRole.admin)
    response = state[0].post(
        f"/api/v1/organizations/{state[2].org_a_id}/invites",
        json={"department_access": ["finance"]},
    )
    assert response.status_code == 403


def test_stale_workos_permission_claims_cannot_restore_guest_access(onboarding_client):
    client, _, _, _, principal = onboarding_client
    seed_workspace(onboarding_client, "guest")
    stale = replace(
        principal,
        role="admin",
        roles=("admin",),
        permissions=("artists:view", "releases:view", "members:manage"),
    )
    client.app.dependency_overrides[get_current_principal] = lambda: stale
    response = client.get("/api/v1/dashboard/summary")
    assert response.status_code == 200, response.text
    assert response.json()["availableCards"] == []
    assert response.json()["authorization"]["permissions"] == []
