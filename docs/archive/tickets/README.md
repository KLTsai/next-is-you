# Historical implementation tickets

Archived on 2026-10-01. This directory preserves the former local backlog derived from the private MVP review spec. It is inactive: IDs, statuses, dates, decisions, and evidence limitations are historical records, not current work assignments or live-provider acceptance.

Active scope, status, and acceptance belong in [GitHub Issues](https://github.com/KLTsai/next-is-you/issues), following the [issue-tracker conventions](../../agents/issue-tracker.md). Preserve adopted decisions from these records when defining follow-up work; do not recreate every retired ticket as an issue. Keep personal research, credentials, and patient-specific data out of tracked files.

## Consequential unfinished work

Retirement does not close these gates. The owning documentation records their procedures and evidence limits; authorize new implementation scope in GitHub Issues before proceeding.

| Gate | Historical evidence | Current owning documentation |
| --- | --- | --- |
| Current runtime and UI acceptance | NIY-008, NIY-023, NIY-024, NIY-025 retain their recorded pending statuses. Prefill, draft-save RPC, and collapse implementations already exist; confirm current behavior rather than implementing them again. | [Local setup and validation](../../../README.md), [local manual checklist](../../NIY-020-LOCAL-MANUAL-CHECKLIST.md) |
| Real LINE identity, invitation, consent, callback, and handset receipt | NIY-005 and NIY-006 establish local behavior, not a complete personal live enrollment or delivery path. API acceptance is not handset delivery. | [Pre-live LINE gates](../../PRE-LIVE-CHECKLIST.md) |
| Trusted hospital reader, identity, freshness, and unavailable behavior | NIY-004 and NIY-016 provide fixtures and links; NIY-021 completed research only. Both live sources remain unverified. | [Source findings](../../../research/NIY-021-findings-summary.md), [pre-live source gates](../../PRE-LIVE-CHECKLIST.md) |
| Deployed persistence, migrations, send/Stop ordering, quota, retention, and recovery | NIY-003, NIY-006, and NIY-009 preserve the local design and protections. Deployed behavior and recoverable backups still require evidence. | [Configuration and migrations](../../../README.md), [pre-live platform gates](../../PRE-LIVE-CHECKLIST.md) |

## Frozen ticket statuses

| ID | Status | Ticket | Depends on |
| --- | --- | --- | --- |
| NIY-001 | Done | [Alert domain and initial schema](NIY-001-alert-domain.md) | None |
| NIY-002 | Done (local acceptance passed) | [Python Worker and local web shell](NIY-002-worker-web-shell.md) | NIY-001 |
| NIY-003 | Done | [D1 repository and visit lifecycle](NIY-003-persistence-lifecycle.md) | NIY-001, NIY-002 |
| NIY-004 | Done (local acceptance passed) | [Hospital adapters and synthetic fixtures](NIY-004-hospital-adapters.md) | NIY-001, NIY-003 |
| NIY-005 | Complete (2026-09-28) | [LINE identity and targeted delivery](NIY-005-line-integration.md) | NIY-002, NIY-003 |
| NIY-006 | Complete | [Scheduler, outbox, and send coordination](NIY-006-scheduler-outbox.md) | NIY-003, NIY-004, NIY-005 |
| NIY-007 | Complete (2026-09-28) | [Settings, status, and stop UI](NIY-007-user-interface.md) | NIY-002 through NIY-006, NIY-010, NIY-016 |
| NIY-008 | Open (GitHub Action reference follow-up, 2026-09-29) | [CI and local acceptance journey](NIY-008-ci-acceptance.md) | NIY-001 through NIY-007, NIY-010 |
| NIY-009 | Complete | [Runtime configuration and secrets management](NIY-009-runtime-configuration-secrets.md) | NIY-002, NIY-005, NIY-006 |
| NIY-010 | Complete (2026-09-28) | [Organizer API](NIY-010-organizer-api.md) | NIY-001 through NIY-006, NIY-009 |
| NIY-015 | Complete (2026-09-29) | [Repository structure review and disposition](NIY-015-repository-structure-review.md) | None |
| NIY-016 | Complete (2026-09-28) | [Trusted hospital progress links](NIY-016-trusted-progress-links.md) | NIY-010 |
| NIY-017 | Complete (2026-09-28) | [Research ticket removal](NIY-017-remove-niy-014.md) | None |
| NIY-018 | Complete (2026-09-29) | [Local rebuildable artifact cleanup](NIY-018-local-artifact-cleanup.md) | NIY-015 |
| NIY-019 | Complete | [Ignore local Python module cache](NIY-019-ignore-python-modules.md) | NIY-018 |
| NIY-020 | Complete (2026-09-29) | [Clarify visit setup and monitoring controls](NIY-020-visit-setup-ux.md) | NIY-007, NIY-008, NIY-010, NIY-016 |
| NIY-021 | Complete (research documented 2026-09-30) | [Verify official progress sources for NTUH and Shin Kong](NIY-021-hospital-source-verification.md) | NIY-004, NIY-016 |
| NIY-022 | Complete (2026-09-29) | [Durable agent guidance](NIY-022-agent-guidance.md) | None |
| NIY-023 | Open | [Prefill saved patient number in draft correction](NIY-023-draft-correction-patient-number.md) | NIY-010, NIY-020 |
| NIY-024 | Implemented (local Wrangler acceptance pending) | [Fix draft-save HTTP 500 across Worker and Durable Object RPC](NIY-024-draft-save-rpc-500.md) | NIY-008, NIY-010 |
| NIY-025 | Implemented (local acceptance passed; pipeline pending) | [Collapse and expand the saved-drafts section](NIY-025-collapsible-saved-drafts.md) | NIY-007, NIY-020 |

## Historical local acceptance guardrails

These guardrails describe the original local implementation phase. They remain evidence limits for its completion statements; the current [pre-live checklist](../../PRE-LIVE-CHECKLIST.md) owns live gates.

- No credentials, real patient details, live hospital requests, live LINE sends, deployment, push, or publication in the local implementation phase.
- A source adapter fixture is not an approved or reliable live connector.
- A LINE API acceptance result is not handset delivery.
- The strict Stop guarantee is not complete until concurrency tests prove no new request begins after confirmed Stop.
- Hospital freshness/access terms, the LINE callback and handset path, Cloudflare Free quota/CPU, and free-account requirements remain pre-live gates.
