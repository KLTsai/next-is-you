# NIY-007: Settings, status, and stop UI

Status: Complete (2026-09-28)

## Goal

Implement the provisionally accepted settings flow, visit status, draft correction, recipient selection, and obvious Stop controls.

## Acceptance criteria

- Session availability is not verified for the selected hospital/date/clinic. The current UI exposes API-supported session codes with a caveat; see the superseding NIY-020 decision and [local manual checklist](../docs/NIY-020-LOCAL-MANUAL-CHECKLIST.md).
- The UI distinguishes draft, active, stopping, stopped, source-unavailable, and terminal states.
- The user can review the hospital source link, selected recipients, latest check, observed queue data, and send result.
- Start requires a fresh trusted matching observation; an unavailable or mismatched source leaves the visit as a draft.
- Stop is reachable and explicit at any point while monitoring.

## Dependencies

NIY-002 through NIY-006, NIY-010, NIY-016.
