"""Commit quota reservations before network I/O, independent of display rollback."""

import math
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from labelos_database.research_models import YouTubeQuotaBucket as Bucket
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from labelos_api.research.errors import AdapterFailure
from labelos_api.research.errors import ProviderErrorCode as Code


def reset_time(now: datetime) -> datetime:
    pacific = ZoneInfo("America/Los_Angeles")
    tomorrow = now.astimezone(pacific).date() + timedelta(days=1)
    return datetime.combine(tomorrow, time(), pacific).astimezone(UTC)


class YouTubeQuota:
    def __init__(self, sessions, *, clock=lambda: datetime.now(UTC), spacing=True):
        self.sessions = sessions
        self.clock = clock
        self.spacing = spacing

    async def reserve(self, bucket: str):
        now = self.clock()
        stamp = int(now.timestamp() * 1000)
        reset = int(reset_time(now).timestamp() * 1000)
        # Reserve headroom for other clients of the same Google API project.
        limit = 80 if bucket == "search" else 8000
        spacing = (2000 if bucket == "search" else 250) if self.spacing else 0
        async with self.sessions() as session, session.begin():
            dialect = session.get_bind().dialect.name
            if dialect not in {"postgresql", "sqlite"}:
                raise AdapterFailure(Code.provider_unavailable)
            insert = pg_insert if dialect == "postgresql" else sqlite_insert
            await session.execute(
                insert(Bucket)
                .values(bucket=bucket, used=0, reset_at=reset, next_at=0)
                .on_conflict_do_nothing(index_elements=["bucket"])
            )
            await session.execute(
                update(Bucket)
                .where(Bucket.bucket == bucket, Bucket.reset_at <= stamp)
                .values(used=0, reset_at=reset)
            )
            claimed = await session.scalar(
                update(Bucket)
                .where(
                    Bucket.bucket == bucket,
                    Bucket.used < limit,
                    Bucket.next_at <= stamp,
                )
                .values(used=Bucket.used + 1, next_at=stamp + spacing)
                .returning(Bucket.bucket)
            )
            if claimed:
                return
            row = await session.scalar(select(Bucket).where(Bucket.bucket == bucket))
            exhausted = row.used >= limit
            remaining = (row.reset_at if exhausted else row.next_at) - stamp
            raise AdapterFailure(
                Code.quota_exceeded if exhausted else Code.rate_limited,
                retry_after_seconds=max(1, math.ceil(remaining / 1000)),
            )

    async def defer(self, bucket: str, seconds: int):
        deadline = int((self.clock().timestamp() + seconds) * 1000)
        async with self.sessions() as session, session.begin():
            await session.execute(
                update(Bucket)
                .where(Bucket.bucket == bucket, Bucket.next_at < deadline)
                .values(next_at=deadline)
            )
