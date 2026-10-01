# NIY-023: Prefill saved patient number in draft correction

Status: Open

## Goal

When an authorized organizer reopens a saved draft for correction, prefill the patient number that was saved with that draft so the organizer does not need to remember or re-enter it.

## Scope

- Add the saved patient number to the minimum correction-specific response required to initialize the correction form.
- Require the existing organizer authorization and current organizer allowlist/CSRF protections for the correction flow.
- Keep the number out of the general organizer visit-list projection, logs, LINE messages, and recipient-facing data.
- Preserve the existing draft lifecycle and correction behavior.

## Acceptance criteria

- Using synthetic local data, create a draft with patient number `85`, then reopen it through the authorized correction flow; the response contains `85` and the correction form visibly pre-fills `85`.
- The general visit-list response does not contain the patient number, while an unauthorized, non-organizer, or invalid-CSRF correction request cannot obtain it.
- The saved value remains correct after multiple drafts exist and after canceling and reopening the selected draft.
- Automated route/UI tests cover authorization, privacy boundaries, and the prefilled correction journey with synthetic data only.

## Dependencies

NIY-010 for organizer API authorization and lifecycle behavior; NIY-020 for the existing correction UI. This ticket supersedes NIY-020's historical patient-number-prefill deferral without erasing that decision.

## Out of scope

- Adding patient numbers to list projections, logs, LINE messages, recipient views, or broad API payloads.
- Changes to patient-number validation, lifecycle semantics, hospital adapters, live providers, secrets, deployment, or real patient data.
