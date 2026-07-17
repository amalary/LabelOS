# Git Workflow

Label OS uses trunk-based development centered on a protected `main` branch. `main` is the only permanent branch. All work should happen in short-lived branches created from an up-to-date `main` branch.

## Branch Names

Use lowercase, hyphen-separated branch names with one of these prefixes:

- `feat/` for new features.
- `fix/` for bug fixes.
- `refactor/` for code restructuring.
- `docs/` for documentation changes.
- `test/` for test-related work.
- `chore/` for maintenance and tooling.
- `ci/` for CI/CD changes.
- `infra/` for infrastructure changes.
- `hotfix/` for urgent production fixes.

Examples:

```text
feat/artist-profile
feat/agent-command-center
fix/dashboard-loading-state
refactor/api-service-layer
docs/update-local-setup
test/add-auth-integration-tests
chore/configure-eslint
ci/add-github-actions
infra/add-postgres-container
hotfix/auth-token-validation
```

Do not create long-lived environment branches such as `develop`, `development`, `staging`, `production`, or `release`. Use tags, deployment environments, and CI/CD configuration for release and deployment workflows.

## Start Work

Create every branch from the latest available `main` branch:

```sh
git checkout main
git pull origin main
git checkout -b feat/example-feature
```

## Commit And Push

After development:

```sh
git status
git add .
git commit -m "feat: add example feature"
git push -u origin feat/example-feature
```

Then:

- Open a pull request into `main`.
- Wait for CI checks.
- Request code review.
- Resolve review comments.
- Squash and merge.
- Delete the branch after merge.
- Pull the latest `main` locally.

## Update A Branch Before Merge

Rebase your branch on the latest `main` before merging:

```sh
git checkout main
git pull origin main
git checkout feat/example-feature
git rebase main
```

Do not rebase a shared branch without coordinating with collaborators first. Rebasing rewrites commit history and can disrupt other contributors using the same branch.

## Delete Merged Branches

After a pull request is merged, safely delete the local and remote branch:

```sh
git branch -d feat/example-feature
git push origin --delete feat/example-feature
```

Use `git branch -d`, not `git branch -D`, unless you have confirmed the branch has been merged or you intentionally want to discard unmerged local commits.

## Conventional Commits

Use conventional commit-style messages:

```text
feat: add artist profile scaffold
fix: prevent duplicate campaign creation
refactor: separate agent execution service
docs: document local development setup
test: add API health endpoint tests
chore: configure repository tooling
ci: add pull request validation workflow
```

Allowed commit types:

```text
feat
fix
refactor
docs
test
chore
ci
build
perf
revert
```

Commit message rules:

- Use lowercase commit types.
- Use the imperative mood.
- Keep the subject concise.
- Do not end the subject with a period.
- Explain significant changes in the commit body.
- Reference related issues when applicable.
- Never commit secrets or `.env` files.

## Pull Request Rules

- Pull requests must target `main`.
- Pull requests should represent one logical change.
- Pull requests should be small enough to review.
- CI must pass before merging.
- At least one approval should be required.
- Conversations should be resolved before merging.
- Direct pushes to `main` should be disabled.
- Force pushes to `main` should be disabled.
- Branch deletion after merge should be enabled.
- Squash merging should be the default merge strategy.

## Recommended Main Branch Protection

Repository administrators should protect `main` with these settings:

- Require a pull request before merging.
- Require at least one approval.
- Dismiss stale approvals when new commits are pushed.
- Require review from Code Owners.
- Require conversation resolution.
- Require status checks to pass.
- Require the branch to be up to date before merging.
- Block direct pushes.
- Block force pushes.
- Block branch deletion.
- Apply rules to administrators.
- Allow squash merging.
- Disable merge commits where practical.
- Automatically delete head branches after merge.

Existing CI check names from `.github/workflows/ci.yml`:

- `Formatting check`
- `Frontend checks`
- `Backend checks`
- `Agent service checks`

If these workflows change, update this list before configuring required status checks.
