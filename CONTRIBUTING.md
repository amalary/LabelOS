# Contributing

Thanks for helping build Label OS. This repository is early, so keep changes small, explicit, and easy to review.

## Workflow

1. Create a focused branch for your change.
2. Make the smallest practical change that solves the problem.
3. Add tests or documentation when behavior, public APIs, or operational assumptions change.
4. Run relevant checks before opening a pull request.
5. Use the pull request template and call out risks, migrations, or follow-up work.

## Branch Strategy

`main` is the only permanent branch and should be protected. Do not commit directly to `main`; open a pull request from a short-lived branch and wait for CI and review before merging.

Create every work branch from an up-to-date `main` branch:

```sh
git checkout main
git pull origin main
git checkout -b feat/example-feature
```

Use these branch prefixes:

- `feat/<short-description>` for new features.
- `fix/<short-description>` for bug fixes.
- `refactor/<short-description>` for code restructuring.
- `docs/<short-description>` for documentation changes.
- `test/<short-description>` for test-related work.
- `chore/<short-description>` for maintenance and tooling.
- `ci/<short-description>` for CI/CD changes.
- `infra/<short-description>` for infrastructure changes.
- `hotfix/<short-description>` for urgent production fixes.

Keep branch names lowercase, hyphen-separated, and specific enough to identify the work.

Do not create long-lived environment branches such as `develop`, `development`, `staging`, `production`, or `release`. Use tags, deployment environments, and CI/CD configuration for release and deployment workflows.

## Conventional Commits

Use conventional commit-style messages so history stays searchable:

```text
feat: add artist profile scaffold
fix: prevent duplicate campaign creation
refactor: separate agent execution service
docs: document local development setup
test: add API health endpoint tests
chore: configure repository tooling
ci: add pull request validation workflow
```

Allowed commit types are `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `ci`, `build`, `perf`, and `revert`.

Commit message rules:

- Use lowercase commit types.
- Use the imperative mood.
- Keep the subject concise.
- Do not end the subject with a period.
- Explain significant changes in the commit body.
- Reference related issues when applicable.
- Never commit secrets or `.env` files.

Prefer one logical change per commit. Use the body of the commit message when reviewers need context about tradeoffs, migrations, or follow-up work.

## Pull Requests

Push your work branch and open a pull request into `main`:

```sh
git status
git add .
git commit -m "feat: add example feature"
git push -u origin feat/example-feature
```

Pull request rules:

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

Before merging, update your branch from `main`:

```sh
git checkout main
git pull origin main
git checkout feat/example-feature
git rebase main
```

Do not rebase a branch shared with other collaborators without coordinating first.

After a pull request is squash-merged, delete the merged branch and update local `main`:

```sh
git branch -d feat/example-feature
git push origin --delete feat/example-feature
git checkout main
git pull origin main
```

## Recommended Branch Protection

Repository administrators should protect `main` with these settings:

- Require a pull request before merging.
- Require at least one approval.
- Dismiss stale approvals when new commits are pushed.
- Require review from Code Owners after replacing the placeholder in `.github/CODEOWNERS`.
- Require conversation resolution.
- Require status checks to pass.
- Require the branch to be up to date before merging.
- Require the existing CI checks named `Formatting check`, `Frontend checks`, `Backend checks`, and `Agent service checks`.
- Block direct pushes.
- Block force pushes.
- Block branch deletion.
- Apply rules to administrators.
- Allow squash merging.
- Disable merge commits where practical.
- Automatically delete head branches after merge.

These are recommended settings only. Contributors should not assume they have repository administrator access.

## Standards

- Do not commit secrets, credentials, private keys, or production data.
- Prefer clear names and boring, maintainable code.
- Avoid adding dependencies or frameworks without a documented reason.
- Keep application features out of foundation-only changes.

## Local Setup

Install dependencies from the repository root:

```sh
pnpm install
cd apps/api
python -m pip install -e ".[dev]"
```

## Testing

Run tests from the repository root unless you are iterating inside a single package:

```sh
pnpm test
pnpm test:web
pnpm test:api
pnpm test:coverage
```

Frontend tests use Vitest, jsdom, and React Testing Library. Keep web app tests next to the page or component they cover with the `*.test.tsx` suffix, for example `apps/web/src/app/login/page.test.tsx`. Keep shared UI tests next to shared source files in `packages/ui/src/**` with the same suffix.

Backend tests use Pytest and FastAPI `TestClient`. Keep API tests under `apps/api/tests`, with shared fixtures in `apps/api/tests/conftest.py`.

Coverage is configured for Vitest and Pytest. Generated files, build outputs, framework config, test files, and caches are excluded from reports. Do not use live external services in unit or API endpoint tests; mock or fixture local behavior instead.
