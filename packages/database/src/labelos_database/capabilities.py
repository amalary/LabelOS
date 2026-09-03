from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid5

CAPABILITY_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


class Capability(StrEnum):
    workspace_view = "workspace.view"
    workspace_update = "workspace.update"
    workspace_member_view = "workspace.member.view"
    workspace_member_invite = "workspace.member.invite"
    workspace_member_roles_manage = "workspace.member.roles.manage"
    workspace_member_remove = "workspace.member.remove"
    role_view = "role.view"
    role_create = "role.create"
    role_update = "role.update"
    role_delete = "role.delete"
    role_assign = "role.assign"
    profile_view = "profile.view"
    profile_edit = "profile.edit"
    artist_profile_view = "artist.profile.view"
    artist_profile_create = "artist.profile.create"
    artist_profile_edit = "artist.profile.edit"
    artist_profile_delete = "artist.profile.delete"
    ar_scouting_view = "ar.scouting.view"
    ar_scouting_create = "ar.scouting.create"
    ar_evaluation_view = "ar.evaluation.view"
    ar_evaluation_create = "ar.evaluation.create"
    ar_signing_approve = "ar.signing.approve"
    release_view = "release.view"
    release_create = "release.create"
    release_edit = "release.edit"
    release_approve = "release.approve"
    marketing_campaign_view = "marketing.campaign.view"
    marketing_campaign_create = "marketing.campaign.create"
    marketing_campaign_edit = "marketing.campaign.edit"
    marketing_campaign_approve = "marketing.campaign.approve"
    marketing_content_view = "marketing.content.view"
    marketing_content_create = "marketing.content.create"
    marketing_content_edit = "marketing.content.edit"
    marketing_content_archive = "marketing.content.archive"
    marketing_content_submit_for_review = "marketing.content.submit_for_review"
    marketing_content_approve = "marketing.content.approve"
    contract_view = "contract.view"
    contract_create = "contract.create"
    contract_edit = "contract.edit"
    contract_review = "contract.review"
    contract_approve = "contract.approve"
    contract_execute = "contract.execute"
    royalty_view = "royalty.view"
    royalty_calculate = "royalty.calculate"
    royalty_statement_view = "royalty.statement.view"
    royalty_statement_create = "royalty.statement.create"
    finance_view = "finance.view"
    finance_report_view = "finance.report.view"
    finance_payment_view = "finance.payment.view"
    finance_payment_approve = "finance.payment.approve"
    analytics_view = "analytics.view"
    analytics_create = "analytics.create"


@dataclass(frozen=True)
class CapabilityDefinition:
    id: str
    key: str
    display_name: str
    description: str
    system_capability: bool = True


def capability_id(capability: Capability) -> str:
    return str(uuid5(NAMESPACE_URL, f"labelos-capability:{capability.value}"))


def is_valid_capability_identifier(identifier: str) -> bool:
    return bool(CAPABILITY_IDENTIFIER_PATTERN.fullmatch(identifier))


def validate_capability_identifier(identifier: str) -> str:
    if not is_valid_capability_identifier(identifier):
        raise ValueError(
            "Capability identifiers must use dot-separated lowercase segments."
        )
    return identifier


def _definition(
    capability: Capability,
    display_name: str,
    description: str,
) -> CapabilityDefinition:
    validate_capability_identifier(capability.value)
    return CapabilityDefinition(
        id=capability_id(capability),
        key=capability.value,
        display_name=display_name,
        description=description,
    )


CAPABILITY_REGISTRY: tuple[CapabilityDefinition, ...] = (
    _definition(
        Capability.workspace_view,
        "View workspace",
        "View workspace settings and basic workspace metadata.",
    ),
    _definition(
        Capability.workspace_update,
        "Update workspace",
        "Update workspace settings and basic workspace metadata.",
    ),
    _definition(
        Capability.workspace_member_view,
        "View workspace members",
        "View workspace member directory and membership details.",
    ),
    _definition(
        Capability.workspace_member_invite,
        "Invite workspace members",
        "Invite members to a workspace.",
    ),
    _definition(
        Capability.workspace_member_roles_manage,
        "Manage member roles",
        "Manage roles assigned to workspace members.",
    ),
    _definition(
        Capability.workspace_member_remove,
        "Remove workspace members",
        "Remove members from a workspace.",
    ),
    _definition(Capability.role_view, "View roles", "View workspace role definitions."),
    _definition(
        Capability.role_create,
        "Create roles",
        "Create custom workspace role definitions.",
    ),
    _definition(
        Capability.role_update,
        "Update roles",
        "Update workspace role definitions.",
    ),
    _definition(
        Capability.role_delete,
        "Delete roles",
        "Delete custom workspace role definitions.",
    ),
    _definition(
        Capability.role_assign,
        "Assign roles",
        "Assign workspace roles to members.",
    ),
    _definition(Capability.profile_view, "View profile", "View user profile data."),
    _definition(
        Capability.profile_edit,
        "Edit profile",
        "Edit the current user's profile.",
    ),
    _definition(
        Capability.artist_profile_view,
        "View artist profiles",
        "View artist profile records in a workspace.",
    ),
    _definition(
        Capability.artist_profile_create,
        "Create artist profiles",
        "Create artist profile records in a workspace.",
    ),
    _definition(
        Capability.artist_profile_edit,
        "Edit artist profiles",
        "Edit artist profile records in a workspace.",
    ),
    _definition(
        Capability.artist_profile_delete,
        "Delete artist profiles",
        "Delete artist profile records in a workspace.",
    ),
    _definition(
        Capability.ar_scouting_view,
        "View A&R scouting",
        "View A&R scouting pipelines and opportunities.",
    ),
    _definition(
        Capability.ar_scouting_create,
        "Create A&R scouting",
        "Create A&R scouting opportunities.",
    ),
    _definition(
        Capability.ar_evaluation_view,
        "View A&R evaluations",
        "View A&R evaluation records.",
    ),
    _definition(
        Capability.ar_evaluation_create,
        "Create A&R evaluations",
        "Create A&R evaluation records.",
    ),
    _definition(
        Capability.ar_signing_approve,
        "Approve A&R signings",
        "Approve A&R signing recommendations.",
    ),
    _definition(Capability.release_view, "View releases", "View release records."),
    _definition(
        Capability.release_create, "Create releases", "Create release records."
    ),
    _definition(Capability.release_edit, "Edit releases", "Edit release records."),
    _definition(
        Capability.release_approve,
        "Approve releases",
        "Approve release plans or delivery readiness.",
    ),
    _definition(
        Capability.marketing_campaign_view,
        "View campaigns",
        "View marketing campaign records.",
    ),
    _definition(
        Capability.marketing_campaign_create,
        "Create campaigns",
        "Create marketing campaign records.",
    ),
    _definition(
        Capability.marketing_campaign_edit,
        "Edit campaigns",
        "Edit marketing campaign records.",
    ),
    _definition(
        Capability.marketing_campaign_approve,
        "Approve campaigns",
        "Approve marketing campaign plans.",
    ),
    _definition(
        Capability.marketing_content_view,
        "View marketing content",
        "View marketing content items in campaign workspaces.",
    ),
    _definition(
        Capability.marketing_content_create,
        "Create marketing content",
        "Create marketing content items for campaigns.",
    ),
    _definition(
        Capability.marketing_content_edit,
        "Edit marketing content",
        "Edit marketing content item details and channels.",
    ),
    _definition(
        Capability.marketing_content_archive,
        "Archive marketing content",
        "Archive marketing content items.",
    ),
    _definition(
        Capability.marketing_content_submit_for_review,
        "Submit marketing content for review",
        "Submit draft marketing content items for review.",
    ),
    _definition(
        Capability.marketing_content_approve,
        "Approve marketing content",
        "Approve marketing content items submitted for review.",
    ),
    _definition(Capability.contract_view, "View contracts", "View contract records."),
    _definition(
        Capability.contract_create,
        "Create contracts",
        "Create contract records.",
    ),
    _definition(Capability.contract_edit, "Edit contracts", "Edit contract records."),
    _definition(
        Capability.contract_review,
        "Review contracts",
        "Review contract records and proposed terms.",
    ),
    _definition(
        Capability.contract_approve,
        "Approve contracts",
        "Approve contract records.",
    ),
    _definition(
        Capability.contract_execute,
        "Execute contracts",
        "Execute or request signature for approved contract records.",
    ),
    _definition(Capability.royalty_view, "View royalties", "View royalty data."),
    _definition(
        Capability.royalty_calculate,
        "Calculate royalties",
        "Calculate royalty statements and allocations.",
    ),
    _definition(
        Capability.royalty_statement_view,
        "View royalty statements",
        "View royalty statements.",
    ),
    _definition(
        Capability.royalty_statement_create,
        "Create royalty statements",
        "Create royalty statements.",
    ),
    _definition(Capability.finance_view, "View finance", "View finance data."),
    _definition(
        Capability.finance_report_view,
        "View finance reports",
        "View finance reports.",
    ),
    _definition(
        Capability.finance_payment_view,
        "View payments",
        "View finance payment records.",
    ),
    _definition(
        Capability.finance_payment_approve,
        "Approve payments",
        "Approve finance payment records.",
    ),
    _definition(
        Capability.analytics_view,
        "View analytics",
        "View analytics data and reports.",
    ),
    _definition(
        Capability.analytics_create,
        "Create analytics",
        "Create analytics metric definitions and observations.",
    ),
)

ALL_CAPABILITIES = frozenset(Capability)
CAPABILITIES_BY_KEY = {definition.key: definition for definition in CAPABILITY_REGISTRY}
