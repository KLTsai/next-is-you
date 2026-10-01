# Research and evidence

Use this page to find implementation work and the local research that informs it. Private source material is not copied into this repository.

## Implementation authority

Active requirements, scope, status, and acceptance are tracked in [GitHub Issues](https://github.com/KLTsai/next-is-you/issues). Follow the [issue-tracker conventions](../docs/agents/issue-tracker.md) when defining or retrieving work.

The former local tickets are [inactive historical records](../docs/archive/tickets/README.md). Preserve their adopted decisions and evidence limitations; their statuses do not establish current acceptance or live-provider readiness.

## Historical implementation evidence

- [NIY-002: Python Worker and local web shell](../docs/archive/tickets/NIY-002-worker-web-shell.md)
- [NIY-003: D1 repository and visit lifecycle](../docs/archive/tickets/NIY-003-persistence-lifecycle.md)
- [NIY-004: Hospital adapters and synthetic fixtures](../docs/archive/tickets/NIY-004-hospital-adapters.md)
- [NIY-005: LINE identity and targeted delivery](../docs/archive/tickets/NIY-005-line-integration.md)
- [NIY-006: Scheduler, outbox, and send coordination](../docs/archive/tickets/NIY-006-scheduler-outbox.md)
- [NIY-007: Settings, status, and stop UI](../docs/archive/tickets/NIY-007-user-interface.md)
- [NIY-008: CI and local acceptance journey](../docs/archive/tickets/NIY-008-ci-acceptance.md)
- [NIY-021: NTUH and Shin Kong public progress source findings](NIY-021-findings-summary.md)

## Local-only supporting material

The local supporting spec is `research/private/mvp-spec-review-2026-09-27-v2.md`; its supporting and archive index is `research/private/README.md`. Both files exist only in the captain primary checkout. They are ignored and untracked, and are not included in this isolated worktree. Use the index to find the spec and archived supporting material; do not treat either as implementation authority unless an active GitHub issue adopts a requirement.

## Firstmate investigation reports

These reports are maintained locally by Firstmate under `/Users/kun/projects/firstmate/data/` and are not part of this repository:

- Spec provenance: `/Users/kun/projects/firstmate/data/next-is-you-spec-v2-ticket-provenance-2026-09-27/report.md`
- Ticket audit: `/Users/kun/projects/firstmate/data/next-is-you-preflight-tickets-2026-09-27/report.md`
- Runtime: `/Users/kun/projects/firstmate/data/next-is-you-preflight-runtime-2026-09-27/report.md`
- NIY-021 public source check: `/Users/kun/projects/firstmate/data/next-is-you-niy-021-public-source-check-20260929/report.md`

Treat these reports as supporting evidence. Any requirements adopted from a report must be captured in an active GitHub issue before they guide implementation.

## Evidence and archives

The local-only spec, investigation reports, and archived records explain decisions and source research. They are supporting evidence. Keep private and patient-specific details out of tracked files.
