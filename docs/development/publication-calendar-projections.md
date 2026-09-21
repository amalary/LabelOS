# Publication-backed calendar projections

Publishing Delivery owns external publication outcome. Calendars read a successful
Publication (`status = published`), its evidence timestamp, provider resource ID,
URL and immutable destination/channel intent. They do not update Marketing
content status, revisions, approval or legacy publication timestamps.

`repositories/publication_calendar.py` supplies the shared, workspace-scoped read
model. Campaign Calendar exposes `marketing.content.published` and
`marketing.content.channel_published` for each successful Publication with IDs
`publication:{publication_id}:{event_type}`. The two event types are alternate
content/channel views of the same external success, not two deliveries. Marketing
Content Calendar consumes the same facts in the content list response and renders
one channel-published instance per Publication alongside existing planning entries.
Published filters and visible-range queries include successful delivery even when
the authored content remains approved or the schedule falls outside the range.

Retries preserve Publication ID; attempts are never calendar event sources.
Duplicate provider results remain fenced by Publishing persistence. Legacy
published projections remain available for content without authoritative success;
a successful Publication suppresses the corresponding legacy content/channel
projection, including when its timestamp falls outside the requested range.

Both calendars invalidate their workspace-scoped caches on the existing
`marketing.publication.changed` transactional outbox event. No extra state owner,
backfill, migration, synthetic content update or duplicate outbox event is needed.
An invalidation during an in-flight calendar read queues a fresh read after that
request settles. Reloads query durable Publication state, and existing UTC/IANA timezone conversion
handles DST boundaries without changing event identity.

Human `complete_manual` actions explicitly remain human assertions under the
existing recovery contract. They do not produce an authoritative published event.
Reconciliation that transitions the Publication to `published` does. Campaign
context is optional at the projection boundary; the current Marketing schema
requires a campaign, so standalone non-campaign Publications cannot currently be
created. This change does not relax that authoring invariant.

Regression coverage includes SQLite and PostgreSQL success/retry/reconciliation,
stale duplicate results, multiple channels/destinations/providers, failures,
campaign/workspace scoping, legacy deduplication, fresh-session reloads, absent
campaign context, DST folds/gaps and realtime cache refresh. Existing scheduled,
approval and campaign events retain their original sources and IDs.

## Verification on 2026-09-17

- Requested API selection (`calendar or marketing or publishing or publication or
realtime`), with local PostgreSQL enabled: 902 cases verified. The broad run
  passed 898; four cases had loaded an earlier multi-channel fixture missing
  schedule fields, and all four passed on the corrected rerun.
- New Publication calendar regression file: 20 passed across SQLite/PostgreSQL.
- Delivery orchestrator: 38 passed.
- Calendar, Marketing, Publishing, scheduling and realtime frontend suites:
  297 passed across 14 files, including the in-flight refresh race.
- Python and TypeScript type checks, changed-file Ruff/ESLint, Black/Prettier and
  diff whitespace checks passed.

The second HIGH calendar blocker is CLOSED for the supported authoritative
Publication lifecycle. The existing non-campaign persistence limitation and
human-versus-provider completion distinction above remain explicit.
