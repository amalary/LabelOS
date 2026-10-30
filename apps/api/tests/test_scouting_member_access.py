"""Real persisted role/department setup through the owner settings endpoint."""

import asyncio

import pytest
from labelos_database.models import Capability as CapabilityRow
from labelos_database.models import MembershipDepartmentAccess, RoleCapability
from labelos_database.roles import DEFAULT_ROLE_CAPABILITY_ASSOCIATIONS
from sqlalchemy import select

from labelos_api.authorization import Capability, authorization_service
from test_organizations_api import _realtime_events, _set_context, _workspace_role_keys
from test_organizations_api import organizations_client as organizations_client


def endpoint(seeded):
    return (
        f"/api/v1/organizations/{seeded.org_a_id}/members/"
        f"{seeded.member_membership_id}/roles"
    )


def test_owner_sets_scouting_access_without_governance(organizations_client):
    client, maker, seeded = organizations_client
    _set_context(client, seeded)

    async def seed_role():
        async with maker() as session:
            for key in DEFAULT_ROLE_CAPABILITY_ASSOCIATIONS["a_and_r"]:
                capability = await session.scalar(
                    select(CapabilityRow).where(CapabilityRow.key == key)
                )
                if capability is None:
                    capability = CapabilityRow(
                        key=key, display_name=key, description=key
                    )
                    session.add(capability)
                    await session.flush()
                session.add(
                    RoleCapability(
                        role_id=seeded.ar_role_id, capability_id=capability.id
                    )
                )
            await session.commit()

    asyncio.run(seed_role())
    assert (
        client.put(
            endpoint(seeded),
            json={"role_ids": [str(seeded.ar_role_id)], "department_access": ["A&R"]},
        ).status_code
        == 200
    )

    async def verify():
        async with maker() as session:
            for capability, expected in [
                (Capability.ar_scouting_view, True),
                (Capability.ar_scouting_create, True),
                (Capability.governance_manage, False),
            ]:
                decision = await authorization_service.decide_capability(
                    session,
                    actor=seeded.member_id,
                    workspace=seeded.org_a_id,
                    capability=capability,
                )
                assert decision.allowed is expected
            grants = (
                await session.scalars(
                    select(MembershipDepartmentAccess).where(
                        MembershipDepartmentAccess.membership_id
                        == seeded.member_membership_id
                    )
                )
            ).all()
            assert len(grants) == 1
            assert grants[0].approved_by == seeded.user_id
            assert grants[0].source == "workspace_settings"

    asyncio.run(verify())
    events = asyncio.run(_realtime_events(maker, seeded.org_a_id))
    audit = [
        event for event in events if event.event_type == "membership.roles.updated"
    ][-1]
    assert audit.payload["departmentAccess"] == ["a&r"]

    # Omitting department access preserves it; removing it revokes scouting.
    assert (
        client.put(
            endpoint(seeded), json={"role_ids": [str(seeded.ar_role_id)]}
        ).status_code
        == 200
    )
    asyncio.run(verify())
    assert (
        client.put(
            endpoint(seeded),
            json={"role_ids": [str(seeded.ar_role_id)], "department_access": []},
        ).status_code
        == 200
    )

    async def verify_revoked():
        async with maker() as session:
            decision = await authorization_service.decide_capability(
                session,
                actor=seeded.member_id,
                workspace=seeded.org_a_id,
                capability=Capability.ar_scouting_view,
            )
            assert not decision.allowed

    asyncio.run(verify_revoked())


def test_department_change_requires_owner_and_is_atomic(organizations_client):
    client, maker, seeded = organizations_client
    from labelos_database.models import MembershipRole

    _set_context(
        client,
        seeded,
        role_for_org_a=MembershipRole.member,
        capability_permissions=("workspace.member.roles.manage", "role.assign"),
    )
    result = client.put(
        endpoint(seeded),
        json={"role_ids": [str(seeded.ar_role_id)], "department_access": ["a&r"]},
    )
    assert result.status_code == 403
    assert asyncio.run(_workspace_role_keys(maker, seeded.member_membership_id)) == []


@pytest.mark.parametrize("departments", [["invented"], ["a&r"]])
def test_invalid_or_foreign_department_change_is_denied(
    organizations_client, departments
):
    client, maker, seeded = organizations_client
    _set_context(client, seeded)
    url = (
        endpoint(seeded)
        if departments == ["invented"]
        else endpoint(seeded).replace(str(seeded.org_a_id), str(seeded.org_b_id))
    )
    response = client.put(
        url,
        json={"role_ids": [str(seeded.ar_role_id)], "department_access": departments},
    )
    assert response.status_code in (403, 404, 422)
    assert asyncio.run(_workspace_role_keys(maker, seeded.member_membership_id)) == []
