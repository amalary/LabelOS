# Analytics Objects

Analytics Objects provide workspace-scoped metric definitions and observations
for workspace, artist profile, campaign, and supported campaign child targets.
The feature intentionally does not introduce a unified campaign object registry.

## Data Model

The canonical tables are:

- `analytics_providers` - workspace-owned source abstraction for internal and
  external analytics systems.
- `analytics_metric_definitions` - workspace-owned metric catalog keyed by
  provider and metric key.
- `analytics_observations` - workspace-owned time-series observations with
  typed value columns.

Workspace APIs use `workspace_id`; database rows store that boundary as
`organization_id`.

Observation targets are represented by:

- `target_type = workspace` with `target_id = workspace_id`.
- `target_type = artist_profile` with `artist_profile_id` and matching
  `target_id`.
- `target_type = campaign` with `campaign_id` and matching `target_id`.
- `target_type = campaign_object` with `campaign_id`,
  `campaign_object_type`, `campaign_object_id`, and matching `target_id`.

Supported campaign object types are currently `goal` and `milestone`.

## Provider Boundary

Providers are deliberately represented as source records, not provider-specific
tables. The generic provider model stores the workspace, stable provider key,
display name, provider type, optional external account id, and metadata needed
to attribute metric definitions and observations.

Future provider adapters should live outside the core observation model. They
should translate external records into `AnalyticsMetricDefinitionCreate` and
`AnalyticsObservationCreate` payloads, supply deterministic idempotency keys,
store provider sync cursors in adapter-owned state, and keep credentials out of
analytics rows. Provider-specific behavior should not branch inside the core
analytics service unless it is a shared correctness rule.

## Validation And Security

Analytics API routes require authentication and then enforce capabilities
through the authorization service:

- `analytics.view` for providers, metric definitions, observations, latest
  values, series, and previous-period comparison.
- `analytics.create` for metric definitions and observation ingestion.

Services validate target ownership before writing observations or accepting
target filters. Artist profiles must resolve through workspace-owned artists;
campaigns must belong to the workspace; campaign child objects must belong to
the supplied campaign and workspace. Unsupported `campaign_object_type` values
are rejected.

Metric definitions own the value type. Observation writes clear all unrelated
value columns and require exactly the typed value column implied by the metric:

- `integer` and `decimal` use `value_numeric`.
- `string` uses `value_text`.
- `boolean` uses `value_boolean`.
- `json` uses `value_json`.

Numeric aggregations (`sum`, `average`, `min`, `max`) are allowed only when a
query resolves to one numeric metric, one provider, and one unit. `latest` and
`count` remain valid for non-numeric metrics.

## Idempotency And Ingestion

Observation idempotency is scoped by workspace, provider, and
`idempotency_key`. Rows with idempotency keys also store a deterministic
fingerprint of the normalized observation payload. Repeated single writes with
the same key and payload return the existing observation without publishing
another realtime event. Reusing the same key with a different payload is
rejected as an idempotency conflict.

Bulk ingestion is all-or-nothing: the service validates the full batch first,
rejects duplicate idempotency keys inside a request for the same provider,
reuses existing matching idempotency rows, rejects idempotency conflicts before
writing new rows, and publishes one batch realtime event only when new
observations are created.

## Query Surfaces

Backend routes live under `/api/v1/workspaces/{workspace_id}/analytics`.
Frontend proxy routes live under `/api/workspaces/{workspaceId}/analytics`.

Read APIs support provider, metric, target, artist, campaign, campaign child,
date range, pagination, latest observation, daily series, and previous-period
comparison filters. Single-metric numeric series and previous-period
aggregations execute in SQL; mixed or nonnumeric read paths preserve typed-value
behavior in the service layer. The frontend shared read surface is used by
workspace analytics, artist profiles, and campaign detail pages, including goal
and milestone inspection. Realtime analytics events invalidate workspace-scoped
analytics caches without forcing a full route refresh on the analytics page.

Agent-facing analytics operations are structured around stable object refs:
`workspace`, `artist_profile`, `campaign`, `goal`, and `milestone`. Campaign
child refs carry the parent `campaign_id` so service validation can preserve
ownership without a registry table.

## Typed Campaign Child Architecture

The current `campaign_object_type + campaign_object_id` approach should remain
while campaign analytics only targets a small, explicit set of child resources
whose ownership can be validated by direct service checks. It keeps the schema
simple, avoids duplicating Campaign or Universal Profile data, and does not add
an abstract table before the product needs one.

A unified campaign object registry would be justified only when at least one of
these becomes true:

- Many more campaign child types need analytics, permissions, activity, or
  attachments through the same generic APIs.
- Cross-child querying requires a single canonical child lifecycle, sort order,
  or polymorphic display contract.
- External integrations need stable object identifiers independent of each
  child table.
- Child-level authorization diverges from the parent campaign and cannot be
  expressed cleanly with direct ownership checks.
- Query plans or indexes become difficult to maintain because child-object
  targets outgrow `goal` and `milestone`.

Until then, adding a registry would increase write paths and consistency risks
without improving correctness.
