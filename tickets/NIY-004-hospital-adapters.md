# NIY-004: Hospital adapters and synthetic fixtures

Status: Done (local acceptance passed)

## Goal

Implement read-only parsers against synthetic fixtures for NTUH Main and Taipei Shin Kong source shapes.

## Acceptance criteria

- The normalized model keeps current number, next number, and call-type values distinct.
- Exact date, department, session, clinic, doctor, and room mismatches fail closed.
- Empty rows, stale samples, schema drift, challenge/denial, and ambiguous values do not produce trusted near alerts.
- No live hospital endpoint is called by tests or local development defaults.

## Dependencies

NIY-001 and NIY-003.

## Current files

- `src/next_is_you/domain.py` keeps current, next, and highest-called numbers separate and normalizes only recognized call-type labels.
- `src/next_is_you/hospital_adapters.py` parses synthetic NTUH Main and Taipei Shin Kong samples without transport code; identity mismatches, stale samples, empty results, schema drift, challenges, denials, and ambiguous matches fail closed.
- `tests/fixtures/hospitals/` contains synthetic source-shaped samples; `tests/test_hospital_adapters.py` covers both adapters and their fail-closed cases.
- Parsed observations remain untrusted until source freshness semantics are independently verified.
- Validation: `uv run pytest -q` and `npm run build` pass locally. Tests and development defaults make no live hospital requests.
