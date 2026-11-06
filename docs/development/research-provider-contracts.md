# A&R provider adapter contracts

Prompt 11 adds the [public music adapter suite](public-music-providers.md).
The following describes the original Prompt 10 boundary; adapters remain explicitly
composed. `SourceProvenance` now also accepts optional source/attribution/license
links, bounded provider fields and an expiry timestamp. Raw vendor payloads remain
outside the normalized contract.

`apps/api/src/labelos_api/research` defines the version-one boundary for future
A&R research and discovery integrations. It includes no vendor implementation,
automatic registration, API route, worker, database migration or live collection.
Adapters are supplied explicitly to `ProviderClient`.

## Relationship to existing systems

- `AnalyticsProvider` remains the workspace-owned source record. Its ID and key
  appear in `CollectionContext`; provider-specific behavior stays outside analytics
  models and services.
- Existing social account providers manage connection lifecycles. Research adapters
  manage read-only artist, catalog and metric retrieval. Publishing adapters retain
  their separate side-effect and reconciliation semantics.
- The development dashboard performance mock remains unchanged.
- `CredentialStore` and `CredentialPayload` supply transient credentials through the
  existing storage abstraction. No credential column or plaintext settings file is
  introduced.
- Collection run and dataset version IDs refer to the existing governance system.
  Record-level source references use the opaque UUID shape accepted by
  `provenance.RawRecordCreate`.

## Adapter interface

Implement `ResearchProviderAdapter` with an immutable `ProviderDescriptor` and the
four async methods below. Inject a transport into each future adapter so tests can
exercise the vendor mapping without a network or database.

| Method           | Request                                            | Response                |
| ---------------- | -------------------------------------------------- | ----------------------- |
| `search_artists` | Query, limit, optional cursor                      | `ArtistSearchResponse`  |
| `lookup_artist`  | Provider-local artist ID                           | `ArtistLookupResponse`  |
| `lookup_catalog` | Artist ID, release/track resource, limit, cursor   | `CatalogLookupResponse` |
| `observations`   | Subject, metric keys, time interval, limit, cursor | `ObservationsResponse`  |

Each method receives a `CollectionContext` and a redacted `CredentialPayload`
(or `None` for public providers). Only declared capabilities can be invoked.
Undeclared methods may raise `AdapterFailure(unsupported_operation)`. Descriptors
name supported resources, the adapter version, maximum page size, authentication
method, required credential fields/scopes, and rate-limit windows/scopes.
An empty rate-limit tuple means no known declared limit, not unlimited access.

Python constructors require explicit types, including tuples, UUIDs, aware datetimes
and `Decimal` values. Contracts reject extra fields, non-finite numbers, blank
identifiers, and mismatched metric types. They are frozen and revalidated when an
adapter returns them, including nested records. `model_dump_json()` and
`model_validate_json()` provide the wire representation.

Artists contain provider-local identities, names and genres. Catalog items contain
release/track identity, title, contributing artist IDs and optional release date;
ISRC and duration belong to tracks. Observations retain subject, metric key,
explicit scalar value type, unit and observation time. Scalars map to analytics
integer/decimal/string/boolean value types. Arbitrary JSON metrics and provider
payloads are deliberately outside this normalized contract. Missing values must
never become zero. Provider-local identity is not evidence that two providers refer
to the same artist or metric semantics.

List methods return a page, including a valid empty page for a successful query
with no matches. A missing artist lookup raises `data_unavailable`. The observation
interval is `[start_at, end_at)`. A `None` cursor indicates the final page. Cursors
must be non-secret opaque tokens; credential-bearing URLs stay in adapter-private
state. The client checks page size, cursor advancement, requested catalog artist
and resource, lookup identity, and observation subject/metric/time boundaries.

## Credentials and ownership

`ProviderConfiguration` accepts only workspace/provider binding, a timeout, and an
optional credential reference produced by the existing store. API keys, tokens and
client secrets have no configuration fields. GCP Secret Manager references are
supported; `memory://` references are only for local development and tests.

Future production composition must use `build_credential_store(settings)`, whose
existing startup policy rejects the memory backend in production-like environments.
The client retrieves credential material only when calling a supported operation;
it checks required nonempty fields and, if declared, `granted_scopes` in the stored
payload. Vendor adapters still validate expiry/revocation with their provider.
OAuth exchange, credential provisioning and rotation stay in the credential and
connection lifecycle, outside this read-only boundary.

The future collection service must authorize workspace membership and verify
provider, credential-reference, run and dataset-version ownership and governance
eligibility before invoking an adapter. The client checks configuration/context
consistency and response provenance; these checks do not query the database or
grant authorization. No integration is wired into application startup in this phase.

Never log credentials, transport exceptions, raw provider payloads or
credential-bearing URLs. Adapters must keep secrets out of all normalized text,
IDs and cursors. Schema validation cannot identify arbitrary secrets copied into
otherwise valid strings.

## Provenance and persistence

Every page and failure carries the caller's collection context, including empty
pages. Every record carries `SourceProvenance` with that same context, an opaque
source reference and an aware collection timestamp. The client rejects mismatches
in workspace, provider ID/key, collection run or dataset version.

For later ingestion, `dataset_version_id`, `collection_run_id` and
`source_reference` map to `RawRecordCreate.version_id`, `collection_run_id` and
`source_reference`. Source references should consistently identify the same collected
source record across mapping steps. Persist normalized lineage through the existing
provenance service; having these identifiers does not itself create lineage rows.
After resolving workspace-owned subjects and metric definitions, observation
values can be mapped to existing analytics create payloads. Deterministic analytics
idempotency keys, cursor persistence, run transitions and raw-payload retention
remain responsibilities of the future collection/ingestion service.

## Failures and scheduling

`ProviderClient` raises `ProviderError` containing a typed `ProviderFailure` with
context, operation and safe `FailureDetails`. It never returns an unvalidated
partial page. Adapters can raise `AdapterFailure` for vendor SDK or business-level
errors; the wrapper also normalizes HTTPX exceptions.

| Code                    | Typical cause                                 | Retryable hint |
| ----------------------- | --------------------------------------------- | -------------- |
| `authentication_failed` | Missing credentials/scopes, HTTP 401/403      | No             |
| `quota_exceeded`        | Exhausted subscription/quota, HTTP 402        | No             |
| `rate_limited`          | HTTP 429                                      | Yes            |
| `timeout`               | Client deadline, transport timeout, HTTP 408  | Yes            |
| `data_unavailable`      | Missing/unavailable record, HTTP 404/410      | No             |
| `provider_unavailable`  | Network/store outage, HTTP 5xx                | Yes            |
| `malformed_data`        | Invalid records or mapping/validation failure | No             |
| `unsupported_operation` | Capability/resource not declared              | No             |
| `invalid_request`       | Binding/page-size mismatch or other HTTP 4xx  | No             |
| `internal_error`        | Unexpected adapter exception                  | No             |

HTTP meanings vary by vendor: adapters should translate vendor-specific quota or
unavailability semantics into `AdapterFailure` before the shared HTTP fallback.
Rate/quota/availability errors may include bounded `retry_after_seconds`; HTTP
`Retry-After` supports seconds and HTTP dates. Invalid hints are discarded. Quota
exhaustion requires intervention or a separately established reset policy.

Retryability and rate limits are scheduling information only. The client performs
one invocation with a configured async deadline covering credential resolution and
adapter work; it never sleeps for rate limits or retries. Cancellation propagates.
Future transports must be asynchronous and cooperate with cancellation; blocking
SDK work cannot be preempted by an asyncio deadline. A distributed quota limiter,
retry policy and collection scheduler are not implemented here.

## Contract tests

`tests/research_provider_contracts.py` provides `ResearchProviderContractTests`.
Future adapter tests can inherit it and provide a `provider_case(scenario)` fixture
returning `(ProviderClient, CollectionContext)` backed by a mock transport. Required
scenarios are `success`, `malformed`, `authentication`, and `rate_limit`; fixtures
use the artist/metric requests in that module and a 60-second rate-limit hint.
Only declared operations run the failure scenarios; undeclared operations must
return `unsupported_operation`. Add vendor-specific mapping fixtures alongside
that suite.

`test_research_providers.py` supplies a mock implementation and exercises runtime
validation, cross-collection rejection, credentials, error sanitization, pagination,
deadlines, cancellation and provenance compatibility without live integrations.

Run from `apps/api`:

```sh
python -m pytest tests/test_research_providers.py -q
```
