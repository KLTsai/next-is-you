---
status: accepted
---

# A visit has one ended state with an end reason

A visit ends for several causes, and the organizer page must say which: the organizer stopped it, the patient number left the hospital's list (#169), the clinic showed no change for an hour (#138), every recipient was removed (#244), or its day is over. The schema had two end states, `stopped` and `expired`, and the tickets assumed groundwork none of them owned: #169 and #138 "shared one end reason", and #160 wrote one sentence for every stopped card.

We decided on 2026-11-25, in the captain's grilling, that a visit's states are `draft`, `active`, `stopping` and `ended`. An ended visit records one end reason and an ended-at clock. The end reasons are `organizer_stopped`, `number_left_list`, `clinic_quiet`, `recipients_removed` and `day_over`, each with its own organizer sentence in the catalog and the frontend text map, covered by the drift test. #247 builds this.

## Considered options

- **One shared end reason for the system's ends.** Rejected: the page could not show "the number is no longer on the list" and "no change for an hour" as different sentences.
- **Keep `stopped` and `expired`, and add a reason.** Rejected: the state names would lie (`stopped` with `day_over`, or `stopped` for an end nobody pressed), and every reader would have to check two fields to know why a visit ended.

## Rules that follow

- `ended` only ever refers to the visit. The glossary's judgment that a clinic finished stays **Clinic ended**, and its end reason is `clinic_quiet`, never `clinic_ended`. `stopped` and `expired` are retired as visit states.
- `stopping` stays only for the organizer's Stop waiting for a message already in flight. An end with nothing in flight, such as removing the last recipient (#244), goes straight to `ended`.
- A visit sent back to draft because the hospital confirmed a mismatch (#148) has not ended and has no end reason; it carries an attention reason. It goes from `active` straight to `draft`, never through `stopping`.
- The 48-hour deletion counts from ended-at, the same for every reason.
- Ending a visit cancels its `pending` and `unknown` reminders because the visit ended. Returning it to draft for a confirmed mismatch cancels them too: an `unknown` reminder retried later could reach the family with the clinic the hospital just said is wrong (captain, 2026-11-26, #249).
- A cancelled reminder records, when it is cancelled, the code of its cause: the visit's end reason, or the confirmed-mismatch attention reason that returned it to draft. The record is for looking back at why a reminder was not sent; no one is shown it. It reuses those two vocabularies and adds no third (captain, 2026-11-26, #249). Pointing to the visit's current reason instead was rejected: a draft corrected and started again no longer carries the attention reason, so the reminder would lose its cause.
