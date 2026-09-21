"""Authoritative Publication facts across both calendar read paths."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from labelos_database.models import MarketingContentItem, RealtimeEvent
from sqlalchemy import select

from labelos_api.api.v1.campaign_calendar import _event_response
from labelos_api.api.v1.marketing_content import _list_response
from labelos_api.repositories import campaign_calendar, marketing_content
from labelos_api.repositories.publication_calendar import list_facts
from labelos_api.repositories.publishing import PublicationConflict
from labelos_api.services.campaign_calendar_service import (
    CampaignCalendarEventQuery,
    _normalize_event,
    list_campaign_calendar_events,
)
from test_publishing_persistence import (
    NOW,
    append,
    result_entry,
    seed,
    start_entry,
)
from test_publishing_persistence import sessions as sessions  # noqa: F401


@pytest.mark.parametrize("path", ["scheduled", "retry", "reconciled", "failed"])
def test_authoritative_calendar_readback(sessions, path):
    async def run():
        async with sessions() as session:
            repo, row, _ = await seed(session)
            workspace, identifier = row.workspace_id, row.id
            item = await session.get(
                MarketingContentItem, row.marketing_content_item_id
            )
            item.status = "approved"
            # Reproduce the audit without any legacy publication timestamps.
            item.channels[0].published_at = None
            item.channels[0].external_post_id = None
            item.channels[0].external_url = None
            await session.flush()
            before = (item.status, item.published_at, item.channels[0].published_at)
            row = await append(repo, row, start_entry(row))
            if path == "retry":
                row = await append(repo, row, result_entry(row, "retryable_failure"))
                row = await append(repo, row, start_entry(row))
            if path == "reconciled":
                row = await append(repo, row, result_entry(row, "unknown"))
            entry = result_entry(
                row,
                "permanent_failure" if path == "failed" else "published",
                "reconciliation" if path == "reconciled" else "provider_response",
            )
            operation = uuid4()
            version = row.transition_version
            row = await repo.append(
                identifier,
                expected_version=version,
                operation_id=operation,
                entry=entry,
            )
            # Stale duplicate provider results cannot create another event.
            with pytest.raises(
                PublicationConflict, match="publication_version_conflict"
            ):
                await repo.append(
                    identifier,
                    expected_version=version,
                    operation_id=operation,
                    entry=entry,
                )
            published_at = row.published_at
            await session.commit()
            assert before == (
                item.status,
                item.published_at,
                item.channels[0].published_at,
            )
        # Fresh sessions exercise calendar reload rather than an ORM identity map.
        observed_ids = []
        for _ in range(2):
            async with sessions() as session:
                query = CampaignCalendarEventQuery(
                    start=NOW - timedelta(days=2),
                    end=NOW + timedelta(days=1),
                    timezone="America/Los_Angeles",
                    include_published=True,
                    event_types=tuple(campaign_calendar.PUBLISHED_EVENT_TYPES),
                    statuses=("published",),
                )
                page = await list_campaign_calendar_events(
                    session, workspace, query=query
                )
                assert len(page.events) == (0 if path == "failed" else 2)
                observed_ids.append([e.id for e in page.events])
                for event in page.events:
                    assert event.source_type == "publication"
                    assert event.status == "published"
                    assert event.source_id == str(identifier)
                    assert datetime.fromisoformat(event.starts_at) == published_at
                    assert event.campaign.id == str(item.campaign_id)
                    assert event.channel.id == str(
                        row.marketing_content_item_channel_id
                    )
                    assert (
                        event.publication.social_account_connection_id
                        == row.social_account_connection_id
                    )
                    assert event.publication.provider == "instagram"
                    assert (
                        _event_response(event).publication.external_post_id
                        == "post-123"
                    )
                assert not (
                    await list_campaign_calendar_events(session, uuid4(), query=query)
                ).events
                hidden = await campaign_calendar.list_events(session, workspace)
                assert not any(
                    e.event_type in campaign_calendar.PUBLISHED_EVENT_TYPES
                    for e in hidden
                )
                # The content calendar includes success even when the planned date
                # is outside the requested range; authoring remains approved.
                if published_at:
                    content_page = await marketing_content.list_items(
                        session,
                        workspace,
                        status="published",
                        limit=100,
                        offset=0,
                        scheduled_start=published_at,
                        scheduled_end=published_at,
                    )
                    response = await _list_response(session, workspace, content_page)
                    assert response.total == 1
                    content = response.marketing_content[0]
                    assert content.status == "approved" and content.published_at is None
                    assert len(content.publications) == 1
                    assert content.publications[0].published_at == published_at
                notices = (
                    await session.scalars(
                        select(RealtimeEvent).where(
                            RealtimeEvent.organization_id == workspace,
                            RealtimeEvent.event_type == "marketing.publication.changed",
                        )
                    )
                ).all()
                assert sum(n.payload["status"] == "published" for n in notices) == (
                    0 if path == "failed" else 1
                )
        assert observed_ids[0] == observed_ids[1]

    asyncio.run(run())


def test_publication_supersedes_legacy_calendar_dates(sessions):
    async def run():
        async with sessions() as session:
            repo, row, _ = await seed(session)
            item = await session.get(
                MarketingContentItem, row.marketing_content_item_id
            )
            item.published_at = NOW - timedelta(days=2)
            row = await append(repo, row, start_entry(row))
            row = await append(repo, row, result_entry(row))
            query = campaign_calendar.CampaignCalendarEventQuery(
                include_published=True,
                event_types=tuple(campaign_calendar.PUBLISHED_EVENT_TYPES),
            )
            events = await campaign_calendar.list_events(
                session, row.workspace_id, query
            )
            assert len(events) == 2
            assert all(
                e.source_id == row.id and e.event_at == row.published_at for e in events
            )
            # Legacy events must also stay suppressed in a range excluding success.
            assert not await campaign_calendar.list_events(
                session,
                row.workspace_id,
                replace(
                    query,
                    range_start=NOW - timedelta(days=3),
                    range_end=NOW - timedelta(days=1),
                ),
            )

    asyncio.run(run())


@pytest.mark.parametrize(
    "instant,offset",
    [
        ("2026-11-01T08:30:00+00:00", "-07:00"),
        ("2026-11-01T09:30:00+00:00", "-08:00"),
        ("2026-03-08T10:30:00+00:00", "-07:00"),
    ],
)
def test_non_campaign_projection_and_dst(sessions, instant, offset):
    async def run():
        async with sessions() as session:
            repo, row, _ = await seed(session)
            row = await append(repo, row, start_entry(row))
            row = await append(repo, row, result_entry(row))
            events = await campaign_calendar.list_events(
                session,
                row.workspace_id,
                campaign_calendar.CampaignCalendarEventQuery(include_published=True),
            )
            event = next(e for e in events if e.publication)
            # Existing schema requires campaign_id. Exercise absent context at the
            # projection boundary without weakening that unrelated invariant.
            event = replace(
                event,
                campaign_id=None,
                campaign_name=None,
                campaign_status=None,
                campaign_type=None,
                approval_request=None,
                event_at=datetime.fromisoformat(instant),
            )
            normalized = await _normalize_event(
                session,
                workspace_id=row.workspace_id,
                actor=None,
                event=event,
                timezone=ZoneInfo("America/Los_Angeles"),
            )
            assert normalized.campaign is None
            assert normalized.starts_at.endswith(offset)
            assert datetime.fromisoformat(
                normalized.starts_at
            ) == datetime.fromisoformat(instant)

    asyncio.run(run())


@pytest.mark.parametrize(
    "providers", [("instagram", "instagram"), ("instagram", "youtube")]
)
def test_multiple_channels_destinations_and_workspace_isolation(sessions, providers):
    from labelos_database.models import (
        ApprovalRequest,
        MarketingContentItemChannel,
        SchedulingJob,
        SocialAccountConnection,
        User,
    )

    from labelos_api.repositories.scheduling import snapshot_for
    from labelos_api.scheduling.payload import prepare_request
    from test_scheduling_persistence import job_for

    async def run():
        async with sessions() as session:
            repo, first, request = await seed(session)
            item = await session.get(
                MarketingContentItem, first.marketing_content_item_id
            )
            approval = await session.get(ApprovalRequest, first.approval_request_id)
            job = await session.get(SchedulingJob, first.scheduling_job_id)
            user = await session.get(User, job.created_by_user_id)
            connection = SocialAccountConnection(
                organization_id=first.workspace_id,
                provider=providers[1],
                connection_method="assisted",
            )
            session.add(connection)
            await session.flush()
            channel = MarketingContentItemChannel(
                marketing_content_item_id=item.id,
                channel=providers[1],
                placement="story",
                social_account_connection_id=connection.id,
                scheduled_at=NOW,
                schedule_timezone="UTC",
                schedule_local_time="2026-09-15T12:00:00",
                schedule_offset_seconds=0,
            )
            session.add(channel)
            await session.flush()
            second_job = job_for(
                item,
                approval,
                user,
                marketing_content_item_channel_id=channel.id,
                social_account_connection_id=connection.id,
            )
            session.add(second_job)
            await session.flush()
            second_request = prepare_request(
                snapshot=snapshot_for(second_job),
                job_id=second_job.id,
                destination_id=connection.id,
                artist_profile_id=None,
                authoring_timezone="UTC",
                correlation_id=uuid4(),
                item=item,
                channel=channel,
                asset_bytes={},
            )
            second = await repo.create(second_request, created_at=NOW)
            other_repo, other, _ = await seed(session)
            for owner, row in [(repo, first), (repo, second), (other_repo, other)]:
                row = await append(owner, row, start_entry(row))
                await append(
                    owner,
                    row,
                    result_entry(row),
                    provider_url="https://example.com/post-123",
                )
            await session.commit()
        async with sessions() as session:
            query = campaign_calendar.CampaignCalendarEventQuery(
                include_published=True,
                event_types=tuple(campaign_calendar.PUBLISHED_EVENT_TYPES),
                campaign_id=item.campaign_id,
            )
            events = await campaign_calendar.list_events(
                session, first.workspace_id, query
            )
            assert len(events) == 4
            assert {e.placement for e in events if e.source_id == second.id} == {
                "story"
            }
            assert {e.source_id for e in events} == {first.id, second.id}
            assert {e.publication.provider for e in events} == set(providers)
            assert {e.publication.social_account_connection_id for e in events} == {
                first.social_account_connection_id,
                connection.id,
            }
            assert all(
                e.publication.provider_url == "https://example.com/post-123"
                for e in events
            )
            assert len({(e.source_id, e.event_type) for e in events}) == 4
            assert not await campaign_calendar.list_events(
                session, other.workspace_id, query
            )
            # Scope filters never borrow a successful publication from another campaign.
            assert not await campaign_calendar.list_events(
                session, first.workspace_id, replace(query, campaign_id=uuid4())
            )
            facts = await list_facts(
                session, first.workspace_id, [item.id, other.marketing_content_item_id]
            )
            assert {f.publication_id for f in facts} == {first.id, second.id}

    asyncio.run(run())
