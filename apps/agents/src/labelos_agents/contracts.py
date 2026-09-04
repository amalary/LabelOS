from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class AgentStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_HUMAN_APPROVAL = "needs_human_approval"


class HumanApprovalRequirement(BaseModel):
    required: bool = True
    reason: str = "Human review is required before production use."


class ConfidenceScore(BaseModel):
    value: float = Field(ge=0.0, le=1.0)
    rationale: str


class EvidenceSource(BaseModel):
    source_type: str
    label: str
    uri: str | None = None
    excerpt: str | None = None


class MarketingApprovalAgentAction(StrEnum):
    CREATE_DRAFT = "create_draft"
    UPDATE_DRAFT = "update_draft"
    SUBMIT_FOR_APPROVAL = "submit_for_approval"
    READ_APPROVAL_OUTCOME = "read_approval_outcome"
    READ_REQUESTED_CHANGE_FEEDBACK = "read_requested_change_feedback"
    REVISE_DRAFT = "revise_draft"
    RESUBMIT_FOR_APPROVAL = "resubmit_for_approval"


class MarketingApprovalAgentProvenance(BaseModel):
    agent_key: str
    task_id: str | None = None
    execution_id: str | None = None
    run_id: str | None = None


class MarketingApprovalAgentOperation(BaseModel):
    action: MarketingApprovalAgentAction
    workspace_id: str
    campaign_id: str
    content_item_id: str | None = None
    approval_request_id: str | None = None
    expected_resource_revision: int | None = Field(default=None, ge=1)
    draft: dict[str, Any] = Field(default_factory=dict)
    requested_capabilities: list[str] = Field(default_factory=list)
    actor_kind: str = "ai_agent"
    actor_key: str
    impersonated_user_id: str | None = None
    provenance: MarketingApprovalAgentProvenance

    @field_validator("actor_kind")
    @classmethod
    def require_agent_actor(cls, value: str) -> str:
        if value != "ai_agent":
            raise ValueError(
                "Marketing approval operations must use an ai_agent actor."
            )
        return value

    @field_validator("requested_capabilities")
    @classmethod
    def deny_capability_grants(cls, value: list[str]) -> list[str]:
        if value:
            raise ValueError(
                "Agents cannot request or grant capabilities in this boundary."
            )
        return value

    @field_validator("impersonated_user_id")
    @classmethod
    def deny_impersonation(cls, value: str | None) -> str | None:
        if value is not None:
            raise ValueError("Agents cannot impersonate a human.")
        return value

    @model_validator(mode="after")
    def validate_boundary(self) -> "MarketingApprovalAgentOperation":
        if (
            self.action
            in {
                MarketingApprovalAgentAction.UPDATE_DRAFT,
                MarketingApprovalAgentAction.SUBMIT_FOR_APPROVAL,
                MarketingApprovalAgentAction.REVISE_DRAFT,
                MarketingApprovalAgentAction.RESUBMIT_FOR_APPROVAL,
            }
            and self.content_item_id is None
        ):
            raise ValueError("content_item_id is required for this operation.")
        if (
            self.action
            in {
                MarketingApprovalAgentAction.READ_APPROVAL_OUTCOME,
                MarketingApprovalAgentAction.READ_REQUESTED_CHANGE_FEEDBACK,
                MarketingApprovalAgentAction.RESUBMIT_FOR_APPROVAL,
            }
            and self.approval_request_id is None
        ):
            raise ValueError("approval_request_id is required for this operation.")
        if (
            self.action
            in {
                MarketingApprovalAgentAction.SUBMIT_FOR_APPROVAL,
                MarketingApprovalAgentAction.RESUBMIT_FOR_APPROVAL,
            }
            and self.expected_resource_revision is None
        ):
            raise ValueError("expected_resource_revision is required for submission.")
        if "scheduled_at" in self.draft or "published_at" in self.draft:
            raise ValueError("Agents cannot schedule or publish marketing content.")
        return self


class AgentIdentity(BaseModel):
    key: str
    name: str
    description: str
    version: str = "0.0.0"

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        if not value:
            raise ValueError("Agent key is required.")
        if value.lower() != value or " " in value:
            raise ValueError("Agent key must be lowercase and contain no spaces.")
        return value


class AgentTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    agent_key: str | None = None
    objective: str
    input: dict[str, Any] = Field(default_factory=dict)
    requires_human_approval: HumanApprovalRequirement = Field(
        default_factory=HumanApprovalRequirement,
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentResult(BaseModel):
    task_id: str
    agent: AgentIdentity
    status: AgentStatus
    summary: str
    output: dict[str, Any] = Field(default_factory=dict)
    confidence: ConfidenceScore
    evidence: list[EvidenceSource] = Field(default_factory=list)
    human_approval: HumanApprovalRequirement = Field(
        default_factory=HumanApprovalRequirement,
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
