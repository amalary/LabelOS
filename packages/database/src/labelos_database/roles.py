from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DefaultRole:
    id: str
    key: str
    display_name: str
    description: str
    system_role: bool = True


@dataclass(frozen=True)
class DefaultCapability:
    id: str
    key: str
    display_name: str
    description: str
    system_capability: bool = True


DEFAULT_ROLES: tuple[DefaultRole, ...] = (
    DefaultRole(
        "d6c9e57c-6f3d-5177-a5dd-da5c1e16a79f",
        "artist",
        "Artist",
        "Artist, performer, or creative act represented in a workspace.",
    ),
    DefaultRole(
        "c5e33d5a-ba69-530a-a91d-72870504c064",
        "manager",
        "Manager",
        "Artist, business, or project manager coordinating work across a workspace.",
    ),
    DefaultRole(
        "3daa23fa-9389-5204-be68-dabd8bfafc61",
        "producer",
        "Producer",
        "Producer responsible for recording, production, or creative direction.",
    ),
    DefaultRole(
        "06d05755-95af-5cfe-8f4e-8c84fd52dc29",
        "songwriter",
        "Songwriter",
        "Composer, lyricist, or writer contributing to musical works.",
    ),
    DefaultRole(
        "060f948c-f937-53d3-aa46-3c609b3b9cd8",
        "a&r",
        "A&R",
        "Artists and repertoire role focused on talent and creative development.",
    ),
    DefaultRole(
        "8c456426-c05d-53e4-a8f3-29ec55063cf5",
        "marketing",
        "Marketing",
        "Marketing role responsible for audience strategy, campaigns, and growth.",
    ),
    DefaultRole(
        "5683c4d1-99f3-59a0-b9d3-1bc932b68038",
        "release_operations",
        "Release Operations",
        "Operations role responsible for release readiness, delivery, and schedules.",
    ),
    DefaultRole(
        "cd1d3ae8-6458-558c-ac73-dea262b3b03d",
        "legal",
        "Legal",
        "Legal role responsible for contracts, rights, clearances, and compliance.",
    ),
    DefaultRole(
        "ed127f45-6845-5771-bd1a-eaee959185db",
        "finance",
        "Finance",
        "Finance role responsible for budgets, payments, accounting, and reporting.",
    ),
    DefaultRole(
        "9fe438d1-95f9-5bc8-89b8-9e09ad0637b4",
        "analytics",
        "Analytics",
        "Analytics role responsible for reporting, insights, and performance review.",
    ),
    DefaultRole(
        "28b2b159-f8bd-53ac-8b12-52bbd0bc998c",
        "executive",
        "Executive",
        "Executive leadership role responsible for strategy and decision-making.",
    ),
    DefaultRole(
        "76157317-6e0b-5a39-a9a4-abe5080fb36b",
        "administrator",
        "Administrator",
        "Workspace administration role responsible for settings and member operations.",
    ),
)

DEFAULT_CAPABILITIES: tuple[DefaultCapability, ...] = (
    DefaultCapability(
        "c74df95e-ecb9-52d9-8b84-96b30804a681",
        "artist.view",
        "View artists",
        "View artist roster records in a workspace.",
    ),
    DefaultCapability(
        "3764312d-1746-53cc-a40e-7ae24cbdd9fe",
        "artist.edit",
        "Edit artists",
        "Edit artist roster records in a workspace.",
    ),
    DefaultCapability(
        "1ab95f5b-0705-5607-8cde-bd3fe3e193d5",
        "artist.create",
        "Create artists",
        "Create artist roster records in a workspace.",
    ),
    DefaultCapability(
        "07b8b035-fcf3-5f97-8f0a-1a41d16b8640",
        "campaign.view",
        "View campaigns",
        "View campaign records in a workspace.",
    ),
    DefaultCapability(
        "36d5aac4-b2e0-5150-bac0-ac3f61c0a899",
        "campaign.create",
        "Create campaigns",
        "Create campaign records in a workspace.",
    ),
    DefaultCapability(
        "a541574b-9fcb-555c-88e5-20de1bb7ae0c",
        "campaign.approve",
        "Approve campaigns",
        "Approve campaign plans in a workspace.",
    ),
    DefaultCapability(
        "a3ae82b7-18bc-5355-ae2b-e27f634bc29b",
        "release.view",
        "View releases",
        "View release records in a workspace.",
    ),
    DefaultCapability(
        "b5af1752-6421-5993-a870-fd5aa2be5f4c",
        "release.edit",
        "Edit releases",
        "Edit release records in a workspace.",
    ),
    DefaultCapability(
        "de8e6375-5642-5f2d-b890-f7ee984a7d2e",
        "contract.view",
        "View contracts",
        "View contract records in a workspace.",
    ),
    DefaultCapability(
        "cb774b23-9007-5031-8863-cf7a92387cb0",
        "contract.upload",
        "Upload contracts",
        "Upload contract documents in a workspace.",
    ),
    DefaultCapability(
        "2abd177e-ab43-5551-9703-e4feb5fdfbb4",
        "contract.approve",
        "Approve contracts",
        "Approve contract records in a workspace.",
    ),
    DefaultCapability(
        "1eb9ac5a-88a6-5d98-8a54-c890cf81306a",
        "contract.sign_request",
        "Request contract signatures",
        "Request signatures for contract records in a workspace.",
    ),
    DefaultCapability(
        "b0fe36a3-4974-52dc-b0a8-82ac6d26eeeb",
        "royalty.view",
        "View royalties",
        "View royalty data in a workspace.",
    ),
    DefaultCapability(
        "dbdb64c5-477d-52a9-b80b-0d8383e49652",
        "finance.view",
        "View finance",
        "View finance data in a workspace.",
    ),
    DefaultCapability(
        "f4b56c01-8da7-5dd9-8f4e-e992bc78cf3d",
        "analytics.view",
        "View analytics",
        "View analytics data in a workspace.",
    ),
    DefaultCapability(
        "4abf0ef9-2f18-501e-bef7-3bf0788e5d22",
        "member.invite",
        "Invite members",
        "Invite members to a workspace.",
    ),
    DefaultCapability(
        "08870e43-42a9-5103-88e8-7bd03d7cef88",
        "member.remove",
        "Remove members",
        "Remove members from a workspace.",
    ),
    DefaultCapability(
        "ca964158-ab5d-5cd4-9c0a-b2288b008497",
        "role.assign",
        "Assign roles",
        "Assign workspace roles to members.",
    ),
    DefaultCapability(
        "cf3a9490-65e2-51c8-88da-c968e6ce0ff7",
        "workspace.manage",
        "Manage workspace",
        "Manage workspace settings.",
    ),
    DefaultCapability(
        "92cf84e4-9f4d-5e12-8557-fb799c4bb634",
        "profile.edit",
        "Edit profile",
        "Edit the current user's profile.",
    ),
)

DEFAULT_ROLE_CAPABILITY_ASSOCIATIONS: dict[str, tuple[str, ...]] = {
    "artist": (
        "artist.view",
        "release.view",
        "campaign.view",
        "analytics.view",
        "profile.edit",
    ),
    "manager": (
        "artist.view",
        "artist.edit",
        "campaign.view",
        "campaign.create",
        "release.view",
        "release.edit",
        "contract.view",
        "royalty.view",
        "analytics.view",
        "profile.edit",
    ),
    "producer": ("release.view", "release.edit", "analytics.view", "profile.edit"),
    "songwriter": ("release.view", "royalty.view", "profile.edit"),
    "a&r": (
        "artist.view",
        "artist.edit",
        "artist.create",
        "campaign.view",
        "release.view",
        "analytics.view",
        "profile.edit",
    ),
    "marketing": (
        "artist.view",
        "campaign.view",
        "campaign.create",
        "campaign.approve",
        "release.view",
        "analytics.view",
        "profile.edit",
    ),
    "release_operations": (
        "release.view",
        "release.edit",
        "campaign.view",
        "analytics.view",
        "profile.edit",
    ),
    "legal": (
        "contract.view",
        "contract.upload",
        "contract.approve",
        "contract.sign_request",
        "profile.edit",
    ),
    "finance": (
        "contract.view",
        "royalty.view",
        "finance.view",
        "analytics.view",
        "profile.edit",
    ),
    "analytics": ("analytics.view", "artist.view", "release.view", "profile.edit"),
    "executive": (
        "artist.view",
        "campaign.view",
        "campaign.approve",
        "release.view",
        "contract.view",
        "contract.approve",
        "royalty.view",
        "finance.view",
        "analytics.view",
        "profile.edit",
    ),
    "administrator": (
        "member.invite",
        "member.remove",
        "role.assign",
        "workspace.manage",
        "artist.view",
        "campaign.view",
        "release.view",
        "contract.view",
        "analytics.view",
        "profile.edit",
    ),
}
