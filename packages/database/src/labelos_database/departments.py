from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DepartmentAccessSensitivity(StrEnum):
    standard = "standard"
    elevated = "elevated"
    sensitive = "sensitive"


@dataclass(frozen=True)
class DefaultDepartment:
    id: str
    slug: str
    display_name: str
    description: str
    access_sensitivity: DepartmentAccessSensitivity = (
        DepartmentAccessSensitivity.standard
    )

    @property
    def key(self) -> str:
        return self.slug


STANDARD_DEPARTMENT_SLUGS = frozenset(
    {
        "artist",
        "production",
        "creative",
        "marketing",
    }
)
ELEVATED_DEPARTMENT_SLUGS = frozenset(
    {
        "management",
        "a&r",
        "analytics",
        "release_operations",
    }
)
SENSITIVE_DEPARTMENT_SLUGS = frozenset(
    {
        "legal",
        "finance",
        "royalties",
        "administration",
    }
)


def department_access_sensitivity_for_slug(slug: str) -> DepartmentAccessSensitivity:
    if slug in SENSITIVE_DEPARTMENT_SLUGS:
        return DepartmentAccessSensitivity.sensitive
    if slug in ELEVATED_DEPARTMENT_SLUGS:
        return DepartmentAccessSensitivity.elevated
    return DepartmentAccessSensitivity.standard


DEFAULT_DEPARTMENTS: tuple[DefaultDepartment, ...] = (
    DefaultDepartment(
        "a52f4731-5d17-5b2f-9626-646b8e38bebb",
        "artist",
        "Artist",
        "Artist-facing workspace for creative identity, roster context, and approvals.",
        department_access_sensitivity_for_slug("artist"),
    ),
    DefaultDepartment(
        "bb0cb695-dd6e-5fa8-875b-99d18b5e97ed",
        "creative",
        "Creative",
        "Creative direction, repertoire, writing, production, and asset development.",
        department_access_sensitivity_for_slug("creative"),
    ),
    DefaultDepartment(
        "6ddeaa4f-678c-5fc4-b116-7126b24542a4",
        "releases",
        "Releases",
        "Release planning, distribution readiness, metadata, delivery, and go-live "
        "tasks.",
        department_access_sensitivity_for_slug("releases"),
    ),
    DefaultDepartment(
        "5bc6106a-4674-50c8-b0ed-30252b8dd699",
        "analytics",
        "Analytics",
        "Label-wide analytics, reporting, performance insights, and trend monitoring.",
        department_access_sensitivity_for_slug("analytics"),
    ),
    DefaultDepartment(
        "c7f657d8-89bd-56ca-b4e9-dd5ffc08a722",
        "production",
        "Production",
        "Recording, production schedules, masters, and deliverable readiness.",
        department_access_sensitivity_for_slug("production"),
    ),
    DefaultDepartment(
        "350239c5-c1f1-5456-80d4-6504b5634b45",
        "songs",
        "Songs",
        "Song catalog, composition records, splits, and repertoire planning.",
        department_access_sensitivity_for_slug("songs"),
    ),
    DefaultDepartment(
        "abe557e6-67e3-54a6-8059-8d74f091efb7",
        "sessions",
        "Sessions",
        "Studio sessions, booking context, recording notes, and collaborator activity.",
        department_access_sensitivity_for_slug("sessions"),
    ),
    DefaultDepartment(
        "2ffd82b0-a774-53b1-a5dd-92d3247a02f7",
        "credits",
        "Credits",
        "Contributor credits, role attribution, and release credit readiness.",
        department_access_sensitivity_for_slug("credits"),
    ),
    DefaultDepartment(
        "9d74786e-944e-55fa-a6b6-67d8a0075abe",
        "management",
        "Artist Management",
        "Artist management, business coordination, approvals, and stakeholder updates.",
        department_access_sensitivity_for_slug("management"),
    ),
    DefaultDepartment(
        "b9eefe50-2c6d-5b8d-bc2e-ce6f2f002b18",
        "marketing",
        "Marketing",
        "Audience strategy, campaigns, content plans, advertising, and growth.",
        department_access_sensitivity_for_slug("marketing"),
    ),
    DefaultDepartment(
        "7e4cbcdb-436d-5220-8c5e-6ecc3b1c4ea8",
        "a&r",
        "A&R",
        "Talent discovery, repertoire planning, creative development, and signings.",
        department_access_sensitivity_for_slug("a&r"),
    ),
    DefaultDepartment(
        "2d936d24-f4ce-5ecf-b32f-481dd2d43b8b",
        "discovery",
        "Discovery",
        "Scouting, intake, pipeline discovery, and early opportunity tracking.",
        department_access_sensitivity_for_slug("discovery"),
    ),
    DefaultDepartment(
        "47f280c2-dacb-5f3b-baf9-6ffe4b73592b",
        "evaluations",
        "Evaluations",
        "Creative, commercial, and operational assessments for talent and projects.",
        department_access_sensitivity_for_slug("evaluations"),
    ),
    DefaultDepartment(
        "fbc152d9-527a-59d9-8dfa-b758eba3f16f",
        "legal",
        "Legal",
        "Contracts, rights, clearances, compliance, and legal approvals.",
        department_access_sensitivity_for_slug("legal"),
    ),
    DefaultDepartment(
        "f12616f4-f67a-5243-b08a-69608f32d3d5",
        "contracts",
        "Contracts",
        "Contract drafting, negotiation, status tracking, and obligation review.",
        department_access_sensitivity_for_slug("contracts"),
    ),
    DefaultDepartment(
        "bff41d16-68a1-5008-b827-e826de685b3f",
        "agreements",
        "Agreements",
        "Deal terms, agreement records, amendments, and approval history.",
        department_access_sensitivity_for_slug("agreements"),
    ),
    DefaultDepartment(
        "a70ff8da-5fc4-5794-9c54-3fdc76e9e06a",
        "finance",
        "Finance",
        "Budgets, payments, accounting, forecasting, and financial reports.",
        department_access_sensitivity_for_slug("finance"),
    ),
    DefaultDepartment(
        "b52268de-f416-5d27-b99f-371efaabb410",
        "royalties",
        "Royalties",
        "Royalty statements, payout tracking, recoupment, and participation records.",
        department_access_sensitivity_for_slug("royalties"),
    ),
    DefaultDepartment(
        "18701c58-6581-53b2-9626-4b1cd127b381",
        "reporting",
        "Reporting",
        "Financial, operational, and performance reports for recurring review.",
        department_access_sensitivity_for_slug("reporting"),
    ),
    DefaultDepartment(
        "6186b04a-dec1-50db-8fad-e9ff80778ff0",
        "release_operations",
        "Release Operations",
        "Legacy release operations workspace retained for existing department access.",
        department_access_sensitivity_for_slug("release_operations"),
    ),
    DefaultDepartment(
        "3b75cc49-2042-588c-9f11-67552b6b9a05",
        "artist_analytics",
        "Artist Analytics",
        "Legacy artist analytics workspace retained for existing department access.",
        department_access_sensitivity_for_slug("artist_analytics"),
    ),
    DefaultDepartment(
        "999035c3-a882-55a1-8f62-c3dc31840809",
        "administration",
        "Workspace Administration",
        "Workspace administration, settings, member operations, and internal controls.",
        department_access_sensitivity_for_slug("administration"),
    ),
)


DEFAULT_ROLE_DEPARTMENT_ACCESS: dict[str, list[str]] = {
    "artist": ["artist", "creative", "releases", "analytics"],
    "producer": ["production", "songs", "sessions", "credits"],
    "management": ["management", "artist", "releases", "marketing", "analytics"],
    "a&r": ["a&r", "discovery", "artist", "evaluations"],
    "legal": ["legal", "contracts", "agreements"],
    "finance": ["finance", "royalties", "reporting"],
    "songwriter": ["songs", "sessions", "credits"],
    "marketing": ["marketing", "artist", "releases", "analytics"],
    "publicity": ["marketing", "artist", "releases", "analytics"],
    "label_executive": [
        "management",
        "artist",
        "releases",
        "marketing",
        "analytics",
        "a&r",
        "legal",
        "finance",
        "reporting",
        "administration",
    ],
    "other": [],
}


DEFAULT_ROLE_DEPARTMENT_ASSOCIATIONS: dict[str, list[str]] = {
    "artist": ["creative", "management"],
    "manager": ["management"],
    "producer": ["creative"],
    "a_and_r": ["a&r"],
    "marketing": ["marketing"],
    "legal": ["legal"],
    "finance": ["finance"],
    "owner": [
        "a&r",
        "management",
        "marketing",
        "release_operations",
        "legal",
        "finance",
        "royalties",
        "analytics",
        "creative",
        "administration",
    ],
    "admin": ["administration"],
}
