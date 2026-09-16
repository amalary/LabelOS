# Scheduling projections and observability

Content responses and Campaign Calendar channel contexts expose `scheduling_job`.
It is a read-only projection of the latest activated job, fetched in one scoped
batch query. No job means `null`. The projection never changes `scheduled_at`:
channel time is planned intent and parent time is independent planning data.
Calendar IDs, milestones, approval events and recorded publication timestamps
remain unchanged. Handoff does not produce publication events.

`active` is false for cancelled, superseded and handed-off jobs, and for a job
whose revision, generation, time, timezone or destination differs from the channel.
`intent_matches` distinguishes historical state from the current plan. State is
an observation, not execution authorization. Editing or reapproving alone cannot
create a replacement projection. Replacement, including after cancellation,
requires fresh approval of a newer revision followed by explicit activation.

## Transactional event contract

Every repository transition inserts its audit record and outbox events in the
same caller-owned transaction. This includes direct repository callers and the
Delivery acceptance savepoint. Rollback removes all of them. No external event
dispatch or metrics increment happens before commit.

Events use the `marketing.scheduling_job.` prefix with `activated`, `claimed`,
`handed_off`, `blocked`, `cancelled`, `superseded`, `lease_expired`,
`handoff_unavailable` and `requeued` suffixes. Recovery can emit both
`lease_expired` and `blocked`; known nonacceptance can emit `handoff_unavailable`
and either `requeued` or `blocked`. These are distinct facts about one transition.

The outbox operation key and event ID are deterministic UUIDs derived from job,
transition version and event type. The existing unique operation key and
`ON CONFLICT DO NOTHING` deduplicate replay without aborting the transaction.
Command operation IDs are also preserved in the payload and audit history.
`correlationId` is stable for the job and matches the Delivery envelope.

Payloads contain only IDs, transition version, status, actor kind and allowlisted
reason codes. Content, assets, credentials, account metadata, worker identities,
cancellation text and exception messages are not copied. Realtime events remain
workspace scoped. Open calendars, content caches and scheduling inspectors refresh
on these events; duplicate SSE event IDs do not trigger another refresh.

`GET /workspaces/{workspace_id}/scheduling/jobs/{job_id}/history` exposes the
append-only audit, after the same content and campaign authorization as job
inspection. `limit` is capped at 100; `before_version` provides stable pagination.
It returns the Delivery correlation ID without exposing raw worker identities.

## Metrics

The private worker writes `scheduling_batch_metrics` after committed work. Two
aggregate SELECTs collect workspace metrics independently of batch/job count:

| Log field                             | Meaning                                                      |
| ------------------------------------- | ------------------------------------------------------------ |
| `job_gauges.pending`                  | Jobs waiting for a claim                                     |
| `job_gauges.due`                      | Pending jobs at or before database time, including late jobs |
| `job_gauges.claimed`                  | Leased jobs                                                  |
| `job_gauges.handed_off`               | Jobs durably accepted by Delivery; not published             |
| `job_gauges.blocked`                  | Jobs requiring intervention                                  |
| `job_gauges.cancelled`                | Cancelled jobs                                               |
| `job_gauges.superseded`               | Retired jobs                                                 |
| `retained_transition_totals.requeued` | Retained committed requeue/revalidation events               |
| `retained_transition_totals.expired`  | Retained committed lease-expiry events                       |
| `failed_count`                        | Failed processing attempts in this batch                     |

Export job counts as gauges and retained event totals as snapshots; do not sum
successive snapshots. Event retention can reduce retained totals. These are not
lifetime counters. For failure counters, filter `scheduling_job_processed` and
sum its `failed_count`; each log includes the job correlation ID. Do not also sum
the batch summary. IDs are diagnostic log fields, not metric labels. An unknown
handoff/commit outcome counts as a failed attempt and leaves its lease recoverable;
it never manufactures a failed terminal state or a publication result.

Validation is in `test_scheduling_integration.py`, PostgreSQL scheduling lifecycle
tests, realtime cache-refresh tests and the calendar state component tests.
