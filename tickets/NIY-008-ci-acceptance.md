# NIY-008: CI and local acceptance journey

Status: Open (GitHub Action reference follow-up, 2026-09-29)

## Follow-up: Wrangler Python Worker startup compatibility

The local synthetic Wrangler run now passes its assets check but fails while
importing `FastAPI` from `src/worker.py`. FastAPI telemetry initializes an
OpenTelemetry key through `uuid4()`, which reaches `os.urandom()` and is
rejected by the Workers runtime during startup. This conflicts with the
earlier NIY-006 local Python Worker + FastAPI + D1 + Durable Object + Cron
smoke, so the repair must identify the dependency or runtime divergence before
changing compatibility behavior.

### Follow-up acceptance criteria

- The failure is reproduced with the tracked synthetic Wrangler configuration
  and the dependency/runtime and relevant commit history are compared with the
  historically successful NIY-006 smoke.
- A behavioral regression test fails before the repair and passes after it,
  covering FastAPI import/startup under the local Workers runtime constraints.
- The synthetic Wrangler Worker completes startup, serves its local HTTP
  journey, and reaches the configured D1, Durable Object, and Cron paths
  without the startup entropy exception.
- The repair preserves secure runtime entropy for application code and does not
  monkey-patch `os.urandom`, use predictable random identifiers, or disable
  Workers startup-entropy protection.
- All verification remains local and synthetic; no live hospital or LINE
  requests, secrets, deployment, tunnels, or publication are used.

## Follow-up: GitHub Action reference

The first GitHub Actions run after publishing the initial repository state failed before any test job ran because `astral-sh/setup-uv@v10` could not be resolved. Restore a resolvable published action reference and confirm the workflow reaches and passes its deterministic gates.

The failed `v10` reference was not a published setup-uv release tag; the publisher's
release history lists `v10.1.0`. Workflow references use resolvable published releases.

### Follow-up acceptance criteria

- Every action reference used by the workflow resolves to a published version.
- A GitHub Actions run for the repair completes the setup steps and reaches the deterministic checks.
- All deterministic checks pass, with no live hospital or LINE requests, secrets setup, or deployment.

## Goal

Add deterministic CI gates and a local synthetic end-to-end journey across the browser, routes, database, scheduler, hospital fixtures, and fake LINE transport.

## Acceptance criteria

- CI runs formatting/lint, type checks, frontend build, Python tests, migration checks, and local HTTP integration tests.
- A synthetic 85-vs-82 visit alerts only selected recipients once; repeated ticks and corrected watches do not resend.
- Equality is display-only, jumps do not catch up, three consecutive unusable reads trigger at most one warning, and Stop is concurrency-tested.
- Tests make no live hospital, LINE, or deployment requests.
- A separate pre-live checklist names the unproven source, LINE, Cloudflare Free, and data-retention gates.

## Dependencies

NIY-001 through NIY-007, NIY-010.

## Implementation and local validation

- `.github/workflows/ci.yml` runs Ruff format and lint, the TypeScript check, frontend tests and build, Playwright Chromium installation, SQLite migration checks, the full Python suite, and an event-aware diff whitespace check. It fetches full Git history; pull requests compare base to head, pushes compare before to after, and new branch pushes use the fetched default branch. Missing or unavailable ranges fail closed. CI uses Python 3.13 and Node 24 with locked dependencies. It has no deploy step or credentials.
- `tests/test_local_acceptance.py` has an HTTP integration journey and a real headless-browser journey. Both use loopback/in-process routes, migrated in-memory SQLite, a synthetic organizer and recipients, the tracked NTUH-shaped fixture, the local scheduler, and fake LINE transport. The browser test blocks browser requests to every origin except its loopback server.
- The journeys assert fail-closed Start without an observation, selected-recipient-only delivery for patient 85/current 82, one alert after repeated ticks, equality and a jump beyond the target producing no alert, Stop confirmation and no later sends. Existing alert/scheduler tests assert one warning on the third consecutive unusable read, no repeat warning, corrected-watch deduplication, and both send-first and Stop-first orderings.
- Run from a clean checkout:

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

- Expected results: Ruff, TypeScript, build, migration, and diff checks exit 0; all 8 frontend tests pass; the migration checker prints `Applied 3 migrations; SQLite schema checks passed.`; all 115 Python tests pass, including the Wrangler startup check and both local acceptance journeys. Tests do not contact live hospitals, LINE, Cloudflare, or deployment targets.
- `tests/test_worker_startup.py` runs `pywrangler dev --local` with the tracked NIY-006 configuration, applies only the local synthetic D1 migrations, and checks Worker health, D1/SQLite Durable Object access, and the local Cron trigger. The actual-browser automated acceptance still uses Uvicorn with local SQLite and fake transports. Source access/freshness, real LINE behavior, deployed Cloudflare limits and restore behavior, and production data-retention operations remain unproven in [the pre-live checklist](../docs/PRE-LIVE-CHECKLIST.md).
