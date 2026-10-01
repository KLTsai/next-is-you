# NIY-005: LINE identity and targeted delivery

Status: Complete (2026-09-28)

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

## Delivered

- Organizer sessions are issued only to configured LINE subject allowlist members and the allowlist is checked again on organizer mutations. Recipient sessions use a distinct role. All state-changing routes require the signed session's CSRF token.
- Organizer invitations are opaque, single-use, stored by hash, and expire after 24 hours. Recipient enrollment uses LINE Login `openid profile`, checks `friendFlag` with the just-issued user access token, discards that token, and creates a pending identity. A separate recipient opt-in activates consent; withdrawal deactivates and erases the identity after in-flight sends settle.
- Visit selection is organizer-only and requires an active opted-in recipient with a successful enrollment friendship check. The recorded friendship check is informational; no claim is made that it proves friendship still holds at dispatch time.
- LINE push requests use the individual-user push endpoint and reject non-user LINE IDs. Results report only `accepted`, `failed`, or `unknown`; they never claim handset delivery.
- Tests use local credentials and fake OAuth, friendship, and push transports.

## Validation

- `uv run pytest`: 79 passed.
- `npm run build`: passed.
- `git diff --check`: passed.
