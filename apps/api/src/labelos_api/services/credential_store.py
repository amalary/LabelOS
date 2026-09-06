import json
import re
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol, Self
from uuid import uuid4

from labelos_api.config import Settings

CredentialData = Mapping[str, Any]

_GCP_REF_PREFIX = "gcp-secret-manager://"
_SECRET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,255}$")
_SAFE_SECRET_PREFIX_PATTERN = re.compile(r"[^A-Za-z0-9_-]+")


class CredentialStoreError(RuntimeError):
    """Base class for credential-store failures with safe public messages."""


class CredentialNotFoundError(CredentialStoreError):
    def __init__(self) -> None:
        super().__init__("Credential material was not found")


class CredentialStoreUnavailableError(CredentialStoreError):
    def __init__(self, operation: str) -> None:
        super().__init__(f"Credential store {operation} failed")


class InvalidCredentialReferenceError(CredentialStoreError):
    def __init__(self) -> None:
        super().__init__("Credential reference is invalid")


class CredentialPayload:
    """Credential material wrapper that does not expose values through repr/json."""

    def __init__(self, values: CredentialData) -> None:
        if not isinstance(values, Mapping):
            raise TypeError("Credential payload must be a mapping")
        self._values = dict(values)

    @classmethod
    def from_json_bytes(cls, data: bytes) -> Self:
        decoded = json.loads(data.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise InvalidCredentialReferenceError()
        return cls(decoded)

    def expose(self) -> dict[str, Any]:
        return dict(self._values)

    def to_json_bytes(self) -> bytes:
        return json.dumps(
            self._values,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def __repr__(self) -> str:
        return "CredentialPayload([REDACTED])"

    __str__ = __repr__


class CredentialStore(Protocol):
    async def put(self, payload: CredentialPayload) -> str:
        """Store credential material and return an opaque reference."""
        ...

    async def get(self, credential_ref: str) -> CredentialPayload:
        """Fetch credential material for an opaque reference."""
        ...

    async def replace(
        self,
        credential_ref: str,
        payload: CredentialPayload,
    ) -> str:
        """Replace credential material and return the reference to keep in SQL."""
        ...

    async def delete(self, credential_ref: str) -> None:
        """Delete credential material after provider-side disconnect is complete."""
        ...


class InMemoryCredentialStore:
    def __init__(self) -> None:
        self._credentials: MutableMapping[str, bytes] = {}
        self.fail_operations: set[str] = set()

    async def put(self, payload: CredentialPayload) -> str:
        self._fail_if_requested("put")
        credential_ref = f"memory://credentials/{uuid4().hex}"
        self._credentials[credential_ref] = payload.to_json_bytes()
        return credential_ref

    async def get(self, credential_ref: str) -> CredentialPayload:
        self._fail_if_requested("get")
        try:
            return CredentialPayload.from_json_bytes(self._credentials[credential_ref])
        except KeyError as exc:
            raise CredentialNotFoundError() from exc

    async def replace(
        self,
        credential_ref: str,
        payload: CredentialPayload,
    ) -> str:
        self._fail_if_requested("replace")
        if credential_ref not in self._credentials:
            raise CredentialNotFoundError()
        self._credentials[credential_ref] = payload.to_json_bytes()
        return credential_ref

    async def delete(self, credential_ref: str) -> None:
        self._fail_if_requested("delete")
        try:
            del self._credentials[credential_ref]
        except KeyError as exc:
            raise CredentialNotFoundError() from exc

    def _fail_if_requested(self, operation: str) -> None:
        if operation in self.fail_operations:
            raise CredentialStoreUnavailableError(operation)


@dataclass(frozen=True, kw_only=True)
class GcpSecretManagerCredentialStore:
    project_id: str
    secret_prefix: str = "labelos-credential"
    client: Any = None

    def __post_init__(self) -> None:
        if not self.project_id:
            raise ValueError("project_id is required")
        object.__setattr__(
            self,
            "secret_prefix",
            _safe_secret_prefix(self.secret_prefix),
        )
        if self.client is None:
            try:
                secretmanager = import_module("google.cloud.secretmanager")
            except ImportError as exc:  # pragma: no cover - environment dependent
                raise CredentialStoreUnavailableError("startup") from exc
            object.__setattr__(
                self,
                "client",
                secretmanager.SecretManagerServiceClient(),
            )

    async def put(self, payload: CredentialPayload) -> str:
        secret_id = f"{self.secret_prefix}-{uuid4().hex}"
        parent = f"projects/{self.project_id}"
        secret_name = f"{parent}/secrets/{secret_id}"
        try:
            self.client.create_secret(
                request={
                    "parent": parent,
                    "secret_id": secret_id,
                    "secret": {"replication": {"automatic": {}}},
                }
            )
            self.client.add_secret_version(
                request={
                    "parent": secret_name,
                    "payload": {"data": payload.to_json_bytes()},
                }
            )
        except Exception as exc:
            raise CredentialStoreUnavailableError("put") from exc
        return f"{_GCP_REF_PREFIX}{secret_name}"

    async def get(self, credential_ref: str) -> CredentialPayload:
        secret_name = _secret_name_from_gcp_ref(credential_ref, self.project_id)
        try:
            response = self.client.access_secret_version(
                request={"name": f"{secret_name}/versions/latest"}
            )
            return CredentialPayload.from_json_bytes(response.payload.data)
        except Exception as exc:
            if _is_gcp_not_found(exc):
                raise CredentialNotFoundError() from exc
            raise CredentialStoreUnavailableError("get") from exc

    async def replace(
        self,
        credential_ref: str,
        payload: CredentialPayload,
    ) -> str:
        secret_name = _secret_name_from_gcp_ref(credential_ref, self.project_id)
        try:
            self.client.add_secret_version(
                request={
                    "parent": secret_name,
                    "payload": {"data": payload.to_json_bytes()},
                }
            )
        except Exception as exc:
            if _is_gcp_not_found(exc):
                raise CredentialNotFoundError() from exc
            raise CredentialStoreUnavailableError("replace") from exc
        return credential_ref

    async def delete(self, credential_ref: str) -> None:
        secret_name = _secret_name_from_gcp_ref(credential_ref, self.project_id)
        try:
            self.client.delete_secret(request={"name": secret_name})
        except Exception as exc:
            if _is_gcp_not_found(exc):
                raise CredentialNotFoundError() from exc
            raise CredentialStoreUnavailableError("delete") from exc


def build_credential_store(settings: Settings) -> CredentialStore:
    backend = settings.credential_store_backend.lower()
    if backend == "memory":
        return InMemoryCredentialStore()
    if backend == "gcp-secret-manager":
        project_id = settings.resolved_credential_store_gcp_project_id
        if not project_id:
            raise CredentialStoreUnavailableError("startup")
        return GcpSecretManagerCredentialStore(
            project_id=project_id,
            secret_prefix=settings.credential_store_secret_prefix,
        )
    raise CredentialStoreUnavailableError("startup")


def _safe_secret_prefix(value: str) -> str:
    safe = _SAFE_SECRET_PREFIX_PATTERN.sub("-", value.strip()).strip("-_").lower()
    return safe[:80] or "labelos-credential"


def _secret_name_from_gcp_ref(credential_ref: str, project_id: str) -> str:
    if not credential_ref.startswith(_GCP_REF_PREFIX):
        raise InvalidCredentialReferenceError()
    secret_name = credential_ref.removeprefix(_GCP_REF_PREFIX)
    parts = secret_name.split("/")
    if (
        len(parts) != 4
        or parts[0] != "projects"
        or parts[2] != "secrets"
        or parts[1] != project_id
        or not _SECRET_ID_PATTERN.fullmatch(parts[3])
    ):
        raise InvalidCredentialReferenceError()
    return secret_name


def _is_gcp_not_found(exc: Exception) -> bool:
    if exc.__class__.__name__ == "NotFound":
        return True
    try:
        from google.api_core import exceptions as google_exceptions
    except ImportError:
        return False
    return isinstance(exc, google_exceptions.NotFound)
