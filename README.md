# Next is you

Next is you is a new application project.

This repository is maintained in English.
More details will be added as the product direction takes shape.

Active work is tracked in [GitHub Issues](https://github.com/KLTsai/next-is-you/issues); see the [issue-tracker conventions](docs/agents/issue-tracker.md). The former local tickets are [archived historical records](docs/archive/tickets/README.md). Their completion statements retain their original evidence limits; the [pre-live checklist](docs/PRE-LIVE-CHECKLIST.md) owns the remaining live gates.

## Local Worker

Install the Python development dependencies with `uv sync --group dev` and the frontend dependencies with `npm ci`. Copy `.env_template` to the repository-root `.env`, then fill only the values needed for local work. For example, run `cp .env_template .env` and open it with `${EDITOR:-vi} .env`; do not put values in shell commands or terminal transcripts. `npm run dev:local` builds the Vite UI, loads that `.env` when present, and serves the FastAPI app at `http://127.0.0.1:8787`. It binds to loopback and does not deploy. The loader never prints configuration values. Do not commit or share `.env`.

For local LINE Login configuration, set `LINE_LOGIN_CHANNEL_ID`, `LINE_LOGIN_CHANNEL_SECRET`, `LINE_LOGIN_REDIRECT_URI`, and a `SESSION_SIGNING_SECRET` of at least 32 UTF-8 bytes. Set `ORGANIZER_LINE_SUBJECTS` to the comma-separated LINE subject IDs authorized as organizers. Missing or invalid settings leave login unavailable. The plain Uvicorn launch has no Cloudflare bindings, so database-backed features and scheduler sends remain unavailable; `LINE_CHANNEL_ACCESS_TOKEN` alone cannot enable sending. `NIY006_LOCAL_TEST_MODE` is ignored by this launch path. Use the separate `wrangler.niy006.test.jsonc` only for the NIY-006 local test harness.

To verify the fail-closed local setup without credentials, leave the copied template blank, start `npm run dev:local`, and in another terminal run `curl -i http://127.0.0.1:8787/auth/line`; the route should return `503`. Open `http://127.0.0.1:8787/` to check the built UI, then stop the server with Ctrl-C. For a configured local login, use only your own local values in `.env`; this standard Python launch has no Cloudflare bindings, and scheduler sends remain disabled. The local `.env` is ignored and may be kept on this machine; never commit or share it. Never paste credential values into commands, tickets, or logs.

Production uses Cloudflare Worker configuration. Store `LINE_LOGIN_CHANNEL_SECRET`, `SESSION_SIGNING_SECRET`, and `LINE_CHANNEL_ACCESS_TOKEN` as Worker secrets. Provision `LINE_LOGIN_CHANNEL_ID`, `LINE_LOGIN_REDIRECT_URI`, and `ORGANIZER_LINE_SUBJECTS` through the deployment environment outside tracked files; treat the organizer allowlist as sensitive operational data. Configure `ASSETS`, `DB`, and `SEND_GATE` as Wrangler platform bindings, not `.env` entries. Never use local `.env` values as production configuration, and never enable `NIY006_LOCAL_TEST_MODE` in production.

## Complete local service rehearsal

Prepare once with `npm ci` and `uv sync --group dev --locked` (uv 0.12.3 or newer,
Python 3.13 or newer), then start the complete local service:

```sh
npm run dev:rehearsal
```

Open <http://127.0.0.1:8787>. This foreground command builds current UI assets,
applies local D1 migrations and serves the Worker with the existing SQLite
Durable Object, synthetic login and fake hospital/LINE providers. It uses the
same `.wrangler/manual-rehearsal` dataset on repeat starts; it does not reset data
or seed recipients. No real credentials are needed and it does not deploy.

Follow the [complete rehearsal guide](docs/LOCAL-REHEARSAL.md) for one-time native
synthetic recipient preparation, UI draft save/edit, saved-draft patient-number
identity, patient-number prefill, Start/Stop, one fake reminder, and
same-dataset restart/duplicate-tick checks.
The guide includes expected results, failure/recovery and Stop/Ctrl-C instructions.
The [lifecycle checklist](docs/NIY-020-LOCAL-MANUAL-CHECKLIST.md) covers additional
fixture UI outcomes. Authenticated organizer draft cards show the synthetic
patient number for local identification; the selected correction flow also
prefills it through the authorized API.

`npm run dev:local` remains a lightweight shell smoke without D1/DO. A real local
binding plus fake delivery is local integration evidence, not hospital freshness,
LINE acceptance, handset delivery or deployed ordering. See the
[pre-live checklist](docs/PRE-LIVE-CHECKLIST.md) for those separate gates.

## CI and local acceptance (NIY-008)

From a clean checkout, install the pinned dependencies and run the same deterministic gates as CI:

```sh
uv sync --group dev --locked
npm ci
uv run playwright install chromium
uv run ruff format --check src tests scripts
uv run ruff check src tests scripts
npm run typecheck
npm run test:ui
npm run build
uv run python scripts/check_migrations.py
uv run pytest -q
git diff --check
```

Expected outcomes: Ruff reports no formatting or lint issues, TypeScript exits successfully, all frontend tests pass, Vite builds `dist/`, the migration checker reports that every migration applied and SQLite schema checks passed, and pytest reports the complete Python suite passed. The Python suite includes `tests/test_local_acceptance.py`, which serves the built browser shell and drives organizer HTTP routes, SQLite, the synthetic hospital fixture, scheduled ticks, and the fake LINE transport in process. Scheduler tests also cover duplicate ticks and corrected watches, equality and jumps past the target, the one-time third-read unavailable warning, and both send/Stop orderings. None of these tests make hospital, LINE, Cloudflare, or deployment requests.

The workflow fetches full Git history so it can check the actual event range. Pull requests check `base...head`; pushes check `before..after`, and new-branch pushes compare against the fetched default branch. `scripts/check_ci_diff.sh` fails when event metadata, commit objects, or a merge base is unavailable. The local `git diff --check` command checks your working tree changes.

The browser test requires the Playwright Chromium browser installed by the command above. The HTTP test uses ASGI transport; the browser test binds a temporary loopback server and blocks browser requests to every other origin. To repeat the separate Wrangler visual journey, follow the [complete local service rehearsal](docs/LOCAL-REHEARSAL.md). See [the pre-live checklist](docs/PRE-LIVE-CHECKLIST.md) for gates local tests do not prove.
