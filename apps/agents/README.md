# Label OS Agent Service

This service contains the execution foundation for Label OS agents. It is a
non-production scaffold: placeholder agents return deterministic mock results,
and no external AI APIs are called.

## Setup

```sh
cd apps/agents
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
```

## Commands

Run tests:

```sh
python -m pytest
```

Run the health command:

```sh
python scripts/health.py health
```

Run the service locally:

```sh
uvicorn labelos_agents.main:app --reload --host 0.0.0.0 --port 4100
```

Health endpoints:

- `/health`
- `/api/v1/status`

## Configuration

Configuration is read from environment variables:

```sh
APP_ENV=local
AGENTS_HOST=0.0.0.0
AGENTS_PORT=4100
AGENTS_LOG_LEVEL=INFO
AGENTS_MODEL_PROVIDER=mock
AGENTS_MODEL_NAME=mock-deterministic
AGENTS_MODEL_TIMEOUT_SECONDS=30
AGENTS_REQUIRE_HUMAN_APPROVAL=true
```

Future provider credentials should be supplied through environment variables
such as `AGENTS_OPENAI_API_KEY`, `AGENTS_ANTHROPIC_API_KEY`, or
`AGENTS_GOOGLE_API_KEY`. Do not commit real API keys.

## Structure

```text
src/labelos_agents/
  agent_definitions/  Agent interfaces, registry, and concrete agents.
  tools/              Future callable tools exposed to agents.
  workflows/          Future multi-step orchestration.
  memory/             Future durable and ephemeral agent memory.
  evaluation/         Future quality, safety, and regression checks.
  providers/          Future model provider integrations.
  routes/             HTTP endpoints.
```

## Shared Contracts

The core contracts live in `labelos_agents.contracts`:

- `AgentIdentity`
- `AgentStatus`
- `AgentTask`
- `AgentResult`
- `ConfidenceScore`
- `EvidenceSource`
- `HumanApprovalRequirement`

## Creating A New Agent

1. Add a module under `src/labelos_agents/agent_definitions/`.
2. Subclass `BaseAgent`.
3. Define a stable `AgentIdentity` with a unique `key`.
4. Implement `execute(self, task: AgentTask) -> AgentResult`.
5. Keep implementation deterministic in tests.
6. Register the agent in `agent_definitions/registry.py`.
7. Add tests for the contract, deterministic output, confidence, evidence, and
   human approval behavior.

Production agents must keep secrets in environment variables and route model
calls through `providers/` rather than calling external APIs directly from agent
definitions.
