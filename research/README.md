# Research and evidence

Use this page to find implementation work and the local research that informs it. Private source material is not copied into this repository.

## Implementation authority

The active implementation tickets are the source of truth for requirements, scope, and acceptance. Review their current status in the [ticket index](../tickets/README.md).

- [NIY-002: Python Worker and local web shell](../tickets/NIY-002-worker-web-shell.md)
- [NIY-003: D1 repository and visit lifecycle](../tickets/NIY-003-persistence-lifecycle.md)
- [NIY-004: Hospital adapters and synthetic fixtures](../tickets/NIY-004-hospital-adapters.md)
- [NIY-005: LINE identity and targeted delivery](../tickets/NIY-005-line-integration.md)
- [NIY-006: Scheduler, outbox, and send coordination](../tickets/NIY-006-scheduler-outbox.md)
- [NIY-007: Settings, status, and stop UI](../tickets/NIY-007-user-interface.md)
- [NIY-008: CI and local acceptance journey](../tickets/NIY-008-ci-acceptance.md)
- [NIY-021: NTUH and Shin Kong public progress source findings](NIY-021-findings-summary.md)

## Local-only supporting material

The current spec is `research/private/mvp-spec-review-2026-09-27-v2.md`; its supporting and archive index is `research/private/README.md`. Both files exist only in the captain primary checkout. They are ignored and untracked, and are not included in this isolated worktree. Use the index to find the current spec and archived supporting material; do not treat either as implementation authority unless a ticket adopts a requirement.

## Firstmate investigation reports

These reports are maintained locally by Firstmate under `/Users/kun/projects/firstmate/data/` and are not part of this repository:

- Spec provenance: `/Users/kun/projects/firstmate/data/next-is-you-spec-v2-ticket-provenance-2026-09-27/report.md`
- Ticket audit: `/Users/kun/projects/firstmate/data/next-is-you-preflight-tickets-2026-09-27/report.md`
- Runtime: `/Users/kun/projects/firstmate/data/next-is-you-preflight-runtime-2026-09-27/report.md`
- NIY-021 public source check: `/Users/kun/projects/firstmate/data/next-is-you-niy-021-public-source-check-20260929/report.md`

Treat these reports as supporting evidence. Any requirements adopted from a report must be captured in an implementation ticket before they guide implementation.

## Evidence and archives

The local-only spec, investigation reports, and archived records explain decisions and source research. They are supporting evidence. Keep private and patient-specific details out of tracked files.
