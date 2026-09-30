# NIY-022: Durable agent guidance

Status: Complete (2026-09-30)

## Goal

Add concise root guidance that keeps routine development aligned with current tickets, accepted decisions, and the limits of local validation.

## Scope

- Review the current root instructions, ticket index, relevant project docs and tickets, source layout, and development history for recurring planning and implementation problems.
- Edit the existing root `AGENTS.md` in place with only durable project-wide rules and contextual pointers.
- Record which concerns remain owned by the ticket index, README, pre-live checklist, and individual tickets.
- Clarify delivery for ticket-only and specification-documentation work: use an ordinary branch and PR without a separate worktree or the full no-mistakes pipeline; never edit `main` directly.
- Keep implementation work on an isolated worktree and the project's configured validation path.

## Acceptance criteria

- Before planning or coding, guidance directs agents to reconcile `tickets/README.md`, the current ticket, and related recorded decisions; new work starts with a ticket containing scope, observable acceptance checks, dependencies, and non-goals.
- Guidance keeps implementation within accepted scope, distinguishes decisions from proposals and unresolved choices, and requires known API or source gaps to be ticketed or explicitly scoped before expanding implementation.
- Guidance requires precise reporting of fixture, local integration, and live-provider evidence; changed lifecycle actions state their resulting and recovery states.
- Setup, migration, credentials, patient-data, and live-readiness procedures remain in their existing authoritative docs instead of being copied into root instructions.
- Root guidance remains compact, non-historical, and useful across supported coding agents. Ticket/index links are valid, and `git diff --check` passes.
- Ticket-only changes remain reviewable through a branch and PR, with lightweight Markdown and link checks; product code, tests, and migrations remain on the implementation path.
- This ticket records what was added to `AGENTS.md`, what stayed in other docs or tickets, and why.

## Non-goals

- No application behavior, tests, migrations, README, or pre-live checklist changes.
- No live hospital, LINE, or Cloudflare requests, secrets, patient data, deployment, push, PR, or merge.

## Completion record

Root `AGENTS.md` now sets ticket-first planning, accepted-scope and dependency order, decision and source-gap handling, truthful validation labels, lifecycle outcome expectations, and the synthetic-data/credential boundary. It points to `README.md` for local setup, test modes, and migrations; `docs/PRE-LIVE-CHECKLIST.md` for live gates; and the current ticket for task-specific behavior and acceptance.

Root `AGENTS.md` also distinguishes documentation-only ticket/backlog/guidance work from product implementation: the former uses a normal branch and PR with lightweight checks and no separate worktree or full no-mistakes run, while the latter uses an isolated worktree and the configured validation path. Neither path writes directly to `main`.

Setup commands and migration instructions remain in the README because they are operational procedures. Live integration gates remain in the pre-live checklist because they apply only when considering real providers. Changing product states and acceptance detail remain in their owning tickets. Ticket state remains in the ticket index. This keeps volatile or task-specific detail out of always-loaded root guidance.

Validation: `git diff --check` passed; the NIY-022 index link resolves to this ticket. The root file remains a compact instruction set rather than a repository history or inventory.
