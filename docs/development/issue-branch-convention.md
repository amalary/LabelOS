# Issue Branch Convention

Label OS GitHub issues should map clearly to branches, commits, and pull requests so work is easy to track from planning through merge.

Use this pattern:

```text
Issue: LOS-101 Implement authentication
Branch: feat/los-101-authentication
Commit: feat(auth): add session validation
Pull request: LOS-101: Implement authentication
```

One branch should normally correspond to one focused issue or one tightly related task. Keep the branch small enough to review, test, and merge without carrying unrelated changes.

## Large Tasks

If an issue is too large for one reviewable pull request, split it into smaller issues before implementation. Each sub-issue should have its own branch and pull request. Use the parent issue to track overall progress.

## Multiple Developers

When multiple developers work on the same issue, prefer separate branches for clearly separated parts of the work. If a shared branch is necessary, coordinate before rebasing, force pushing, or rewriting commit history.

## Stacked Work

For stacked work, create a branch for each reviewable step. Each branch should build on the previous branch only when the later work cannot reasonably be reviewed independently.

Name stacked branches with the issue key and a short task label:

```text
feat/los-101-auth-api
feat/los-101-login-ui
feat/los-101-session-tests
```

## Dependent Pull Requests

If one pull request depends on another, state the dependency in the pull request description and target the dependent branch only when needed for review. Retarget the pull request to `main` after the dependency merges.

Keep dependent pull requests narrow. Avoid adding unrelated follow-up work while waiting for an earlier pull request to merge.

## Cross-Cutting Infrastructure Changes

Cross-cutting infrastructure changes should still have a focused issue and branch. Use the `infra/`, `ci/`, `build/`, or `chore/` prefix as appropriate:

```text
infra/los-204-deployment-env-vars
ci/los-205-required-status-checks
chore/los-206-repository-settings
```

When infrastructure work affects several teams or services, document the affected areas in the issue and pull request so reviewers can verify the full impact.

## Emergency Production Fixes

Emergency production fixes should use the `hotfix/` prefix and reference the issue or incident:

```text
hotfix/los-301-session-expiry
```

Keep hotfix branches minimal. After the fix is merged, update the issue with the production impact, validation performed, and any follow-up work that should become separate issues.
