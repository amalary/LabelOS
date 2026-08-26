# Enterprise Hierarchy Extension Path

LabelOS does not implement enterprise hierarchy yet. The current architecture
should only preserve room for future structures such as:

```text
Universal Music Group
-> Republic Records
-> Def Jam
-> individual label workspace
```

or:

```text
Parent Company
-> Division
-> Subsidiary
-> Workspace
```

## Current Contract

- `UniversalProfile` is a durable person identity record. It is not owned by a
  workspace and must not gain workspace-specific columns.
- `workspace_memberships.workspace_id` is the stable local workspace reference
  used for profile membership, authorization scope, role assignment scope, and
  profile listing APIs.
- `workspace_memberships.profile_id` references `universal_profiles.id`, so the
  same person can belong to multiple workspaces through separate memberships.
- `organization_memberships` is retained as the current WorkOS-backed
  administrative membership record. Its name is historical compatibility, not
  the enterprise hierarchy model.
- `organizations` is currently the local workspace backing table. It should be
  treated as the present workspace container, not as a permanent claim that each
  workspace is a top-level enterprise organization.

## Boundaries For This Stage

Do not add placeholder enterprise tables, parent links, subsidiary tables,
policy inheritance columns, or enterprise administration routes until a product
workflow needs them. Empty hierarchy tables would create migration and
authorization surface area without a tested behavior contract.

Application code should prefer workspace terminology at the profile and
authorization boundary:

- use `workspace_id` for profile membership APIs;
- use `CurrentUserContext.active_workspace_id` for workspace-scoped decisions;
- use `MembershipContext.workspace_id` when comparing a membership to a
  requested workspace;
- avoid assuming that a WorkOS `org_id` will always be the only way to select a
  workspace.

## Future Extension

When enterprise hierarchy is needed, add it beside the workspace model instead
of replacing Universal Profile or overloading membership records.

The likely path is:

1. Introduce an enterprise-owned hierarchy model only when required, such as
   `enterprise_nodes` or `workspace_groups`, with explicit node type values for
   parent company, division, subsidiary, and label grouping.
2. Link workspaces to hierarchy nodes through stable workspace IDs. Do not move
   person identity or workspace membership into the hierarchy table.
3. Keep direct workspace membership as the authoritative grant for workspace
   access until inherited permission rules are explicitly designed, migrated,
   and tested.
4. Add inherited permissions as a separate resolver layer in
   `AuthorizationService`, after direct workspace grants, so direct membership
   behavior remains understandable and auditable.
5. Version any enterprise policy API separately from existing workspace profile
   APIs. Existing endpoints such as `/workspaces/{workspace_id}/profiles` should
   continue to work for nested workspaces.

## Non-Goals

This note does not introduce:

- parent organizations;
- subsidiaries;
- inherited permissions;
- cross-company policies;
- enterprise administration;
- hierarchical workspace switching.

