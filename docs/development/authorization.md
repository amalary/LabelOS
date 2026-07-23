# Authorization

Label OS uses WorkOS AuthKit for authentication and WorkOS RBAC claims for
backend authorization decisions. The frontend can hide or disable unavailable
actions, but FastAPI route dependencies are the authoritative enforcement point.

## WorkOS AuthKit Claims

AuthKit access tokens are JWTs. WorkOS documents these relevant session claims:

- `sub` - WorkOS user ID.
- `sid` - WorkOS session ID.
- `org_id` - selected organization ID, when an organization is active.
- `role` - organization membership role, when an organization is active.
- `permissions` - permission slugs assigned to the active role.

WorkOS RBAC supports permissions assigned to roles. In multiple-role mode, a
membership receives the union of permissions across its roles. The backend
accepts the documented `role` claim and is tolerant of a `roles` list claim for
multiple-role sessions.

## Roles

Initial Label OS application roles:

- `owner`
- `admin`
- `member`

The database still contains the legacy `viewer` enum for migration
compatibility, but the initial public application policy is Owner/Admin/Member.

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

## Backend Guards

Reusable FastAPI dependencies live in `labelos_api.authorization`:

- `require_authenticated_user()`
- `require_organization()`
- `require_role(role)`
- `require_permission(permission)`

Missing, expired, or invalid bearer tokens return `401`. Validly authenticated
users without the required organization, role, or permission return `403`.

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

## Frontend Helpers

Frontend helpers live in `apps/web/src/lib/authorization.ts`. Use them to hide
or disable UI controls for unavailable actions. These helpers must only improve
the user experience; they must not replace backend route guards.
