# NIY-004: Hospital adapters and synthetic fixtures

Status: Open

## Goal

Implement read-only parsers against synthetic fixtures for NTUH Main and Taipei Shin Kong source shapes.

## Acceptance criteria

- The normalized model keeps current number, next number, and call-type values distinct.
- Exact date, department, session, clinic, doctor, and room mismatches fail closed.
- Empty rows, stale samples, schema drift, challenge/denial, and ambiguous values do not produce trusted near alerts.
- No live hospital endpoint is called by tests or local development defaults.

## Dependencies

NIY-001 and NIY-003.
