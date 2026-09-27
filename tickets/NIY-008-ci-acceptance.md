# NIY-008: CI and local acceptance journey

Status: Open

## Goal

Add deterministic CI gates and a local synthetic end-to-end journey across the browser, routes, database, scheduler, hospital fixtures, and fake LINE transport.

## Acceptance criteria

- CI runs formatting/lint, type checks, frontend build, Python tests, migration checks, and local HTTP integration tests.
- A synthetic 85-vs-82 visit alerts only selected recipients once; repeated ticks and corrected watches do not resend.
- Equality is display-only, jumps do not catch up, three consecutive unusable reads trigger at most one warning, and Stop is concurrency-tested.
- Tests make no live hospital, LINE, or deployment requests.
- A separate pre-live checklist names the unproven source, LINE, Cloudflare Free, and data-retention gates.

## Dependencies

NIY-001 through NIY-007.
