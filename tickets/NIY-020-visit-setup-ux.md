# NIY-020: Clarify visit setup and monitoring controls

Status: Complete (2026-09-29)

## Goal

Make visit setup, correction, start, and stop understandable during the next local manual acceptance.

## Captain decision (2026-09-29)

“A：先限縮 NIY-020（建議）- 先完成現有 API 支援的按鈕、草稿與停止 UX；動態診次選項和修正時回填已存診號先列後續 API 工作，等 NIY-021 查證後再定。這會暫時保留部分設定摩擦。”

Accordingly, NIY-020 used the existing API only. Dynamic clinic/date-specific session options and prefilling the saved patient number during correction were deferred to follow-up API work pending NIY-021 findings. The UI may present the three session codes accepted by the current API, but must say these do not confirm clinic/date availability.

Dynamic sessions remain deferred pending evidence in the [NIY-021 findings summary](../research/NIY-021-findings-summary.md). The earlier patient-number-prefill deferral is superseded by [NIY-023](NIY-023-draft-correction-patient-number.md), which narrows exposure to the authorized correction flow.

## Captain-confirmed needs

- The first manual walkthrough left the draft, correction, revalidation, save, cancel, and stop actions unclear.
- Setup should avoid asking the user to re-enter codes or full values when the current flow already knows them. Existing projected settings should be prefilled. The current API still does not return the saved patient number; the authorized correction-flow follow-up is tracked in [NIY-023](NIY-023-draft-correction-patient-number.md).
- A clinic may offer morning, afternoon, and evening sessions. Dynamic clinic/date-specific session options are deferred by the captain decision above; do not imply the API's accepted session codes confirm availability.
- The revised local flow must be understandable before real LINE-account testing. This ticket does not authorize real LINE calls, secrets, or deployment.

## Proposed implementation guardrails

These are acceptance suggestions, not additional UI decisions made by the captain:

- Reassess the existing "check or modify settings" action. Keep it only if it serves a distinct purpose; otherwise make the correction path directly reachable and avoid a redundant button.
- Show draft, active, stopping, and stopped states from the API's actual result; do not claim a stop succeeded while it is pending or failed.
- Keep Stop visible during active monitoring and explain its effect on future monitoring and notifications.
- Use readable hospital, department, clinic, doctor, and session labels where the current data supports them. Do not invent number lookup or partial-number matching.
- Do not claim session availability without clinic/date-specific options from the API. Dynamic options are deferred as stated above.
- Use automated UI coverage and a synthetic-data local checklist to verify the revised flow.

## Scope

- Clarify the draft and correction actions and the effect of unsaved edits.
- Make available monitoring actions and their outcomes clear in the UI.
- Prefer human-readable choices and avoid repeated entry where existing data is available.
- Make the current API's accepted session codes understandable without presenting them as a verified clinic/date schedule.
- Provide a local manual-acceptance checklist using synthetic data.

## Acceptance criteria

- Draft, correction, revalidation, save, and cancel actions are distinguishable, and unsaved edits are not mistaken for saved settings.
- Starting or stopping monitoring does not display a state that conflicts with the API result.
- The user can find Stop while monitoring is active and can understand its effect.
- Hospital, clinic, and session choices use readable labels where the current data supports them.
- The current API's session codes have readable labels and a clear note that they are not verified for the selected clinic and date. Dynamic availability remains deferred pending NIY-021.
- Automated UI tests cover the revised flow, including navigation and unsuccessful or pending actions where supported by the existing API.
- The local manual checklist states the expected screen and outcome at each step and uses synthetic data and fake hospital and LINE adapters.
- Local tests pass. No real patient information, LINE delivery, live hospital polling, secrets, or deployment are used.

## Dependencies

NIY-007, NIY-008, NIY-010, and NIY-016.

## Out of scope

- Changing backend lifecycle or serialized Stop semantics. If the current API cannot support the required UI behavior, file a separate ticket before expanding this scope.
- Real LINE account testing, live hospital requests or polling, secrets setup, Cloudflare configuration, and deployment.

## Implementation outcome

- No standalone "check or modify settings" button was added. **修正草稿** and **修正後重新檢查** open the relevant correction form directly; **重新檢查並開始提醒** is a distinct lifecycle action.
- Draft edits show their unsaved state, preserve entered values through refreshes, and distinguish save from cancel. Start and Stop feedback follows the service response and refreshed visit state.
- The browser acceptance journey covers unavailable Start, saved draft edits, canceled edits, failed Stop, successful Stop, and correction of a stopped visit. See the [synthetic local checklist](../docs/NIY-020-LOCAL-MANUAL-CHECKLIST.md).
