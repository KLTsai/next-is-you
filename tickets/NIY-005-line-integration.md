# NIY-005: LINE identity and targeted delivery

Status: Open

## Goal

Implement LINE Login/session interfaces, organizer allowlisting, short-lived recipient invitations, opt-in/withdrawal, friendship checks, and one-recipient push requests behind testable adapters.

## Acceptance criteria

- Organizer and recipient permissions are distinct and enforced server-side.
- Visit selection requires prior recipient opt-in and current eligibility.
- Outbound requests target recipients individually and never use group broadcast.
- Transport results distinguish accepted, failed, and unknown; they never claim handset delivery.
- Tests use fake LINE transport and local credentials only.

## Dependencies

NIY-002 and NIY-003.
