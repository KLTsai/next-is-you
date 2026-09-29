# Next is you

This repository is maintained in English.

Use English for code, comments, documentation, commit messages, issues, pull requests, and repository records.
Conversation with the captain may mix Traditional Chinese and English when it happens outside repository artifacts.

## Work order and scope

- Before planning or coding, reconcile `tickets/README.md`, the current ticket, and linked decisions. Reuse or update an existing ticket. Define new work in a ticket with scope, observable checks, dependencies, and non-goals before coding.
- Follow dependency order and accepted scope. Separate requirements from suggestions or unresolved choices. For API or source gaps, record the gap and narrow scope or create a dependent ticket before expanding behavior.
- Keep unrelated repository maintenance or contribution work outside product scope unless an accepted ticket names the dependency.

## Evidence and user outcomes

- Label validation as fixture/mock, local integration, or live provider. Use `README.md` for local setup, test modes, and migrations; `docs/PRE-LIVE-CHECKLIST.md` for live gates; and the relevant ticket for behavior and acceptance.
- Lifecycle UI changes define clear success, pending, failure, cancellation/stop, and recovery outcomes.
- Use synthetic local data. Follow `README.md` for secrets; never put credentials or patient data in repository artifacts.

Keep this file to durable, repository-wide guidance. Put ticket status in `tickets/` and task-specific procedures in their owning docs.
