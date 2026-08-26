# Authorization

Label OS uses WorkOS AuthKit for authentication and WorkOS RBAC claims for
backend authorization decisions. The frontend can hide or disable unavailable
actions, but FastAPI route dependencies are the authoritative enforcement point.

## WorkOS AuthKit Claims

AuthKit access tokens are JWTs. WorkOS documents these relevant session claims:

- `sub` - WorkOS user ID.
- `sid` - WorkOS session ID.
- `org_id` - selected organization ID, when an organization is active.
- `role` - WorkOS administrative role for the active organization.
- `permissions` - permission slugs assigned to the active role.

WorkOS RBAC supports permissions assigned to roles. In multiple-role mode, a
membership receives the union of permissions across its roles. The backend
accepts the documented `role` claim and is tolerant of a `roles` list claim for
multiple-role sessions. Product capabilities are resolved locally from LabelOS
workspace membership and role tables; WorkOS permissions remain authentication
and coarse administrative signals.

## Workspace Permission

Local workspace memberships store administrative authority separately from a
person's music-industry job function:

- `owner`
- `admin`
- `member`
- `guest`

This value lives on `organization_memberships.workspace_permission`. The legacy
`role` field is still mirrored for compatibility with existing WorkOS RBAC
claims and older API consumers.

Memberships store professional identity separately from authorization:

- `membership_professional_roles` links each workspace membership to one or more
  extensible `professional_roles` records, with `is_primary` for a preferred
  role.
- `departments` defines the canonical LabelOS application departments.
  Each department has a default `access_sensitivity` of `standard`, `elevated`,
  or `sensitive`.
- `membership_department_access` stores persisted department grants for each
  membership and department. Each record carries an `access_level`, grant
  `source`, optional approver, and approval timestamp so access is auditable.
- `organization_memberships.department_access` is a compatibility projection of
  approved department slugs only.

A professional role is not the only source of department access. Role defaults,
invitations, administrator grants, manual requests, and workspace ownership are
persisted as grant records, and those records authorize data access.

Memberships also carry optional action-level grants:

- `organization_memberships.capability_permissions` stores explicit capability
  slugs for a workspace membership.
- Workspace permission supplies baseline capabilities. Explicit capability
  grants can add specific actions without broadening workspace administration.
- Owners are treated as having all department access and all capabilities.

Authorization decisions should use this layered model:

```text
Universal Profile
-> active Workspace Membership by workspace_id
-> Workspace Roles
-> Role Capabilities
+ explicit Membership Capability Permission
+ Department Access for resource-scoped actions
= Authorization
```

Workspace authorization code should compare requested scopes through
`workspace_id` rather than assuming the current WorkOS organization-backed
storage model is the permanent enterprise shape. See
`docs/development/enterprise-hierarchy-extension.md` for the hierarchy extension
boundary.

Application code should not inline access rules such as
`user.role == "legal"` or department-specific role checks. Backend access
decisions flow through the central `AuthorizationService.can(...)` resolver:

```python
authorization_service.can(
    user=context,
    workspace=context.active_workspace_id,
    capability=Capability.contract_upload,
    resource=AuthorizationResource(department="legal"),
)
```

Frontend helpers expose the same convention for presentation-only decisions:

```ts
can(subject, workspace, capabilities.contractUpload, { department: "legal" });
```

## Departments

Departments are application work areas, not professional roles. The initial
LabelOS department catalog is:

- `artist` - Artist
- `creative` - Creative
- `releases` - Releases
- `analytics` - Analytics
- `production` - Production
- `songs` - Songs
- `sessions` - Sessions
- `credits` - Credits
- `management` - Management
- `marketing` - Marketing
- `a&r` - A&R
- `discovery` - Discovery
- `evaluations` - Evaluations
- `legal` - Legal
- `contracts` - Contracts
- `agreements` - Agreements
- `finance` - Finance
- `royalties` - Royalties
- `reporting` - Reporting
- `administration` - Workspace Administration

Legacy department slugs retained for existing memberships:

- `release_operations` - Release Operations
- `artist_analytics` - Artist Analytics

## Department Access Policies

Department sensitivity defines the default approval posture for access requests.
Workspace owners should eventually be able to customize these policies per
workspace, so the seeded department value is a default policy classification,
not a hard-coded product rule.

| Sensitivity | Default Policy                                                                       | Departments                                            |
| ----------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------ |
| Standard    | May allow automatic access when requested by a trusted role or onboarding flow.      | `artist`, `production`, `creative`, `marketing`        |
| Elevated    | Requires additional approval before access is granted.                               | `management`, `a&r`, `analytics`, `release_operations` |
| Sensitive   | Generally requires explicit authorization from an owner or authorized administrator. | `legal`, `finance`, `royalties`, `administration`      |

Professional roles carry default department grants, but they are not identical
to departments. The resulting access is persisted in
`membership_department_access` with `source = "role_default"`. Examples:

| Professional Role | Suggested Department Requests                                |
| ----------------- | ------------------------------------------------------------ |
| Artist            | `artist`, `creative`, `releases`, `analytics`                |
| Producer          | `production`, `songs`, `sessions`, `credits`                 |
| Management        | `management`, `artist`, `releases`, `marketing`, `analytics` |
| A&R               | `a&r`, `discovery`, `artist`, `evaluations`                  |
| Legal             | `legal`, `contracts`, `agreements`                           |
| Finance           | `finance`, `royalties`, `reporting`                          |

## Permissions

- `organization:manage`
- `members:manage`
- `artists:view`
- `artists:manage`
- `releases:view`
- `releases:manage`
- `campaigns:view`
- `campaigns:manage`
- `analytics:view`
- `royalties:view`
- `royalties:manage`
- `contracts:view`
- `contracts:manage`
- `agents:view`
- `agents:manage`
- `settings:manage`

## Initial Mapping

| Role   | Permissions                                                                                                                                                                                                                             |
| ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Owner  | All permissions.                                                                                                                                                                                                                        |
| Admin  | `members:manage`, `artists:view`, `artists:manage`, `releases:view`, `releases:manage`, `campaigns:view`, `campaigns:manage`, `analytics:view`, `contracts:view`, `contracts:manage`, `agents:view`, `agents:manage`, `settings:manage` |
| Member | `artists:view`, `releases:view`, `campaigns:view`, `analytics:view`, `royalties:view`, `contracts:view`, `agents:view`                                                                                                                  |

## Capabilities

Capabilities control individual actions inside a department. They use dot-case
slugs because they describe application actions rather than WorkOS RBAC
permissions.

Initial capabilities:

- `artist.view`
- `artist.edit`
- `artist.create`
- `campaign.view`
- `campaign.create`
- `campaign.approve`
- `release.view`
- `release.edit`
- `contract.view`
- `contract.upload`
- `contract.approve`
- `contract.sign_request`
- `royalty.view`
- `finance.view`
- `analytics.view`
- `member.invite`
- `member.remove`
- `role.assign`
- `workspace.manage`
- `profile.edit`

Initial baseline capability mapping:

| Source                      | Capabilities                                                                                                                           |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| Owner workspace permission  | All capabilities.                                                                                                                      |
| Admin workspace permission  | Broad operational capabilities including artist, campaign, release, contract, analytics, member, role, workspace, and profile actions. |
| Member workspace permission | View-oriented artist, campaign, release, analytics, and profile actions.                                                               |
| Guest workspace permission  | No default capabilities.                                                                                                               |
| Workspace roles             | Union of capabilities from every assigned role in `workspace_membership_roles` through `role_capabilities`.                            |
| Explicit membership grants  | Additional capability slugs stored on `organization_memberships.capability_permissions`.                                               |

The resolver denies by default:

- Unknown capability, permission, or role strings return `False`.
- Missing workspace context returns `False` for capabilities.
- Inactive, invited, removed, or otherwise non-`active` workspace memberships do
  not authorize capabilities.
- Multiple roles are additive only. They can grant the union of capabilities,
  but they do not bypass department access for resource-scoped checks.

## Backend Guards

Reusable FastAPI dependencies live in `labelos_api.authorization`:

- `require_authenticated_user()`
- `require_organization()`
- `require_role(role)`
- `require_permission(permission)`
- `require_capability(capability, department=...)`

These dependencies delegate to `authorization_service.can(...)`, which is the
single authority for backend access decisions.

Missing, expired, or invalid bearer tokens return `401`. Validly authenticated
users without the required organization, role, permission, department, or
capability return `403`.

Example:

```python
@router.get("/authorization/examples/artists-manage")
async def manage_artists_example(
    _context: Annotated[
        CurrentUserContext,
        Depends(require_permission(Permission.artists_manage)),
    ],
) -> ProtectedRouteResponse:
    return ProtectedRouteResponse(ok=True, guard="artists:manage")
```

Capability example:

```python
@router.post("/authorization/examples/contracts")
async def create_contract_example(
    _context: Annotated[
        CurrentUserContext,
        Depends(require_capability(Capability.contract_upload, department="legal")),
    ],
) -> ProtectedRouteResponse:
    return ProtectedRouteResponse(ok=True, guard="contract.upload")
```

## Frontend Helpers

Frontend helpers live in `apps/web/src/lib/authorization.ts`. Use them to hide
or disable UI controls for unavailable actions. These helpers must only improve
the user experience; they must not replace backend route guards.

## Adding Capabilities

New capabilities should be introduced through the central catalog before any UI
or route consumes them:

1. Add a dot-case key to the backend `Capability` enum in
   `apps/api/src/labelos_api/authorization.py`.
2. Add the same key to `DEFAULT_CAPABILITIES` in
   `packages/database/src/labelos_database/roles.py` with a stable UUID,
   display name, and description.
3. Add role defaults in `DEFAULT_ROLE_CAPABILITY_ASSOCIATIONS` only for roles
   that should receive the capability automatically.
4. Add or update an Alembic migration when the database seed data changes.
5. Add the frontend presentation constant in
   `apps/web/src/lib/authorization.ts`.
6. Protect backend routes with `require_capability(...)` or call
   `authorization_service.can(...)` in service code. UI components should
   consume already-resolved authorization state or frontend helpers only for
   presentation.
7. Add allow and deny tests. At minimum cover no membership, inactive
   membership, missing capability, missing department when applicable, and a
   role or explicit grant that allows the action.

Do not cache resolved capabilities unless the invalidation path is obvious for
membership status changes, role assignment changes, role capability changes,
and explicit membership grant changes. The current request-scoped context is
safe because it is rebuilt from the database for each authenticated request.
