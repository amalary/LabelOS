"""Schema/client drift checks also run without a PostgreSQL service."""

import runpy
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.openapi import utils as openapi_utils
from fastapi.testclient import TestClient

from labelos_api.api.v1.scheduling import router, scheduling_controls
from labelos_api.auth import get_current_user_context, get_session
from labelos_api.exceptions import register_exception_handlers
from labelos_api.scheduling.contracts import SchedulingFeatureControls


@pytest.mark.parametrize("expanded_validation_schema", [False, True])
def test_generated_scheduling_client_matches_public_openapi(
    monkeypatch, expanded_validation_schema
):
    if expanded_validation_schema:
        # New FastAPI versions describe raw input/context in their default 422.
        # Scheduling strips these at runtime and must own its public contract.
        definition = deepcopy(openapi_utils.validation_error_definition)
        definition["properties"].update(
            input={"title": "Input"},
            ctx={"title": "Context", "type": "object"},
        )
        monkeypatch.setattr(openapi_utils, "validation_error_definition", definition)
    root = Path(__file__).resolve().parents[3]
    generator = runpy.run_path(str(root / "scripts/generate-scheduling-client.py"))
    assert (
        generator["OUTPUT"].read_text(encoding="utf-8")
        == generator["generated_source"]()
    )


def test_scheduling_validation_schema_matches_redacted_response():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    register_exception_handlers(app)

    async def session_override():
        yield AsyncMock()

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user_context] = lambda: object()
    app.dependency_overrides[scheduling_controls] = SchedulingFeatureControls
    schema = app.openapi()
    for methods in schema["paths"].values():
        for operation in methods.values():
            assert operation["responses"]["422"]["content"]["application/json"][
                "schema"
            ] == {"$ref": "#/components/schemas/SchedulingValidationErrorResponse"}
    error_schema = schema["components"]["schemas"]["SchedulingValidationError"]
    assert set(error_schema["properties"]) == {"type", "loc", "msg"}
    assert set(error_schema["required"]) == {"type", "loc", "msg"}
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/workspaces/{uuid4()}/scheduling/jobs",
            params={"limit": "PRIVATE_INVALID_INPUT"},
        )
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert errors
    assert all(set(error) == {"type", "loc", "msg"} for error in errors)
    assert "PRIVATE_INVALID_INPUT" not in response.text
