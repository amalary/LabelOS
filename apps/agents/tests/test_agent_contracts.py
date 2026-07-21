import pytest

from labelos_agents.agent_definitions.base import BaseAgent
from labelos_agents.agent_definitions.scouting import ScoutingAgent
from labelos_agents.contracts import (
    AgentIdentity,
    AgentStatus,
    AgentTask,
    ConfidenceScore,
    EvidenceSource,
    HumanApprovalRequirement,
)


def test_base_agent_is_abstract() -> None:
    with pytest.raises(TypeError):
        BaseAgent()


def test_agent_identity_requires_lowercase_key_without_spaces() -> None:
    with pytest.raises(ValueError):
        AgentIdentity(
            key="Bad Key",
            name="Bad Agent",
            description="Invalid identity fixture.",
        )


def test_contract_types_validate_expected_fields() -> None:
    identity = ScoutingAgent.identity
    task = AgentTask(objective="Find emerging pop artists.")
    confidence = ConfidenceScore(value=0.5, rationale="Mock rationale.")
    evidence = EvidenceSource(source_type="mock", label="Fixture")
    approval = HumanApprovalRequirement(required=True, reason="Review required.")

    assert identity.key == "scouting"
    assert task.objective == "Find emerging pop artists."
    assert confidence.value == 0.5
    assert evidence.source_type == "mock"
    assert approval.required is True
    assert AgentStatus.NEEDS_HUMAN_APPROVAL.value == "needs_human_approval"


def test_confidence_score_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError):
        ConfidenceScore(value=1.5, rationale="Invalid.")
