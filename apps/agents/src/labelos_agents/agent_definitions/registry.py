from labelos_agents.agent_definitions.base import BaseAgent
from labelos_agents.agent_definitions.marketing import MarketingAgent
from labelos_agents.agent_definitions.release_planning import ReleasePlanningAgent
from labelos_agents.agent_definitions.scouting import ScoutingAgent


def build_agent_registry() -> dict[str, BaseAgent]:
    agents: list[BaseAgent] = [
        ScoutingAgent(),
        ReleasePlanningAgent(),
        MarketingAgent(),
    ]
    return {agent.identity.key: agent for agent in agents}
