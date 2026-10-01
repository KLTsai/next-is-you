# NIY-003: D1 repository and visit lifecycle

Status: Done

## Goal

Implement repository operations for drafts, immutable logical visit series, the frozen recipient roster, corrected watches, recipient withdrawal, terminal state, and scheduled deletion.

## Acceptance criteria

- The first Start freezes additions to the recipient roster for that logical visit series; removal remains allowed.
- Corrections preserve the logical visit ID and per-recipient alert caps.
- Stop and cutoff create a terminal state and schedule deletion of visit identifiers and notification rows 48 hours later.
- Drafts expire 48 hours after the intended visit-day cutoff.
- Local tests prove cleanup cannot delete a terminal visit while an outbound event is in flight. D1 restore reconciliation and send-ordering protection remain cross-ticket integration acceptance; this ticket's SQLite tests do not prove them.

## Dependencies

NIY-001 and NIY-002.

## Current implementation

- `src/next_is_you/persistence.py` provides prepared D1 binding operations, draft handling, roster freeze, correction, stop/cutoff, withdrawal cleanup, and 48-hour expiry.
- Stop validates its timestamp before moving an active visit into the stopping state.
- Local lifecycle tests use SQLite with the tracked D1-compatible migration; they do not prove Cloudflare D1 runtime behavior.
- Real D1 Time Travel restore reconciliation and the Durable Object send-ordering gate remain unverified integration requirements.
