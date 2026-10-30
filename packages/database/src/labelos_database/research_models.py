"""Operational quota state only. Never store provider content in this table."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from labelos_database.base import Base, TimestampMixin, UUIDPrimaryKey


class YouTubeQuotaBucket(Base):
    __tablename__ = "youtube_quota_buckets"

    # Deliberately deployment-wide, across workspaces AND credential references.
    # A key rotation or a new workspace must not create a fresh quota allocation.
    bucket: Mapped[str] = mapped_column(String(16), primary_key=True)
    used: Mapped[int] = mapped_column(Integer, nullable=False)
    reset_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    next_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    __table_args__ = (
        CheckConstraint("bucket IN ('search', 'channels')", name="valid_bucket"),
        CheckConstraint("used >= 0", name="nonnegative_usage"),
    )


class ScoutingCandidate(TimestampMixin, Base):
    __tablename__ = "scouting_candidates"
    id: Mapped[UUIDPrimaryKey]
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(200), default="Untitled candidate")
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="new")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        CheckConstraint(
            "status IN ('new', 'reviewing', 'shortlisted', 'passed')",
            name="review_status",
        ),
    )


class ScoutingSource(Base):
    __tablename__ = "scouting_sources"
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    channel_id: Mapped[str] = mapped_column(String(24), primary_key=True)
    # A deferred FK lets an atomic unique source claim precede the human row.
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "scouting_candidates.id",
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    __table_args__ = (UniqueConstraint("candidate_id"),)
