from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


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
