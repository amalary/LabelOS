# Social Account Connections

## Purpose

Social Account Connections model destinations that LabelOS can route marketing
content to. They answer operational questions such as which account a draft post
targets, whether that destination is healthy, and whether publishing should be
automatic or assisted by a human.

They are not profile metadata, analytics-source attribution, or channel taxonomy:

- `ProfileLink` is profile metadata, not an operational social connection.
- `AnalyticsProvider` is analytics-source attribution, not an account connection.
- `MarketingContentItemChannel` represents content-channel targeting, not
  credential or connectivity ownership.

## Workspace Terminology

`SocialAccountConnection` is the canonical account connection model. API routes
use `workspace_id`; database rows store the same workspace boundary as
`organization_id`.

Development docs and APIs should use "workspace" for product-facing behavior.
Database models and lower-level repositories may use "organization" because
workspace ownership is persisted through `organization_id`.

## Data Model

The model stores:

- workspace ownership through `organization_id`
- optional `artist_profile_id`
- provider key, external account id, handle, display name, and profile URL
- `connection_method`
- lifecycle `status`
- provider-neutral `capabilities`
- opaque `credential_ref`
- token expiry, sync, health, and last error metadata
- sanitized provider metadata
- user/profile creator references

Artist association is optional. Workspace-level label or marketing accounts can
exist without an artist profile, while artist-specific accounts can be linked to
an `ArtistProfile`. Services validate that any supplied artist profile belongs
to the workspace.

Active duplicate prevention is scoped to workspace, provider, connection method,
and external account id. Disconnected rows do not block replacement.

## Connection Methods

`connection_method` is one of:

- `assisted` - a manually operated account destination. It has no OAuth
  credential and exposes `manual_publish`.
- `direct_api` - a first-party provider OAuth/API connection owned directly by
  LabelOS. YouTube is the reference implementation.
- `third_party` - a connection brokered through a future social integration
  vendor. Vendor ids and tenant details stay in adapter metadata or adapter-owned
  storage.

The default provider registry always includes assisted adapters for supported
providers. Direct API adapters are registered only when required configuration
exists. No commercial third-party vendor is selected yet.

## Lifecycle

Connection statuses are:

- `pending`
- `connected`
- `limited`
- `reconnect_required`
- `disconnected`
- `error`

Assisted connections are registered as `connected` because LabelOS can route
work to a human-assisted destination immediately. Absence of credentials is not
a reconnect signal for assisted connections.

Direct API and third-party connections move through OAuth or vendor connection
flows, health checks, metadata sync, credential refresh, and disconnect. Invalid
status transitions are rejected. Disconnected connections are terminal for
updates, clear credential references, and can be replaced by a new active
connection for the same external account.

Health checks map provider-neutral failures into stable statuses. Authorization
or credential failures become `reconnect_required`; insufficient scope becomes
`limited`; malformed provider responses and sync failures become `error`; rate
limits and provider outages preserve the current status.

## Capabilities

Capabilities describe what the connected destination can do:

- `content_publish`
- `manual_publish`
- `manual_metrics`
- `account_analytics_read`
- `post_analytics_read`

These are provider-neutral connection capabilities. They are distinct from user
authorization capabilities such as `marketing.account.view`,
`marketing.account.manage`, `marketing.content.edit`, or analytics permissions.
User capabilities determine whether the actor may view or mutate LabelOS
resources. Social account capabilities describe the external destination's
operational abilities.

Resolved capability helpers expose:

- `can_auto_publish`
- `requires_manual_publish`
- `supports_manual_metrics`
- `can_read_account_analytics`
- `can_read_post_analytics`

Publishing and analytics execution are intentionally outside the connection
adapter contract.

## Provider Adapter Architecture

`SocialAccountConnectionProvider` is the provider-neutral adapter contract for
connection lifecycle behavior only:

- validate account identity
- normalize account identity and capabilities
- build authorization requests
- complete OAuth exchanges
- refresh credentials
- retrieve account identity
- check health
- synchronize metadata
- disconnect

Adapters normalize external provider or vendor responses into the canonical
`SocialAccountConnection` shape. Product surfaces and downstream workflow code
should depend on canonical fields, not vendor-specific payloads.

`ThirdPartySocialAccountConnectionProvider` is the vendor-neutral boundary for
future integration-service account links. It keeps vendor connection ids,
service account ids, tenant ids, and similar details under
`provider_metadata["third_party"]` or adapter-owned credential/config storage.
Those details must not leak into Draft Posts, calendars, scheduling contracts,
or delivery contracts.

## CredentialStore Boundary

Credential material is never stored in `SocialAccountConnection` rows. The row
stores only `credential_ref`, an opaque reference to `CredentialStore`.

`CredentialStore` supports `put`, `get`, `replace`, and `delete`. The local test
implementation is in memory; configured production storage can use GCP Secret
Manager. `CredentialPayload` intentionally redacts its string representation,
and API responses sanitize metadata keys that look credential-bearing.

Provider metadata is for non-secret account/provider details. Sensitive keys are
filtered before persistence and serialization.

## OAuth State Security

OAuth state is persisted in `OAuthAuthorizationState` with:

- workspace ownership as `organization_id`
- SHA-256 `state_hash`, never the raw nonce
- actor user binding
- provider and connection method binding
- pending/consumed/expired status
- expiry timestamp
- relative `safe_redirect_path`
- optional PKCE verifier credential ref

State nonces are random URL-safe values, expire after a short TTL, are consumed
once, and must match workspace, actor, provider, and connection method on
callback. Redirect targets must be relative application paths; callback failure
redirects include only status, not provider tokens or error details.

## Assisted Fallback Workflow

Assisted connections provide the fallback when a platform cannot be connected by
API or when LabelOS intentionally defers automatic publishing. They expose
`manual_publish`, pass health checks as `assisted_action_required`, and can be
selected as marketing content channel destinations.

`prepare_assisted_publish_handoff` returns a read-only handoff DTO for a single
approved channel and selected intended publication time. It includes account
identity, capability, health, assets, copy, hashtags, safe profile link,
instructions, and an optional future completion payload. It does not create
tasks, schedule work, publish posts, or write completion state.

## Draft Posts And Channels

Draft Posts are represented by `MarketingContentItem`. Per-channel targeting is
represented by `MarketingContentItemChannel`.

`MarketingContentItemChannel.social_account_connection_id` optionally points to
the selected `SocialAccountConnection`. The channel owns content targeting
fields such as channel, placement, planned times, copy override, asset refs, and
publication result fields. The social account connection owns destination
identity, health, credential reference, and capabilities.

Channel destination validation enforces canonical connection ownership and
publishing capability rules before a draft channel can point at an account:
workspace, provider, artist compatibility, non-disconnected status, and
`content_publish` or `manual_publish`. Health states such as
`reconnect_required`, `pending`, `limited`, or `error` remain selectable so
planning can preserve the intended destination while the readiness projection
surfaces delivery warnings.

## Destination Resolver

`resolve_destinations` evaluates workspace connections for a requested provider,
optional artist profile, optional desired capability, and optional requested
connection id.

It returns provider-neutral destination readiness:

- whether an account is usable
- whether it supports automatic publication
- whether it requires assisted publication
- whether it can provide analytics
- unavailable reasons such as missing connection, disconnected,
  reconnect-required, connection error, missing capability, provider mismatch,
  wrong artist, or wrong workspace

This keeps Draft Posts and future schedulers from embedding provider-specific
eligibility logic.

## Calendar And Realtime

Campaign calendar projections include marketing content item and
marketing-content-channel events. Channel events include the resolved social
account connection so calendar consumers can expose destination readiness
without owning credential state.

Social account mutations publish workspace-scoped realtime/activity events with
sanitized payloads:

- `marketing.social_account.connected`
- `marketing.social_account.updated`
- `marketing.social_account.disconnected`
- `marketing.social_account.health_changed`

Frontend realtime handling invalidates social account connection caches when
these events arrive for the current workspace.

## Deferred Boundaries

The [Scheduling Engine contract](scheduling-engine-contract.md) owns future
scheduling decisions:

- selecting approved content for publication
- preserving channel authoring time as an immutable approved job snapshot
- due-time validation, claims, cancellation, supersession, and durable handoff
- scheduling state separate from provider delivery state

Publishing Delivery owns future execution:

- automatic provider publication calls
- assisted manual task lifecycle
- manual assignment and reminders
- delivery retries and failure history
- final write-back of `published_at`, `external_post_id`, and `external_url`
- publication audit/history beyond the current channel result fields

Social Account Connections intentionally stop at destination identity,
credential reference, connection lifecycle, capabilities, health, and
destination resolution.
