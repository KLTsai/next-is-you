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

## Hospital source research

- [Hospital schedule and queue progress survey](hospital-schedule-and-progress-survey.md) (2026-11-17): how 15 Taiwan hospitals publish their clinic schedule and queue progress, and where the capability model in Issue #45 does not fit. Not evidence that any hospital is ready for a reader.
- [Automated reading of public hospital pages under Taiwan law](automated-access-taiwan-law.md) (2026-11-17): what statutes, court decisions and agency letters say about the reading rules in the README. Source research by a non-lawyer, not legal advice.

## LINE research

- [LINE rich menu progress button and the message quota](line-rich-menu-progress-button.md) (2026-11-20): whether a rich menu tap can return the current queue progress as a reply that does not count toward the monthly message quota, how postback, webhook and reply tokens fit together, Taiwan plan quotas from 2026-11-01, and what separate staging and production accounts mean for menus.
- [LINE notice layout and animated icons](line-notice-layout-and-animated-icons-2026-11-27.md) (2026-11-27): how many full-width characters fit on one line of a LINE text bubble and in a notification preview, and whether LINE emoji or a Flex animated image can replace text. Stickers were excluded by the captain. Supporting evidence for #152; the characters-per-line figure is an estimate, not a handset measurement.

## Delivery and operations research

- [Schema migration risk practices](schema-migration-risk-practices.md) (2026-11-19): how teams classify, review, rehearse, back up, and roll forward schema changes, with SQLite rebuild and Cloudflare D1 specifics and what fits a solo operator.
- [Workers Free plan 10 ms CPU limit and the Python tick](workers-free-cpu-limit-2026-11-21.md) (2026-11-21): how Cloudflare counts and enforces CPU per invocation for Cron and Durable Object invocations and Python Workers, and which techniques fit this project's tick. Supporting evidence for #162 and #170, not a measurement.
- [CI gates and Cloudflare usage tracking](ci-gates-and-cloudflare-usage-2026-11-24.md) (2026-11-24): how the seven CI gates compare with GitHub, actionlint and Release Please guidance, and what Cloudflare offers on the Free plan to track Worker, Durable Object and D1 usage against daily limits. Supporting evidence for #203.
- [Reading a large NTUH clinic schedule in parts on the Workers Free plan](ntuh-schedule-chunked-read-2026-11-24.md) (2026-11-24): whether a clinic schedule page over the reader's size cap can be read completely by streaming or splitting it, which Free plan limits bind, and what dropping unused markup saves. Supporting evidence for #188, measured on CPython only.
- [Clinic schedule read: call sites, hosts and blast radius](schedule-read-call-sites-2026-11-24.md) (2026-11-24): where the clinic picker, Start and the daily recheck read the clinic schedule, what shares their Durable Object, and what a slow, failed or partial read does today. Supporting evidence for #188.
- [Clinic schedule read and each visit situation](schedule-read-lifecycle-impact-2026-11-24.md) (2026-11-24): how a single streamed read and a stored multi-step read would each affect every visit situation, and which tests cover them. Supporting evidence for #188.
- [Durable Object concurrency, alarms and Free plan limits](cloudflare-do-concurrency-2026-11-24.md) (2026-11-24): how Durable Objects interleave and abort, how alarms retry, and the Free plan storage and duration limits that a large read would use. Supporting evidence for #188.
- [Cutting CI wall time for the backend and browser test job](ci-test-wall-time-2026-11-23.md) (2026-11-23): what the browser tests share on one machine, and how matrix sharding, pytest-xdist, cheaper fixtures, caching and affected-test selection compare. It recommends 4 pytest-split shards behind one job that keeps the gate name.
- [CI/CD main branch policy and versioning before production](CI-CD-main-policy-and-versioning.md) (2026-11-15): whether every change must go through a pull request, what GitHub can enforce for this repository, and how Release Please versions should be managed between the release PR merge and production.
- [firstmate and Matt Pocock's skills workflow](firstmate-and-matt-skills-workflow.md) (2026-11-18): whether firstmate can implement work defined with `grilling`, `to-spec` and `to-tickets`, and where the two workflows conflict. The captain chose Option A: all phases run in this repository's own session, firstmate for exploration only.

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
