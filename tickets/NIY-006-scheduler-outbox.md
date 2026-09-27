# NIY-006: Scheduler, outbox, and send coordination

Status: Open

## Goal

Implement scheduled evaluation, durable event creation, retry-key reuse, and strict coordination among sends, Stop, recipient removal, withdrawal, and cutoff.

## Acceptance criteria

- Duplicate scheduled ticks cannot create a second near or unavailable event for a recipient and logical visit.
- Each event is persisted before an external request and reuses its stable LINE retry key after uncertain outcomes.
- Stop confirmation waits for already-started requests to settle and prevents any later request from starting.
- Withdrawal/removal erases identity-linked rows after in-flight sends settle and prevents further sends.
- Local concurrency tests cover overlap, restart/recovery, and the cutoff boundary.

## Dependencies

NIY-003, NIY-004, and NIY-005.
