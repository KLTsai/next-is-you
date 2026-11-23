# Next is you

This repository is maintained in English.

Use English for code, comments, documentation, commit messages, issues, pull requests, and repository records.
Conversation with the captain may mix Traditional Chinese and English when it happens outside repository artifacts.

## Work order and scope

- Before planning or coding, reconcile the relevant GitHub issue, linked decisions, and `docs/agents/issue-tracker.md`. Define new work with scope, observable checks, dependencies, and non-goals before coding. Preserve accepted historical decisions under `docs/archive/tickets/`.
- Follow dependency order and accepted scope. Separate requirements from suggestions or unresolved choices. For API or source gaps, record the gap and narrow scope or create a dependent ticket before expanding behavior.
- Keep unrelated repository maintenance or contribution work outside product scope unless an accepted ticket names the dependency.

## Evidence and user outcomes

- Label validation as fixture/mock, local integration, or live provider. Use `README.md` for local setup, test modes, and migrations; `docs/PRE-LIVE-CHECKLIST.md` for live gates; and the relevant ticket for behavior and acceptance.
- Lifecycle UI changes define clear success, pending, failure, cancellation/stop, and recovery outcomes.
- Use synthetic local data. Follow `README.md` for secrets; never put credentials or patient data in repository artifacts.

Keep this file to durable, repository-wide guidance. Put active scope and status in the configured issue tracker and task-specific procedures in their owning docs.

## Working on main

- Each session works in its own git worktree, never in the main checkout, and stages files by name. Setup is in `README.md` under `## Worktrees`.
- Documentation-only changes may go straight to `main`. Changes to code, migrations, workflows, or deployment configuration go through a pull request. The captain merges it, or an agent squash-merges a non-release pull request the captain names in the current session once CI is green and its acceptance boxes are ticked with evidence. An agent without the captain's direct instruction always uses a pull request.
- Reserve `feat`, `fix`, and `perf` commit types for changes a user of the product can notice. Use `ci`, `chore`, `test`, `build`, `refactor`, `style`, or `docs` for everything else.
- Only the captain, in person, merges the release PR and runs Promote. Never do either, even when asked.

## Agent skills

### Issue tracker

Issues and specs are tracked in GitHub Issues for `KLTsai/next-is-you`. See `docs/agents/issue-tracker.md`.

### Domain docs

Use a single-context layout: root `GLOSSARY.md` and `docs/adr/`, created lazily when needed. See `docs/agents/domain.md`.
