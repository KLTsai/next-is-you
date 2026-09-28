# NIY-008: CI and local acceptance journey

Status: Complete (local acceptance passed, 2026-09-28)

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

- `.github/workflows/ci.yml` runs Ruff format and lint, the TypeScript check, frontend tests and build, Playwright Chromium installation, SQLite migration checks, the full Python suite, and `git diff --check`. CI uses Python 3.13 and Node 24 with locked dependencies. It has no deploy step or credentials.
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

- Expected results: Ruff, TypeScript, build, migration, and diff checks exit 0; all 8 frontend tests pass; the migration checker prints `Applied 3 migrations; SQLite schema checks passed.`; all 113 Python tests pass, including both local acceptance journeys. Tests do not contact live hospitals, LINE, Cloudflare, or deployment targets.
- Wrangler-backed manual acceptance could not be run on the task runner: its `uv 0.11.32` is below the `pywrangler` minimum `0.12.3`. The actual-browser automated acceptance uses Uvicorn with local SQLite and fake transports. Source access/freshness, real LINE behavior, deployed Cloudflare limits and restore behavior, and production data-retention operations remain unproven in [the pre-live checklist](../docs/PRE-LIVE-CHECKLIST.md).
