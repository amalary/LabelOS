import re
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
    and_,
    false,
    func,
    true,
)
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship, validates

from labelos_database.base import Base, TimestampMixin, UUIDPrimaryKey
from labelos_database.departments import DEFAULT_ROLE_DEPARTMENT_ACCESS
from labelos_database.scheduling import (
    SchedulingBlockedReason,
    SchedulingJobStatus,
    SchedulingMetadata,
    SchedulingUTCDateTime,
    safe_scheduling_metadata,
    scheduling_timezone,
)
from labelos_database.scheduling_guards import register_scheduling_guards

_LOCALE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*$")
PROFILE_MODULE_RELATIONSHIPS = ("artist_profiles",)
SENSITIVE_JSON_KEY_PARTS = frozenset(
    {
        "access_token",
        "authorization",
        "client_secret",
        "code",
        "credential",
        "id_token",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "token",
    }
)
SENSITIVE_TEXT_PATTERNS = (
    re.compile(
        r"(?i)\b(access[-_]?token|refresh[-_]?token|id[-_]?token|client[-_]?secret|"
        r"password|private[-_]?key|secret|credential)\b"
        r"(\s*[:=]\s*)([^\s,;]+)"
    ),
    re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._~+/=-]{6,})"),
)


def _required_text(value: str | None, field_name: str) -> str:
    if value is None:
        raise ValueError(f"{field_name} is required")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _json_object(value: dict | None, field_name: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return value


def _json_key_is_sensitive(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_JSON_KEY_PARTS)


def _without_sensitive_json_keys(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _without_sensitive_json_keys(item)
            for key, item in value.items()
            if not _json_key_is_sensitive(str(key))
        }
    if isinstance(value, list):
        return [_without_sensitive_json_keys(item) for item in value]
    return value


def _redact_sensitive_text(value: str | None) -> str | None:
    normalized = _optional_text(value)
    if normalized is None:
        return None
    redacted = SENSITIVE_TEXT_PATTERNS[1].sub("Bearer [redacted]", normalized)
    return SENSITIVE_TEXT_PATTERNS[0].sub(r"\1\2[redacted]", redacted)


def _json_list(value: list | None, field_name: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a JSON array")
    return value


def _validate_url(value: str | None) -> str:
    normalized = _required_text(value, "url")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be an absolute HTTP(S) URL")
    return normalized


class WorkspacePermission(StrEnum):
    owner = "owner"
    admin = "admin"
    member = "member"
    guest = "guest"


class MembershipRole(StrEnum):
    owner = "owner"
    admin = "admin"
    member = "member"
    artist = "artist"
    guest = "guest"
    viewer = "viewer"


class CampaignType(StrEnum):
    release = "release"
    marketing = "marketing"
    artist_development = "artist_development"
    catalog = "catalog"
    other = "other"


class CampaignStatus(StrEnum):
    draft = "draft"
    planning = "planning"
    active = "active"
    paused = "paused"
    completed = "completed"
    cancelled = "cancelled"
    archived = "archived"


class MarketingContentItemStatus(StrEnum):
    draft = "draft"
    in_review = "in_review"
    approved = "approved"
    scheduled = "scheduled"
    published = "published"
    cancelled = "cancelled"
    archived = "archived"


class ApprovalRequestStatus(StrEnum):
    requested = "requested"
    in_review = "in_review"
    changes_requested = "changes_requested"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


class ApprovalStageStatus(StrEnum):
    pending = "pending"
    in_review = "in_review"
    changes_requested = "changes_requested"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"
    invalidated = "invalidated"


class ApprovalDecisionValue(StrEnum):
    submitted = "submitted"
    approved = "approved"
    rejected = "rejected"
    changes_requested = "changes_requested"
    resubmitted = "resubmitted"
    invalidated = "invalidated"
    cancelled = "cancelled"


class AnalyticsMetricValueType(StrEnum):
    integer = "integer"
    decimal = "decimal"
    string = "string"
    boolean = "boolean"
    json = "json"


class SocialAccountConnectionMethod(StrEnum):
    direct_api = "direct_api"
    third_party = "third_party"
    assisted = "assisted"


class SocialAccountConnectionStatus(StrEnum):
    pending = "pending"
    connected = "connected"
    limited = "limited"
    reconnect_required = "reconnect_required"
    disconnected = "disconnected"
    error = "error"


class OAuthAuthorizationStateStatus(StrEnum):
    pending = "pending"
    consumed = "consumed"
    expired = "expired"


def workspace_permission_from_role(role: MembershipRole) -> WorkspacePermission:
    if role == MembershipRole.artist:
        return WorkspacePermission.member
    if role == MembershipRole.viewer:
        return WorkspacePermission.guest
    return WorkspacePermission(role.value)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[UUIDPrimaryKey]
    workos_user_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(120))
    last_name: Mapped[str | None] = mapped_column(String(120))
    profile_image_url: Mapped[str | None] = mapped_column(String(2048))
    display_name: Mapped[str | None] = mapped_column(String(200))

    owned_organizations: Mapped[list["Organization"]] = relationship(
        back_populates="owner",
        foreign_keys="Organization.owner_user_id",
    )
    memberships: Mapped[list["OrganizationMembership"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    auth_identities: Mapped[list["AuthIdentity"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    universal_profile: Mapped["UniversalProfile | None"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    created_marketing_content_items: Mapped[list["MarketingContentItem"]] = (
        relationship(
            back_populates="created_by_user",
            foreign_keys="MarketingContentItem.created_by_user_id",
        )
    )
    created_social_account_connections: Mapped[list["SocialAccountConnection"]] = (
        relationship(
            back_populates="created_by_user",
            foreign_keys="SocialAccountConnection.created_by_user_id",
        )
    )
    oauth_authorization_states: Mapped[list["OAuthAuthorizationState"]] = relationship(
        back_populates="actor_user",
        cascade="all, delete-orphan",
        foreign_keys="OAuthAuthorizationState.actor_user_id",
    )

    __table_args__ = (
        UniqueConstraint("workos_user_id", name="uq_users_workos_user_id"),
        Index("ix_users_workos_user_id", "workos_user_id"),
    )


class UniversalProfile(Base, TimestampMixin):
    __tablename__ = "universal_profiles"

    id: Mapped[UUIDPrimaryKey]
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    display_name: Mapped[str | None] = mapped_column(String(200))
    first_name: Mapped[str | None] = mapped_column(String(120))
    last_name: Mapped[str | None] = mapped_column(String(120))
    slug: Mapped[str | None] = mapped_column(String(120))
    headline: Mapped[str | None] = mapped_column(String(240))
    biography: Mapped[str | None] = mapped_column(String(4000))
    avatar_url: Mapped[str | None] = mapped_column(String(2048))
    location: Mapped[str | None] = mapped_column(String(240))
    timezone: Mapped[str | None] = mapped_column(String(120))
    primary_email: Mapped[str | None] = mapped_column(String(320))
    profile_status: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="active",
        server_default="active",
    )
    onboarding_status: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="not_started",
        server_default="not_started",
    )

    user: Mapped[User] = relationship(back_populates="universal_profile")
    attributes: Mapped[list["ProfileAttribute"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by=lambda: (
            ProfileAttribute.sort_order.asc(),
            ProfileAttribute.attribute_type.asc(),
            ProfileAttribute.created_at.asc(),
            ProfileAttribute.id.asc(),
        ),
    )
    links: Mapped[list["ProfileLink"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by=lambda: (
            ProfileLink.sort_order.asc(),
            ProfileLink.link_type.asc(),
            ProfileLink.created_at.asc(),
            ProfileLink.id.asc(),
        ),
    )
    preference: Mapped["ProfilePreference | None"] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        uselist=False,
    )
    workspace_memberships: Mapped[list["WorkspaceMembership"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        foreign_keys="WorkspaceMembership.profile_id",
    )
    artist_profiles: Mapped[list["ArtistProfile"]] = relationship(
        back_populates="universal_profile",
        cascade="all, delete-orphan",
    )
    created_marketing_content_items: Mapped[list["MarketingContentItem"]] = (
        relationship(
            back_populates="created_by_profile",
            foreign_keys="MarketingContentItem.created_by_profile_id",
        )
    )
    owned_marketing_content_items: Mapped[list["MarketingContentItem"]] = relationship(
        back_populates="owner_profile",
        foreign_keys="MarketingContentItem.owner_profile_id",
    )
    approved_marketing_content_items: Mapped[list["MarketingContentItem"]] = (
        relationship(
            back_populates="approved_by_profile",
            foreign_keys="MarketingContentItem.approved_by_profile_id",
        )
    )
    created_social_account_connections: Mapped[list["SocialAccountConnection"]] = (
        relationship(
            back_populates="created_by_profile",
            foreign_keys="SocialAccountConnection.created_by_profile_id",
        )
    )

    @property
    def profile_modules(self) -> dict[str, list[object]]:
        return {
            relationship_name.removesuffix("_profiles"): list(
                getattr(self, relationship_name)
            )
            for relationship_name in PROFILE_MODULE_RELATIONSHIPS
        }

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_universal_profiles_user_id"),
        UniqueConstraint("slug", name="uq_universal_profiles_slug"),
        Index("ix_universal_profiles_user_id", "user_id"),
        Index("ix_universal_profiles_slug", "slug"),
        Index("ix_universal_profiles_display_name", "display_name"),
        Index("ix_universal_profiles_primary_email", "primary_email"),
        Index("ix_universal_profiles_profile_status", "profile_status"),
        Index("ix_universal_profiles_onboarding_status", "onboarding_status"),
    )


class ProfileAttribute(Base, TimestampMixin):
    __tablename__ = "profile_attributes"

    id: Mapped[UUIDPrimaryKey]
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("universal_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    attribute_type: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="user",
        server_default="user",
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    profile: Mapped[UniversalProfile] = relationship(back_populates="attributes")

    @validates("attribute_type", "value", "source")
    def _validate_required_text(self, key: str, value: str | None) -> str:
        return _required_text(value, key)

    @validates("label")
    def _validate_label(self, _key: str, value: str | None) -> str | None:
        return _optional_text(value)

    @validates("metadata_json")
    def _validate_metadata(self, key: str, value: dict | None) -> dict:
        return _json_object(value, key)

    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "attribute_type",
            "value",
            name="uq_profile_attributes_profile_id_type_value",
        ),
        Index("ix_profile_attributes_profile_id", "profile_id"),
        Index("ix_profile_attributes_attribute_type", "attribute_type"),
        Index("ix_profile_attributes_profile_id_type", "profile_id", "attribute_type"),
        Index("ix_profile_attributes_is_primary", "is_primary"),
    )


class ProfileLink(Base, TimestampMixin):
    __tablename__ = "profile_links"

    id: Mapped[UUIDPrimaryKey]
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("universal_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    link_type: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    username: Mapped[str | None] = mapped_column(String(120))
    external_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="active",
        server_default="active",
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    profile: Mapped[UniversalProfile] = relationship(back_populates="links")

    @validates("link_type", "status")
    def _validate_required_text(self, key: str, value: str | None) -> str:
        return _required_text(value, key)

    @validates("label", "username", "external_id")
    def _validate_optional_text(self, _key: str, value: str | None) -> str | None:
        return _optional_text(value)

    @validates("url")
    def _validate_profile_link_url(self, _key: str, value: str | None) -> str:
        return _validate_url(value)

    @validates("metadata_json")
    def _validate_metadata(self, key: str, value: dict | None) -> dict:
        return _json_object(value, key)

    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "link_type",
            "url",
            name="uq_profile_links_profile_id_type_url",
        ),
        Index("ix_profile_links_profile_id", "profile_id"),
        Index("ix_profile_links_link_type", "link_type"),
        Index("ix_profile_links_profile_id_type", "profile_id", "link_type"),
        Index("ix_profile_links_status", "status"),
        Index("ix_profile_links_is_primary", "is_primary"),
    )


class ProfilePreference(Base, TimestampMixin):
    __tablename__ = "profile_preferences"

    id: Mapped[UUIDPrimaryKey]
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("universal_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    locale: Mapped[str | None] = mapped_column(String(35))
    timezone: Mapped[str | None] = mapped_column(String(120))
    default_workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    email_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    push_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    sms_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    marketing_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    interface_theme: Mapped[str | None] = mapped_column(String(60))
    interface_density: Mapped[str | None] = mapped_column(String(60))
    notification_preferences: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    interface_preferences: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    integration_preferences: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    profile: Mapped[UniversalProfile] = relationship(back_populates="preference")
    default_workspace: Mapped["Organization | None"] = relationship()

    @validates("locale")
    def _validate_locale(self, _key: str, value: str | None) -> str | None:
        normalized = _optional_text(value)
        if normalized is not None and _LOCALE_PATTERN.fullmatch(normalized) is None:
            raise ValueError("locale must be a valid BCP 47-style locale")
        return normalized

    @validates("timezone", "interface_theme", "interface_density")
    def _validate_optional_text(self, _key: str, value: str | None) -> str | None:
        return _optional_text(value)

    @validates(
        "notification_preferences",
        "interface_preferences",
        "integration_preferences",
    )
    def _validate_json_preferences(self, key: str, value: dict | None) -> dict:
        return _json_object(value, key)

    __table_args__ = (
        UniqueConstraint("profile_id", name="uq_profile_preferences_profile_id"),
        Index("ix_profile_preferences_profile_id", "profile_id"),
        Index("ix_profile_preferences_locale", "locale"),
        Index("ix_profile_preferences_timezone", "timezone"),
        Index("ix_profile_preferences_default_workspace_id", "default_workspace_id"),
    )


class AuthIdentity(Base, TimestampMixin):
    __tablename__ = "auth_identities"

    id: Mapped[UUIDPrimaryKey]
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))

    user: Mapped[User] = relationship(back_populates="auth_identities")

    __table_args__ = (
        UniqueConstraint(
            "provider", "subject", name="uq_auth_identities_provider_subject"
        ),
        Index("ix_auth_identities_user_id", "user_id"),
    )


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[UUIDPrimaryKey]
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    workos_organization_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    owner: Mapped[User] = relationship(
        back_populates="owned_organizations",
        foreign_keys=[owner_user_id],
    )
    memberships: Mapped[list["OrganizationMembership"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    workspace_memberships: Mapped[list["WorkspaceMembership"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    artists: Mapped[list["Artist"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    releases: Mapped[list["Release"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    campaigns: Mapped[list["Campaign"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    contracts: Mapped[list["Contract"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    royalties: Mapped[list["Royalty"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    analytics_events: Mapped[list["AnalyticsEvent"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    analytics_providers: Mapped[list["AnalyticsProvider"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    analytics_metric_definitions: Mapped[list["AnalyticsMetricDefinition"]] = (
        relationship(
            back_populates="organization",
            cascade="all, delete-orphan",
        )
    )
    analytics_observations: Mapped[list["AnalyticsObservation"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    social_account_connections: Mapped[list["SocialAccountConnection"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    oauth_authorization_states: Mapped[list["OAuthAuthorizationState"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    ai_agents: Mapped[list["AIAgent"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    team_settings: Mapped[list["TeamSetting"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    workspace_invites: Mapped[list["WorkspaceInvite"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
        foreign_keys="WorkspaceInvite.organization_id",
    )
    roles: Mapped[list["Role"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    marketing_content_items: Mapped[list["MarketingContentItem"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    approval_requests: Mapped[list["ApprovalRequest"]] = relationship(
        back_populates="organization"
    )
    approval_decisions: Mapped[list["ApprovalDecision"]] = relationship(
        back_populates="organization"
    )

    __table_args__ = (
        UniqueConstraint(
            "workos_organization_id",
            name="uq_organizations_workos_organization_id",
        ),
        Index("ix_organizations_owner_user_id", "owner_user_id"),
        Index("ix_organizations_workos_organization_id", "workos_organization_id"),
    )


class OrganizationMembership(Base, TimestampMixin):
    __tablename__ = "organization_memberships"

    def __init__(self, **kwargs: object) -> None:
        if "workspace_permission" not in kwargs and "role" in kwargs:
            role = kwargs["role"]
            if isinstance(role, MembershipRole):
                kwargs["workspace_permission"] = workspace_permission_from_role(role)
            elif role == "viewer":
                kwargs["workspace_permission"] = WorkspacePermission.guest
            else:
                kwargs["workspace_permission"] = role
        super().__init__(**kwargs)

    id: Mapped[UUIDPrimaryKey]
    workos_membership_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[MembershipRole] = mapped_column(
        Enum(
            MembershipRole,
            name="organization_membership_role",
            values_callable=lambda roles: [role.value for role in roles],
        ),
        nullable=False,
        default=MembershipRole.member,
        server_default=MembershipRole.member.value,
    )
    workspace_permission: Mapped[WorkspacePermission] = mapped_column(
        Enum(
            WorkspacePermission,
            name="workspace_permission",
            values_callable=lambda permissions: [
                permission.value for permission in permissions
            ],
        ),
        nullable=False,
        default=WorkspacePermission.member,
        server_default=WorkspacePermission.member.value,
    )
    status: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="active",
        server_default="active",
    )
    department_access: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    capability_permissions: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")
    professional_role_links: Mapped[list["MembershipProfessionalRole"]] = relationship(
        back_populates="membership",
        cascade="all, delete-orphan",
        order_by=lambda: (
            MembershipProfessionalRole.is_primary.desc(),
            MembershipProfessionalRole.created_at.asc(),
            MembershipProfessionalRole.professional_role_id.asc(),
        ),
    )
    department_access_grants: Mapped[list["MembershipDepartmentAccess"]] = relationship(
        back_populates="membership",
        cascade="all, delete-orphan",
        order_by=lambda: (
            MembershipDepartmentAccess.created_at.asc(),
            MembershipDepartmentAccess.id.asc(),
        ),
    )
    workspace_membership: Mapped["WorkspaceMembership | None"] = relationship(
        back_populates="organization_membership",
        uselist=False,
    )

    @property
    def professional_roles(self) -> tuple[str, ...]:
        return tuple(
            link.professional_role.display_name
            for link in sorted(
                self.professional_role_links,
                key=lambda link: (
                    not link.is_primary,
                    (
                        link.professional_role.display_name
                        if link.professional_role is not None
                        else ""
                    ),
                ),
            )
            if link.status == "active" and link.professional_role is not None
        )

    @property
    def approved_department_access(self) -> tuple[str, ...]:
        grants = list(self.department_access_grants)
        if not grants:
            return tuple(self.department_access)

        ordered: list[str] = []
        seen: set[str] = set()
        department_order: dict[str, int] = {}
        for role_departments in DEFAULT_ROLE_DEPARTMENT_ACCESS.values():
            for department_slug in role_departments:
                department_order.setdefault(department_slug, len(department_order))

        def append(department_slug: str) -> None:
            if department_slug in seen:
                return
            ordered.append(department_slug)
            seen.add(department_slug)

        for department_slug in self.department_access:
            append(department_slug)

        role_default_grant_slugs = {
            grant.department_slug for grant in grants if grant.source == "role_default"
        }
        if role_default_grant_slugs:
            for link in sorted(
                self.professional_role_links,
                key=lambda link: (
                    not link.is_primary,
                    (
                        link.professional_role.display_name
                        if link.professional_role is not None
                        else ""
                    ),
                ),
            ):
                if link.status != "active" or link.professional_role is None:
                    continue
                for department_slug in DEFAULT_ROLE_DEPARTMENT_ACCESS.get(
                    link.professional_role.slug,
                    [],
                ):
                    if department_slug in role_default_grant_slugs:
                        append(department_slug)

        for grant in sorted(
            grants,
            key=lambda grant: (
                department_order.get(grant.department_slug, len(department_order)),
                grant.department_slug,
            ),
        ):
            append(grant.department_slug)

        return tuple(ordered)

    @property
    def pending_department_access(self) -> tuple[str, ...]:
        return ()

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_organization_memberships_organization_id_user_id",
        ),
        UniqueConstraint(
            "workos_membership_id",
            name="uq_organization_memberships_workos_membership_id",
        ),
        Index("ix_organization_memberships_organization_id", "organization_id"),
        Index("ix_organization_memberships_user_id", "user_id"),
        Index(
            "ix_organization_memberships_workos_membership_id",
            "workos_membership_id",
        ),
    )


class WorkspaceMembership(Base, TimestampMixin):
    __tablename__ = "workspace_memberships"

    id: Mapped[UUIDPrimaryKey]
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("universal_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_membership_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organization_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="active",
        server_default="active",
    )
    invited_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("universal_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workspace: Mapped[Organization] = relationship(
        back_populates="workspace_memberships"
    )
    profile: Mapped[UniversalProfile] = relationship(
        back_populates="workspace_memberships",
        foreign_keys=[profile_id],
    )
    inviter: Mapped[UniversalProfile | None] = relationship(foreign_keys=[invited_by])
    organization_membership: Mapped[OrganizationMembership | None] = relationship(
        back_populates="workspace_membership"
    )
    role_assignments: Mapped[list["WorkspaceMembershipRole"]] = relationship(
        back_populates="workspace_membership",
        cascade="all, delete-orphan",
        order_by=lambda: (
            WorkspaceMembershipRole.assigned_at.asc(),
            WorkspaceMembershipRole.role_id.asc(),
        ),
    )
    campaign_links: Mapped[list["CampaignMember"]] = relationship(
        back_populates="workspace_membership",
        cascade="all, delete-orphan",
    )

    @property
    def professional_roles(self) -> tuple[str, ...]:
        if self.organization_membership is None:
            return ()
        return self.organization_membership.professional_roles

    @property
    def roles(self) -> tuple["Role", ...]:
        return tuple(
            assignment.role
            for assignment in sorted(
                (
                    assignment
                    for assignment in self.role_assignments
                    if assignment.role is not None
                ),
                key=lambda assignment: (
                    assignment.assigned_at,
                    assignment.role.key,
                ),
            )
        )

    @property
    def role_keys(self) -> tuple[str, ...]:
        return tuple(role.key for role in self.roles)

    @property
    def capability_keys(self) -> tuple[str, ...]:
        seen: set[str] = set()
        capability_keys: list[str] = []
        for role in self.roles:
            for capability in sorted(role.capabilities, key=lambda item: item.key):
                if capability.key in seen:
                    continue
                capability_keys.append(capability.key)
                seen.add(capability.key)
        return tuple(capability_keys)

    @property
    def department_access(self) -> tuple[str, ...]:
        if self.organization_membership is None:
            return ()
        return self.organization_membership.approved_department_access

    @property
    def workspace_permission(self) -> WorkspacePermission | None:
        if self.organization_membership is None:
            return None
        return self.organization_membership.workspace_permission

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "profile_id",
            name="uq_workspace_memberships_workspace_id_profile_id",
        ),
        UniqueConstraint(
            "organization_membership_id",
            name="uq_workspace_memberships_organization_membership_id",
        ),
        Index("ix_workspace_memberships_workspace_id", "workspace_id"),
        Index("ix_workspace_memberships_profile_id", "profile_id"),
        Index(
            "ix_workspace_memberships_organization_membership_id",
            "organization_membership_id",
        ),
        Index("ix_workspace_memberships_status", "status"),
        Index("ix_workspace_memberships_invited_by", "invited_by"),
    )


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    def __init__(self, **kwargs: object) -> None:
        if "name" not in kwargs and "display_name" in kwargs:
            kwargs["name"] = kwargs["display_name"]
        if "display_name" not in kwargs and "name" in kwargs:
            kwargs["display_name"] = kwargs["name"]
        if "is_system_role" not in kwargs and "system_role" in kwargs:
            kwargs["is_system_role"] = kwargs["system_role"]
        if "system_role" not in kwargs and "is_system_role" in kwargs:
            kwargs["system_role"] = kwargs["is_system_role"]
        super().__init__(**kwargs)

    id: Mapped[UUIDPrimaryKey]
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    is_system_role: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    system_role: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )

    workspace: Mapped[Organization | None] = relationship(back_populates="roles")
    workspace_membership_assignments: Mapped[list["WorkspaceMembershipRole"]] = (
        relationship(
            back_populates="role",
            cascade="all, delete-orphan",
        )
    )
    department_links: Mapped[list["RoleDepartment"]] = relationship(
        back_populates="role",
        cascade="all, delete-orphan",
    )
    capability_links: Mapped[list["RoleCapability"]] = relationship(
        back_populates="role",
        cascade="all, delete-orphan",
        order_by=lambda: (
            RoleCapability.created_at.asc(),
            RoleCapability.capability_id.asc(),
        ),
    )

    @validates("key", "name", "display_name", "description")
    def _validate_required_text(self, key: str, value: str | None) -> str:
        return _required_text(value, key)

    @property
    def capabilities(self) -> tuple["Capability", ...]:
        return tuple(
            link.capability
            for link in self.capability_links
            if link.capability is not None
        )

    __table_args__ = (
        Index(
            "uq_roles_system_key",
            "key",
            unique=True,
            postgresql_where=workspace_id.is_(None),
            sqlite_where=workspace_id.is_(None),
        ),
        Index(
            "uq_roles_workspace_id_key",
            "workspace_id",
            "key",
            unique=True,
            postgresql_where=workspace_id.is_not(None),
            sqlite_where=workspace_id.is_not(None),
        ),
        Index("ix_roles_workspace_id", "workspace_id"),
        Index("ix_roles_workspace_id_key", "workspace_id", "key"),
        Index("ix_roles_key", "key"),
        Index("ix_roles_is_system_role", "is_system_role"),
        Index("ix_roles_system_role", "system_role"),
    )


class Capability(Base, TimestampMixin):
    __tablename__ = "capabilities"

    id: Mapped[UUIDPrimaryKey]
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    system_capability: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )

    role_links: Mapped[list["RoleCapability"]] = relationship(
        back_populates="capability",
        cascade="all, delete-orphan",
    )

    @validates("key", "display_name", "description")
    def _validate_required_text(self, key: str, value: str | None) -> str:
        return _required_text(value, key)

    __table_args__ = (
        UniqueConstraint("key", name="uq_capabilities_key"),
        Index("ix_capabilities_key", "key"),
        Index("ix_capabilities_system_capability", "system_capability"),
    )


class RoleCapability(Base):
    __tablename__ = "role_capabilities"

    id: Mapped[UUIDPrimaryKey]
    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    capability_id: Mapped[UUID] = mapped_column(
        ForeignKey("capabilities.id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="system_default",
        server_default="system_default",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )

    role: Mapped["Role"] = relationship(back_populates="capability_links")
    capability: Mapped[Capability] = relationship(back_populates="role_links")

    @property
    def capability_key(self) -> str:
        return self.capability.key

    @validates("source")
    def _validate_required_text(self, key: str, value: str | None) -> str:
        return _required_text(value, key)

    __table_args__ = (
        UniqueConstraint(
            "role_id",
            "capability_id",
            name="uq_role_capabilities_role_id_capability_id",
        ),
        Index("ix_role_capabilities_role_id", "role_id"),
        Index("ix_role_capabilities_capability_id", "capability_id"),
        Index("ix_role_capabilities_source", "source"),
    )


class WorkspaceMembershipRole(Base):
    __tablename__ = "workspace_membership_roles"

    id: Mapped[UUIDPrimaryKey]
    membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspace_memberships.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )

    workspace_membership: Mapped[WorkspaceMembership] = relationship(
        back_populates="role_assignments"
    )
    role: Mapped[Role] = relationship(back_populates="workspace_membership_assignments")
    assigner: Mapped[User | None] = relationship()

    @validates("metadata_json")
    def _validate_metadata(self, key: str, value: dict | None) -> dict:
        return _json_object(value, key)

    __table_args__ = (
        UniqueConstraint(
            "membership_id",
            "role_id",
            name="uq_workspace_membership_roles_membership_id_role_id",
        ),
        Index(
            "ix_workspace_membership_roles_membership_id",
            "membership_id",
        ),
        Index("ix_workspace_membership_roles_role_id", "role_id"),
        Index("ix_workspace_membership_roles_assigned_by", "assigned_by"),
        Index("ix_workspace_membership_roles_assigned_at", "assigned_at"),
    )


class WorkspaceInvite(Base, TimestampMixin):
    __tablename__ = "workspace_invites"

    id: Mapped[UUIDPrimaryKey]
    token: Mapped[str] = mapped_column(String(120), nullable=False)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    inviter_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    invitee_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    professional_roles: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    workspace_roles: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    proposed_department_access: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    maximum_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    use_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    status: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="active",
        server_default="active",
    )

    organization: Mapped[Organization] = relationship(
        back_populates="workspace_invites",
        foreign_keys=[organization_id],
    )
    inviter: Mapped[User | None] = relationship(foreign_keys=[inviter_user_id])

    __table_args__ = (
        UniqueConstraint("token", name="uq_workspace_invites_token"),
        Index("ix_workspace_invites_organization_id", "organization_id"),
        Index("ix_workspace_invites_inviter_user_id", "inviter_user_id"),
        Index("ix_workspace_invites_invitee_email", "invitee_email"),
        Index("ix_workspace_invites_token", "token"),
        Index("ix_workspace_invites_status_expires_at", "status", "expires_at"),
    )


class WebhookEvent(Base, TimestampMixin):
    __tablename__ = "webhook_events"

    id: Mapped[UUIDPrimaryKey]
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(120))
    resource_id: Mapped[str | None] = mapped_column(String(255))
    workos_event_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    processing_status: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="processed",
        server_default="processed",
    )

    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_webhook_events_provider_id"),
        Index("ix_webhook_events_provider_event_id", "provider", "event_id"),
        Index(
            "ix_webhook_events_resource_created_at",
            "provider",
            "resource_type",
            "resource_id",
            "workos_event_created_at",
        ),
    )


class ProfessionalRole(Base, TimestampMixin):
    __tablename__ = "professional_roles"

    id: Mapped[UUIDPrimaryKey]
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    default_department_access: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    membership_links: Mapped[list["MembershipProfessionalRole"]] = relationship(
        back_populates="professional_role",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("slug", name="uq_professional_roles_slug"),
        Index("ix_professional_roles_slug", "slug"),
        Index("ix_professional_roles_is_active", "is_active"),
    )


class Department(Base, TimestampMixin):
    __tablename__ = "departments"

    id: Mapped[UUIDPrimaryKey]
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    access_sensitivity: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="standard",
        server_default="standard",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    membership_access_grants: Mapped[list["MembershipDepartmentAccess"]] = relationship(
        back_populates="department",
        cascade="all, delete-orphan",
    )
    role_links: Mapped[list["RoleDepartment"]] = relationship(
        back_populates="department",
        cascade="all, delete-orphan",
    )

    @property
    def key(self) -> str:
        return self.slug

    @key.setter
    def key(self, value: str) -> None:
        self.slug = value

    __table_args__ = (
        UniqueConstraint("slug", name="uq_departments_slug"),
        Index("ix_departments_slug", "slug"),
        Index("ix_departments_is_active", "is_active"),
    )


class MembershipDepartmentAccess(Base, TimestampMixin):
    __tablename__ = "membership_department_access"

    id: Mapped[UUIDPrimaryKey]
    membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("organization_memberships.id", ondelete="CASCADE"),
        nullable=False,
    )
    department_id: Mapped[UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
    )
    access_level: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="member",
        server_default="member",
    )
    source: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="role_default",
        server_default="role_default",
    )
    approved_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    membership: Mapped[OrganizationMembership] = relationship(
        back_populates="department_access_grants"
    )
    department: Mapped[Department] = relationship(
        back_populates="membership_access_grants"
    )
    approver: Mapped[User | None] = relationship()

    @property
    def department_slug(self) -> str:
        return self.department.slug

    __table_args__ = (
        UniqueConstraint(
            "membership_id",
            "department_id",
            name="uq_membership_department_access_membership_id_department_id",
        ),
        Index(
            "ix_membership_department_access_membership_id",
            "membership_id",
        ),
        Index(
            "ix_membership_department_access_department_id",
            "department_id",
        ),
        Index(
            "ix_membership_department_access_access_level",
            "access_level",
        ),
        Index(
            "ix_membership_department_access_source",
            "source",
        ),
    )


class RoleDepartment(Base):
    __tablename__ = "role_departments"

    id: Mapped[UUIDPrimaryKey]
    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    department_id: Mapped[UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
    )
    access_level: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="responsibility",
        server_default="responsibility",
    )
    source: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="system_default",
        server_default="system_default",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )

    role: Mapped["Role"] = relationship(back_populates="department_links")
    department: Mapped[Department] = relationship(back_populates="role_links")

    @property
    def department_key(self) -> str:
        return self.department.key

    __table_args__ = (
        UniqueConstraint(
            "role_id",
            "department_id",
            name="uq_role_departments_role_id_department_id",
        ),
        Index("ix_role_departments_role_id", "role_id"),
        Index("ix_role_departments_department_id", "department_id"),
        Index("ix_role_departments_access_level", "access_level"),
        Index("ix_role_departments_source", "source"),
    )


class MembershipProfessionalRole(Base):
    __tablename__ = "membership_professional_roles"

    membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("organization_memberships.id", ondelete="CASCADE"),
        primary_key=True,
    )
    professional_role_id: Mapped[UUID] = mapped_column(
        ForeignKey("professional_roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    status: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="active",
        server_default="active",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )

    membership: Mapped[OrganizationMembership] = relationship(
        back_populates="professional_role_links"
    )
    professional_role: Mapped[ProfessionalRole] = relationship(
        back_populates="membership_links"
    )

    __table_args__ = (
        Index(
            "ix_membership_professional_roles_membership_id",
            "membership_id",
        ),
        Index(
            "ix_membership_professional_roles_professional_role_id",
            "professional_role_id",
        ),
        Index(
            "ix_membership_professional_roles_status",
            "status",
        ),
    )


class RealtimeEvent(Base, TimestampMixin):
    __tablename__ = "realtime_events"

    id: Mapped[UUIDPrimaryKey]
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(180), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    schema_version: Mapped[int] = mapped_column(nullable=False, default=1)
    entity_type: Mapped[str | None] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(120))
    operation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_display_name: Mapped[str | None] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    organization: Mapped[Organization] = relationship()
    actor: Mapped[User | None] = relationship()

    __table_args__ = (
        Index(
            "ix_realtime_events_organization_created", "organization_id", "created_at"
        ),
        Index("ix_realtime_events_channel_created", "channel", "created_at"),
        UniqueConstraint("operation_id", name="uq_realtime_events_operation_id"),
    )


class OrganizationOwnedMixin:
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )


class Artist(Base, TimestampMixin, OrganizationOwnedMixin):
    __tablename__ = "artists"

    id: Mapped[UUIDPrimaryKey]
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="artists")
    profile: Mapped["ArtistProfile | None"] = relationship(
        back_populates="artist",
        cascade="all, delete-orphan",
        uselist=False,
    )
    campaign_links: Mapped[list["CampaignArtist"]] = relationship(
        back_populates="artist",
        cascade="all, delete-orphan",
    )
    marketing_content_items: Mapped[list["MarketingContentItem"]] = relationship(
        back_populates="artist"
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "name", name="uq_artists_organization_id_name"
        ),
        Index("ix_artists_organization_id", "organization_id"),
    )


class ProfileModuleMixin:
    __profile_module_key__: ClassVar[str]
    __universal_profile_relationship__: ClassVar[str]

    id: Mapped[UUIDPrimaryKey]
    universal_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("universal_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )

    @declared_attr
    def universal_profile(cls) -> Mapped[UniversalProfile]:
        return relationship(back_populates=cls.__universal_profile_relationship__)


class ArtistProfile(Base, TimestampMixin, ProfileModuleMixin):
    """Person-backed artist module linked to a workspace catalog artist.

    Catalog artists may exist without this module. When this row exists it
    represents a known UniversalProfile acting as that artist identity.
    """

    __tablename__ = "artist_profiles"
    __profile_module_key__ = "artist"
    __universal_profile_relationship__ = "artist_profiles"

    artist_id: Mapped[UUID] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"),
        nullable=False,
    )
    stage_name: Mapped[str | None] = mapped_column(String(200))
    genres: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    influences: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    imagery: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    dsp_links: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    catalog_references: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    creative_metadata: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    career_stage: Mapped[str | None] = mapped_column(String(120))
    audience: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    preferences: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    artist: Mapped[Artist] = relationship(back_populates="profile")
    analytics_observations: Mapped[list["AnalyticsObservation"]] = relationship(
        back_populates="artist_profile",
    )
    social_account_connections: Mapped[list["SocialAccountConnection"]] = relationship(
        back_populates="artist_profile"
    )

    @validates("stage_name", "career_stage")
    def _validate_optional_text(self, _key: str, value: str | None) -> str | None:
        return _optional_text(value)

    @validates(
        "imagery",
        "dsp_links",
        "creative_metadata",
        "audience",
        "preferences",
    )
    def _validate_json_objects(self, key: str, value: dict | None) -> dict:
        return _json_object(value, key)

    @validates("genres", "influences", "catalog_references")
    def _validate_json_lists(self, key: str, value: list | None) -> list:
        return _json_list(value, key)

    __table_args__ = (
        UniqueConstraint("artist_id", name="uq_artist_profiles_artist_id"),
        Index("ix_artist_profiles_artist_id", "artist_id"),
        Index("ix_artist_profiles_universal_profile_id", "universal_profile_id"),
        Index("ix_artist_profiles_stage_name", "stage_name"),
        Index("ix_artist_profiles_career_stage", "career_stage"),
    )


class SocialAccountConnection(Base, TimestampMixin, OrganizationOwnedMixin):
    __tablename__ = "social_account_connections"

    id: Mapped[UUIDPrimaryKey]
    artist_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artist_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    external_account_id: Mapped[str | None] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255))
    profile_url: Mapped[str | None] = mapped_column(String(2048))
    connection_method: Mapped[SocialAccountConnectionMethod] = mapped_column(
        Enum(
            SocialAccountConnectionMethod,
            name="social_account_connection_method",
            values_callable=lambda methods: [method.value for method in methods],
        ),
        nullable=False,
        default=SocialAccountConnectionMethod.assisted,
        server_default=SocialAccountConnectionMethod.assisted.value,
    )
    status: Mapped[SocialAccountConnectionStatus] = mapped_column(
        Enum(
            SocialAccountConnectionStatus,
            name="social_account_connection_status",
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        nullable=False,
        default=SocialAccountConnectionStatus.pending,
        server_default=SocialAccountConnectionStatus.pending.value,
    )
    capabilities: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    credential_ref: Mapped[str | None] = mapped_column(String(500))
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_health_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_error_code: Mapped[str | None] = mapped_column(String(120))
    last_error_message: Mapped[str | None] = mapped_column(String(2000))
    provider_metadata: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("universal_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization: Mapped[Organization] = relationship(
        back_populates="social_account_connections"
    )
    artist_profile: Mapped[ArtistProfile | None] = relationship(
        back_populates="social_account_connections"
    )
    created_by_user: Mapped[User | None] = relationship(
        back_populates="created_social_account_connections",
        foreign_keys=[created_by_user_id],
    )
    created_by_profile: Mapped[UniversalProfile | None] = relationship(
        back_populates="created_social_account_connections",
        foreign_keys=[created_by_profile_id],
    )

    @validates("provider")
    def _validate_provider(self, key: str, value: str | None) -> str:
        return _required_text(value, key)

    @validates(
        "external_account_id",
        "username",
        "display_name",
        "credential_ref",
        "last_error_code",
    )
    def _validate_optional_text(self, _key: str, value: str | None) -> str | None:
        return _optional_text(value)

    @validates("last_error_message")
    def _validate_last_error_message(
        self,
        _key: str,
        value: str | None,
    ) -> str | None:
        redacted = _redact_sensitive_text(value)
        return redacted[:2000] if redacted is not None else None

    @validates("profile_url")
    def _validate_profile_url(self, _key: str, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_url(value)

    @validates("capabilities")
    def _validate_capabilities(self, key: str, value: list | None) -> list:
        return _json_list(value, key)

    @validates("provider_metadata")
    def _validate_provider_metadata(self, key: str, value: dict | None) -> dict:
        sanitized = _without_sensitive_json_keys(_json_object(value, key))
        if not isinstance(sanitized, dict):
            raise ValueError(f"{key} must be a JSON object")
        return sanitized

    __table_args__ = (
        Index("ix_social_account_connections_organization_id", "organization_id"),
        Index(
            "ix_social_account_connections_organization_provider",
            "organization_id",
            "provider",
        ),
        Index(
            "ix_social_account_connections_organization_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_social_account_connections_organization_artist_profile",
            "organization_id",
            "artist_profile_id",
        ),
        Index(
            "ix_social_account_connections_provider_external_account",
            "provider",
            "external_account_id",
        ),
        Index(
            "uq_social_account_connections_org_provider_external",
            "organization_id",
            "provider",
            "connection_method",
            "external_account_id",
            unique=True,
            postgresql_where=(
                external_account_id.is_not(None)
                & (status != SocialAccountConnectionStatus.disconnected)
            ),
            sqlite_where=(
                external_account_id.is_not(None)
                & (status != SocialAccountConnectionStatus.disconnected)
            ),
        ),
    )


class Release(Base, TimestampMixin, OrganizationOwnedMixin):
    __tablename__ = "releases"

    id: Mapped[UUIDPrimaryKey]
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    artist_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artists.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization: Mapped[Organization] = relationship(back_populates="releases")
    artist: Mapped[Artist | None] = relationship()
    campaign_links: Mapped[list["CampaignRelease"]] = relationship(
        back_populates="release",
        cascade="all, delete-orphan",
    )
    marketing_content_items: Mapped[list["MarketingContentItem"]] = relationship(
        back_populates="release"
    )

    __table_args__ = (
        Index("ix_releases_organization_id", "organization_id"),
        Index("ix_releases_organization_id_artist_id", "organization_id", "artist_id"),
    )


class CampaignRelease(Base, TimestampMixin):
    __tablename__ = "campaign_releases"

    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        primary_key=True,
    )
    release_id: Mapped[UUID] = mapped_column(
        ForeignKey("releases.id", ondelete="CASCADE"),
        primary_key=True,
    )
    relationship_kind: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="related",
        server_default="related",
    )

    campaign: Mapped["Campaign"] = relationship(back_populates="release_links")
    release: Mapped[Release] = relationship(back_populates="campaign_links")

    __table_args__ = (
        Index("ix_campaign_releases_campaign_id", "campaign_id"),
        Index("ix_campaign_releases_release_id", "release_id"),
        Index("ix_campaign_releases_relationship_kind", "relationship_kind"),
    )


class CampaignArtist(Base, TimestampMixin):
    __tablename__ = "campaign_artists"

    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        primary_key=True,
    )
    artist_id: Mapped[UUID] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"),
        primary_key=True,
    )
    relationship_kind: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="collaborator",
        server_default="collaborator",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    campaign: Mapped["Campaign"] = relationship(back_populates="artist_links")
    artist: Mapped[Artist] = relationship(back_populates="campaign_links")

    __table_args__ = (
        Index("ix_campaign_artists_campaign_id", "campaign_id"),
        Index("ix_campaign_artists_artist_id", "artist_id"),
        Index("ix_campaign_artists_relationship_kind", "relationship_kind"),
    )


class CampaignMember(Base, TimestampMixin):
    __tablename__ = "campaign_members"

    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        primary_key=True,
    )
    workspace_membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspace_memberships.id", ondelete="CASCADE"),
        primary_key=True,
    )
    participation_status: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="active",
        server_default="active",
    )
    responsibility_label: Mapped[str | None] = mapped_column(String(120))

    campaign: Mapped["Campaign"] = relationship(back_populates="member_links")
    workspace_membership: Mapped[WorkspaceMembership] = relationship(
        back_populates="campaign_links"
    )

    __table_args__ = (
        Index("ix_campaign_members_campaign_id", "campaign_id"),
        Index("ix_campaign_members_workspace_membership_id", "workspace_membership_id"),
        Index("ix_campaign_members_participation_status", "participation_status"),
        Index("ix_campaign_members_responsibility_label", "responsibility_label"),
    )


class Campaign(Base, TimestampMixin, OrganizationOwnedMixin):
    __tablename__ = "campaigns"

    id: Mapped[UUIDPrimaryKey]
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(4000))
    campaign_type: Mapped[CampaignType] = mapped_column(
        Enum(CampaignType, name="campaign_type"),
        nullable=False,
        default=CampaignType.other,
        server_default=CampaignType.other.value,
    )
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus, name="campaign_status"),
        nullable=False,
        default=CampaignStatus.draft,
        server_default=CampaignStatus.draft.value,
    )
    start_date: Mapped[date | None] = mapped_column(Date)
    target_end_date: Mapped[date | None] = mapped_column(Date)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("universal_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    owner_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("universal_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    primary_artist_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artists.id", ondelete="SET NULL"),
        nullable=True,
    )
    release_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("releases.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization: Mapped[Organization] = relationship(back_populates="campaigns")
    release: Mapped[Release | None] = relationship()
    release_links: Mapped[list[CampaignRelease]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    artist_links: Mapped[list[CampaignArtist]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    member_links: Mapped[list[CampaignMember]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    goals: Mapped[list["CampaignGoal"]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by=lambda: (CampaignGoal.created_at.asc(), CampaignGoal.id.asc()),
    )
    milestones: Mapped[list["CampaignMilestone"]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by=lambda: (
            CampaignMilestone.target_date.asc().nulls_last(),
            CampaignMilestone.created_at.asc(),
            CampaignMilestone.id.asc(),
        ),
    )
    created_by_user: Mapped[User | None] = relationship(
        foreign_keys=[created_by_user_id]
    )
    created_by_profile: Mapped[UniversalProfile | None] = relationship(
        foreign_keys=[created_by_profile_id]
    )
    owner_profile: Mapped[UniversalProfile | None] = relationship(
        foreign_keys=[owner_profile_id]
    )
    primary_artist: Mapped[Artist | None] = relationship(
        foreign_keys=[primary_artist_id]
    )
    analytics_observations: Mapped[list["AnalyticsObservation"]] = relationship(
        back_populates="campaign",
    )
    marketing_content_items: Mapped[list["MarketingContentItem"]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by=lambda: (
            MarketingContentItem.scheduled_at.asc().nulls_last(),
            MarketingContentItem.created_at.asc(),
            MarketingContentItem.id.asc(),
        ),
    )

    @validates("name")
    def _validate_name(self, _key: str, value: str | None) -> str:
        return _required_text(value, "name")

    @validates("description")
    def _validate_description(self, _key: str, value: str | None) -> str | None:
        return _optional_text(value)

    __table_args__ = (
        Index("ix_campaigns_organization_id", "organization_id"),
        Index(
            "ix_campaigns_organization_id_campaign_type",
            "organization_id",
            "campaign_type",
        ),
        Index("ix_campaigns_organization_id_status", "organization_id", "status"),
        Index(
            "ix_campaigns_organization_id_owner_profile_id",
            "organization_id",
            "owner_profile_id",
        ),
        Index(
            "ix_campaigns_organization_id_created_by_user_id",
            "organization_id",
            "created_by_user_id",
        ),
        Index(
            "ix_campaigns_organization_id_created_by_profile_id",
            "organization_id",
            "created_by_profile_id",
        ),
        Index(
            "ix_campaigns_organization_id_primary_artist_id",
            "organization_id",
            "primary_artist_id",
        ),
        Index(
            "ix_campaigns_organization_id_release_id", "organization_id", "release_id"
        ),
        Index(
            "ix_campaigns_organization_id_start_date",
            "organization_id",
            "start_date",
        ),
        Index(
            "ix_campaigns_organization_id_target_end_date",
            "organization_id",
            "target_end_date",
        ),
    )


class ApprovalRequest(Base, TimestampMixin):
    __tablename__ = "approval_requests"

    id: Mapped[UUIDPrimaryKey]
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    resource_type: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(nullable=False)
    resource_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    status: Mapped[ApprovalRequestStatus] = mapped_column(
        Enum(ApprovalRequestStatus, name="approval_request_status"),
        nullable=False,
        default=ApprovalRequestStatus.requested,
        server_default=ApprovalRequestStatus.requested.value,
    )
    requested_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    requested_by_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("universal_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    submitted_by_actor_kind: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="user",
        server_default="user",
    )
    submitted_by_actor_key: Mapped[str | None] = mapped_column(String(255))
    current_stage_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(4000))
    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization: Mapped[Organization] = relationship(
        back_populates="approval_requests"
    )
    requested_by_user: Mapped[User | None] = relationship(
        foreign_keys=[requested_by_user_id]
    )
    requested_by_profile: Mapped[UniversalProfile | None] = relationship(
        foreign_keys=[requested_by_profile_id]
    )
    stages: Mapped[list["ApprovalRequestStage"]] = relationship(
        back_populates="approval_request",
        order_by=lambda: (
            ApprovalRequestStage.stage_order.asc(),
            ApprovalRequestStage.created_at.asc(),
            ApprovalRequestStage.id.asc(),
        ),
    )
    decisions: Mapped[list["ApprovalDecision"]] = relationship(
        back_populates="approval_request",
        order_by=lambda: (
            ApprovalDecision.created_at.asc(),
            ApprovalDecision.id.asc(),
        ),
    )
    marketing_content_items: Mapped[list["MarketingContentItem"]] = relationship(
        back_populates="approval_request"
    )

    @validates("resource_type", "submitted_by_actor_kind", "title")
    def _validate_required_text(self, key: str, value: str | None) -> str:
        return _required_text(value, key)

    @validates("submitted_by_actor_key", "summary")
    def _validate_optional_text(self, _key: str, value: str | None) -> str | None:
        return _optional_text(value)

    @validates("metadata_json")
    def _validate_metadata(self, key: str, value: dict | None) -> dict:
        return _json_object(value, key)

    __table_args__ = (
        CheckConstraint(
            "resource_revision >= 1",
            name="resource_revision_positive",
        ),
        CheckConstraint(
            "current_stage_order >= 1",
            name="current_stage_order_positive",
        ),
        Index("ix_approval_requests_organization_id", "organization_id"),
        Index(
            "ix_approval_requests_organization_id_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_approval_requests_resource_lookup",
            "organization_id",
            "resource_type",
            "resource_id",
            "resource_revision",
        ),
        Index(
            "ix_approval_requests_queue_order",
            "organization_id",
            "status",
            "submitted_at",
        ),
        Index(
            "ix_approval_requests_requested_by_user",
            "organization_id",
            "requested_by_user_id",
        ),
        Index(
            "ix_approval_requests_requested_by_profile",
            "organization_id",
            "requested_by_profile_id",
        ),
        Index(
            "uq_approval_requests_active_resource_revision",
            "organization_id",
            "resource_type",
            "resource_id",
            "resource_revision",
            unique=True,
            postgresql_where=and_(
                status.in_(
                    (
                        ApprovalRequestStatus.requested,
                        ApprovalRequestStatus.in_review,
                        ApprovalRequestStatus.changes_requested,
                    )
                )
            ),
            sqlite_where=and_(
                status.in_(
                    (
                        ApprovalRequestStatus.requested,
                        ApprovalRequestStatus.in_review,
                        ApprovalRequestStatus.changes_requested,
                    )
                )
            ),
        ),
    )


class ApprovalRequestStage(Base, TimestampMixin):
    __tablename__ = "approval_request_stages"

    id: Mapped[UUIDPrimaryKey]
    approval_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="RESTRICT"),
        nullable=False,
    )
    stage_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    required_capability: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[ApprovalStageStatus] = mapped_column(
        Enum(ApprovalStageStatus, name="approval_stage_status"),
        nullable=False,
        default=ApprovalStageStatus.pending,
        server_default=ApprovalStageStatus.pending.value,
    )
    assigned_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("universal_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    approval_request: Mapped[ApprovalRequest] = relationship(back_populates="stages")
    assigned_profile: Mapped[UniversalProfile | None] = relationship(
        foreign_keys=[assigned_profile_id]
    )
    decisions: Mapped[list["ApprovalDecision"]] = relationship(
        back_populates="stage",
        order_by=lambda: (
            ApprovalDecision.created_at.asc(),
            ApprovalDecision.id.asc(),
        ),
    )

    @validates("required_capability")
    def _validate_required_text(self, key: str, value: str | None) -> str:
        return _required_text(value, key)

    __table_args__ = (
        CheckConstraint(
            "stage_order >= 1",
            name="stage_order_positive",
        ),
        UniqueConstraint(
            "approval_request_id",
            "stage_order",
            name="uq_approval_request_stages_request_stage_order",
        ),
        Index(
            "ix_approval_request_stages_approval_request_id",
            "approval_request_id",
        ),
        Index(
            "ix_approval_request_stages_request_status",
            "approval_request_id",
            "status",
        ),
        Index(
            "ix_approval_request_stages_reviewer_queue",
            "assigned_profile_id",
            "status",
            "started_at",
        ),
        Index(
            "ix_approval_request_stages_required_capability",
            "required_capability",
        ),
    )


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"

    id: Mapped[UUIDPrimaryKey]
    approval_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="RESTRICT"),
        nullable=False,
    )
    stage_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("approval_request_stages.id", ondelete="SET NULL"),
        nullable=True,
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    decision: Mapped[ApprovalDecisionValue] = mapped_column(
        Enum(ApprovalDecisionValue, name="approval_decision_value"),
        nullable=False,
    )
    decided_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_by_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("universal_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_kind: Mapped[str] = mapped_column(String(60), nullable=False)
    actor_key: Mapped[str | None] = mapped_column(String(255))
    reason: Mapped[str | None] = mapped_column(String(4000))
    payload: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )

    approval_request: Mapped[ApprovalRequest] = relationship(back_populates="decisions")
    stage: Mapped[ApprovalRequestStage | None] = relationship(
        back_populates="decisions",
        foreign_keys=[stage_id],
    )
    organization: Mapped[Organization] = relationship(
        back_populates="approval_decisions"
    )
    decided_by_user: Mapped[User | None] = relationship(
        foreign_keys=[decided_by_user_id]
    )
    decided_by_profile: Mapped[UniversalProfile | None] = relationship(
        foreign_keys=[decided_by_profile_id]
    )

    @validates("actor_kind")
    def _validate_required_text(self, key: str, value: str | None) -> str:
        return _required_text(value, key)

    @validates("actor_key", "reason")
    def _validate_optional_text(self, _key: str, value: str | None) -> str | None:
        return _optional_text(value)

    @validates("payload")
    def _validate_payload(self, key: str, value: dict | None) -> dict:
        return _json_object(value, key)

    __table_args__ = (
        Index("ix_approval_decisions_organization_id", "organization_id"),
        Index(
            "ix_approval_decisions_request_created",
            "approval_request_id",
            "created_at",
        ),
        Index("ix_approval_decisions_stage_id", "stage_id"),
        Index(
            "ix_approval_decisions_organization_decision",
            "organization_id",
            "decision",
        ),
        Index(
            "ix_approval_decisions_decided_by_user",
            "organization_id",
            "decided_by_user_id",
        ),
        Index(
            "ix_approval_decisions_decided_by_profile",
            "organization_id",
            "decided_by_profile_id",
        ),
    )


class MarketingContentItem(Base, TimestampMixin, OrganizationOwnedMixin):
    __tablename__ = "marketing_content_items"

    id: Mapped[UUIDPrimaryKey]
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    artist_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artists.id", ondelete="SET NULL"),
        nullable=True,
    )
    release_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("releases.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    copy_text: Mapped[str | None] = mapped_column(String(8000))
    asset_refs: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    status: Mapped[MarketingContentItemStatus] = mapped_column(
        Enum(MarketingContentItemStatus, name="marketing_content_item_status"),
        nullable=False,
        default=MarketingContentItemStatus.draft,
        server_default=MarketingContentItemStatus.draft.value,
    )
    content_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    approved_revision: Mapped[int | None] = mapped_column(Integer)
    approval_request_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("universal_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("universal_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    owner_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("universal_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization: Mapped[Organization] = relationship(
        back_populates="marketing_content_items"
    )
    campaign: Mapped[Campaign] = relationship(back_populates="marketing_content_items")
    channels: Mapped[list["MarketingContentItemChannel"]] = relationship(
        back_populates="marketing_content_item",
        cascade="all, delete-orphan",
        order_by=lambda: (
            MarketingContentItemChannel.channel.asc(),
            MarketingContentItemChannel.placement.asc(),
            MarketingContentItemChannel.created_at.asc(),
        ),
    )
    artist: Mapped[Artist | None] = relationship(
        back_populates="marketing_content_items",
        foreign_keys=[artist_id],
    )
    release: Mapped[Release | None] = relationship(
        back_populates="marketing_content_items",
        foreign_keys=[release_id],
    )
    approved_by_profile: Mapped[UniversalProfile | None] = relationship(
        back_populates="approved_marketing_content_items",
        foreign_keys=[approved_by_profile_id],
    )
    created_by_user: Mapped[User | None] = relationship(
        back_populates="created_marketing_content_items",
        foreign_keys=[created_by_user_id],
    )
    created_by_profile: Mapped[UniversalProfile | None] = relationship(
        back_populates="created_marketing_content_items",
        foreign_keys=[created_by_profile_id],
    )
    owner_profile: Mapped[UniversalProfile | None] = relationship(
        back_populates="owned_marketing_content_items",
        foreign_keys=[owner_profile_id],
    )
    approval_request: Mapped[ApprovalRequest | None] = relationship(
        back_populates="marketing_content_items",
        foreign_keys=[approval_request_id],
    )

    @validates("title", "content_type")
    def _validate_required_text(self, key: str, value: str | None) -> str:
        return _required_text(value, key)

    @validates("copy_text")
    def _validate_optional_text(self, _key: str, value: str | None) -> str | None:
        return _optional_text(value)

    @validates("asset_refs")
    def _validate_asset_refs(self, key: str, value: list | None) -> list:
        return _json_list(value, key)

    @validates("metadata_json")
    def _validate_metadata(self, key: str, value: dict | None) -> dict:
        return _json_object(value, key)

    __table_args__ = (
        CheckConstraint(
            "content_revision >= 1",
            name="content_revision_positive",
        ),
        Index("ix_marketing_content_items_organization_id", "organization_id"),
        Index(
            "ix_marketing_content_items_organization_id_campaign_id",
            "organization_id",
            "campaign_id",
        ),
        Index(
            "ix_marketing_content_items_organization_id_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_marketing_content_items_organization_id_scheduled_at",
            "organization_id",
            "scheduled_at",
        ),
        Index(
            "ix_marketing_content_items_organization_id_published_at",
            "organization_id",
            "published_at",
        ),
        Index(
            "ix_marketing_content_items_organization_id_artist_id",
            "organization_id",
            "artist_id",
        ),
        Index(
            "ix_marketing_content_items_organization_id_release_id",
            "organization_id",
            "release_id",
        ),
        Index(
            "ix_marketing_content_items_org_owner_profile",
            "organization_id",
            "owner_profile_id",
        ),
        Index(
            "ix_marketing_content_items_org_created_user",
            "organization_id",
            "created_by_user_id",
        ),
        Index(
            "ix_marketing_content_items_org_created_profile",
            "organization_id",
            "created_by_profile_id",
        ),
        Index(
            "ix_marketing_content_items_org_approval_request",
            "organization_id",
            "approval_request_id",
        ),
    )


class MarketingMediaAsset(Base):
    """Prepared media, addressed by digest within one workspace/content item."""

    __tablename__ = "marketing_media_assets"

    workspace_id: Mapped[UUID] = mapped_column(primary_key=True)
    content_item_id: Mapped[UUID] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    media_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes] = mapped_column(LargeBinary)

    __table_args__ = (
        ForeignKeyConstraint(
            ["content_item_id", "workspace_id"],
            ["marketing_content_items.id", "marketing_content_items.organization_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("length(sha256) = 64", name="digest_length"),
        CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 16777216 AND length(data) = size_bytes",
            name="bounded_data",
        ),
    )


class MarketingContentItemChannel(Base, TimestampMixin):
    __tablename__ = "marketing_content_item_channels"

    id: Mapped[UUIDPrimaryKey]
    marketing_content_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("marketing_content_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    social_account_connection_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("social_account_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    channel: Mapped[str] = mapped_column(String(80), nullable=False)
    placement: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="default",
        server_default="default",
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    schedule_generation: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    schedule_timezone: Mapped[str | None] = mapped_column(String(255))
    schedule_local_time: Mapped[str | None] = mapped_column(String(32))
    schedule_offset_seconds: Mapped[int | None] = mapped_column(Integer)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_post_id: Mapped[str | None] = mapped_column(String(255))
    external_url: Mapped[str | None] = mapped_column(String(2048))
    copy_text_override: Mapped[str | None] = mapped_column(String(8000))
    asset_refs: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    marketing_content_item: Mapped[MarketingContentItem] = relationship(
        back_populates="channels"
    )
    social_account_connection: Mapped[SocialAccountConnection | None] = relationship()

    @validates("channel", "placement")
    def _validate_required_text(self, key: str, value: str | None) -> str:
        return _required_text(value, key)

    @validates("external_post_id", "external_url", "copy_text_override")
    def _validate_optional_text(self, _key: str, value: str | None) -> str | None:
        return _optional_text(value)

    @validates("asset_refs")
    def _validate_asset_refs(self, key: str, value: list | None) -> list:
        return _json_list(value, key)

    @validates("metadata_json")
    def _validate_metadata(self, key: str, value: dict | None) -> dict:
        return _json_object(value, key)

    __table_args__ = (
        UniqueConstraint(
            "marketing_content_item_id",
            "channel",
            "placement",
            name="uq_marketing_content_item_channels_item_channel_placement",
        ),
        Index(
            "ix_marketing_content_item_channels_marketing_content_item_id",
            "marketing_content_item_id",
        ),
        Index(
            "ix_marketing_content_item_channels_social_account_connection_id",
            "social_account_connection_id",
        ),
        Index("ix_marketing_content_item_channels_channel", "channel"),
        Index(
            "ix_marketing_content_item_channels_channel_scheduled_at",
            "channel",
            "scheduled_at",
        ),
    )


# Candidate keys for workspace-scoped scheduling references. These never bind a
# historical job to the parent's mutable current revision or schedule intent.
Index(
    "uq_marketing_content_items_schedule_scope",
    MarketingContentItem.id,
    MarketingContentItem.organization_id,
    unique=True,
)
Index(
    "uq_marketing_channels_schedule_scope",
    MarketingContentItemChannel.id,
    MarketingContentItemChannel.marketing_content_item_id,
    unique=True,
)
Index(
    "uq_social_accounts_schedule_scope",
    SocialAccountConnection.id,
    SocialAccountConnection.organization_id,
    unique=True,
)
Index(
    "uq_approval_requests_schedule_scope",
    ApprovalRequest.id,
    ApprovalRequest.organization_id,
    ApprovalRequest.resource_type,
    ApprovalRequest.resource_id,
    ApprovalRequest.resource_revision,
    unique=True,
)


class SchedulingExecutionControl(Base):
    """Fail-closed workspace execution switch, locked before scheduling sources."""

    __tablename__ = "scheduling_execution_controls"

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    execution_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )


class SchedulingJob(Base, TimestampMixin):
    """Immutable authorization snapshot with mutable, fenced coordination state."""

    __tablename__ = "scheduling_jobs"

    id: Mapped[UUIDPrimaryKey]
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    marketing_content_item_id: Mapped[UUID] = mapped_column(nullable=False)
    marketing_content_item_channel_id: Mapped[UUID] = mapped_column(nullable=False)
    social_account_connection_id: Mapped[UUID | None]
    approval_request_id: Mapped[UUID] = mapped_column(nullable=False)
    approval_resource_type: Mapped[str] = mapped_column(
        String(120),
        default="marketing_content_item",
        server_default="marketing_content_item",
        nullable=False,
    )
    authorized_content_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schedule_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(
        SchedulingUTCDateTime(), nullable=False
    )
    schedule_timezone: Mapped[str] = mapped_column(String(255), nullable=False)
    effective_artist_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artists.id", ondelete="RESTRICT")
    )
    status: Mapped[SchedulingJobStatus] = mapped_column(
        Enum(SchedulingJobStatus, name="scheduling_job_status", create_constraint=True),
        default=SchedulingJobStatus.pending,
        server_default="pending",
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    activation_operation_id: Mapped[UUID] = mapped_column(nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(SchedulingUTCDateTime())
    claim_expires_at: Mapped[datetime | None] = mapped_column(SchedulingUTCDateTime())
    claimed_by: Mapped[str | None] = mapped_column(String(255))
    fencing_token: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0", nullable=False
    )
    transition_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    handed_off_at: Mapped[datetime | None] = mapped_column(SchedulingUTCDateTime())
    # Opaque Delivery receipt reference; no Delivery-owned storage is introduced.
    handoff_receipt_id: Mapped[UUID | None]
    blocked_at: Mapped[datetime | None] = mapped_column(SchedulingUTCDateTime())
    blocked_reason_code: Mapped[SchedulingBlockedReason | None] = mapped_column(
        Enum(
            SchedulingBlockedReason,
            name="scheduling_blocked_reason",
            create_constraint=True,
        )
    )
    blocked_metadata: Mapped[dict] = mapped_column(
        SchedulingMetadata(), default=dict, server_default="{}", nullable=False
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(SchedulingUTCDateTime())
    cancellation_reason: Mapped[str | None] = mapped_column(String(120))
    supersedes_job_id: Mapped[UUID | None]
    lineage_root_job_id: Mapped[UUID | None]
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    @validates("schedule_timezone")
    def _validate_timezone(self, _key: str, value: str) -> str:
        return scheduling_timezone(value)

    @validates("blocked_metadata")
    def _validate_blocked_metadata(self, _key: str, value: dict) -> dict:
        return safe_scheduling_metadata(value)

    __table_args__ = (
        ForeignKeyConstraint(
            ["marketing_content_item_id", "workspace_id"],
            ["marketing_content_items.id", "marketing_content_items.organization_id"],
            name="fk_scheduling_jobs_content_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["marketing_content_item_channel_id", "marketing_content_item_id"],
            [
                "marketing_content_item_channels.id",
                "marketing_content_item_channels.marketing_content_item_id",
            ],
            name="fk_scheduling_jobs_channel_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["social_account_connection_id", "workspace_id"],
            [
                "social_account_connections.id",
                "social_account_connections.organization_id",
            ],
            name="fk_scheduling_jobs_destination_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "approval_request_id",
                "workspace_id",
                "approval_resource_type",
                "marketing_content_item_id",
                "authorized_content_revision",
            ],
            [
                "approval_requests.id",
                "approval_requests.organization_id",
                "approval_requests.resource_type",
                "approval_requests.resource_id",
                "approval_requests.resource_revision",
            ],
            name="fk_scheduling_jobs_approval_snapshot",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "workspace_id",
            "marketing_content_item_id",
            name="uq_scheduling_jobs_lineage_scope",
        ),
        ForeignKeyConstraint(
            ["supersedes_job_id", "workspace_id", "marketing_content_item_id"],
            [
                "scheduling_jobs.id",
                "scheduling_jobs.workspace_id",
                "scheduling_jobs.marketing_content_item_id",
            ],
            name="fk_scheduling_jobs_predecessor",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["lineage_root_job_id", "workspace_id", "marketing_content_item_id"],
            [
                "scheduling_jobs.id",
                "scheduling_jobs.workspace_id",
                "scheduling_jobs.marketing_content_item_id",
            ],
            name="fk_scheduling_jobs_lineage_root",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("idempotency_key", name="uq_scheduling_jobs_idempotency_key"),
        UniqueConstraint(
            "workspace_id",
            "activation_operation_id",
            name="uq_scheduling_jobs_activation_operation",
        ),
        UniqueConstraint(
            "handoff_receipt_id", name="uq_scheduling_jobs_handoff_receipt"
        ),
        CheckConstraint(
            "authorized_content_revision >= 1 AND schedule_generation >= 1 "
            "AND fencing_token >= 0 AND transition_version >= 1",
            name="counters",
        ),
        CheckConstraint(
            "approval_resource_type = 'marketing_content_item'", name="approval_type"
        ),
        CheckConstraint(
            "length(trim(schedule_timezone)) > 0 AND length(trim(idempotency_key)) > 0",
            name="snapshot_text",
        ),
        CheckConstraint(
            "(claimed_at IS NULL AND claim_expires_at IS NULL AND claimed_by IS NULL) "
            "OR (claimed_at IS NOT NULL AND claim_expires_at IS NOT NULL "
            "AND claimed_by IS NOT NULL AND length(trim(claimed_by)) > 0 "
            "AND claim_expires_at > claimed_at AND fencing_token > 0)",
            name="lease",
        ),
        CheckConstraint(
            "status != 'claimed' OR claimed_at IS NOT NULL", name="claimed_lease"
        ),
        CheckConstraint(
            "(handed_off_at IS NULL AND handoff_receipt_id IS NULL AND status != 'handed_off') "
            "OR (handed_off_at IS NOT NULL AND handoff_receipt_id IS NOT NULL "
            "AND social_account_connection_id IS NOT NULL AND status = 'handed_off')",
            name="handoff_receipt",
        ),
        CheckConstraint(
            "(blocked_at IS NULL AND blocked_reason_code IS NULL) OR "
            "(blocked_at IS NOT NULL AND blocked_reason_code IS NOT NULL)",
            name="blocked_reason",
        ),
        CheckConstraint(
            "status != 'blocked' OR blocked_at IS NOT NULL", name="blocked_details"
        ),
        CheckConstraint(
            "(cancelled_at IS NULL AND cancellation_reason IS NULL AND status != 'cancelled') "
            "OR (cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL "
            "AND length(trim(cancellation_reason)) > 0 AND status = 'cancelled')",
            name="cancellation",
        ),
        CheckConstraint(
            "supersedes_job_id IS NULL OR supersedes_job_id != id",
            name="predecessor_not_self",
        ),
        CheckConstraint(
            "(supersedes_job_id IS NULL AND lineage_root_job_id IS NULL) OR "
            "(supersedes_job_id IS NOT NULL AND lineage_root_job_id IS NOT NULL "
            "AND lineage_root_job_id != id)",
            name="lineage",
        ),
        Index(
            "uq_scheduling_jobs_active_channel",
            "marketing_content_item_channel_id",
            unique=True,
            postgresql_where=status.in_(("pending", "claimed", "blocked")),
            sqlite_where=status.in_(("pending", "claimed", "blocked")),
        ),
        Index(
            "uq_scheduling_jobs_handed_off_intent",
            "marketing_content_item_channel_id",
            "authorized_content_revision",
            "schedule_generation",
            unique=True,
            postgresql_where=status.in_(
                ("pending", "claimed", "blocked", "handed_off")
            ),
            sqlite_where=status.in_(("pending", "claimed", "blocked", "handed_off")),
        ),
        Index(
            "ix_scheduling_jobs_due",
            "scheduled_for",
            "id",
            postgresql_where=status == "pending",
            sqlite_where=status == "pending",
        ),
        Index(
            "ix_scheduling_jobs_expired_claim",
            "claim_expires_at",
            "id",
            postgresql_where=status == "claimed",
            sqlite_where=status == "claimed",
        ),
        Index("ix_scheduling_jobs_workspace_list", "workspace_id", "created_at", "id"),
        Index(
            "ix_scheduling_jobs_workspace_status_due",
            "workspace_id",
            "status",
            "scheduled_for",
            "id",
        ),
        Index(
            "ix_scheduling_jobs_channel_history",
            "marketing_content_item_channel_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_scheduling_jobs_content", "workspace_id", "marketing_content_item_id"
        ),
        Index("ix_scheduling_jobs_approval", "approval_request_id"),
        Index("ix_scheduling_jobs_destination", "social_account_connection_id"),
    )


class SchedulingJobTransition(Base):
    """Append-only audit records, written with the job by the future command layer."""

    __tablename__ = "scheduling_job_transitions"
    id: Mapped[UUIDPrimaryKey]
    job_id: Mapped[UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    marketing_content_item_id: Mapped[UUID] = mapped_column(nullable=False)
    transition_version: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_id: Mapped[UUID] = mapped_column(nullable=False)
    operation: Mapped[str] = mapped_column(String(60), nullable=False)
    from_status: Mapped[SchedulingJobStatus | None] = mapped_column(
        Enum(SchedulingJobStatus, name="scheduling_job_status", create_constraint=True)
    )
    to_status: Mapped[SchedulingJobStatus] = mapped_column(
        Enum(SchedulingJobStatus, name="scheduling_job_status", create_constraint=True),
        nullable=False,
    )
    actor_kind: Mapped[str] = mapped_column(String(60), nullable=False)
    actor_key: Mapped[str] = mapped_column(String(255), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        SchedulingUTCDateTime(),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "workspace_id", "marketing_content_item_id"],
            [
                "scheduling_jobs.id",
                "scheduling_jobs.workspace_id",
                "scheduling_jobs.marketing_content_item_id",
            ],
            name="fk_scheduling_job_transitions_job_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "job_id", "transition_version", name="uq_scheduling_job_transitions_version"
        ),
        CheckConstraint("transition_version >= 1", name="version_positive"),
        CheckConstraint(
            "length(trim(operation)) > 0 AND length(trim(actor_kind)) > 0 "
            "AND length(trim(actor_key)) > 0",
            name="audit_identity",
        ),
        Index(
            "ix_scheduling_job_transitions_workspace",
            "workspace_id",
            "created_at",
            "id",
        ),
    )


register_scheduling_guards(SchedulingJob.__table__, SchedulingJobTransition.__table__)


class OAuthAuthorizationState(Base, TimestampMixin, OrganizationOwnedMixin):
    __tablename__ = "oauth_authorization_states"

    id: Mapped[UUIDPrimaryKey]
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    connection_method: Mapped[SocialAccountConnectionMethod] = mapped_column(
        Enum(
            SocialAccountConnectionMethod,
            name="social_account_connection_method",
            values_callable=lambda methods: [method.value for method in methods],
        ),
        nullable=False,
    )
    status: Mapped[OAuthAuthorizationStateStatus] = mapped_column(
        Enum(
            OAuthAuthorizationStateStatus,
            name="oauth_authorization_state_status",
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        nullable=False,
        default=OAuthAuthorizationStateStatus.pending,
        server_default=OAuthAuthorizationStateStatus.pending.value,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    safe_redirect_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    pkce_credential_ref: Mapped[str | None] = mapped_column(String(500))

    organization: Mapped[Organization] = relationship(
        back_populates="oauth_authorization_states"
    )
    actor_user: Mapped[User] = relationship(
        back_populates="oauth_authorization_states",
        foreign_keys=[actor_user_id],
    )

    @validates("state_hash")
    def _validate_state_hash(self, key: str, value: str | None) -> str:
        normalized = _required_text(value, key)
        if len(normalized) != 64 or not all(
            character in "0123456789abcdef" for character in normalized
        ):
            raise ValueError("state_hash must be a lowercase SHA-256 hex digest")
        return normalized

    @validates("provider")
    def _validate_provider(self, key: str, value: str | None) -> str:
        return _required_text(value, key).lower()

    @validates("safe_redirect_path")
    def _validate_safe_redirect_path(self, key: str, value: str | None) -> str:
        normalized = _required_text(value, key)
        parsed = urlparse(normalized)
        if (
            parsed.scheme
            or parsed.netloc
            or not normalized.startswith("/")
            or normalized.startswith("//")
            or "\\" in normalized
        ):
            raise ValueError("safe_redirect_path must be a relative application path")
        return normalized

    @validates("pkce_credential_ref")
    def _validate_pkce_credential_ref(
        self,
        _key: str,
        value: str | None,
    ) -> str | None:
        return _optional_text(value)

    __table_args__ = (
        UniqueConstraint("state_hash", name="uq_oauth_authorization_states_hash"),
        Index("ix_oauth_authorization_states_organization_id", "organization_id"),
        Index(
            "ix_oauth_authorization_states_org_provider_method",
            "organization_id",
            "provider",
            "connection_method",
        ),
        Index(
            "ix_oauth_authorization_states_actor_user_id",
            "actor_user_id",
        ),
        Index(
            "ix_oauth_authorization_states_status_expires_at",
            "status",
            "expires_at",
        ),
    )


class CampaignGoal(Base, TimestampMixin):
    __tablename__ = "campaign_goals"

    id: Mapped[UUIDPrimaryKey]
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(String(4000))
    target_value: Mapped[str | None] = mapped_column(String(500))
    success_criteria: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="active",
        server_default="active",
    )

    campaign: Mapped[Campaign] = relationship(back_populates="goals")

    @validates("title", "status")
    def _validate_required_text(self, key: str, value: str | None) -> str:
        return _required_text(value, key)

    @validates("description", "target_value", "success_criteria")
    def _validate_optional_text(self, _key: str, value: str | None) -> str | None:
        return _optional_text(value)

    __table_args__ = (
        Index("ix_campaign_goals_campaign_id", "campaign_id"),
        Index("ix_campaign_goals_campaign_id_status", "campaign_id", "status"),
    )


class CampaignMilestone(Base, TimestampMixin):
    __tablename__ = "campaign_milestones"

    id: Mapped[UUIDPrimaryKey]
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(String(4000))
    target_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="open",
        server_default="open",
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    campaign: Mapped[Campaign] = relationship(back_populates="milestones")
    created_by_user: Mapped[User | None] = relationship()

    @validates("title", "status")
    def _validate_required_text(self, key: str, value: str | None) -> str:
        return _required_text(value, key)

    @validates("description")
    def _validate_description(self, _key: str, value: str | None) -> str | None:
        return _optional_text(value)

    __table_args__ = (
        Index("ix_campaign_milestones_campaign_id", "campaign_id"),
        Index(
            "ix_campaign_milestones_campaign_id_status",
            "campaign_id",
            "status",
        ),
        Index(
            "ix_campaign_milestones_campaign_id_target_date",
            "campaign_id",
            "target_date",
        ),
        Index(
            "ix_campaign_milestones_created_by_user_id",
            "created_by_user_id",
        ),
    )


class Contract(Base, TimestampMixin, OrganizationOwnedMixin):
    __tablename__ = "contracts"

    id: Mapped[UUIDPrimaryKey]
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    artist_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artists.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization: Mapped[Organization] = relationship(back_populates="contracts")
    artist: Mapped[Artist | None] = relationship()

    __table_args__ = (
        Index("ix_contracts_organization_id", "organization_id"),
        Index("ix_contracts_organization_id_artist_id", "organization_id", "artist_id"),
    )


class Royalty(Base, TimestampMixin, OrganizationOwnedMixin):
    __tablename__ = "royalties"

    id: Mapped[UUIDPrimaryKey]
    release_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("releases.id", ondelete="SET NULL"),
        nullable=True,
    )
    period: Mapped[str] = mapped_column(String(40), nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="royalties")
    release: Mapped[Release | None] = relationship()

    __table_args__ = (
        Index("ix_royalties_organization_id", "organization_id"),
        Index(
            "ix_royalties_organization_id_release_id", "organization_id", "release_id"
        ),
    )


class AnalyticsEvent(Base, TimestampMixin, OrganizationOwnedMixin):
    __tablename__ = "analytics_events"

    id: Mapped[UUIDPrimaryKey]
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    organization: Mapped[Organization] = relationship(back_populates="analytics_events")

    __table_args__ = (Index("ix_analytics_events_organization_id", "organization_id"),)


class AnalyticsProvider(Base, TimestampMixin, OrganizationOwnedMixin):
    __tablename__ = "analytics_providers"

    id: Mapped[UUIDPrimaryKey]
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_type: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="internal",
        server_default="internal",
    )
    external_account_id: Mapped[str | None] = mapped_column(String(255))
    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    organization: Mapped[Organization] = relationship(
        back_populates="analytics_providers"
    )
    metric_definitions: Mapped[list["AnalyticsMetricDefinition"]] = relationship(
        back_populates="provider",
        cascade="all, delete-orphan",
    )
    observations: Mapped[list["AnalyticsObservation"]] = relationship(
        back_populates="provider",
    )

    @validates("key", "display_name", "provider_type")
    def _validate_required_text(self, key: str, value: str | None) -> str:
        return _required_text(value, key)

    @validates("external_account_id")
    def _validate_optional_text(self, _key: str, value: str | None) -> str | None:
        return _optional_text(value)

    @validates("metadata_json")
    def _validate_metadata(self, key: str, value: dict | None) -> dict:
        return _json_object(value, key)

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "key",
            name="uq_analytics_providers_organization_id_key",
        ),
        Index("ix_analytics_providers_organization_id", "organization_id"),
        Index(
            "ix_analytics_providers_organization_id_provider_type",
            "organization_id",
            "provider_type",
        ),
    )


class AnalyticsMetricDefinition(Base, TimestampMixin, OrganizationOwnedMixin):
    __tablename__ = "analytics_metric_definitions"

    id: Mapped[UUIDPrimaryKey]
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("analytics_providers.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    value_type: Mapped[AnalyticsMetricValueType] = mapped_column(
        Enum(AnalyticsMetricValueType, name="analytics_metric_value_type"),
        nullable=False,
        default=AnalyticsMetricValueType.decimal,
        server_default=AnalyticsMetricValueType.decimal.value,
    )
    default_unit: Mapped[str | None] = mapped_column(String(80))
    aggregation: Mapped[str | None] = mapped_column(String(80))
    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    organization: Mapped[Organization] = relationship(
        back_populates="analytics_metric_definitions"
    )
    provider: Mapped[AnalyticsProvider] = relationship(
        back_populates="metric_definitions"
    )
    observations: Mapped[list["AnalyticsObservation"]] = relationship(
        back_populates="metric_definition",
        cascade="all, delete-orphan",
    )

    @validates("key", "display_name")
    def _validate_required_text(self, key: str, value: str | None) -> str:
        return _required_text(value, key)

    @validates("description", "default_unit", "aggregation")
    def _validate_optional_text(self, _key: str, value: str | None) -> str | None:
        return _optional_text(value)

    @validates("metadata_json")
    def _validate_metadata(self, key: str, value: dict | None) -> dict:
        return _json_object(value, key)

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider_id",
            "key",
            name="uq_analytics_metric_definitions_workspace_provider_key",
        ),
        Index("ix_analytics_metric_definitions_organization_id", "organization_id"),
        Index("ix_analytics_metric_definitions_provider_id", "provider_id"),
        Index(
            "ix_analytics_metric_definitions_workspace_key",
            "organization_id",
            "key",
        ),
        Index(
            "ix_analytics_metric_definitions_workspace_value_type",
            "organization_id",
            "value_type",
        ),
    )


class AnalyticsObservation(Base, TimestampMixin, OrganizationOwnedMixin):
    __tablename__ = "analytics_observations"

    id: Mapped[UUIDPrimaryKey]
    metric_definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("analytics_metric_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("analytics_providers.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[UUID | None] = mapped_column(nullable=True)
    artist_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artist_profiles.id", ondelete="CASCADE"),
        nullable=True,
    )
    campaign_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=True,
    )
    campaign_object_type: Mapped[str | None] = mapped_column(String(120))
    campaign_object_id: Mapped[UUID | None] = mapped_column(nullable=True)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    value_text: Mapped[str | None] = mapped_column(String(1000))
    value_boolean: Mapped[bool | None] = mapped_column(Boolean)
    value_json: Mapped[dict | None] = mapped_column(JSON)
    unit: Mapped[str | None] = mapped_column(String(80))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_record_id: Mapped[str | None] = mapped_column(String(255))
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    idempotency_fingerprint: Mapped[str | None] = mapped_column(String(64))
    dimensions: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    organization: Mapped[Organization] = relationship(
        back_populates="analytics_observations"
    )
    metric_definition: Mapped[AnalyticsMetricDefinition] = relationship(
        back_populates="observations"
    )
    provider: Mapped[AnalyticsProvider] = relationship(back_populates="observations")
    artist_profile: Mapped[ArtistProfile | None] = relationship(
        back_populates="analytics_observations"
    )
    campaign: Mapped[Campaign | None] = relationship(
        back_populates="analytics_observations"
    )

    @validates("target_type")
    def _validate_target_type(self, key: str, value: str | None) -> str:
        return _required_text(value, key)

    @validates(
        "campaign_object_type",
        "value_text",
        "unit",
        "source_record_id",
        "idempotency_key",
    )
    def _validate_optional_text(self, _key: str, value: str | None) -> str | None:
        return _optional_text(value)

    @validates("dimensions", "metadata_json")
    def _validate_json_objects(self, key: str, value: dict | None) -> dict:
        return _json_object(value, key)

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider_id",
            "idempotency_key",
            name="uq_analytics_observations_workspace_provider_idempotency",
        ),
        Index("ix_analytics_observations_organization_id", "organization_id"),
        Index("ix_analytics_observations_metric_definition_id", "metric_definition_id"),
        Index("ix_analytics_observations_provider_id", "provider_id"),
        Index(
            "ix_analytics_observations_workspace_metric_observed",
            "organization_id",
            "metric_definition_id",
            "observed_at",
        ),
        Index(
            "ix_analytics_observations_workspace_target_observed",
            "organization_id",
            "target_type",
            "target_id",
            "observed_at",
        ),
        Index(
            "ix_analytics_observations_workspace_artist_observed",
            "organization_id",
            "artist_profile_id",
            "observed_at",
        ),
        Index(
            "ix_analytics_observations_workspace_campaign_observed",
            "organization_id",
            "campaign_id",
            "observed_at",
        ),
        Index(
            "ix_analytics_observations_workspace_campaign_object_observed",
            "organization_id",
            "campaign_object_type",
            "campaign_object_id",
            "observed_at",
        ),
        Index(
            "ix_analytics_observations_workspace_source_record",
            "organization_id",
            "provider_id",
            "source_record_id",
        ),
    )


class AIAgent(Base, TimestampMixin, OrganizationOwnedMixin):
    __tablename__ = "ai_agents"

    id: Mapped[UUIDPrimaryKey]
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="ai_agents")

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "name", name="uq_ai_agents_organization_id_name"
        ),
        Index("ix_ai_agents_organization_id", "organization_id"),
    )


class TeamSetting(Base, TimestampMixin, OrganizationOwnedMixin):
    __tablename__ = "team_settings"

    id: Mapped[UUIDPrimaryKey]
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    organization: Mapped[Organization] = relationship(back_populates="team_settings")

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "key", name="uq_team_settings_organization_id_key"
        ),
        Index("ix_team_settings_organization_id", "organization_id"),
    )


# Register delivery storage after its canonical scheduling/content dependencies.
from labelos_database.publishing_models import (  # noqa: F401
    Publication,
    PublicationAction,
    PublicationAttempt,
    PublicationLease,
    PublicationListMetadata,
    PublicationTransition,
)
