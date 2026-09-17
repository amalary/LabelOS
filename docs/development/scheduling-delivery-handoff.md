# Scheduling to Delivery acceptance boundary

The [Stage 3 Delivery Orchestrator](delivery-orchestrator.md) now supplies an
internal transactional receiver through this composer. Production receiver
selection remains unavailable; the original boundary below remains unchanged.

The internal `services.scheduling_handoff.accept_scheduling_handoff` composition
boundary implements the acceptance policy in the
[Scheduling Engine contract](scheduling-engine-contract.md). It is not a worker,
public endpoint, provider publisher, or production Delivery inbox. The only
deployable receiver is unavailable. The transactional successful receiver lives
exclusively in tests.

## Envelope and results

`PublishingDeliveryAcceptancePort.accept(session, request)` returns exactly one of:

- `DurableAccepted(receipt)`: stable receipt UUID, original idempotency key and
  envelope fingerprint. Acceptance becomes durable at the caller's outer commit.
- `RetryableUnavailable`: known nonacceptance, with a fixed safe reason code.
- `TerminalRejected`: invalid request or hard conflict, with a fixed safe reason
  code. No receiver details or input values are copied into the result.

`DeliveryAcceptanceRequest` retains its existing nested `ScheduleSnapshot` and
repository field names. `payload.envelope(request)` defines the wire/storage names:
`scheduling_job_id`, `workspace_id`, `content_item_id`, `content_channel_id`,
`social_account_connection_id`, `approval_request_id`,
`authorized_content_revision`, `schedule_generation`, `scheduled_for`,
`execution_mode`, `idempotency_key`, `correlation_id`, `artist_profile_id`,
`authoring_timezone`, `payload_schema_version`, and `content`.

The key is `labelos:scheduling:v1:{workspace_id}:{job_id}` and never changes with a
claim, fence, retry or recovery. Correlation is a UUID chosen once for the handoff;
reuse it on every attempt. SHA-256 covers the full canonical envelope, including
correlation and routing, and excludes only the fingerprint itself. Equal key and
fingerprint return the original receipt. Equal key and different fingerprint are
terminal conflicts; accepted content must never be overwritten. Receivers must
retain the complete envelope for durable readback after an ambiguous commit.

## Resolved normalization policy: payload v1

The exact fixtures are in `tests/test_scheduling_handoff.py`.

- UTF-8 JSON, sorted object keys, compact separators, no NaN, no ASCII escaping.
  Unknown fields, noncanonical bytes and unsupported versions are rejected.
- Text uses Unicode NFC and LF newlines. Caption uses a nonempty channel override,
  then parent copy; absent copy remains JSON null. Whitespace within copy is kept.
- Channel and placement are explicit. Asset order is preserved, including repeats.
  Nonempty channel assets override parent assets; empty channel assets inherit.
- Hashtags come only from structured parent then channel `metadata.hashtags`
  lists. Ignore nonstrings and blanks; strip surrounding whitespace, add `#`
  where missing, deduplicate case-insensitively while retaining first spelling
  and order. Do not infer hashtags from caption text.
- The delivery metadata allowlist is empty in v1. No account metadata, arbitrary
  content metadata, credentials, credential references, raw tokens, profile URLs,
  completion results or provider results are serialized. Caption and media remain
  the authorized user content, not sources of account credentials.
- Instants use UTC with six fractional digits and `Z`; IDs use canonical UUID text.
  Only automatic execution is accepted. Manual execution requires a future contract.

## Resolved asset policy: approved digest plus embedded immutable bytes

There is no versioned asset store in the current content model. An arbitrary JSON
ID, a bare URL, or a claim that a URL is immutable cannot establish immutability.
Each selected **approved source** asset reference must have exactly these fields:

```json
{ "sha256": "<64 lowercase hex digits>", "size_bytes": 123, "media_type": "image/png" }
```

Preparation receives a server-side mapping from digest to bytes. It performs no
network I/O and never fetches a URL under database locks. The approved reference's
digest and size must match those bytes. Media types are restricted to syntactically
valid image, video or audio types without parameters. Each nonempty asset is capped
at 16 MiB; the complete canonical content payload is capped at 24 MiB.

The snapshot retains each reference plus canonical `content_base64`. The receiver
decodes it and independently verifies size and SHA-256. The full bytes are retained
in the accepted envelope, so subsequent edits, deletion, storage replacement or
expired download links cannot change accepted content. Before acceptance, source
references and copy are reloaded under locks and normalized again; they must match
the prepared snapshot exactly. The approved digest also prevents a mutable source
from changing bytes between approval and preparation.

Legacy mutable references fail closed. Converting them to digest references is a
material content edit requiring fresh approval through existing content authoring;
handoff does not silently upgrade them. Larger assets require a future verified
immutable storage adapter and payload version; they are not accepted by weakening
these checks. This policy resolves the normalization and immutability gates for
this boundary without inventing an unverified external storage guarantee.

## Transaction and deployment integration

The caller owns one PostgreSQL transaction. The internal
[bounded processor](scheduling-processor.md) scopes its server-constructed workload
principal and locks durable execution controls before calling the composer. Its
host must authenticate that principal; the composer must not be exposed to user
JSON or wired directly to an unauthenticated worker. Controls are trusted
transaction-local inputs, not environment-only promises.

The composer locks source/approval/job rows in the existing order, checks current
approval, revision, generation, schedule, destination and effective artist, and
verifies the worker/fence/lease and due window before calling the receiver. It
records `handed_off` only for `DurableAccepted` with matching bindings. The final
conditional write checks lease and lateness again. Inbox insertion and job/history
write use the same session and transaction. A savepoint rolls back both on rejection,
unavailability, mismatched receipts or failure. The outer caller still commits once.
No publication fields or published events are written.

An accepted replay returns its original receipt even after later content edits or
execution shutdown. A mismatched replay fails. An unavailable receiver leaves the
job unchanged; this module does not introduce a retry loop. Unexpected/ambiguous
failures propagate for durable reconciliation; they are not classified as safe retries.
Logs contain only a fixed outcome and validated correlation UUID, never payloads,
account objects, receiver representations or exception messages.

`DELIVERY_RECEIVER_BACKEND=unavailable` is the default and only deployable selection.
Both startup validation and the receiver factory reject fake, memory, successful
no-op and unknown backends in every environment, including production. A test can
inject a fake directly; no production fake implementation is shipped. Receiver
readiness must remain false. Successful execution requires a certified transactional
Delivery adapter and an authenticated worker host. Neither is enabled by the processor.

`prepare_assisted_publish_handoff` remains unchanged and read-only. Its current
mutable asset references and manual completion fields do not meet this acceptance
schema. It is not called for automatic delivery and never counts as acceptance.

## Verification

Unit tests cover exact canonical fixtures, fallback and ordering, immutable asset
copying, digest tampering, mutable reference rejection, schema/fingerprint binding,
revision/scope checks, secret exclusion and production configuration. PostgreSQL
tests use a test-only durable inbox with a unique key and complete envelope bytes.
They verify stable and concurrent receipt replay, hard conflicts, later edits,
retryable/terminal nonacceptance, partial-write and outer rollback, receipt mismatch,
fresh source/destination/fence validation and sanitized structured logs.

Run from `apps/api` with `TEST_POSTGRES_URL` pointing to a disposable local test
database; the fixture creates and drops isolated schemas:

```powershell
python -m pytest tests/test_scheduling_handoff.py tests/test_scheduling_handoff_postgres.py tests/test_scheduling_contracts.py tests/test_scheduling_repository.py tests/test_scheduling_activation.py -q
```

Local validation on 2026-09-15 covered 278 scheduling cases, including eligibility:
277 passed in the combined run; the remaining golden-fixture encoding error was
fixed and all 42 payload/configuration cases passed on focused rerun. This includes
52 new boundary cases (42 unit/configuration and 10 PostgreSQL). Scoped Ruff,
Black, Pyright, Markdown Prettier and `git diff --check` passed.

Broader auth/credential checks found an existing generated frontend registry missing
`marketing.content.schedule`; those files were not changed. Including the existing
config module in Pyright also reports its pre-existing string-versus-list
`allowed_frontend_origins` constructor argument. Neither issue is caused by the
receiver configuration change.
