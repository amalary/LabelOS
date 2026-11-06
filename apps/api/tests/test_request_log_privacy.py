from types import SimpleNamespace

import pytest
from starlette.requests import Request

from labelos_api.logging import _request_log_fields


@pytest.mark.parametrize("matched", [True, False])
def test_invitation_token_and_query_do_not_enter_request_logs(matched):
    scope = {
        "type": "http",
        "method": "GET",
        "scheme": "http",
        "server": ("localhost", 4000),
        "path": "/api/v1/organizations/invites/PRIVATE_INVITATION_TOKEN/accept",
        "query_string": b"code=PRIVATE_CALLBACK_CODE",
        "headers": [],
    }
    if matched:
        scope["route"] = SimpleNamespace(
            path="/api/v1/organizations/invites/{token}/accept"
        )
    fields = _request_log_fields(Request(scope), 404, 1)
    assert "PRIVATE_" not in str(fields)
    assert fields["route"].endswith("/invites/{token}/accept")
    assert fields["http_status"] == 404


def test_exception_logs_also_redact_invitation_paths(caplog):
    import logging

    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from labelos_api.exceptions import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/invites/{token}")
    def missing(token: str):
        raise HTTPException(404, "Not found")

    with (
        caplog.at_level(logging.INFO, logger="labelos_api.exceptions"),
        TestClient(app) as client,
    ):
        assert client.get("/invites/PRIVATE_INVITATION_TOKEN").status_code == 404
    records = [
        record for record in caplog.records if record.name == "labelos_api.exceptions"
    ]
    assert records
    assert all("PRIVATE_" not in str(record.__dict__) for record in records)
