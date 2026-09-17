# Publishing Provider Adapter Contract (Stage 4)

Stage 8 adds durable failure classification and retry eligibility; see
[publishing retries](publishing-retries.md) for the current execution policy.

Stage 5 adds an explicit YouTube implementation and registry factory; see
[YouTube publishing adapter](youtube-publishing-adapter.md). The Stage 4 behavior
below remains the default when no registry is supplied.

Publishing Delivery now routes through an explicit `ProviderRegistry` to a
`PublishingProviderAdapter`. External platform behavior belongs entirely to that
adapter. No real adapter, SDK, network client, endpoint, worker, or production
registration is introduced. The default registry is empty and fails closed.

## Interface and values

Defined in `apps/api/src/labelos_api/publishing/providers.py`:

```python
class PublishingProviderAdapter(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...
    def validate(self, request: PublicationRequest) -> ProviderResult | None: ...
    async def publish(self, request: PublicationRequest) -> ProviderResult: ...
    async def reconcile(self, request: PublicationRequest) -> ProviderResult: ...
```

- `ProviderCapabilities` exposes only `publish` and `reconcile` booleans.
- `PublicationRequest` is an immutable projection of the validated accepted
  envelope: workspace/publication/destination IDs, canonical provider, expected
  account identity fingerprint, stable publication idempotency key, bound attempt,
  channel, placement, caption, hashtags, and media.
- `PublicationMedia` carries approved bytes, SHA-256, and media type. It never
  resolves a URL. Content, media bytes, and destination identity are hidden in repr.
- `ProviderResult` carries a `ProviderOutcome`, optional sanitized external post
  ID, authoritative `confirmed_absent` assertion, and optional advisory
  `retry_after_seconds` (0–604800). No raw JSON, error text, SDK objects, credentials,
  or arbitrary metadata enter core code.

The orchestrator constructs the request; adapters cannot rewrite approved content.
`validate` is synchronous and side-effect-free, with no credential lookup or network
access. It returns `None` for ready, or a normalized rejection. Invalid preflight
results/exceptions return `invalid_adapter_validation` without starting an attempt.
Rejections leave the Publication pending (or retryable) and return their reason to
the caller. There is no preflight history transition or implicit retry loop.

Adapters normalize known provider responses and exceptions inside their methods;
a separate SDK-error-to-domain method is unnecessary. Unexpected exceptions and
malformed publish results become ambiguous evidence. Core code neither interprets
HTTP status codes nor logs provider error messages. Runtime validation runs both
at result construction and upon crossing the adapter boundary.

## Result semantics

| Provider outcome         | Required assertion/data                                                  | Existing durable Publication state            |
| ------------------------ | ------------------------------------------------------------------------ | --------------------------------------------- |
| `published`              | Sanitized nonblank final external post ID; no absence assertion          | `published`                                   |
| `accepted`               | External processing is unfinished; no final post ID or absence assertion | `manual_action_required`, unknown evidence    |
| `retryable_failure`      | Authoritative nonpublication                                             | `retryable_failure`, temporary unavailability |
| `permanent_failure`      | Authoritative nonpublication; request is invalid                         | `permanent_failure`, invalid content          |
| `authorization_required` | Authoritative nonpublication; authentication/authorization repair needed | `permanent_failure`, authorization required   |
| `rate_limited`           | Authoritative nonpublication; optional retry hint                        | `retryable_failure`, rate limited             |
| `ambiguous`              | Publication cannot be established or excluded                            | `manual_action_required`, unknown evidence    |
| `unsupported`            | Publish operation was not performed                                      | `permanent_failure`, destination unavailable  |

An authentication failure, rate limit, timeout, or partial upload after an uncertain
write does **not** prove nonpublication; the adapter must return `ambiguous` unless
it can establish absence. On reconciliation, absence means absence of the original
publication, not merely failure of the status query. A query authorization error
alone therefore cannot mark the publication permanently failed.

`accepted` is distinct in the application result, but deliberately uses Stage 1's
existing unknown/manual-action lifecycle. Acceptance is not success and never
permits republishing. This stage adds no schema, async job state, background poller,
or durable provider operation handle. Adapters may advertise reconciliation only
when they can locate the original attempt from the stable request identity. A
future provider that requires an opaque upload/job handle needs a concrete durable
receipt design before that capability is enabled; the core does not pretend an
in-memory response is recoverable after process death.

Authorization failures are terminal for this accepted publication; reconnecting
does not silently reactivate it. Retry hints are returned to the trusted caller,
not persisted as scheduling deadlines or enforced as a new retry policy.

## Registry and orchestration

The registry copies a trusted server-supplied mapping into an immutable view.
Canonical lowercase keys resolve exactly; there are no aliases, heuristic network
names, fallback adapters, dynamic imports, or public configuration routes. The
orchestrator uses the provider retained from the canonical destination, never a
client-selected adapter. Unknown providers return `unsupported_provider` and an
unsupported operation returns `unsupported_capability`, with no new attempt.
The fake adapter is only in tests and is never automatically registered.

`execute(..., registry=...)` preserves Stage 3's transaction boundaries:

1. Revalidate source/destination, resolve the adapter, validate locally, and commit
   the attempt start in a short transaction.
2. Call `publish` outside database transactions and locks.
3. Validate the result, bind normalized evidence to the canonical workspace,
   publication, destination and attempt in core code, then atomically persist the
   lifecycle transition, history, and outbox using the expected version.

`reconcile(..., registry=...)` reloads the retained envelope and latest attempt in
workspace scope, calls the optional adapter operation outside the transaction,
then uses the same version-guarded evidence path. It does not create another
attempt, call publish, or recheck mutable authoring approval. An unsupported lookup
leaves state unchanged: it is not evidence that the publication never happened.
Repeated pending/ambiguous observations leave an already unresolved publication
unchanged. Authoritative reconciliation can establish success or nonpublication.

Reconciliation is permitted only from `manual_action_required`. Looking up an
actively executing attempt could incorrectly report absence before its publish
request has been sent. A recovery host must establish that an interrupted attempt
is no longer executing and record interruption through the existing evidence port
before invoking reconciliation. There is no automatic stale-attempt takeover.

Only an explicit later execute can retry confirmed nonpublication. Cancellation,
unknown commits, and result-write failures retain Stage 3's recovery behavior.
Concurrent result commits cannot overwrite a newer lifecycle version. Stable
LabelOS keys alone do not guarantee external exactly-once delivery.

Before external I/O, each real adapter must resolve credentials within the request's
workspace and bind the authenticated account to the retained destination identity:
SHA-256 of canonical JSON `[provider, external_account_id]`. Account replacement
must never redirect accepted work or its reconciliation. This stage specifies the
obligation; no real credential implementation is supplied.

## Verification and Stage 5

`test_publishing_providers.py` uses a deterministic `FakePublishingAdapter` and an
in-memory SQLite repository. It needs no network or provider credentials. It covers
exact resolution, unknown providers, immutable requests, stable retry keys, all
normalized outcomes, malformed results, exception sanitization, capability checks,
preflight rejection, persisted lifecycle integration, and reconciliation without
republishing. Only Scheduling preparation is substituted; the repository,
transactions, evidence, history, and outbox are real. The existing PostgreSQL
`test_delivery_orchestrator.py` suite now uses the registry/contract and retains
its full Scheduling authorization, concurrency, rollback, and I/O-boundary tests.

Run the network-free contract/domain suites from `apps/api`:

```powershell
python -m pytest tests/test_publishing_providers.py tests/test_publishing_contracts.py -q
```

Validation on 2026-09-16: 182 network-free adapter/domain cases passed, including
50 Stage 4 cases. The existing delivery, publishing persistence, and Scheduling
handoff regression passed 170 cases with an isolated local PostgreSQL cluster and
SQLite where supported. API-wide Ruff, scoped Black, root Pyright, documentation
Prettier, and diff whitespace checks passed. No full API regression is claimed.

Stage 5 is ready to implement a YouTube adapter against this boundary. It must
prove account binding, local request validation, upload/error normalization,
idempotency and uncertain-outcome recovery with mocked provider responses before
production registration. Reconciliation support must reflect actual provider
guarantees. No YouTube, TikTok, Meta, or other platform response shape or behavior
has been added to the core domain.
