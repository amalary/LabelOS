from abc import ABC, abstractmethod

from labelos_agents.contracts import AgentIdentity, AgentResult, AgentTask


class BaseAgent(ABC):
    identity: AgentIdentity

    @abstractmethod
    async def execute(self, task: AgentTask) -> AgentResult:
        """Execute an agent task and return a structured result."""
