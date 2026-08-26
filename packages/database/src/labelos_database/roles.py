from __future__ import annotations

from dataclasses import dataclass

from labelos_database.capabilities import CAPABILITY_REGISTRY, Capability
from labelos_database.capabilities import CapabilityDefinition as DefaultCapability


@dataclass(frozen=True)
class DefaultRole:
    id: str
    key: str
    display_name: str
    description: str
    system_role: bool = True


DEFAULT_ROLES: tuple[DefaultRole, ...] = (
    DefaultRole(
        "c2915cf2-10ba-50ec-a8a6-e4a5e5519f24",
        "owner",
        "Owner",
        "Workspace owner with full control over workspace configuration, access, "
        "and operations.",
    ),
    DefaultRole(
        "d3f8c6e8-60f0-5902-9630-65f96f61c016",
        "admin",
        "Admin",
        "Workspace administrator responsible for member operations, role assignment, "
        "and workspace administration.",
    ),
    DefaultRole(
        "e7450235-df07-503d-86e4-24977695ad9e",
        "member",
        "Member",
        "Workspace member with baseline access to profiles, artist records, "
        "releases, campaigns, and analytics.",
    ),
    DefaultRole(
        "d6c9e57c-6f3d-5177-a5dd-da5c1e16a79f",
        "artist",
        "Artist",
        "Artist, performer, or creative act represented in a workspace.",
    ),
    DefaultRole(
        "060f948c-f937-53d3-aa46-3c609b3b9cd8",
        "a_and_r",
        "A&R",
        "Artists and repertoire role focused on talent and creative development.",
    ),
    DefaultRole(
        "c5e33d5a-ba69-530a-a91d-72870504c064",
        "manager",
        "Manager",
        "Artist, business, or project manager coordinating work across a workspace.",
    ),
    DefaultRole(
        "cd1d3ae8-6458-558c-ac73-dea262b3b03d",
        "legal",
        "Legal",
        "Legal role responsible for contracts, rights, clearances, and compliance.",
    ),
    DefaultRole(
        "8c456426-c05d-53e4-a8f3-29ec55063cf5",
        "marketing",
        "Marketing",
        "Marketing role responsible for audience strategy, campaigns, and growth.",
    ),
    DefaultRole(
        "ed127f45-6845-5771-bd1a-eaee959185db",
        "finance",
        "Finance",
        "Finance role responsible for budgets, payments, accounting, and reporting.",
    ),
    DefaultRole(
        "3daa23fa-9389-5204-be68-dabd8bfafc61",
        "producer",
        "Producer",
        "Producer responsible for recording, production, or creative direction.",
    ),
)

DEFAULT_CAPABILITIES: tuple[DefaultCapability, ...] = CAPABILITY_REGISTRY

DEFAULT_ROLE_CAPABILITY_ASSOCIATIONS: dict[str, tuple[str, ...]] = {
    "owner": tuple(capability.value for capability in Capability),
    "admin": (
        Capability.workspace_view.value,
        Capability.workspace_update.value,
        Capability.workspace_member_view.value,
        Capability.workspace_member_invite.value,
        Capability.workspace_member_roles_manage.value,
        Capability.workspace_member_remove.value,
        Capability.role_view.value,
        Capability.role_create.value,
        Capability.role_update.value,
        Capability.role_delete.value,
        Capability.role_assign.value,
        Capability.profile_view.value,
        Capability.profile_edit.value,
        Capability.artist_profile_view.value,
        Capability.artist_profile_create.value,
        Capability.artist_profile_edit.value,
        Capability.artist_profile_delete.value,
        Capability.ar_scouting_view.value,
        Capability.ar_evaluation_view.value,
        Capability.release_view.value,
        Capability.release_create.value,
        Capability.release_edit.value,
        Capability.marketing_campaign_view.value,
        Capability.marketing_campaign_create.value,
        Capability.marketing_campaign_edit.value,
        Capability.contract_view.value,
        Capability.royalty_view.value,
        Capability.finance_view.value,
        Capability.finance_report_view.value,
        Capability.analytics_view.value,
    ),
    "member": (
        Capability.profile_view.value,
        Capability.profile_edit.value,
        Capability.artist_profile_view.value,
        Capability.release_view.value,
        Capability.marketing_campaign_view.value,
        Capability.analytics_view.value,
    ),
    "artist": (
        Capability.profile_view.value,
        Capability.profile_edit.value,
        Capability.artist_profile_view.value,
        Capability.artist_profile_edit.value,
        Capability.release_view.value,
        Capability.marketing_campaign_view.value,
        Capability.royalty_view.value,
        Capability.analytics_view.value,
    ),
    "a_and_r": (
        Capability.profile_view.value,
        Capability.profile_edit.value,
        Capability.artist_profile_view.value,
        Capability.artist_profile_create.value,
        Capability.artist_profile_edit.value,
        Capability.ar_scouting_view.value,
        Capability.ar_scouting_create.value,
        Capability.ar_evaluation_view.value,
        Capability.ar_evaluation_create.value,
        Capability.ar_signing_approve.value,
        Capability.release_view.value,
        Capability.marketing_campaign_view.value,
        Capability.analytics_view.value,
    ),
    "manager": (
        Capability.profile_view.value,
        Capability.profile_edit.value,
        Capability.artist_profile_view.value,
        Capability.artist_profile_edit.value,
        Capability.release_view.value,
        Capability.release_edit.value,
        Capability.marketing_campaign_view.value,
        Capability.marketing_campaign_create.value,
        Capability.contract_view.value,
        Capability.royalty_view.value,
        Capability.analytics_view.value,
    ),
    "legal": (
        Capability.profile_view.value,
        Capability.profile_edit.value,
        Capability.contract_view.value,
        Capability.contract_create.value,
        Capability.contract_edit.value,
        Capability.contract_review.value,
        Capability.contract_approve.value,
    ),
    "marketing": (
        Capability.profile_view.value,
        Capability.profile_edit.value,
        Capability.artist_profile_view.value,
        Capability.release_view.value,
        Capability.marketing_campaign_view.value,
        Capability.marketing_campaign_create.value,
        Capability.marketing_campaign_edit.value,
        Capability.marketing_campaign_approve.value,
        Capability.analytics_view.value,
    ),
    "finance": (
        Capability.profile_view.value,
        Capability.profile_edit.value,
        Capability.contract_view.value,
        Capability.royalty_view.value,
        Capability.royalty_calculate.value,
        Capability.royalty_statement_view.value,
        Capability.royalty_statement_create.value,
        Capability.finance_view.value,
        Capability.finance_report_view.value,
        Capability.finance_payment_view.value,
        Capability.analytics_view.value,
    ),
    "producer": (
        Capability.profile_view.value,
        Capability.profile_edit.value,
        Capability.artist_profile_view.value,
        Capability.release_view.value,
        Capability.release_create.value,
        Capability.release_edit.value,
        Capability.analytics_view.value,
    ),
}
