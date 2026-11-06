import anyio

from labelos_api import auth


def test_request_dependency_closes_inner_session_on_disconnect(monkeypatch):
    closed = []

    async def fake_session(_settings):
        try:
            yield object()
        finally:
            await anyio.sleep(0)
            closed.append(True)

    monkeypatch.setattr(auth, "get_async_session", fake_session)

    async def run():
        dependency = auth.get_session(None)
        await anext(dependency)
        with anyio.CancelScope() as cancellation:
            cancellation.cancel()
            await dependency.aclose()
        assert closed == [True]

    anyio.run(run)


def test_postgres_disconnect_returns_connection(monkeypatch, postgres_test_engine):
    from labelos_database import session as database_session
    from sqlalchemy import event, text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    checked_in = []
    event.listen(
        postgres_test_engine.sync_engine, "checkin", lambda *_: checked_in.append(True)
    )
    monkeypatch.setattr(
        database_session,
        "get_sessionmaker",
        lambda _: async_sessionmaker(postgres_test_engine),
    )

    async def run():
        dependency = auth.get_session(None)
        session = await anext(dependency)
        await session.execute(text("SELECT 1"))
        checked_in.clear()
        with anyio.CancelScope() as cancellation:
            cancellation.cancel()
            await dependency.aclose()
        assert checked_in == [True]

    anyio.run(run)
