"""Short PostgreSQL ownership transactions. Always lock publication before lease.

No Scheduling claim is reused: acceptance ended that execution concern. Callers
own commit/rollback; database wall time governs every lease and worker due check.
"""

from datetime import timedelta
from uuid import UUID

from labelos_database.models import Publication, PublicationLease
from sqlalchemy import and_, func, or_, select

from labelos_api.publishing.execution import PublicationClaim
from labelos_api.publishing.recovery import action_filters


class PublicationLeaseLost(RuntimeError):
    """Ownership expired, was revoked, or belongs to a different worker."""


async def database_now(session):
    return await session.scalar(select(func.clock_timestamp()))


async def require_ownership(session, row, claim):
    """Caller holds the publication lock through its final write and commit."""
    lease = await session.get(PublicationLease, row.id, populate_existing=True)
    if claim is None:
        if lease is not None and lease.owner_id is not None:
            raise PublicationLeaseLost("publication_claim_required")
        return lease
    if (
        lease is None
        or claim.workspace_id != row.workspace_id
        or claim.publication_id != row.id
        or lease.owner_id != claim.owner_id
        or lease.fencing_token != claim.fencing_token
        or lease.expires_at is None
        or lease.expires_at <= await database_now(session)
    ):
        raise PublicationLeaseLost("publication_lease_lost")
    return lease


class PublicationLeaseRepository:
    def __init__(self, session, workspace_id):
        self.session, self.workspace_id = session, workspace_id

    async def claim_next(self, *, owner_id: UUID, duration: timedelta, exclude=()):
        if not isinstance(owner_id, UUID) or not owner_id.int:
            raise ValueError("invalid_publication_worker")
        if not timedelta(seconds=1) <= duration <= timedelta(hours=1):
            raise ValueError("invalid_publication_lease_duration")
        now = await database_now(self.session)
        available, eligible = action_filters(now)
        row = await self.session.scalar(
            select(Publication)
            .join(PublicationLease, PublicationLease.publication_id == Publication.id)
            .where(
                Publication.workspace_id == self.workspace_id,
                Publication.id.not_in(exclude),
                available,
                or_(
                    PublicationLease.owner_id.is_(None),
                    PublicationLease.expires_at <= now,
                ),
                or_(
                    Publication.status == "pending",
                    and_(
                        Publication.status == "retryable_failure",
                        eligible,
                        PublicationLease.interrupted.is_(False),
                    ),
                    and_(
                        Publication.status.in_(("processing", "retrying")),
                        PublicationLease.expires_at <= now,
                    ),
                ),
            )
            # Cancelled (including invalidated approval) is terminal and excluded.
            # Rotate transient preflight refusals so later work remains reachable.
            .order_by(
                PublicationLease.fencing_token, Publication.created_at, Publication.id
            )
            .with_for_update(of=Publication, skip_locked=True)
            .execution_options(populate_existing=True)
            .limit(1)
        )
        if row is None:
            return None
        lease = await self.session.get(PublicationLease, row.id, populate_existing=True)
        recovering = row.status in ("processing", "retrying")
        lease.fencing_token += 1
        lease.owner_id = owner_id
        lease.expires_at = await database_now(self.session) + duration
        lease.interrupted = lease.interrupted or recovering
        await self.session.flush()
        return PublicationClaim(
            workspace_id=self.workspace_id,
            publication_id=row.id,
            owner_id=owner_id,
            fencing_token=lease.fencing_token,
            transition_version=row.transition_version,
            recovering=recovering,
        )

    async def _owned(self, claim):
        row = await self.session.scalar(
            select(Publication)
            .where(
                Publication.id == claim.publication_id,
                Publication.workspace_id == self.workspace_id,
            )
            .with_for_update()
        )
        if row is None:
            raise PublicationLeaseLost("publication_lease_lost")
        return await require_ownership(self.session, row, claim)

    async def renew(self, claim, duration):
        if not timedelta(seconds=1) <= duration <= timedelta(hours=1):
            raise ValueError("invalid_publication_lease_duration")
        lease = await self._owned(claim)
        assert lease is not None
        lease.expires_at = await database_now(self.session) + duration
        await self.session.flush()

    async def release(self, claim):
        lease = await self._owned(claim)
        assert lease is not None
        row = await self.session.get(Publication, claim.publication_id)
        if row is None or row.status not in ("pending", "retryable_failure"):
            raise PublicationLeaseLost("publication_started_requires_outcome")
        lease.owner_id = lease.expires_at = None
        await self.session.flush()
