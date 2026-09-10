import asyncio
import json
import logging

import pytest

from labelos_api.config import Settings
from labelos_api.logging import JsonFormatter
from labelos_api.services.credential_store import (
    CredentialNotFoundError,
    CredentialPayload,
    CredentialStoreUnavailableError,
    GcpSecretManagerCredentialStore,
    InMemoryCredentialStore,
    InvalidCredentialReferenceError,
    build_credential_store,
)

SECRET_VALUES = {
    "access_token": "access-token-secret",
    "refresh_token": "refresh-token-secret",
    "token_type": "Bearer",
    "provider_secret": {"client_secret": "client-secret-value"},
}


def test_in_memory_credential_store_writes_reads_replaces_and_deletes() -> None:
    async def run() -> dict[str, object]:
        store = InMemoryCredentialStore()
        credential_ref = await store.put(CredentialPayload(SECRET_VALUES))
        first = await store.get(credential_ref)
        returned_ref = await store.replace(
            credential_ref,
            CredentialPayload({"access_token": "replacement-token"}),
        )
        second = await store.get(credential_ref)
        await store.delete(credential_ref)
        missing_after_delete = False
        try:
            await store.get(credential_ref)
        except CredentialNotFoundError:
            missing_after_delete = True
        return {
            "credential_ref": credential_ref,
            "first": first.expose(),
            "returned_ref": returned_ref,
            "second": second.expose(),
            "missing_after_delete": missing_after_delete,
        }

    result = asyncio.run(run())

    assert str(result["credential_ref"]).startswith("memory://credentials/")
    assert result["first"] == SECRET_VALUES
    assert result["returned_ref"] == result["credential_ref"]
    assert result["second"] == {"access_token": "replacement-token"}
    assert result["missing_after_delete"] is True


def test_in_memory_credential_store_reports_missing_secret_safely() -> None:
    async def run() -> str:
        store = InMemoryCredentialStore()
        try:
            await store.get("memory://credentials/missing-access-token-secret")
        except CredentialNotFoundError as exc:
            return str(exc)
        raise AssertionError("expected CredentialNotFoundError")

    message = asyncio.run(run())

    assert message == "Credential material was not found"
    assert "missing-access-token-secret" not in message
    assert "access-token-secret" not in message


@pytest.mark.parametrize("operation", ["put", "get", "replace", "delete"])
def test_in_memory_credential_store_backend_failure_messages_are_safe(
    operation: str,
) -> None:
    async def run() -> str:
        store = InMemoryCredentialStore()
        credential_ref = await store.put(CredentialPayload({"access_token": "stored"}))
        store.fail_operations.add(operation)
        try:
            if operation == "put":
                await store.put(CredentialPayload(SECRET_VALUES))
            elif operation == "get":
                await store.get(credential_ref)
            elif operation == "replace":
                await store.replace(credential_ref, CredentialPayload(SECRET_VALUES))
            else:
                await store.delete(credential_ref)
        except CredentialStoreUnavailableError as exc:
            return str(exc)
        raise AssertionError("expected CredentialStoreUnavailableError")

    message = asyncio.run(run())

    assert message == f"Credential store {operation} failed"
    assert "access-token-secret" not in message
    assert "refresh-token-secret" not in message


def test_credential_payload_is_not_json_serialized_or_represented_with_secrets() -> (
    None
):
    payload = CredentialPayload(SECRET_VALUES)

    assert repr(payload) == "CredentialPayload([REDACTED])"
    assert str(payload) == "CredentialPayload([REDACTED])"
    with pytest.raises(TypeError):
        json.dumps(payload)


def test_credential_payload_is_redacted_by_json_formatter_logs() -> None:
    formatter = JsonFormatter(
        service_name="labelos-api",
        service_version="test",
        environment="test",
    )
    record = logging.makeLogRecord(
        {
            "name": "labelos_api.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "stored credential",
            "args": (),
            "credential_payload": CredentialPayload(SECRET_VALUES),
            "provider_metadata": {"safe": "ok"},
        }
    )

    formatted = formatter.format(record)
    parsed = json.loads(formatted)

    assert "access-token-secret" not in formatted
    assert "refresh-token-secret" not in formatted
    assert parsed["credential_payload"] == "[REDACTED]"
    assert parsed["provider_metadata"] == {"safe": "ok"}


@pytest.mark.parametrize("environment", ["local", "development", "dev", "test"])
def test_build_credential_store_allows_memory_for_local_and_tests(
    environment: str,
) -> None:
    assert isinstance(
        build_credential_store(Settings(environment=environment)),
        InMemoryCredentialStore,
    )


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_production_like_startup_rejects_in_memory_credential_store(
    environment: str,
) -> None:
    settings = Settings(
        environment=environment,
        workos_client_id="client_prod",
        workos_webhook_secret="whsec_prod",
        credential_store_backend="memory",
    )

    with pytest.raises(RuntimeError, match="CREDENTIAL_STORE_BACKEND=memory"):
        settings.validate_startup_environment()


def test_production_like_credential_store_builder_rejects_in_memory_backend() -> None:
    settings = Settings(
        environment="production",
        credential_store_backend="memory",
    )

    with pytest.raises(RuntimeError, match="CREDENTIAL_STORE_BACKEND=memory"):
        build_credential_store(settings)


def test_production_startup_rejects_memory_backend_for_non_workos_auth() -> None:
    settings = Settings(
        environment="production",
        auth_provider="local",
        credential_store_backend="memory",
    )

    with pytest.raises(RuntimeError, match="CREDENTIAL_STORE_BACKEND=memory"):
        settings.validate_startup_environment()


def test_production_startup_accepts_gcp_secret_manager_backend() -> None:
    settings = Settings(
        environment="production",
        workos_client_id="client_prod",
        workos_webhook_secret="whsec_prod",
        credential_store_backend="gcp-secret-manager",
        credential_store_gcp_project_id="labelos-prod",
    )

    settings.validate_startup_environment()


def test_production_startup_rejects_unknown_credential_backend() -> None:
    settings = Settings(
        environment="production",
        workos_client_id="client_prod",
        workos_webhook_secret="whsec_prod",
        credential_store_backend="memory-fallback",
        credential_store_gcp_project_id="labelos-prod",
    )

    with pytest.raises(RuntimeError, match="must be gcp-secret-manager"):
        settings.validate_startup_environment()


def test_production_startup_requires_gcp_project_for_secret_manager() -> None:
    settings = Settings(
        environment="production",
        workos_client_id="client_prod",
        workos_webhook_secret="whsec_prod",
        credential_store_backend="gcp-secret-manager",
    )

    with pytest.raises(RuntimeError, match="GCP_PROJECT_ID"):
        settings.validate_startup_environment()


class FakeSecretManagerClient:
    def __init__(self) -> None:
        self.secrets: dict[str, list[bytes]] = {}
        self.created_secret_ids: list[str] = []
        self.fail_next: str | None = None

    def create_secret(self, *, request: dict) -> None:
        self._fail_if_requested("create_secret")
        name = f"{request['parent']}/secrets/{request['secret_id']}"
        self.created_secret_ids.append(request["secret_id"])
        self.secrets[name] = []

    def add_secret_version(self, *, request: dict) -> None:
        self._fail_if_requested("add_secret_version")
        if request["parent"] not in self.secrets:
            raise FakeNotFound()
        self.secrets[request["parent"]].append(request["payload"]["data"])

    def access_secret_version(self, *, request: dict):
        self._fail_if_requested("access_secret_version")
        secret_name = request["name"].removesuffix("/versions/latest")
        if secret_name not in self.secrets:
            raise FakeNotFound()
        return FakeAccessResponse(self.secrets[secret_name][-1])

    def delete_secret(self, *, request: dict) -> None:
        self._fail_if_requested("delete_secret")
        if request["name"] not in self.secrets:
            raise FakeNotFound()
        del self.secrets[request["name"]]

    def _fail_if_requested(self, operation: str) -> None:
        if self.fail_next == operation:
            self.fail_next = None
            raise RuntimeError("provider included access-token-secret in raw error")


class FakeNotFound(Exception):
    pass


class FakeAccessResponse:
    def __init__(self, data: bytes) -> None:
        self.payload = FakePayload(data)


class FakePayload:
    def __init__(self, data: bytes) -> None:
        self.data = data


def test_gcp_secret_manager_store_uses_opaque_names_and_versions() -> None:
    async def run() -> dict[str, object]:
        client = FakeSecretManagerClient()
        store = GcpSecretManagerCredentialStore(
            project_id="labelos-prod",
            secret_prefix="labelos credential",
            client=client,
        )
        credential_ref = await store.put(CredentialPayload(SECRET_VALUES))
        original = await store.get(credential_ref)
        returned_ref = await store.replace(
            credential_ref,
            CredentialPayload({"access_token": "rotated-token"}),
        )
        rotated = await store.get(credential_ref)
        await store.delete(credential_ref)
        return {
            "credential_ref": credential_ref,
            "secret_id": client.created_secret_ids[0],
            "original": original.expose(),
            "returned_ref": returned_ref,
            "rotated": rotated.expose(),
            "deleted": client.secrets == {},
        }

    result = asyncio.run(run())

    assert str(result["credential_ref"]).startswith(
        "gcp-secret-manager://projects/labelos-prod/secrets/labelos-credential-"
    )
    assert "instagram" not in str(result["credential_ref"])
    assert "user" not in str(result["credential_ref"])
    assert str(result["secret_id"]).startswith("labelos-credential-")
    assert result["original"] == SECRET_VALUES
    assert result["returned_ref"] == result["credential_ref"]
    assert result["rotated"] == {"access_token": "rotated-token"}
    assert result["deleted"] is True


def test_gcp_secret_manager_store_validates_refs_before_backend_calls() -> None:
    async def run() -> str:
        store = GcpSecretManagerCredentialStore(
            project_id="labelos-prod",
            client=FakeSecretManagerClient(),
        )
        try:
            await store.get(
                "gcp-secret-manager://projects/other/secrets/access-token-secret"
            )
        except InvalidCredentialReferenceError as exc:
            return str(exc)
        raise AssertionError("expected InvalidCredentialReferenceError")

    message = asyncio.run(run())

    assert message == "Credential reference is invalid"
    assert "access-token-secret" not in message


def test_gcp_secret_manager_store_backend_failure_messages_are_safe() -> None:
    async def run() -> str:
        client = FakeSecretManagerClient()
        client.fail_next = "create_secret"
        store = GcpSecretManagerCredentialStore(
            project_id="labelos-prod",
            client=client,
        )
        try:
            await store.put(CredentialPayload(SECRET_VALUES))
        except CredentialStoreUnavailableError as exc:
            return str(exc)
        raise AssertionError("expected CredentialStoreUnavailableError")

    message = asyncio.run(run())

    assert message == "Credential store put failed"
    assert "access-token-secret" not in message
