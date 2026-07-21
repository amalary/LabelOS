from labelos_agents.contracts import (
    AgentIdentity,
    AgentResult,
    AgentStatus,
    AgentTask,
    ConfidenceScore,
    EvidenceSource,
    HumanApprovalRequirement,
)


def build_mock_result(
    *,
    task: AgentTask,
    agent: AgentIdentity,
    summary: str,
    output: dict,
    confidence_value: float,
    evidence_label: str,
) -> AgentResult:
    return AgentResult(
        task_id=task.task_id,
        agent=agent,
        status=AgentStatus.NEEDS_HUMAN_APPROVAL,
        summary=summary,
        output=output,
        confidence=ConfidenceScore(
            value=confidence_value,
            rationale="Deterministic mock output for service scaffolding.",
        ),
        evidence=[
            EvidenceSource(
                source_type="mock",
                label=evidence_label,
                excerpt="Generated from static placeholder rules.",
            ),
        ],
        human_approval=HumanApprovalRequirement(
            required=True,
            reason="Placeholder agent output requires human approval.",
        ),
    )
