"""Durable delivery intent, immutable starts and append-only observations."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from labelos_database.base import Base, UUIDPrimaryKey
from labelos_database.publishing_guards import register_publishing_guards
from labelos_database.publication_action_guards import register_action_guards
from labelos_database.publishing import (
    STATES,
    OPERATIONS,
    OUTCOMES,
    REASONS,
    SOURCES,
    PublicResourceURL,
    choices,
)
from labelos_database.scheduling import SchedulingUTCDateTime

JOB_SCOPE = (
    "id",
    "workspace_id",
    "marketing_content_item_id",
    "marketing_content_item_channel_id",
    "social_account_connection_id",
    "approval_request_id",
    "authorized_content_revision",
    "schedule_generation",
)
Index(
    "uq_scheduling_jobs_publication_scope",
    *(Base.metadata.tables["scheduling_jobs"].c[c] for c in JOB_SCOPE),
    unique=True,
)
Index(
    "uq_social_accounts_publication_provider",
    *(
        Base.metadata.tables["social_account_connections"].c[c]
        for c in ("id", "organization_id", "provider")
    ),
    unique=True,
)


class Publication(Base):
    __tablename__ = "publications"
    id: Mapped[UUIDPrimaryKey]
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    scheduling_job_id: Mapped[UUID]
    marketing_content_item_id: Mapped[UUID]
    marketing_content_item_channel_id: Mapped[UUID]
    social_account_connection_id: Mapped[UUID]
    approval_request_id: Mapped[UUID]
    authorized_content_revision: Mapped[int]
    schedule_generation: Mapped[int]
    provider: Mapped[str] = mapped_column(String(80))
    destination_identity: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending"
    )
    failure_category: Mapped[str | None] = mapped_column(String(40))
    retry_disposition: Mapped[str | None] = mapped_column(String(32))
    next_retry_at: Mapped[datetime | None] = mapped_column(SchedulingUTCDateTime())
    retry_deadline_at: Mapped[datetime | None] = mapped_column(SchedulingUTCDateTime())
    retry_policy_version: Mapped[int | None] = mapped_column(Integer)
    transition_version: Mapped[int] = mapped_column(default=0, server_default="0")
    receipt_id: Mapped[UUID]
    idempotency_key: Mapped[str] = mapped_column(String(160))
    payload_schema_version: Mapped[int]
    payload_fingerprint: Mapped[str] = mapped_column(String(64))
    canonical_envelope: Mapped[bytes] = mapped_column(LargeBinary)
    correlation_id: Mapped[UUID]
    external_post_id: Mapped[str | None] = mapped_column(String(512))
    provider_url: Mapped[str | None] = mapped_column(PublicResourceURL())
    published_at: Mapped[datetime | None] = mapped_column(SchedulingUTCDateTime())
    cancelled_at: Mapped[datetime | None] = mapped_column(SchedulingUTCDateTime())
    cancellation_reason: Mapped[str | None] = mapped_column(String(40))
    manual_action_at: Mapped[datetime | None] = mapped_column(SchedulingUTCDateTime())
    manual_action_reason: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(SchedulingUTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(SchedulingUTCDateTime())
    attempts: Mapped[list["PublicationAttempt"]] = relationship(
        viewonly=True, order_by="PublicationAttempt.number", lazy="raise"
    )
    transitions: Mapped[list["PublicationTransition"]] = relationship(
        viewonly=True, order_by="PublicationTransition.version", lazy="raise"
    )
    actions: Mapped[list["PublicationAction"]] = relationship(
        viewonly=True, order_by="PublicationAction.version", lazy="raise"
    )
    __table_args__ = (
        ForeignKeyConstraint(
            ["scheduling_job_id", *JOB_SCOPE[1:]],
            ["scheduling_jobs." + c for c in JOB_SCOPE],
            name="fk_publications_job_snapshot",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["social_account_connection_id", "workspace_id", "provider"],
            [
                "social_account_connections.id",
                "social_account_connections.organization_id",
                "social_account_connections.provider",
            ],
            name="fk_publications_provider_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "workspace_id", name="uq_publications_scope"),
        UniqueConstraint(
            "workspace_id", "scheduling_job_id", name="uq_publications_job"
        ),
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_publications_idempotency"
        ),
        UniqueConstraint("receipt_id", name="uq_publications_receipt"),
        UniqueConstraint(
            "workspace_id",
            "marketing_content_item_channel_id",
            "authorized_content_revision",
            "schedule_generation",
            name="uq_publications_intent",
        ),
        CheckConstraint(choices("status", STATES), name="status"),
        CheckConstraint(
            "transition_version >= 0 AND authorized_content_revision > 0 AND schedule_generation > 0 AND payload_schema_version = 1",
            name="versions",
        ),
        CheckConstraint(
            "length(payload_fingerprint) = 64 AND length(canonical_envelope) > 0 AND length(canonical_envelope) <= 25169920",
            name="envelope",
        ),
        CheckConstraint(
            "(status = 'published' AND published_at IS NOT NULL AND external_post_id IS NOT NULL AND length(trim(external_post_id)) > 0 AND length(external_post_id) <= 512) OR (status != 'published' AND published_at IS NULL AND external_post_id IS NULL AND provider_url IS NULL)",
            name="publication_evidence",
        ),
        CheckConstraint(
            "(status = 'cancelled' AND cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL AND cancellation_reason = 'scheduling_cancelled') OR (status != 'cancelled' AND cancelled_at IS NULL AND cancellation_reason IS NULL)",
            name="cancellation",
        ),
        CheckConstraint(
            "(status = 'manual_action_required' AND manual_action_at IS NOT NULL AND manual_action_reason IS NOT NULL AND manual_action_reason = 'outcome_unknown') OR (status != 'manual_action_required' AND manual_action_at IS NULL AND manual_action_reason IS NULL)",
            name="manual_action",
        ),
        CheckConstraint(
            "updated_at >= created_at AND (published_at IS NULL OR published_at >= created_at) AND (cancelled_at IS NULL OR cancelled_at >= created_at) AND (manual_action_at IS NULL OR manual_action_at >= created_at)",
            name="chronology",
        ),
        CheckConstraint(
            "provider_url IS NULL OR (provider_url LIKE 'https://%' AND provider_url NOT LIKE '%?%' AND provider_url NOT LIKE '%#%' AND provider_url NOT LIKE '%@%')",
            name="public_url",
        ),
        Index(
            "ix_publications_workspace_status",
            "workspace_id",
            "status",
            "created_at",
            "id",
        ),
        Index("ix_publications_retry_due", "workspace_id", "next_retry_at", "id"),
        Index("ix_publications_content", "workspace_id", "marketing_content_item_id"),
        Index("ix_publications_destination", "social_account_connection_id"),
        Index(
            "uq_publications_provider_resource",
            "workspace_id",
            "social_account_connection_id",
            "external_post_id",
            unique=True,
            postgresql_where=external_post_id.is_not(None),
            sqlite_where=external_post_id.is_not(None),
        ),
    )


class PublicationAction(Base):
    """Append-only human resolution, separate from authoritative provider facts."""

    __tablename__ = "publication_actions"
    id: Mapped[UUIDPrimaryKey]
    workspace_id: Mapped[UUID]
    publication_id: Mapped[UUID]
    version: Mapped[int]
    publication_version: Mapped[int]
    operation_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reason_code: Mapped[str] = mapped_column(String(40))
    occurred_at: Mapped[datetime] = mapped_column(SchedulingUTCDateTime())
    retry_until: Mapped[datetime | None] = mapped_column(SchedulingUTCDateTime())
    external_post_id: Mapped[str | None] = mapped_column(String(512))
    provider_url: Mapped[str | None] = mapped_column(PublicResourceURL())
    __table_args__ = (
        ForeignKeyConstraint(
            ["publication_id", "workspace_id"],
            ["publications.id", "publications.workspace_id"],
            name="fk_publication_actions_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "publication_id", "version", name="uq_publication_actions_version"
        ),
        UniqueConstraint(
            "workspace_id", "operation_id", name="uq_publication_actions_operation"
        ),
        CheckConstraint("version > 0 AND publication_version > 0", name="versions"),
        CheckConstraint(
            "operation IN ('begin_manual', 'complete_manual', 'authorize_retry')",
            name="operation",
        ),
        CheckConstraint(
            "(operation = 'authorize_retry' AND retry_until IS NOT NULL AND retry_until > occurred_at) OR (operation != 'authorize_retry' AND retry_until IS NULL)",
            name="retry_until",
        ),
        CheckConstraint(
            "operation = 'complete_manual' OR (external_post_id IS NULL AND provider_url IS NULL)",
            name="evidence",
        ),
        CheckConstraint(
            "external_post_id IS NULL OR (length(trim(external_post_id)) > 0 AND length(external_post_id) <= 512)",
            name="external_id",
        ),
        CheckConstraint(
            "provider_url IS NULL OR (provider_url LIKE 'https://%' AND provider_url NOT LIKE '%?%' AND provider_url NOT LIKE '%#%' AND provider_url NOT LIKE '%@%')",
            name="public_url",
        ),
        Index(
            "ix_publication_actions_workspace",
            "workspace_id",
            "publication_id",
            "version",
        ),
    )


class PublicationLease(Base):
    """Execution ownership, separate from the immutable publication journal."""

    __tablename__ = "publication_leases"
    publication_id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID]
    fencing_token: Mapped[int] = mapped_column(default=0, server_default="0")
    owner_id: Mapped[UUID | None]
    expires_at: Mapped[datetime | None] = mapped_column(SchedulingUTCDateTime())
    interrupted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    __table_args__ = (
        ForeignKeyConstraint(
            ["publication_id", "workspace_id"],
            ["publications.id", "publications.workspace_id"],
            name="fk_publication_leases_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint("fencing_token >= 0", name="fence"),
        CheckConstraint(
            "(owner_id IS NULL AND expires_at IS NULL) OR "
            "(owner_id IS NOT NULL AND expires_at IS NOT NULL AND fencing_token > 0)",
            name="ownership",
        ),
        Index("ix_publication_leases_expiry", "workspace_id", "expires_at"),
    )


class PublicationAttempt(Base):
    __tablename__ = "publication_attempts"
    id: Mapped[UUIDPrimaryKey]
    workspace_id: Mapped[UUID]
    publication_id: Mapped[UUID]
    number: Mapped[int]
    started_at: Mapped[datetime] = mapped_column(SchedulingUTCDateTime())
    execution_id: Mapped[UUID]
    observations: Mapped[list["PublicationTransition"]] = relationship(
        viewonly=True, order_by="PublicationTransition.version", lazy="raise"
    )

    @property
    def latest_observation(self):
        return next(
            (entry for entry in reversed(self.observations) if entry.outcome), None
        )

    @property
    def completed_at(self):
        # The first execution observation completes execution; later reconciliation
        # appends evidence without changing this timestamp or the immutable start.
        return next(
            (entry.observed_at for entry in self.observations if entry.outcome), None
        )

    @property
    def outcome(self):
        entry = self.latest_observation
        return entry.outcome if entry else None

    @property
    def failure_reason(self):
        entry = self.latest_observation
        return entry.failure_reason if entry else None

    @property
    def retry_eligible(self):
        entry = self.latest_observation
        return bool(
            entry and entry.retry_disposition in ("automatic", "provider_delay")
        )

    __table_args__ = (
        ForeignKeyConstraint(
            ["publication_id", "workspace_id"],
            ["publications.id", "publications.workspace_id"],
            ondelete="RESTRICT",
            name="fk_publication_attempts_scope",
        ),
        UniqueConstraint(
            "id", "publication_id", "workspace_id", name="uq_publication_attempts_scope"
        ),
        UniqueConstraint(
            "workspace_id",
            "publication_id",
            "number",
            name="uq_publication_attempts_number",
        ),
        UniqueConstraint(
            "workspace_id", "execution_id", name="uq_publication_attempts_execution"
        ),
        CheckConstraint("number > 0", name="number"),
    )


class PublicationTransition(Base):
    __tablename__ = "publication_transitions"
    id: Mapped[UUIDPrimaryKey]
    workspace_id: Mapped[UUID]
    publication_id: Mapped[UUID]
    version: Mapped[int]
    operation_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[str] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(SchedulingUTCDateTime())
    attempt_id: Mapped[UUID | None]
    observed_at: Mapped[datetime | None] = mapped_column(SchedulingUTCDateTime())
    outcome: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str | None] = mapped_column(String(32))
    failure_reason: Mapped[str | None] = mapped_column(String(40))
    external_post_id: Mapped[str | None] = mapped_column(String(512))
    failure_category: Mapped[str | None] = mapped_column(String(40))
    retry_disposition: Mapped[str | None] = mapped_column(String(32))
    next_retry_at: Mapped[datetime | None] = mapped_column(SchedulingUTCDateTime())
    retry_deadline_at: Mapped[datetime | None] = mapped_column(SchedulingUTCDateTime())
    retry_policy_version: Mapped[int | None] = mapped_column(Integer)
    retry_after_seconds: Mapped[int | None] = mapped_column(Integer)
    # No free-form provider metadata. This bounded integer is the only response diagnostic.
    http_status: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (
        Index(
            "uq_publication_transitions_attempt_start",
            "attempt_id",
            unique=True,
            postgresql_where=operation.in_(("start", "retry")),
            sqlite_where=operation.in_(("start", "retry")),
        ),
        ForeignKeyConstraint(
            ["publication_id", "workspace_id"],
            ["publications.id", "publications.workspace_id"],
            name="fk_publication_transitions_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["attempt_id", "publication_id", "workspace_id"],
            [
                "publication_attempts.id",
                "publication_attempts.publication_id",
                "publication_attempts.workspace_id",
            ],
            name="fk_publication_transitions_attempt",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workspace_id",
            "publication_id",
            "version",
            name="uq_publication_transitions_version",
        ),
        UniqueConstraint(
            "workspace_id", "operation_id", name="uq_publication_transitions_operation"
        ),
        CheckConstraint("version > 0", name="version"),
        CheckConstraint(choices("operation", OPERATIONS), name="operation"),
        CheckConstraint(choices("from_status", STATES), name="from_status"),
        CheckConstraint(choices("to_status", STATES), name="to_status"),
        CheckConstraint(choices("outcome", OUTCOMES), name="outcome"),
        CheckConstraint(choices("source", SOURCES), name="source"),
        CheckConstraint(choices("failure_reason", REASONS), name="reason"),
        CheckConstraint(
            "http_status IS NULL OR (http_status >= 100 AND http_status <= 599 AND outcome IS NOT NULL)",
            name="http_status",
        ),
        CheckConstraint(
            "(operation IN ('start', 'retry') AND attempt_id IS NOT NULL AND outcome IS NULL AND observed_at IS NULL AND source IS NULL AND failure_reason IS NULL AND external_post_id IS NULL) OR (operation = 'cancel' AND attempt_id IS NULL AND outcome IS NULL AND observed_at IS NULL AND source IS NULL AND failure_reason IS NULL AND external_post_id IS NULL) OR (operation NOT IN ('start', 'retry', 'cancel') AND attempt_id IS NOT NULL AND outcome IS NOT NULL AND observed_at IS NOT NULL AND source IS NOT NULL)",
            name="shape",
        ),
        CheckConstraint(
            "outcome IS NULL OR (outcome = 'published' AND external_post_id IS NOT NULL AND length(trim(external_post_id)) > 0 AND length(external_post_id) <= 512 AND failure_reason IS NULL) OR (outcome != 'published' AND external_post_id IS NULL AND failure_reason IS NOT NULL AND ((outcome = 'unknown' AND failure_reason = 'outcome_unknown') OR (outcome != 'unknown' AND failure_reason != 'outcome_unknown')))",
            name="evidence",
        ),
        CheckConstraint(
            "source != 'execution_interrupted' OR outcome = 'unknown'",
            name="interruption",
        ),
        CheckConstraint(
            "observed_at IS NULL OR observed_at <= occurred_at", name="chronology"
        ),
        CheckConstraint(
            "(operation = 'start' AND from_status = 'pending' AND to_status = 'processing') OR (operation = 'retry' AND from_status = 'retryable_failure' AND to_status = 'retrying') OR (operation = 'cancel' AND from_status IN ('pending', 'retryable_failure') AND to_status = 'cancelled') OR (from_status IN ('processing', 'retrying', 'manual_action_required') AND (from_status != 'manual_action_required' OR source = 'reconciliation') AND ((operation = 'confirm_success' AND outcome = 'published' AND to_status = 'published') OR (operation = 'fail_retryable' AND outcome = 'retryable_failure' AND to_status = 'retryable_failure') OR (operation = 'fail_permanently' AND outcome = 'permanent_failure' AND to_status = 'permanent_failure') OR (operation = 'require_manual_action' AND outcome = 'unknown' AND to_status = 'manual_action_required' AND from_status != 'manual_action_required')))",
            name="edge",
        ),
        Index(
            "ix_publication_transitions_attempt",
            "workspace_id",
            "publication_id",
            "attempt_id",
            "version",
        ),
    )


for _table in (
    Base.metadata.tables["publications"],
    Base.metadata.tables["publication_transitions"],
):
    for _name, _sql in (
        (
            "retry_category",
            "failure_category IS NULL OR failure_category IN ('transient_network', 'provider_unavailable', 'rate_limited', 'authentication', 'authorization', 'invalid_content_media', 'unsupported_operation', 'ambiguous_outcome', 'permanent_rejection', 'internal_failure')",
        ),
        (
            "retry_disposition",
            "retry_disposition IS NULL OR retry_disposition IN ('automatic', 'provider_delay', 'blocked_reconnection', 'reconciliation_required', 'permanent', 'manual_action', 'exhausted')",
        ),
        ("retry_policy", "retry_policy_version IS NULL OR retry_policy_version = 1"),
        (
            "retry_schedule",
            "(next_retry_at IS NULL AND (retry_disposition IS NULL OR retry_disposition NOT IN ('automatic', 'provider_delay'))) OR (next_retry_at IS NOT NULL AND retry_disposition IS NOT NULL AND retry_disposition IN ('automatic', 'provider_delay') AND retry_deadline_at IS NOT NULL AND next_retry_at < retry_deadline_at AND failure_category IS NOT NULL AND failure_category IN ('transient_network', 'provider_unavailable', 'rate_limited') AND retry_policy_version IS NOT NULL AND retry_policy_version = 1)",
        ),
    ):
        _table.append_constraint(CheckConstraint(_sql, name=_name))
Base.metadata.tables["publications"].append_constraint(
    CheckConstraint(
        "next_retry_at IS NULL OR (status = 'retryable_failure' AND next_retry_at >= updated_at)",
        name="retry_state",
    )
)
Base.metadata.tables["publication_transitions"].append_constraint(
    CheckConstraint(
        "retry_after_seconds IS NULL OR (retry_after_seconds >= 0 AND retry_after_seconds <= 604800 AND outcome = 'retryable_failure')",
        name="retry_hint",
    )
)

register_publishing_guards(
    Publication.__table__, PublicationAttempt.__table__, PublicationTransition.__table__
)
register_action_guards(PublicationAction.__table__)
