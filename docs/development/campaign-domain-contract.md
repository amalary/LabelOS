# Campaign Domain Contract

Stage 12 defines Campaigns as a production integration boundary for LabelOS. The
current feature owns the core Campaign record, campaign team links, artist and
release links, goals, milestones, realtime activity, and workspace-scoped API
contracts. It intentionally does not create speculative tables for future
departments.

## Domain Model

A Campaign is a workspace-scoped operational container. It coordinates work
across artists, releases, people, goals, milestones, departments, and eventually
AI agents. Campaigns are broader than release plans: one campaign may coordinate
zero, one, or many releases.

Workspaces are currently backed by `organizations`, so the database ownership
column remains `organization_id`. API and service boundaries use `workspace_id`
terminology and map it to `organization_id` internally.

| Model               | Purpose                                                 |
| ------------------- | ------------------------------------------------------- |
| `Campaign`          | Canonical workspace-owned campaign record.              |
| `CampaignMember`    | Campaign participation link to `workspace_memberships`. |
| `CampaignArtist`    | Campaign association to workspace catalog `artists`.    |
| `CampaignRelease`   | Many-to-many association to workspace `releases`.       |
| `CampaignGoal`      | Lightweight campaign outcome target.                    |
| `CampaignMilestone` | Lightweight campaign planning checkpoint.               |

Core fields:

| Field                                         | Notes                                                                |
| --------------------------------------------- | -------------------------------------------------------------------- |
| `id`                                          | Stable Campaign identifier.                                          |
| `organization_id`                             | Workspace isolation boundary.                                        |
| `name`, `description`                         | Human name and optional brief.                                       |
| `campaign_type`                               | `release`, `marketing`, `artist_development`, `catalog`, or `other`. |
| `status`                                      | Lifecycle state.                                                     |
| `start_date`, `target_end_date`               | Optional planning dates.                                             |
| `created_by_user_id`, `created_by_profile_id` | Creator audit references when known.                                 |
| `owner_profile_id`                            | Accountable Universal Profile when assigned.                         |
| `primary_artist_id`                           | Optional primary workspace catalog artist.                           |
| `release_id`                                  | Legacy nullable single-release pointer retained for compatibility.   |

## Lifecycle

Canonical statuses are:

- `draft` - captured but not ready for planning or execution.
- `planning` - being scoped, staffed, scheduled, or budgeted.
- `active` - currently in execution.
- `paused` - intentionally suspended but expected to resume.
- `completed` - finished successfully or operationally closed.
- `cancelled` - stopped before completion and not expected to resume.
- `archived` - retained for history and hidden from active operational views.

Allowed transitions are enforced in `labelos_api.services.campaign_service`.
Operational views should treat `planning`, `active`, and `paused` as open work.
Archive is preferred over destructive deletion for records with downstream
activity.

## Relationship Model

Relationships must preserve workspace isolation:

- `owner_profile_id` and `created_by_profile_id` must belong to active workspace
  members when supplied.
- `created_by_user_id` must map to an active workspace member when supplied.
- `primary_artist_id` and `CampaignArtist.artist_id` must belong to the same
  workspace.
- `release_id` and `CampaignRelease.release_id` must belong to the same
  workspace.
- `CampaignMember.workspace_membership_id` must be active in the campaign
  workspace.

`campaigns.release_id` remains a compatibility pointer. The Campaign service
keeps it aligned with release associations: the first linked release populates
the pointer, a `primary` relationship replaces it, and removing the pointed
release falls back to another primary link, then the first remaining link, then
`null`. New release-aware code must still read and write `campaign_releases` for
the complete relationship set.

Future integration attachment points:

| Area               | Boundary                                                                                                                       |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| Release Operations | Attach release operations records to `campaign_id` and validate linked releases through `campaign_releases`.                   |
| Marketing          | Use `Campaign.campaign_type = marketing` plus future plans, channels, calendars, and spend rows keyed by `campaign_id`.        |
| Legal / Contracts  | Link contract reviews, rights checks, and policy gates by `campaign_id`; do not infer legal access from campaign membership.   |
| Assets             | Attach creative, audio, video, artwork, and file references by `campaign_id` after an asset registry exists.                   |
| Finance / Budgets  | Attach budget, forecast, spend, and approval records by `campaign_id`; keep finance authorization separate.                    |
| Analytics          | Attribute metrics, reports, and events with `campaign_id`; child metrics use `campaign_object_type` plus `campaign_object_id`. |
| Approvals          | Attach approval requests and signoff history by `campaign_id` with immutable audit metadata.                                   |
| AI agents          | Agent assignments, recommendations, and run history must include `campaign_id`, actor/run metadata, and human review state.    |

Do not add empty tables for these areas until a concrete workflow needs a
foreign key, API contract, or persisted state.

## Capability Mapping

Campaign API operations use capability checks as the authoritative backend
control:

| Capability                   | Used For                                                                                                    |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `marketing.campaign.view`    | List and read campaigns, members, artists, releases, goals, and milestones.                                 |
| `marketing.campaign.create`  | Create campaign records.                                                                                    |
| `marketing.campaign.edit`    | Update campaign fields, archive campaigns, mutate team and relationship links, mutate goals and milestones. |
| `marketing.campaign.approve` | Change lifecycle status through the status endpoint.                                                        |

Legacy WorkOS-style permissions `campaigns:view` and `campaigns:manage` remain
compatibility inputs only. Frontend checks are advisory; backend checks are
authoritative.

## API Surface

Backend routes live under `/api/v1/workspaces/{workspace_id}/campaigns`.
Frontend proxy routes live under `/api/workspaces/{workspaceId}/campaigns`.

Core endpoints:

- `GET /campaigns?limit=50&offset=0` returns `{ campaigns, total, limit, offset }`.
- `POST /campaigns` creates a Campaign.
- `GET /campaigns/{campaign_id}` reads one Campaign.
- `PATCH /campaigns/{campaign_id}` updates editable fields.
- `PATCH /campaigns/{campaign_id}/status` changes lifecycle status.
- `POST /campaigns/{campaign_id}/archive` archives through lifecycle rules.
- `GET|PUT|DELETE /campaigns/{campaign_id}/members[...]`.
- `GET|PUT|DELETE /campaigns/{campaign_id}/artists[...]`.
- `GET|PUT|DELETE /campaigns/{campaign_id}/releases[...]`.
- `GET|POST|PATCH|DELETE /campaigns/{campaign_id}/goals[...]`.
- `GET|POST|PATCH|DELETE /campaigns/{campaign_id}/milestones[...]`.
- `POST /milestones/{milestone_id}/complete` and archive helpers for planning
  workflow shortcuts.

List pagination is offset-based and bounded to `limit <= 100`. Relationship and
planning sublists are currently unpaged because they are narrow child
collections; add pagination there only when product usage requires larger
collections.

## Realtime And Activity

Campaign mutations enqueue workspace-scoped realtime events in the caller's
database transaction. Events become visible after commit and use
`entity_type = "campaign"` with the Campaign id as `entity_id`.

Current event families:

- `campaign.created`, `campaign.updated`, `campaign.status_changed`
- `campaign.member_added`, `campaign.member_updated`, `campaign.member_removed`
- `campaign.artist_associated`, `campaign.artist_removed`
- `campaign.release_associated`, `campaign.release_removed`
- `campaign.goal_created`, `campaign.goal_updated`, `campaign.goal_completed`
- `campaign.milestone_created`, `campaign.milestone_updated`,
  `campaign.milestone_completed`

Payloads include workspace-safe identifiers and display fields such as
`campaignId`, `campaignName`, relationship ids, changed fields, and previous
status where useful. Future agent-executed changes must include the initiating
agent/run identity and human review metadata.

## Campaign Analytics Objects

Campaign analytics observations live in the Analytics Objects model documented
in [Analytics Objects](analytics-objects.md). Campaign-level observations use
`target_type = campaign`, `campaign_id`, and `target_id = campaign_id`.
Goal and milestone observations use `target_type = campaign_object`,
`campaign_id`, `campaign_object_type`, and `campaign_object_id`.

The current typed child reference is sufficient for the implemented child set
because goals and milestones already have direct parent campaign ownership and
service-level validators. Do not add a unified campaign object registry until
multiple new child types need a shared lifecycle, generic child authorization,
external object identity, or cross-child APIs that cannot be represented by the
current explicit validators.

## Frontend Routes

- `/campaigns` lists workspace campaigns, supports create, handles loading,
  error, empty, read-only, and paged list states.
- `/campaigns/[campaignId]` shows overview, team, goals, milestones, releases,
  activity, and future attachment placeholders.
- `/api/workspaces/[workspaceId]/campaigns...` proxies browser requests to the
  FastAPI workspace API and preserves query strings for list pagination.

## Known Limitations

- Campaign filtering, sorting controls, and cursor pagination are not implemented.
- Goal and milestone editors are represented in the API but the detail UI only
  displays current data.
- Campaign member management UI is not implemented beyond display and placeholder
  controls.
- `release_id` remains a compatibility pointer and does not represent the full
  campaign release set.
- Campaign activity is an event stream, not a complete immutable audit ledger.
- Department-specific authorization is not yet layered onto each future
  relationship type.

## Intentionally Deferred

- Release Operations department workflows.
- Marketing calendar/channel/spend planning.
- Legal contract review and rights workflows.
- Asset registry and campaign asset attachment UI.
- Finance budgets, forecasts, spend actuals, and finance approvals.
- Department-specific analytics adapters beyond the generic Analytics Objects
  provider abstraction.
- Approval queues, signoff policies, and escalation workflows.
- AI agent assignment, run history, recommendations, and human-in-the-loop review.
- Cross-workspace campaigns and external collaborator access models.

## Recommended Next Feature

Build the Approval Queue as the next Campaign-adjacent feature. Campaign status
changes already distinguish edit from approve capability, and future release,
legal, asset, budget, and agent workflows all need the same human signoff
primitive. A shared approval model should attach to `campaign_id` only when the
first approval workflow is implemented, preserve workspace isolation, emit
realtime activity, and store immutable decision metadata.
