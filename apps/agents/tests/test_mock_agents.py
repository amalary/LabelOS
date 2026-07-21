import asyncio

import pytest

from labelos_agents.agent_definitions.marketing import MarketingAgent
from labelos_agents.agent_definitions.registry import build_agent_registry
from labelos_agents.agent_definitions.release_planning import ReleasePlanningAgent
from labelos_agents.agent_definitions.scouting import ScoutingAgent
from labelos_agents.contracts import AgentStatus, AgentTask


@pytest.mark.parametrize(
    ("agent", "task", "expected_key", "expected_summary"),
    [
        (
            ScoutingAgent(),
            AgentTask(
                objective="Scout artists.",
                input={"genre": "indie pop", "region": "Los Angeles"},
            ),
            "scouting",
            "Mock scouting shortlist prepared for indie pop in Los Angeles.",
        ),
        (
            ReleasePlanningAgent(),
            AgentTask(
                objective="Plan release.",
                input={"release_name": "Friday Single"},
            ),
            "release-planning",
            "Mock release plan generated for Friday Single.",
        ),
        (
            MarketingAgent(),
            AgentTask(
                objective="Plan campaign.",
                input={"audience": "playlist editors"},
            ),
            "marketing",
            "Mock marketing campaign outline prepared for playlist editors.",
        ),
    ],
)
def test_placeholder_agents_return_deterministic_results(
    agent,
    task: AgentTask,
    expected_key: str,
    expected_summary: str,
) -> None:
    first_result = asyncio.run(agent.execute(task))
    second_result = asyncio.run(agent.execute(task))

    assert first_result.agent.key == expected_key
    assert first_result.status == AgentStatus.NEEDS_HUMAN_APPROVAL
    assert first_result.summary == expected_summary
    assert first_result.output == second_result.output
    assert first_result.confidence == second_result.confidence
    assert first_result.evidence == second_result.evidence
    assert first_result.human_approval.required is True


def test_registry_exposes_all_placeholder_agents() -> None:
    registry = build_agent_registry()

    assert set(registry) == {"scouting", "release-planning", "marketing"}
