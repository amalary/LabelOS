from labelos_agents.agent_definitions.base import BaseAgent
from labelos_agents.agent_definitions.common import build_mock_result
from labelos_agents.contracts import AgentIdentity, AgentResult, AgentTask


class ScoutingAgent(BaseAgent):
    identity = AgentIdentity(
        key="scouting",
        name="Scouting Agent",
        description="Mocks artist discovery and scouting recommendations.",
    )

    async def execute(self, task: AgentTask) -> AgentResult:
        genre = str(task.input.get("genre", "unknown"))
        region = str(task.input.get("region", "global"))
        return build_mock_result(
            task=task,
            agent=self.identity,
            summary=f"Mock scouting shortlist prepared for {genre} in {region}.",
            output={
                "shortlist": [
                    {
                        "artist_name": "Northstar Demo",
                        "fit_reason": f"Placeholder {genre} momentum in {region}.",
                        "priority": "medium",
                    },
                ],
                "next_step": "Ask an A&R lead to review the mock shortlist.",
            },
            confidence_value=0.42,
            evidence_label="Mock scouting fixture",
        )
