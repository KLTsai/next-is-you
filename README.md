# Next is you

> Watches a hospital queue page and sends a LINE reminder when your number is almost up.

[English (current)] · [繁體中文](README.zh-TW.md)

## What this is

Afternoon clinics at NTU Hospital's ophthalmology department can run for hours. A family member sits in the waiting room while the rest of the family stays elsewhere, hoping to arrive just in time. The light-number board moves at its own pace, so the only honest way to know when to leave is to keep refreshing the queue page by hand.

Next is you is a small private tool that does that watching. The owner opens a stable URL in a browser, drafts today's visit (hospital, department, room, doctor, afternoon session), and presses Start. A Cloudflare Worker then reads the public registration-progress page on a schedule, matches the clinic row, and - when the current number is close - sends one LINE message to the recipients the owner has invited.

It is a tool for one family and the people they invite, not a public service. Reminders stay held across every environment until the owner's own handset pilot (Issue #22) explicitly authorizes a real send.

## Status

Honest status as of today. The GitHub tracker is the authoritative source.

| Piece | State | Issue |
| --- | --- | --- |
| Private HTTPS service deployed, reminders held | In place; held bootstrap only, no live sends | [#18](https://github.com/KLTsai/next-is-you/issues/18) |
| LINE enrollment and withdrawal UI | In progress | [#19](https://github.com/KLTsai/next-is-you/issues/19) |
| NTU ophthalmology afternoon reader | Fixture and local integration evidence; live hospital behavior unverified | [#17](https://github.com/KLTsai/next-is-you/issues/17), [#20](https://github.com/KLTsai/next-is-you/issues/20) |
| Private storage recovery and operator readiness | Open | [#21](https://github.com/KLTsai/next-is-you/issues/21) |
| Owner's handset pilot (first real reminder) | Not yet performed | [#22](https://github.com/KLTsai/next-is-you/issues/22) |

Nothing in this list means a real patient reminder has been delivered. The Status table is the single place that describes what works today versus what is being built; features gated behind an open issue are not claimed anywhere else in this document.

The current single-hospital scope (NTU main-campus ophthalmology afternoon) is a starting point. Supporting additional hospitals is intended future work; each new source will need its own evidence record of a usable public page in the same shape as [Issue #17](https://github.com/KLTsai/next-is-you/issues/17) before it is added.

## How it works

```
   owner's browser                Cloudflare Worker                     LINE
   ----------------                -----------------                    ----
   create draft  ─────────►   store reminder in D1
     (hospital, room,              │
      doctor, session)             ▼
                              one-minute cron tick
                                   │
                                   ▼
                              NTUH reader fetches the
                              public registration-progress
                              list, matches the clinic row
                                   │
                                   ▼
                              send-gate (held) ─────────►  one message when
                                                           the called number
                                                           is almost up
```

The reader stores only the matched row's fields (room, doctor, clinic type, current number) for the clinic the owner's draft names. Raw response bodies are not retained. The send-gate is a per-environment hold: no environment emits a real LINE message until the Issue #22 pilot flips it, by design.

## For the owner (daily use)

Daily use is browser-only. The owner's stable origin is a fixed `workers.dev` URL set up during the first-time deployment; use the bookmark saved during that setup.

1. Open the stable URL in any browser.
2. Create a draft for today's visit.
3. Press **Start**.
4. Close the browser. The service continues watching the queue on its one-minute schedule.

To stop or hold:

- **Stop a reminder**: in the UI, open the active reminder and confirm **停止提醒**. A notification already in flight may settle before Stop confirms. See the [stop and recovery notes in the HTTPS service doc](docs/HTTPS-SERVICE.md#stop-failure-recovery-and-rollback).
- **Hold the whole service** (when the system is misbehaving): the owner, signed in, sets recovery hold through the authorized status API. The exact console snippet lives in the [HTTPS service manual acceptance section](docs/HTTPS-SERVICE.md#manual-deployed-acceptance-unrun). Recovery hold survives Worker restarts and must be set before any restore or code rollback.
- **Rollback the deployment**: use the native Wrangler rollback procedure in the [stop, failure recovery and rollback section](docs/HTTPS-SERVICE.md#stop-failure-recovery-and-rollback). Only roll back to a version compatible with the current schema and preserved SQLite class; this README deliberately does not restate the exact commands.

First-time deployment (secrets, Login channel registration, provisioning) is a separate owner setup; see [docs/HTTPS-SERVICE.md](docs/HTTPS-SERVICE.md).

## For other families (self-hosting)

Self-hosting is a real path, with real prerequisites and a real limit on scope.

Prerequisites:

- A Cloudflare account with Workers, D1, and SQLite Durable Objects available (the held bootstrap targets the Free plan; see the [HTTPS service doc's Free-plan table](docs/HTTPS-SERVICE.md#free-plan-and-origin-decision) for the quotas it depends on).
- A LINE Developers account with a Login channel and a Messaging channel under the same provider; the owner's LINE subject (a stable identifier, not a display name) must be privately supplied.
- Your own copy of this repository.

Scope limit: the only hospital source this project reads today is NTU Hospital's main campus (總院區) ophthalmology (眼科) afternoon session, 13:30-16:30, matched against the Dr. appointment list rows on the official public registration-progress page. See [docs/NTUH-READER.md](docs/NTUH-READER.md) for the exact supported scope and known gaps. Any other hospital, department, or session needs its own evidence pass in the shape of [Issue #17](https://github.com/KLTsai/next-is-you/issues/17) before it can be added.

For the end-to-end owner setup sequence (local proof, Wrangler login, D1 creation, migrations, deployment, LINE callback registration, acceptance), follow [docs/HTTPS-SERVICE.md](docs/HTTPS-SERVICE.md) in order.

## For developers

Install the locked dependencies once:

```sh
npm ci
uv sync --group dev --locked
```

Local entrypoints:

- **Complete local service rehearsal:** `npm run dev:rehearsal`, then open <http://127.0.0.1:8787>. Real local D1 and SQLite Durable Object bindings, synthetic login, fake providers. Needs no credentials. Follow the [complete rehearsal guide](docs/LOCAL-REHEARSAL.md) for the first synthetic setup, draft, Start/Stop, fake send, duplicate tick, and restart journey.
- **Lightweight shell smoke:** `npm run dev:local`, then open <http://127.0.0.1:8787>. UI build plus the Python ASGI app on loopback, no Cloudflare bindings. With the blank template, `curl -i http://127.0.0.1:8787/auth/line` returns `503`. Does not exercise database features or reminder sends.

CI-equivalent deterministic checks:

```sh
uv run playwright install chromium
uv run ruff format --check src tests
uv run ruff check src tests
npm run typecheck
npm run test:ui
npm run build
uv run python scripts/check_migrations.py
uv run pytest -q
git diff --check
```

These are fixture/mock and local automated evidence; they do not contact a live hospital or LINE, deploy, or prove handset delivery. See the [CI workflow](.github/workflows/ci.yml) for the gates it runs.

Linked procedures:

- [Complete rehearsal guide](docs/LOCAL-REHEARSAL.md)
- [NTUH reader guide](docs/NTUH-READER.md)
- [Pre-live checklist](docs/PRE-LIVE-CHECKLIST.md)
- [Local manual checklist](docs/NIY-020-LOCAL-MANUAL-CHECKLIST.md)
- [HTTPS service preparation](docs/HTTPS-SERVICE.md)
- [Research index](research/README.md), including the [NIY-021 findings summary](research/NIY-021-findings-summary.md)
- [Issue-tracker conventions](docs/agents/issue-tracker.md); historical records are [archived](docs/archive/tickets/README.md)

Active work is tracked in [GitHub Issues](https://github.com/KLTsai/next-is-you/issues).

## Scope and non-goals

Next is you is a private family tool. It will not:

- Become a public SaaS or support multi-tenant onboarding.
- Calculate ETAs, predict the next number, or infer the queue from neighboring rows.
- Add paid-plan features, status badges that depend on external services, or marketing surfaces.

Reminder sends remain held in every environment until the owner's handset pilot ([Issue #22](https://github.com/KLTsai/next-is-you/issues/22)) explicitly authorizes a real reminder.

## Privacy

Next is you is designed to keep as little as it needs:

- **What is stored:** invitation records, consent records, and outbox events for scheduling and deduplication. No raw hospital response bodies are retained; the reader keeps only the matched row's fields (room, doctor, clinic type, current number) for the clinic the owner's draft names.
- **Appointment cutoff:** at 23:59 Taipei time on the appointment date, active reminders expire and no further notices are sent.
- **Active-data cleanup:** drafts and expired reminders are cleaned up 48 hours after the Taipei-midnight cutoff; stopped reminders are cleaned up 48 hours after Stop.
- **Withdrawal:** when a recipient withdraws, their record is erased.
- **Backups:** backup retention is tracked separately from active-data cleanup; see the [pre-live checklist](docs/PRE-LIVE-CHECKLIST.md) for the deployed storage and backup gates.

The exact mechanics live in the storage and lifecycle docs; this section states them in plain terms. The owner's stable origin is a public `workers.dev` URL whose static shell and `/api/healthz` endpoint are reachable to anyone, while organizer data and mutations require an allowlisted LINE session and CSRF.
