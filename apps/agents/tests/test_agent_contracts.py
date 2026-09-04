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
    MarketingApprovalAgentAction,
    MarketingApprovalAgentOperation,
    MarketingApprovalAgentProvenance,
)
from labelos_agents.tools.analytics import (
    AnalyticsObjectRef,
    AnalyticsObjectType,
    AnalyticsOperationName,
    AnalyticsOperationRequest,
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


def test_agent_analytics_tool_contract_is_structured_and_deterministic() -> None:
    request = AnalyticsOperationRequest(
        operation=AnalyticsOperationName.summarize_campaign_metrics,
        workspace_id="workspace_123",
        target=AnalyticsObjectRef(
            object_type=AnalyticsObjectType.campaign,
            object_id="campaign_123",
        ),
    )

    assert request.operation.value == "summarize_campaign_metrics"
    assert request.target is not None
    assert request.target.object_type == AnalyticsObjectType.campaign
    assert request.metric_selectors == []


def test_marketing_approval_agent_contract_allows_safe_revision_flow() -> None:
    operation = MarketingApprovalAgentOperation(
        action=MarketingApprovalAgentAction.RESUBMIT_FOR_APPROVAL,
        workspace_id="workspace_01",
        campaign_id="campaign_01",
        content_item_id="content_01",
        approval_request_id="approval_01",
        expected_resource_revision=2,
        draft={"copy_text": "Revised caption."},
        actor_key="agent:marketing:exec_01",
        provenance=MarketingApprovalAgentProvenance(
            agent_key="marketing",
            task_id="task_01",
            execution_id="exec_01",
        ),
    )

    assert operation.action == MarketingApprovalAgentAction.RESUBMIT_FOR_APPROVAL
    assert operation.actor_kind == "ai_agent"
    assert operation.provenance.execution_id == "exec_01"


def test_marketing_approval_agent_contract_denies_unsafe_boundary_requests() -> None:
    base = {
        "workspace_id": "workspace_01",
        "campaign_id": "campaign_01",
        "content_item_id": "content_01",
        "actor_key": "agent:marketing:exec_01",
        "provenance": MarketingApprovalAgentProvenance(agent_key="marketing"),
    }

    with pytest.raises(ValueError):
        MarketingApprovalAgentOperation(
            **base,
            action=MarketingApprovalAgentAction.SUBMIT_FOR_APPROVAL,
        )
    with pytest.raises(ValueError):
        MarketingApprovalAgentOperation(
            **base,
            action=MarketingApprovalAgentAction.UPDATE_DRAFT,
            requested_capabilities=["marketing.content.approve"],
        )
    with pytest.raises(ValueError):
        MarketingApprovalAgentOperation(
            **base,
            action=MarketingApprovalAgentAction.UPDATE_DRAFT,
            impersonated_user_id="user_01",
        )
    with pytest.raises(ValueError):
        MarketingApprovalAgentOperation(
            **base,
            action=MarketingApprovalAgentAction.UPDATE_DRAFT,
            draft={"scheduled_at": "2026-09-03T12:00:00Z"},
        )
