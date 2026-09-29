# NIY-022: Durable agent guidance

Status: Open

## Goal

Add concise root guidance that keeps routine development aligned with current tickets, accepted decisions, and the limits of local validation.

## Scope

- Review the current root instructions, ticket index, relevant project docs and tickets, source layout, and development history for recurring planning and implementation problems.
- Edit the existing root `AGENTS.md` in place with only durable project-wide rules and contextual pointers.
- Record which concerns remain owned by the ticket index, README, pre-live checklist, and individual tickets.

## Acceptance criteria

- Before planning or coding, guidance directs agents to reconcile `tickets/README.md`, the current ticket, and related recorded decisions; new work starts with a ticket containing scope, observable acceptance checks, dependencies, and non-goals.
- Guidance keeps implementation within accepted scope, distinguishes decisions from proposals and unresolved choices, and requires known API or source gaps to be ticketed or explicitly scoped before expanding implementation.
- Guidance requires precise reporting of fixture, local integration, and live-provider evidence; changed lifecycle actions state their resulting and recovery states.
- Setup, migration, credentials, patient-data, and live-readiness procedures remain in their existing authoritative docs instead of being copied into root instructions.
- Root guidance remains compact, non-historical, and useful across supported coding agents. Ticket/index links are valid, and `git diff --check` passes.
- This ticket records what was added to `AGENTS.md`, what stayed in other docs or tickets, and why.

## Non-goals

- No application behavior, tests, migrations, README, or pre-live checklist changes.
- No live hospital, LINE, or Cloudflare requests, secrets, patient data, deployment, push, PR, or merge.
