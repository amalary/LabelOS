"""Entrypoint tests with real RSA verification and a stubbed Google key endpoint."""

import asyncio
import json
import time
from functools import partial
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import ValidationError

from labelos_api import scheduling_worker as host
from labelos_api.config import Settings, get_settings
from labelos_api.scheduling import worker_auth
from labelos_api.services.scheduling_processor import (
    SchedulingBatchResult,
    SchedulingExecutionRefused,
)
from test_scheduling_handoff_postgres import inbox
from test_scheduling_handoff_postgres import sessions as handoff_sessions
from test_scheduling_processor_postgres import RecordingReceiver, ready
from test_scheduling_repository import sessions as repository_sessions  # noqa: F401

sessions = handoff_sessions

AUDIENCE = "https://scheduling-worker-test.run.app"
SUBJECT = "123456789012345678901"
EMAIL = "scheduling-invoker@test-project.iam.gserviceaccount.com"
ASYNC_CLIENT = httpx.AsyncClient


@pytest.fixture
def worker_settings():
    return Settings(
        environment="production",
        scheduling_worker_oidc_audience=AUDIENCE,
        scheduling_worker_service_account_email=EMAIL,
        scheduling_worker_service_account_subject=SUBJECT,
        scheduling_worker_workspace_id=uuid4(),
    )


@pytest.fixture
def tokens(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="test-key", alg="RS256", use="sig")

    def google(request):
        assert str(request.url) == worker_auth.GOOGLE_JWKS_URL
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"keys": [jwk]})

    monkeypatch.setattr(
        worker_auth.httpx,
        "AsyncClient",
        partial(ASYNC_CLIENT, transport=httpx.MockTransport(google)),
    )

    def token(*, omit=None, signing_key=None, headers=None, **overrides):
        claims = dict(
            iss="https://accounts.google.com",
            aud=AUDIENCE,
            sub=SUBJECT,
            email=EMAIL,
            email_verified=True,
            iat=int(time.time()) - 1,
            exp=int(time.time()) + 3600,
        )
        claims.update(overrides)
        if omit:
            claims.pop(omit)
        return jwt.encode(
            claims,
            signing_key or key,
            algorithm="RS256",
            headers=headers or {"kid": "test-key"},
        )

    return token


@pytest.fixture
def worker_client(monkeypatch, worker_settings):
    monkeypatch.setattr(host, "get_settings", lambda: worker_settings)
    return TestClient(host.create_worker_app())


def test_defaults_and_environment_parsing(monkeypatch):
    defaults = Settings()
    assert defaults.scheduling_execution_enabled is False
    assert defaults.scheduling_worker_batch_size == 25
    assert defaults.scheduling_worker_lease_seconds == 120
    assert defaults.scheduling_worker_lateness_seconds == 300
    assert defaults.scheduling_worker_timeout_seconds == 30
    monkeypatch.setenv("SCHEDULING_EXECUTION_ENABLED", "false")
    monkeypatch.setenv("SCHEDULING_WORKER_BATCH_SIZE", "7")
    monkeypatch.setenv("SCHEDULING_WORKER_LEASE_SECONDS", "90")
    monkeypatch.setenv("SCHEDULING_WORKER_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("SCHEDULING_WORKER_LATENESS_SECONDS", "75")
    settings = get_settings()
    assert not settings.scheduling_execution_enabled
    assert settings.scheduling_worker_batch_size == 7
    assert settings.scheduling_worker_lease_seconds == 90
    assert settings.scheduling_worker_timeout_seconds == 10
    assert settings.scheduling_worker_lateness_seconds == 75


@pytest.mark.parametrize(
    "field,value",
    [
        ("scheduling_worker_batch_size", 0),
        ("scheduling_worker_batch_size", 1001),
        ("scheduling_worker_lease_seconds", 0),
        ("scheduling_worker_lease_seconds", 3601),
        ("scheduling_worker_lateness_seconds", -1),
        ("scheduling_worker_lateness_seconds", 86401),
        ("scheduling_worker_timeout_seconds", 0),
        ("scheduling_worker_timeout_seconds", 301),
        ("scheduling_worker_auth_mode", "none"),
        ("scheduling_worker_auth_mode", "shared-secret"),
        ("scheduling_execution_enabled", "perhaps"),
    ],
)
def test_invalid_configuration(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


@pytest.mark.parametrize(
    "overrides",
    [
        {"scheduling_worker_auth_mode": "local-cli"},
        {"scheduling_worker_service_account_email": "user@example.com"},
        {"scheduling_worker_service_account_email": None},
        {"scheduling_worker_service_account_subject": None},
        {"scheduling_worker_service_account_subject": "user-id"},
        {"scheduling_worker_workspace_id": None},
        {"scheduling_worker_oidc_audience": None},
        {"scheduling_worker_oidc_audience": "http://worker.run.app"},
        {"scheduling_worker_oidc_audience": AUDIENCE + "/internal/scheduling/run-due"},
        {"scheduling_worker_oidc_audience": AUDIENCE + "?aud=spoof"},
        {"scheduling_worker_lease_seconds": 30},
        {"delivery_receiver_backend": "fake"},
        {"delivery_receiver_backend": "memory"},
        {"database_echo": True},
        {"database_url": "sqlite+aiosqlite://"},
    ],
)
def test_worker_startup_fails_closed(worker_settings, overrides):
    with pytest.raises(RuntimeError):
        worker_auth.validate_worker_settings(
            Settings(**(worker_settings.model_dump() | overrides))
        )


def test_worker_does_not_need_human_secrets(worker_settings):
    worker_auth.validate_worker_settings(worker_settings)
    assert worker_settings.workos_client_id is None
    assert worker_settings.workos_webhook_secret is None


@pytest.mark.parametrize("cloud_variable", ["K_SERVICE", "CLOUD_RUN_JOB"])
def test_cloud_rejects_local_environment(monkeypatch, worker_settings, cloud_variable):
    monkeypatch.setenv(cloud_variable, "worker")
    worker_settings.environment = "local"
    with pytest.raises(RuntimeError):
        worker_auth.validate_worker_settings(worker_settings)
    worker_settings.scheduling_worker_auth_mode = "local-cli"
    with pytest.raises(RuntimeError):
        worker_auth.validate_worker_settings(worker_settings, local_cli=True)


def test_local_cli_requires_explicit_mode_and_loopback_db(worker_settings):
    worker_settings.scheduling_worker_auth_mode = "local-cli"
    with pytest.raises(RuntimeError):
        worker_auth.validate_worker_settings(worker_settings, local_cli=True)
    worker_settings.environment = "local"
    worker_auth.validate_worker_settings(worker_settings, local_cli=True)
    worker_settings.database_url = "postgresql+asyncpg://user@remote-db:5432/db"
    with pytest.raises(RuntimeError):
        worker_auth.validate_worker_settings(worker_settings, local_cli=True)
    worker_settings.database_url = "postgresql+asyncpg://localhost/db?host=remote-db"
    with pytest.raises(RuntimeError):
        worker_auth.validate_worker_settings(worker_settings, local_cli=True)


def test_local_cli_is_explicit_and_disabled_by_default(
    monkeypatch, worker_settings, capsys
):
    worker_settings.environment = "local"
    worker_settings.scheduling_worker_auth_mode = "local-cli"
    monkeypatch.setattr(host, "get_settings", lambda: worker_settings)
    with pytest.raises(SystemExit):
        host.main([])
    assert host.main(["--execute"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "execution_disabled"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic secret"},
        {"Authorization": "Bearer broken"},
        {"X-Serverless-Authorization": "Bearer unsigned.platform.token"},
        {"X-Worker-Identity": EMAIL, "X-CloudScheduler": "true"},
    ],
)
def test_no_anonymous_or_header_trust(worker_client, headers):
    response = worker_client.post(
        host.WORKER_PATH, headers=headers, json={"actor": None}
    )
    assert response.status_code == 401
    assert "worker_id" not in response.json()
    assert response.headers["x-request-id"]


@pytest.mark.parametrize(
    "overrides,status",
    [
        ({"iss": "https://api.workos.com"}, 401),
        ({"iss": "https://accounts.google.com.attacker.test"}, 401),
        ({"aud": "https://another.run.app"}, 401),
        ({"aud": [AUDIENCE, "https://another.run.app"]}, 401),
        ({"exp": 1}, 401),
        ({"iat": 9999999999}, 401),
        ({"sub": "999999999999999999999"}, 403),
        ({"email": "owner@example.com"}, 403),
        ({"email_verified": False}, 403),
        ({"email_verified": "true"}, 403),
    ],
)
def test_token_claims(worker_client, tokens, overrides, status):
    response = worker_client.post(
        host.WORKER_PATH, headers={"Authorization": f"Bearer {tokens(**overrides)}"}
    )
    assert response.status_code == status
    assert "worker_id" not in response.json()


@pytest.mark.parametrize(
    "claim", ["iss", "aud", "sub", "exp", "iat", "email", "email_verified"]
)
def test_required_token_claims(worker_client, tokens, claim):
    assert (
        worker_client.post(
            host.WORKER_PATH, headers={"Authorization": f"Bearer {tokens(omit=claim)}"}
        ).status_code
        == 401
    )


def test_signature_and_key_id(worker_client, tokens):
    foreign_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for token in [tokens(signing_key=foreign_key), tokens(headers={"kid": "unknown"})]:
        assert (
            worker_client.post(
                host.WORKER_PATH, headers={"Authorization": f"Bearer {token}"}
            ).status_code
            == 401
        )


@pytest.mark.parametrize(
    "algorithm,key", [("none", None), ("HS256", "test-secret" * 4)]
)
def test_unsigned_and_symmetric_tokens_denied(worker_client, algorithm, key):
    token = jwt.encode(
        {"sub": SUBJECT, "email": EMAIL},
        key,
        algorithm=algorithm,
        headers={"kid": "test-key"},
    )
    assert (
        worker_client.post(
            host.WORKER_PATH, headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 401
    )


def test_authentication_timeout_is_bounded(worker_client, tokens, monkeypatch):
    cancelled = []

    async def stalled(_):
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.append(True)

    monkeypatch.setattr(worker_auth, "_google_signing_key", stalled)
    monkeypatch.setattr(worker_auth, "AUTH_TIMEOUT_SECONDS", 0.01)
    response = worker_client.post(
        host.WORKER_PATH, headers={"Authorization": f"Bearer {tokens()}"}
    )
    assert response.status_code == 503
    assert cancelled == [True]


def test_auth_key_service_failure(worker_client, tokens, monkeypatch):
    async def unavailable(_):
        raise httpx.ConnectError("sensitive internals")

    monkeypatch.setattr(worker_auth, "_google_signing_key", unavailable)
    response = worker_client.post(
        host.WORKER_PATH, headers={"Authorization": f"Bearer {tokens()}"}
    )
    assert response.status_code == 503
    assert "sensitive" not in response.text


def test_disabled_authenticated_call_no_database(worker_client, tokens, monkeypatch):
    def no_db(_):
        pytest.fail("Disabled invocation accessed DB")

    monkeypatch.setattr(host, "get_sessionmaker", no_db)
    response = worker_client.post(
        host.WORKER_PATH,
        headers={"Authorization": f"Bearer {tokens()}"},
        json={"actor": None, "workspace_id": str(uuid4()), "execution_enabled": True},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "execution_disabled"
    assert response.json()["correlation_id"] == response.headers["x-request-id"]
    assert response.json()["worker_id"].startswith("scheduling:")


def test_receiver_unavailable_does_not_claim(
    worker_client, worker_settings, tokens, monkeypatch
):
    worker_settings.scheduling_execution_enabled = True
    monkeypatch.setattr(host, "get_sessionmaker", lambda _: pytest.fail("DB accessed"))
    response = worker_client.post(
        host.WORKER_PATH, headers={"Authorization": f"Bearer {tokens()}"}
    )
    assert response.status_code == 503
    assert response.json()["status"] == "receiver_unavailable"


@pytest.fixture
def stub_processor(monkeypatch, worker_settings):
    worker_settings.scheduling_execution_enabled = True
    monkeypatch.setattr(host, "configured_receiver", lambda _: object())
    monkeypatch.setattr(host, "get_sessionmaker", lambda _: object())
    return host.SchedulingDueJobProcessor


def test_scope_limits_and_safe_response(
    worker_client, worker_settings, tokens, stub_processor, monkeypatch
):
    async def run(processor, workspace):
        assert workspace == worker_settings.scheduling_worker_workspace_id
        assert processor.worker.workspace_ids == frozenset({workspace})
        assert processor.batch_size == worker_settings.scheduling_worker_batch_size
        assert processor.window == worker_settings.scheduling_worker_lateness_seconds
        assert (
            processor.lease_duration.total_seconds()
            == worker_settings.scheduling_worker_lease_seconds
        )
        return SchedulingBatchResult(
            2, 1, {"handed_off": 1, "secret-provider-error": 1}
        )

    monkeypatch.setattr(stub_processor, "run", run)
    response = worker_client.post(
        host.WORKER_PATH,
        headers={"Authorization": f"Bearer {tokens()}"},
        json={"workspace_id": str(uuid4()), "batch_size": 999999},
    )
    assert response.status_code == 200
    assert response.json()["outcomes"] == {"handed_off": 1, "job_failed": 1}
    assert set(response.json()) == {
        "status",
        "claimed",
        "recovered",
        "outcomes",
        "correlation_id",
        "worker_id",
    }
    assert "secret-provider" not in response.text


def test_timeout_cancels_work(
    worker_client, worker_settings, tokens, stub_processor, monkeypatch
):
    worker_settings.scheduling_worker_timeout_seconds = 1
    cancelled = []

    async def run(*_):
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.append(True)

    monkeypatch.setattr(stub_processor, "run", run)
    response = worker_client.post(
        host.WORKER_PATH, headers={"Authorization": f"Bearer {tokens()}"}
    )
    assert response.status_code == 504
    assert response.json()["status"] == "timed_out"
    assert "claimed" not in response.json()  # Commit outcomes may be ambiguous.
    assert cancelled == [True]


@pytest.mark.parametrize(
    "error,status,code",
    [
        (RuntimeError("secret SQL payload"), "failed", 503),
        (SchedulingExecutionRefused("private details"), "execution_refused", 200),
    ],
)
def test_safe_failures(
    worker_client, tokens, stub_processor, monkeypatch, error, status, code
):
    async def run(*_):
        raise error

    monkeypatch.setattr(stub_processor, "run", run)
    response = worker_client.post(
        host.WORKER_PATH, headers={"Authorization": f"Bearer {tokens()}"}
    )
    assert response.status_code == code
    assert response.json()["status"] == status
    assert str(error) not in response.text


def test_none_is_not_authentication(worker_settings):
    with pytest.raises(TypeError):
        asyncio.run(host.run_sweep(worker_settings, None, str(uuid4())))


def test_entrypoint_not_in_user_app(client, worker_client):
    assert client.post(host.WORKER_PATH).status_code == 404
    assert worker_client.get("/api/v1/authorization/context").status_code == 404
    assert worker_client.get("/docs").status_code == 404
    assert worker_client.get("/openapi.json").status_code == 404
    assert worker_client.get(host.WORKER_PATH).status_code == 405
    assert worker_client.get("/health").json() == {"status": "ok"}


def test_duplicate_http_invocations_are_harmless(
    sessions, worker_settings, tokens, monkeypatch
):
    from labelos_database.models import SchedulingJob
    from sqlalchemy import func, select

    async def run():
        workspace, jobs = await ready(sessions, count=5)
        worker_settings.scheduling_worker_workspace_id = workspace
        worker_settings.scheduling_worker_batch_size = 3
        worker_settings.scheduling_execution_enabled = True
        receiver = RecordingReceiver()
        monkeypatch.setattr(host, "get_settings", lambda: worker_settings)
        monkeypatch.setattr(host, "get_sessionmaker", lambda _: sessions)
        monkeypatch.setattr(host, "configured_receiver", lambda _: receiver)
        app = host.create_worker_app()
        headers = {"Authorization": f"Bearer {tokens()}", "x-request-id": str(uuid4())}
        async with ASYNC_CLIENT(
            transport=httpx.ASGITransport(app=app), base_url=AUDIENCE
        ) as client:
            responses = await asyncio.gather(
                *(client.post(host.WORKER_PATH, headers=headers) for _ in range(2))
            )
            replay = await client.post(host.WORKER_PATH, headers=headers)
        assert all(response.status_code == 200 for response in responses)
        assert sum(response.json()["claimed"] for response in responses) == 5
        assert all(response.json()["claimed"] <= 3 for response in responses)
        assert responses[0].json()["worker_id"] != responses[1].json()["worker_id"]
        assert replay.json()["claimed"] == 0
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(inbox)) == 5
            saved = (await session.scalars(select(SchedulingJob))).all()
            assert len(saved) == len(jobs)
            assert all(job.status == "handed_off" for job in saved)

    asyncio.run(run())


def test_http_timeout_rolls_back_acceptance_and_retry_recovers(
    sessions, worker_settings, tokens, monkeypatch
):
    from labelos_database.models import SchedulingJob
    from sqlalchemy import func, select

    from test_scheduling_repository import expire

    class SlowReceiver(RecordingReceiver):
        async def accept(self, session, request):
            result = await super().accept(session, request)
            await asyncio.sleep(60)
            return result

    async def run():
        workspace, jobs = await ready(sessions)
        worker_settings.scheduling_worker_workspace_id = workspace
        worker_settings.scheduling_execution_enabled = True
        worker_settings.scheduling_worker_timeout_seconds = 1
        monkeypatch.setattr(host, "get_settings", lambda: worker_settings)
        monkeypatch.setattr(host, "get_sessionmaker", lambda _: sessions)
        monkeypatch.setattr(host, "configured_receiver", lambda _: SlowReceiver())
        app = host.create_worker_app()
        headers = {"Authorization": f"Bearer {tokens()}"}
        async with ASYNC_CLIENT(
            transport=httpx.ASGITransport(app=app), base_url=AUDIENCE
        ) as client:
            response = await client.post(host.WORKER_PATH, headers=headers)
            assert response.status_code == 504
            async with sessions.begin() as session:
                assert (
                    await session.scalar(select(func.count()).select_from(inbox)) == 0
                )
                job = await session.get(SchedulingJob, jobs[0].id)
                assert job.status == "claimed"
                await expire(session, job.id)
            worker_settings.scheduling_worker_timeout_seconds = 30
            monkeypatch.setattr(
                host, "configured_receiver", lambda _: RecordingReceiver()
            )
            replay = await client.post(host.WORKER_PATH, headers=headers)
            assert replay.status_code == 200
            assert replay.json()["outcomes"] == {"handed_off": 1}
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(inbox)) == 1

    asyncio.run(run())
