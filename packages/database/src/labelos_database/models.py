from enum import StrEnum
from uuid import UUID

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from labelos_database.base import Base, TimestampMixin, UUIDPrimaryKey


class MembershipRole(StrEnum):
    owner = "owner"
    admin = "admin"
    member = "member"
    viewer = "viewer"


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

    __table_args__ = (
        UniqueConstraint("workos_user_id", name="uq_users_workos_user_id"),
        Index("ix_users_workos_user_id", "workos_user_id"),
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
    ai_agents: Mapped[list["AIAgent"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    team_settings: Mapped[list["TeamSetting"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
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
    status: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="active",
        server_default="active",
    )

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")

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

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "name", name="uq_artists_organization_id_name"
        ),
        Index("ix_artists_organization_id", "organization_id"),
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

    __table_args__ = (
        Index("ix_releases_organization_id", "organization_id"),
        Index("ix_releases_organization_id_artist_id", "organization_id", "artist_id"),
    )


class Campaign(Base, TimestampMixin, OrganizationOwnedMixin):
    __tablename__ = "campaigns"

    id: Mapped[UUIDPrimaryKey]
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    release_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("releases.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization: Mapped[Organization] = relationship(back_populates="campaigns")
    release: Mapped[Release | None] = relationship()

    __table_args__ = (
        Index("ix_campaigns_organization_id", "organization_id"),
        Index(
            "ix_campaigns_organization_id_release_id", "organization_id", "release_id"
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
