import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from labelos_database.base import Base
from labelos_database.models import (
    OAuthAuthorizationState,
    OAuthAuthorizationStateStatus,
    Organization,
    SocialAccountConnectionMethod,
    UniversalProfile,
    User,
    WorkspaceMembership,
)
from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from labelos_api.services.credential_store import InMemoryCredentialStore
from labelos_api.services.oauth_state_service import (
    OAuthStateBindingError,
    OAuthStateConsumedError,
    OAuthStateCreate,
    OAuthStateExpiredError,
    OAuthStateMalformedError,
    OAuthStateMissingError,
    OAuthStateNotFoundError,
    OAuthStateRedirectError,
    cleanup_expired_states,
    consume_state,
    create_state,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def sessionmaker() -> Iterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare_database())
    yield async_sessionmaker(bind=engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


async def _seed_workspace_actor(session: AsyncSession) -> dict[str, object]:
    workspace = Organization(
        name="OAuth Workspace",
        slug=f"oauth-workspace-{uuid4()}",
        owner=User(email=f"owner-{uuid4()}@example.com"),
    )
    actor = User(email=f"actor-{uuid4()}@example.com")
    actor_profile = UniversalProfile(user=actor, slug=f"actor-{uuid4()}")
    membership = WorkspaceMembership(workspace=workspace, profile=actor_profile)

    other_workspace = Organization(
        name="Other OAuth Workspace",
        slug=f"other-oauth-workspace-{uuid4()}",
        owner=User(email=f"other-owner-{uuid4()}@example.com"),
    )
    other_actor = User(email=f"other-actor-{uuid4()}@example.com")
    other_actor_profile = UniversalProfile(
        user=other_actor,
        slug=f"other-actor-{uuid4()}",
    )
    other_membership = WorkspaceMembership(
        workspace=other_workspace,
        profile=other_actor_profile,
    )
    session.add_all([membership, other_membership])
    await session.flush()
    return {
        "workspace": workspace,
        "actor": actor,
        "other_workspace": other_workspace,
        "other_actor": other_actor,
    }


async def _create_pending_state(
    session: AsyncSession,
    *,
    workspace_id,
    actor_user_id,
    provider: str = "instagram",
    method: SocialAccountConnectionMethod = SocialAccountConnectionMethod.direct_api,
    redirect_path: str = "/workspace/settings?tab=connections",
    pkce: str | None = None,
    credential_store: InMemoryCredentialStore | None = None,
    now: datetime | None = None,
):
    return await create_state(
        session,
        OAuthStateCreate(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            provider=provider,
            connection_method=method,
            safe_redirect_path=redirect_path,
            pkce_code_verifier=pkce,
        ),
        credential_store=credential_store,
        now=now,
    )


def test_oauth_state_creation_persists_hashed_one_time_server_state(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, object]:
        async with sessionmaker() as session:
            seeded = await _seed_workspace_actor(session)
            workspace = seeded["workspace"]
            actor = seeded["actor"]
            assert isinstance(workspace, Organization)
            assert isinstance(actor, User)
            store = InMemoryCredentialStore()

            pending = await _create_pending_state(
                session,
                workspace_id=workspace.id,
                actor_user_id=actor.id,
                provider="Twitter",
                method=SocialAccountConnectionMethod.direct_api,
                pkce="pkce-secret-verifier",
                credential_store=store,
            )
            record = await session.scalar(select(OAuthAuthorizationState))
            assert record is not None
            pkce_payload = await store.get(record.pkce_credential_ref or "")
            return {
                "state_length": len(pending.state),
                "state_in_db": pending.state == record.state_hash,
                "hash_length": len(record.state_hash),
                "workspace_id": record.organization_id,
                "actor_user_id": record.actor_user_id,
                "provider": record.provider,
                "method": record.connection_method,
                "status": record.status,
                "redirect": record.safe_redirect_path,
                "pkce_ref": record.pkce_credential_ref,
                "pkce": pkce_payload.expose(),
            }

    result = asyncio.run(run())
    assert result["state_length"] >= 32
    assert result["state_in_db"] is False
    assert result["hash_length"] == 64
    assert result["provider"] == "x"
    assert result["method"] == SocialAccountConnectionMethod.direct_api
    assert result["status"] == OAuthAuthorizationStateStatus.pending
    assert result["redirect"] == "/workspace/settings?tab=connections"
    assert str(result["pkce_ref"]).startswith("memory://credentials/")
    assert result["pkce"] == {"pkce_code_verifier": "pkce-secret-verifier"}


def test_oauth_state_valid_consumption_marks_record_consumed_and_returns_pkce(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, object]:
        async with sessionmaker() as session:
            seeded = await _seed_workspace_actor(session)
            workspace = seeded["workspace"]
            actor = seeded["actor"]
            assert isinstance(workspace, Organization)
            assert isinstance(actor, User)
            store = InMemoryCredentialStore()
            issued_at = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
            pending = await _create_pending_state(
                session,
                workspace_id=workspace.id,
                actor_user_id=actor.id,
                pkce="verifier",
                credential_store=store,
                now=issued_at,
            )

            consumed = await consume_state(
                session,
                state=pending.state,
                workspace_id=workspace.id,
                actor_user_id=actor.id,
                provider="instagram",
                connection_method=SocialAccountConnectionMethod.direct_api,
                credential_store=store,
                now=issued_at + timedelta(minutes=1),
            )
            return {
                "status": consumed.record.status,
                "consumed_at": consumed.record.consumed_at,
                "redirect": consumed.record.safe_redirect_path,
                "pkce": consumed.pkce_payload,
            }

    result = asyncio.run(run())
    assert result["status"] == OAuthAuthorizationStateStatus.consumed
    assert result["consumed_at"] is not None
    assert result["redirect"] == "/workspace/settings?tab=connections"
    assert result["pkce"] == {"pkce_code_verifier": "verifier"}


def test_oauth_state_replay_is_rejected(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> bool:
        async with sessionmaker() as session:
            seeded = await _seed_workspace_actor(session)
            workspace = seeded["workspace"]
            actor = seeded["actor"]
            assert isinstance(workspace, Organization)
            assert isinstance(actor, User)
            pending = await _create_pending_state(
                session,
                workspace_id=workspace.id,
                actor_user_id=actor.id,
            )
            await consume_state(
                session,
                state=pending.state,
                workspace_id=workspace.id,
                actor_user_id=actor.id,
                provider="instagram",
                connection_method=SocialAccountConnectionMethod.direct_api,
            )
            try:
                await consume_state(
                    session,
                    state=pending.state,
                    workspace_id=workspace.id,
                    actor_user_id=actor.id,
                    provider="instagram",
                    connection_method=SocialAccountConnectionMethod.direct_api,
                )
            except OAuthStateConsumedError:
                return True
            return False

    assert asyncio.run(run()) is True


def test_oauth_state_expiry_marks_record_expired_and_blocks_consumption(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, object]:
        async with sessionmaker() as session:
            seeded = await _seed_workspace_actor(session)
            workspace = seeded["workspace"]
            actor = seeded["actor"]
            assert isinstance(workspace, Organization)
            assert isinstance(actor, User)
            issued_at = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
            pending = await _create_pending_state(
                session,
                workspace_id=workspace.id,
                actor_user_id=actor.id,
                now=issued_at,
            )
            try:
                await consume_state(
                    session,
                    state=pending.state,
                    workspace_id=workspace.id,
                    actor_user_id=actor.id,
                    provider="instagram",
                    connection_method=SocialAccountConnectionMethod.direct_api,
                    now=issued_at + timedelta(minutes=11),
                )
            except OAuthStateExpiredError:
                record = await session.scalar(select(OAuthAuthorizationState))
                assert record is not None
                return {"expired": True, "status": record.status}
            return {"expired": False}

    assert asyncio.run(run()) == {
        "expired": True,
        "status": OAuthAuthorizationStateStatus.expired,
    }


@pytest.mark.parametrize(
    ("field", "error"),
    [
        ("workspace", OAuthStateBindingError),
        ("provider", OAuthStateBindingError),
        ("method", OAuthStateBindingError),
        ("actor", OAuthStateBindingError),
    ],
)
def test_oauth_state_rejects_wrong_callback_binding(
    sessionmaker: async_sessionmaker[AsyncSession],
    field: str,
    error: type[Exception],
) -> None:
    async def run() -> bool:
        async with sessionmaker() as session:
            seeded = await _seed_workspace_actor(session)
            workspace = seeded["workspace"]
            actor = seeded["actor"]
            other_workspace = seeded["other_workspace"]
            other_actor = seeded["other_actor"]
            assert isinstance(workspace, Organization)
            assert isinstance(actor, User)
            assert isinstance(other_workspace, Organization)
            assert isinstance(other_actor, User)
            pending = await _create_pending_state(
                session,
                workspace_id=workspace.id,
                actor_user_id=actor.id,
            )
            kwargs = {
                "workspace_id": workspace.id,
                "actor_user_id": actor.id,
                "provider": "instagram",
                "connection_method": SocialAccountConnectionMethod.direct_api,
            }
            if field == "workspace":
                kwargs["workspace_id"] = other_workspace.id
            elif field == "provider":
                kwargs["provider"] = "tiktok"
            elif field == "method":
                kwargs["connection_method"] = SocialAccountConnectionMethod.third_party
            elif field == "actor":
                kwargs["actor_user_id"] = other_actor.id

            try:
                await consume_state(session, state=pending.state, **kwargs)
            except error:
                record = await session.scalar(select(OAuthAuthorizationState))
                assert record is not None
                return record.status == OAuthAuthorizationStateStatus.pending
            return False

    assert asyncio.run(run()) is True


@pytest.mark.parametrize(
    "redirect_path",
    [
        "https://evil.example/callback",
        "//evil.example/callback",
        r"/\evil",
        "",
    ],
)
def test_oauth_state_creation_rejects_unsafe_redirects(
    sessionmaker: async_sessionmaker[AsyncSession],
    redirect_path: str,
) -> None:
    async def run() -> bool:
        async with sessionmaker() as session:
            seeded = await _seed_workspace_actor(session)
            workspace = seeded["workspace"]
            actor = seeded["actor"]
            assert isinstance(workspace, Organization)
            assert isinstance(actor, User)
            try:
                await _create_pending_state(
                    session,
                    workspace_id=workspace.id,
                    actor_user_id=actor.id,
                    redirect_path=redirect_path,
                )
            except OAuthStateRedirectError:
                return True
            return False

    assert asyncio.run(run()) is True


def test_oauth_state_rejects_malformed_missing_and_unknown_nonce(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, bool]:
        async with sessionmaker() as session:
            seeded = await _seed_workspace_actor(session)
            workspace = seeded["workspace"]
            actor = seeded["actor"]
            assert isinstance(workspace, Organization)
            assert isinstance(actor, User)
            result: dict[str, bool] = {}
            base = {
                "workspace_id": workspace.id,
                "actor_user_id": actor.id,
                "provider": "instagram",
                "connection_method": SocialAccountConnectionMethod.direct_api,
            }

            try:
                await consume_state(session, state=None, **base)
            except OAuthStateMissingError:
                result["missing"] = True

            try:
                await consume_state(session, state="not valid", **base)
            except OAuthStateMalformedError:
                result["malformed"] = True

            try:
                await consume_state(session, state="A" * 43, **base)
            except OAuthStateNotFoundError:
                result["unknown"] = True

            return result

    assert asyncio.run(run()) == {
        "missing": True,
        "malformed": True,
        "unknown": True,
    }


def test_oauth_state_cleanup_deletes_expired_records(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> dict[str, object]:
        async with sessionmaker() as session:
            seeded = await _seed_workspace_actor(session)
            workspace = seeded["workspace"]
            actor = seeded["actor"]
            assert isinstance(workspace, Organization)
            assert isinstance(actor, User)
            now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
            await _create_pending_state(
                session,
                workspace_id=workspace.id,
                actor_user_id=actor.id,
                now=now - timedelta(minutes=20),
            )
            await _create_pending_state(
                session,
                workspace_id=workspace.id,
                actor_user_id=actor.id,
                now=now,
            )

            deleted = await cleanup_expired_states(session, now=now)
            rows = list((await session.scalars(select(OAuthAuthorizationState))).all())
            return {"deleted": deleted, "remaining": len(rows)}

    assert asyncio.run(run()) == {"deleted": 1, "remaining": 1}


def test_oauth_authorization_state_model_defines_security_contract() -> None:
    table = OAuthAuthorizationState.__table__
    column_names = set(table.columns.keys())
    index_names = {index.name for index in table.indexes}
    constraint_names = {constraint.name for constraint in table.constraints}
    foreign_key_deletions = {
        foreign_key.parent.name: foreign_key.ondelete
        for foreign_key in table.foreign_keys
    }

    assert {
        "id",
        "organization_id",
        "state_hash",
        "actor_user_id",
        "provider",
        "connection_method",
        "status",
        "expires_at",
        "consumed_at",
        "safe_redirect_path",
        "pkce_credential_ref",
        "created_at",
        "updated_at",
    } <= column_names
    assert "state" not in column_names
    assert "nonce" not in column_names
    assert "pkce_code_verifier" not in column_names
    assert "client_secret" not in column_names
    assert "access_token" not in column_names
    assert "refresh_token" not in column_names
    assert "uq_oauth_authorization_states_hash" in constraint_names
    assert {
        "ix_oauth_authorization_states_organization_id",
        "ix_oauth_authorization_states_org_provider_method",
        "ix_oauth_authorization_states_actor_user_id",
        "ix_oauth_authorization_states_status_expires_at",
    } <= index_names
    assert foreign_key_deletions == {
        "organization_id": "CASCADE",
        "actor_user_id": "CASCADE",
    }


def test_oauth_authorization_state_migration_upgrade_downgrade_reupgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "oauth-state-migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    config = Config(str(REPO_ROOT / "packages/database/alembic.ini"))
    engine = create_engine(f"sqlite:///{database_path}")
    metadata = MetaData()
    Table(
        "users",
        metadata,
        Column("id", String(), primary_key=True),
        Column("created_at", DateTime(timezone=True), server_default=func.now()),
        Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    )
    Table(
        "organizations",
        metadata,
        Column("id", String(), primary_key=True),
        Column("created_at", DateTime(timezone=True), server_default=func.now()),
        Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    )
    metadata.create_all(engine)
    engine.dispose()

    command.stamp(config, "202609051900")
    command.upgrade(config, "202609061300")
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.connect() as connection:
            table_names = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        assert OAuthAuthorizationState.__tablename__ in table_names
    finally:
        engine.dispose()

    command.downgrade(config, "202609051900")
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.connect() as connection:
            table_names = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        assert OAuthAuthorizationState.__tablename__ not in table_names
    finally:
        engine.dispose()

    command.upgrade(config, "202609061300")
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.connect() as connection:
            table_names = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        assert OAuthAuthorizationState.__tablename__ in table_names
    finally:
        engine.dispose()
