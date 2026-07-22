from enum import StrEnum
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, String, UniqueConstraint
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
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
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
        UniqueConstraint("provider", "subject", name="uq_auth_identities_provider_subject"),
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
        unique=True,
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

    __table_args__ = (Index("ix_organizations_owner_user_id", "owner_user_id"),)


class OrganizationMembership(Base, TimestampMixin):
    __tablename__ = "organization_memberships"

    id: Mapped[UUIDPrimaryKey]
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

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_organization_memberships_organization_id_user_id",
        ),
        Index("ix_organization_memberships_organization_id", "organization_id"),
        Index("ix_organization_memberships_user_id", "user_id"),
    )
