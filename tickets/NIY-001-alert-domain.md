# NIY-001: Alert domain and initial schema

Status: In progress

The initial implementation draft was started before this ticket was moved out of the Git-excluded research area. The files below are now explicitly tracked against this ticket; subsequent changes follow this acceptance checklist.

## Goal

Implement pure, deterministic rules for comparable queue observations, the near window, the one-time unavailable warning, and minimal persistence constraints.

## Acceptance criteria

- A near alert is eligible only for a trustworthy, exactly matching clinic observation from 1 through 3 numbers before the patient's registration number.
- Equality updates state only; it does not send a second alert or stop a visit. A value beyond the patient's number does not create a catch-up alert.
- Untrusted or mismatched observations suppress near alerts. Three consecutive unusable reads produce at most one unavailable event per selected recipient and logical visit; a usable sample resets the consecutive-read count.
- Deduplication is represented by a persistence uniqueness constraint for each visit, recipient, and event kind.
- The initial migration contains only the five MVP tables and cascades recipient deletion to identity-linked visit selections and outbound events.
- Unit tests run locally with no hospital or LINE network calls.

## Current files

- `src/next_is_you/domain.py`
- `src/next_is_you/alerts.py`
- `migrations/0001_initial.sql`
- `tests/test_alerts.py`
- `tests/test_schema.py`

## Not in scope

Live hospital reads, LINE sends, authenticated user routes, Workers deployment, production Durable Object coordination, or claims that current/next semantics have been proven against a live clinic.
