# Implementation tickets

This repository does not yet use an external issue tracker. These checked-in tickets provide a small, reviewable local backlog derived from the private MVP review spec. Keep implementation artifacts here or in their normal source, test, and migration paths. Keep personal research, credentials, and patient-specific data out of tracked files.

## Tickets

| ID | Status | Ticket | Depends on |
| --- | --- | --- | --- |
| NIY-001 | Done | [Alert domain and initial schema](NIY-001-alert-domain.md) | None |
| NIY-002 | Done (local acceptance passed) | [Python Worker and local web shell](NIY-002-worker-web-shell.md) | NIY-001 |
| NIY-003 | Done | [D1 repository and visit lifecycle](NIY-003-persistence-lifecycle.md) | NIY-001, NIY-002 |
| NIY-004 | Done (local acceptance passed) | [Hospital adapters and synthetic fixtures](NIY-004-hospital-adapters.md) | NIY-001, NIY-003 |
| NIY-005 | Complete (2026-09-28) | [LINE identity and targeted delivery](NIY-005-line-integration.md) | NIY-002, NIY-003 |
| NIY-006 | Complete | [Scheduler, outbox, and send coordination](NIY-006-scheduler-outbox.md) | NIY-003, NIY-004, NIY-005 |
| NIY-007 | Open | [Settings, status, and stop UI](NIY-007-user-interface.md) | NIY-002 through NIY-006, NIY-010 |
| NIY-008 | Open | [CI and local acceptance journey](NIY-008-ci-acceptance.md) | NIY-001 through NIY-007, NIY-010 |
| NIY-009 | Complete | [Runtime configuration and secrets management](NIY-009-runtime-configuration-secrets.md) | NIY-002, NIY-005, NIY-006 |
| NIY-010 | Open | [Organizer API](NIY-010-organizer-api.md) | NIY-001 through NIY-006, NIY-009 |
| NIY-014 | Open | [Research documentation navigation](NIY-014-research-navigation.md) | None |
| NIY-015 | Open | [Repository structure review and disposition](NIY-015-repository-structure-review.md) | None |

## Acceptance guardrails

- No credentials, real patient details, live hospital requests, live LINE sends, deployment, push, or publication in the local implementation phase.
- A source adapter fixture is not an approved or reliable live connector.
- A LINE API acceptance result is not handset delivery.
- The strict Stop guarantee is not complete until concurrency tests prove no new request begins after confirmed Stop.
- Hospital freshness/access terms, the LINE callback and handset path, Cloudflare Free quota/CPU, and free-account requirements remain pre-live gates.
