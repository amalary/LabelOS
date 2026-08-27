# Campaign Domain Contract

Stage 2 formalizes the canonical Campaign domain for LabelOS. This contract
extends the existing organization-owned `campaigns` resource; it does not replace
the table or reinterpret existing campaign records as releases.

## Definition

A Campaign is a workspace-scoped operational container. It coordinates work
across artists, releases, people, goals, milestones, assets, departments, and
eventually AI agents.

Campaigns are broader than release plans. A campaign may coordinate one release,
many releases, no releases, a catalog initiative, an artist development effort,
or a marketing workstream. Application code must not assume one campaign equals
one release.

In the current schema, workspaces are backed by `organizations`, so the canonical
workspace ownership column remains `organization_id`. New APIs and service code
should use `workspace_id` terminology at boundaries while mapping to
`organization_id` until a distinct workspace table exists.

## Core Model

The canonical Campaign model supports:

| Field | Required | Notes |
| --- | --- | --- |
| `id` | Yes | Stable Campaign identifier. |
| `organization_id` | Yes | Current workspace ownership boundary. |
| `name` | Yes | Human-readable campaign name. |
| `description` | No | Operational brief or summary. |
| `campaign_type` | Yes | Extensible type enum. |
| `status` | Yes | Lifecycle status enum. |
| `start_date` | No | Planned or actual start date. |
| `target_end_date` | No | Planned target completion date. |
| `created_at` | Yes | Timestamp from the shared timestamp mixin. |
| `updated_at` | Yes | Timestamp from the shared timestamp mixin. |
| `created_by_user_id` | No | Auth user that created the record, when known. |
| `created_by_profile_id` | No | Universal Profile for the creator, when known. |
| `owner_profile_id` | No | Universal Profile accountable for the campaign. |
| `primary_artist_id` | No | Optional primary workspace catalog artist. |
| `release_id` | No | Legacy nullable single-release pointer retained for compatibility. |

`created_by_profile_id` and `owner_profile_id` must refer to profiles that are
members of the campaign workspace when supplied. This is a service-level invariant
until profile/workspace membership constraints can be expressed directly.

`primary_artist_id` points at the workspace-owned `artists` catalog resource. If
that artist has an `artist_profiles` row, consumers can traverse from the catalog
artist to the person-backed artist profile.

## Campaign Types

Initial campaign types are intentionally small:

- `release` - work coordinated around one or more releases.
- `marketing` - audience, content, advertising, publicity, or growth work.
- `artist_development` - career, creative, audience, or operational development
  for an artist.
- `catalog` - back catalog, archival, rights, or catalog growth initiatives.
- `other` - valid fallback for imported or not-yet-classified work.

New types should be added only when they change behavior, permissions, workflow,
reporting, or user-facing grouping. Free-form labels and tags should live in a
separate taxonomy or metadata layer rather than expanding this enum prematurely.

## Lifecycle

Canonical Campaign lifecycle values:

- `draft` - captured but not ready for planning or execution.
- `planning` - being scoped, staffed, scheduled, or budgeted.
- `active` - currently in execution.
- `paused` - intentionally suspended but expected to resume.
- `completed` - finished successfully or operationally closed.
- `cancelled` - stopped before completion and not expected to resume.
- `archived` - retained for history and hidden from active operational views.

Operational views should treat only `planning`, `active`, and `paused` as open
work by default. Destructive deletion is not part of the lifecycle contract;
archival should be preferred for records with downstream activity.

## Release Coordination

The existing nullable `campaigns.release_id` is retained as a compatibility
pointer for old code and simple single-release workflows. New domain logic should
prefer an association table that links campaigns to releases.

Rules:

- A campaign can link to zero, one, or many releases.
- A release can participate in zero, one, or many campaigns.
- `campaigns.release_id` may mirror the primary release while legacy callers
  still depend on it, but it must not be treated as the complete set of releases.
- Multi-release workflows should write to the campaign-release association first.
- Services must verify that linked releases share the campaign workspace.

## Attachment Points

Stage 2 creates contract-level attachment points without implementing every
future subsystem:

| Area | Attachment Point |
| --- | --- |
| Releases | Campaign-release association records. |
| Marketing | Campaign type plus future marketing plans, channels, calendars, and spend. |
| Legal | Future legal reviews, contract links, rights checks, and policy gates. |
| Tasks | Future campaign-owned tasks, milestones, assignments, and dependencies. |
| Assets | Future campaign asset links for creative, audio, video, imagery, and files. |
| Budgets | Future budget, spend, forecast, and approval records. |
| Analytics | Future campaign-attributed metrics, events, reports, and goals. |
| Approvals | Future campaign approval requests, states, signoffs, and escalation history. |
| Agents | Future AI agent assignments, run history, recommendations, and audit metadata. |

Each future subsystem should attach to Campaign by `campaign_id` and preserve
workspace isolation. Cross-workspace campaign coordination requires a separate
explicit collaboration model and is out of scope for this contract.

## Authorization And Realtime

Existing campaign capabilities remain valid:

- `marketing.campaign.view`
- `marketing.campaign.create`
- `marketing.campaign.edit`
- `marketing.campaign.approve`

The legacy WorkOS-style permissions `campaigns:view` and `campaigns:manage`
remain compatibility permissions. Future workflow-specific operations should use
capabilities rather than adding broad permissions.

Realtime event types such as `campaign.updated` should identify the Campaign as
the entity and include workspace-scoped payloads. Agent-executed campaign changes
must include actor and audit metadata when the agent subsystem is attached.
