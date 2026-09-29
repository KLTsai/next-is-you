# NIY-020: Clarify visit setup and monitoring controls

Status: Open

## Goal

Make visit setup, correction, start, and stop understandable during the next local manual acceptance.

## Captain-confirmed needs

- The first manual walkthrough left the draft, correction, revalidation, save, cancel, and stop actions unclear.
- Setup should avoid asking the user to re-enter codes or full values when the current flow already knows them.
- A clinic may offer morning, afternoon, and evening sessions. The user must be able to choose the intended session, including a later session after an earlier one has ended.
- The revised local flow must be understandable before real LINE-account testing. This ticket does not authorize real LINE calls, secrets, or deployment.

## Proposed implementation guardrails

These are acceptance suggestions, not additional UI decisions made by the captain:

- Reassess the existing "check or modify settings" action. Keep it only if it serves a distinct purpose; otherwise make the correction path directly reachable and avoid a redundant button.
- Show draft, active, stopping, and stopped states from the API's actual result; do not claim a stop succeeded while it is pending or failed.
- Keep Stop visible during active monitoring and explain its effect on future monitoring and notifications.
- Use readable hospital, department, clinic, doctor, and session labels where the current data supports them. Do not invent number lookup or partial-number matching.
- Offer only sessions actually returned for the selected clinic and date.
- Use automated UI coverage and a synthetic-data local checklist to verify the revised flow.

## Scope

- Clarify the draft and correction actions and the effect of unsaved edits.
- Make available monitoring actions and their outcomes clear in the UI.
- Prefer human-readable choices and avoid repeated entry where existing data is available.
- Keep session choices consistent with the options available for the selected clinic and date.
- Provide a local manual-acceptance checklist using synthetic data.

## Acceptance criteria

- Draft, correction, revalidation, save, and cancel actions are distinguishable, and unsaved edits are not mistaken for saved settings.
- Starting or stopping monitoring does not display a state that conflicts with the API result.
- The user can find Stop while monitoring is active and can understand its effect.
- Hospital, clinic, and session choices use readable labels where the current data supports them.
- Session choices reflect the selected clinic and date; unavailable sessions are not fabricated.
- Automated UI tests cover the revised flow, including navigation and unsuccessful or pending actions where supported by the existing API.
- The local manual checklist states the expected screen and outcome at each step and uses synthetic data and fake hospital and LINE adapters.
- Local tests pass. No real patient information, LINE delivery, live hospital polling, secrets, or deployment are used.

## Dependencies

NIY-007, NIY-008, NIY-010, and NIY-016.

## Out of scope

- Changing backend lifecycle or serialized Stop semantics. If the current API cannot support the required UI behavior, file a separate ticket before expanding this scope.
- Real LINE account testing, live hospital requests or polling, secrets setup, Cloudflare configuration, and deployment.
