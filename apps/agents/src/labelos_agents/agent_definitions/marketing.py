from labelos_agents.agent_definitions.base import BaseAgent
from labelos_agents.agent_definitions.common import build_mock_result
from labelos_agents.contracts import AgentIdentity, AgentResult, AgentTask


class MarketingAgent(BaseAgent):
    identity = AgentIdentity(
        key="marketing",
        name="Marketing Agent",
        description="Mocks campaign channel and message recommendations.",
    )

    async def execute(self, task: AgentTask) -> AgentResult:
        audience = str(task.input.get("audience", "core fans"))
        return build_mock_result(
            task=task,
            agent=self.identity,
            summary=f"Mock marketing campaign outline prepared for {audience}.",
            output={
                "channels": ["owned social", "email", "short-form video"],
                "message": f"Placeholder campaign message for {audience}.",
                "next_step": "Route campaign copy through marketing approval.",
            },
            confidence_value=0.4,
            evidence_label="Mock marketing fixture",
        )
