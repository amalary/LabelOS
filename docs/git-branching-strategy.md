# Git Branching Strategy

This document defines the Label OS Git branching workflow.

## Permanent Branches

| Branch | Purpose |
| --- | --- |
| `main` | Production-ready code. |
| `develop` | MVP integration branch. |

## Work Branches

Use these branch prefixes for focused work:

| Prefix | Use for |
| --- | --- |
| `feature/<ticket-or-scope>` | New product or application functionality. |
| `bugfix/<ticket-or-scope>` | Non-production bug fixes. |
| `hotfix/<ticket-or-scope>` | Urgent production fixes. |
| `refactor/<ticket-or-scope>` | Code restructuring without intended behavior changes. |
| `docs/<ticket-or-scope>` | Documentation-only changes. |
| `test/<ticket-or-scope>` | Test-only changes or test infrastructure. |
| `infra/<ticket-or-scope>` | Infrastructure, deployment, or CI/CD changes. |
| `security/<ticket-or-scope>` | Security fixes or security hardening. |
| `design/<ticket-or-scope>` | Design system, UX, or visual changes. |
| `release/<version>` | Release preparation. |

## Branch Sources and Destinations

| Branch type | Starts from | Merges into | Notes |
| --- | --- | --- | --- |
| Normal work branches | `develop` | `develop` | Applies to `feature`, `bugfix`, `refactor`, `docs`, `test`, `infra`, `security`, and `design` branches. |
| `hotfix/<ticket-or-scope>` | `main` | `main` | Must also be synchronized back into `develop`. |
| `release/<version>` | `develop` | `main` | After the release is merged, synchronize `main` back into `develop`. |

## Naming Rules

- Use lowercase names.
- Use hyphens between words.
- Keep names concise and descriptive.
- Include a ticket number when one exists.
- Do not include personal names in branch names.
- Do not use vague names such as `changes`, `updates`, `work`, or `test-branch`.
- Create work, hotfix, and release branches when the work starts. Do not create placeholder branches for planned future work.

## Examples

- `feature/los-101-authentication`
- `feature/los-102-dashboard-shell`
- `infra/los-103-ci-pipeline`
- `docs/los-104-architecture`
- `bugfix/los-105-login-redirect`
- `hotfix/los-106-token-validation`
- `release/v0.1.0`

## Normal Workflow

1. Update `develop`.
2. Create a work branch from `develop`.
3. Make focused commits.
4. Push the branch.
5. Open a pull request into `develop`.
6. Pass automated checks.
7. Obtain approval.
8. Squash merge.
9. Delete the merged branch.

## Hotfix Workflow

1. Update `main`.
2. Create a `hotfix/<ticket-or-scope>` branch from `main`.
3. Make the focused production fix.
4. Push the branch.
5. Open a pull request into `main`.
6. Pass automated checks.
7. Obtain approval.
8. Squash merge into `main`.
9. Synchronize the hotfix back into `develop`.
10. Delete the merged branch.

## Release Workflow

1. Update `develop`.
2. Create a `release/<version>` branch from `develop`.
3. Make release preparation changes only.
4. Push the branch.
5. Open a pull request into `main`.
6. Pass automated checks.
7. Obtain approval.
8. Squash merge into `main`.
9. Synchronize `main` back into `develop`.
10. Delete the merged branch.

## Branch Cleanup

After a branch is merged and synchronized to the required destination branches, delete the local and remote branch.

```sh
git branch -d docs/example-change
git push origin --delete docs/example-change
```

Use `git branch -d` for normal cleanup. Use `git branch -D` only after confirming that discarding unmerged local commits is intentional.
