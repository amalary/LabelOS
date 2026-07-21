from labelos_agents.agent_definitions.base import BaseAgent
from labelos_agents.agent_definitions.common import build_mock_result
from labelos_agents.contracts import AgentIdentity, AgentResult, AgentTask


class ReleasePlanningAgent(BaseAgent):
    identity = AgentIdentity(
        key="release-planning",
        name="Release Planning Agent",
        description="Mocks release milestone planning recommendations.",
    )

    async def execute(self, task: AgentTask) -> AgentResult:
        release_name = str(task.input.get("release_name", "Untitled Release"))
        return build_mock_result(
            task=task,
            agent=self.identity,
            summary=f"Mock release plan generated for {release_name}.",
            output={
                "milestones": [
                    {"week": -8, "activity": "Finalize creative assets"},
                    {"week": -6, "activity": "Confirm distribution metadata"},
                    {"week": -2, "activity": "Prepare launch approvals"},
                ],
                "next_step": "Validate dates with the release manager.",
            },
            confidence_value=0.45,
            evidence_label="Mock release planning fixture",
        )
