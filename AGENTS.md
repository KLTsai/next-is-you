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

## Agent skills

### Issue tracker

Issues and specs are tracked in GitHub Issues for `KLTsai/next-is-you`. See `docs/agents/issue-tracker.md`.

### Domain docs

Use a single-context layout: root `CONTEXT.md` and `docs/adr/`, created lazily when needed. See `docs/agents/domain.md`.
