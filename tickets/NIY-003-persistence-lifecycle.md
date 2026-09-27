# NIY-003: D1 repository and visit lifecycle

Status: In progress

## Goal

Implement repository operations for drafts, immutable logical visit series, the frozen recipient roster, corrected watches, recipient withdrawal, terminal state, and scheduled deletion.

## Acceptance criteria

- The first Start freezes additions to the recipient roster for that logical visit series; removal remains allowed.
- Corrections preserve the logical visit ID and per-recipient alert caps.
- Stop and cutoff create a terminal state and schedule deletion of visit identifiers and notification rows 48 hours later.
- Drafts expire 48 hours after the intended visit-day cutoff.
- Tests prove restore or cleanup cannot revive active watches or replay outbound events.

## Dependencies

NIY-001 and NIY-002.
