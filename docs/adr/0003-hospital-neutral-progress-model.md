---
status: accepted
---

# Readers report what they are sure of, and reminders decide from whichever facts are present

The first reminder rule read one number per clinic, NTUH's list-card current light, and sent a near reminder when it was 1-3 below the patient number. Live reads on 2026-11-20 showed that number is not the front of the queue: patients sent for tests and patients who were passed come back in between, so the light jumped 22 → 42 → 8 in one morning while the highest called stood at 25. Each hospital also exposes different signals: NTUH has the highest called and every remaining number's status, 長庚 the next two numbers, 中榮 the people waiting, 慈濟 a waiting count with a warning that numbers skip (`research/hospital-schedule-and-progress-survey.md`).

We decided on 2026-11-20, in the #136 grilling, that:

- Each hospital reader reports a progress observation in which every field is optional and present only when the source states it outright: current light, highest called, the patient number's own status (not checked in, checked in, check-in position, being seen, absent from the list), the clinic's check-in-order position, people waiting, and source flags. A reader never estimates a field the page does not show.
- The reminder rule is one hospital-neutral rule that chooses which reminders it can send from the fields present. A reminder whose facts a hospital cannot supply is never sent for that hospital. There is no per-hospital reminder rule.
- Estimates, such as "about N people ahead", are made by the rule from reported facts, are worded as estimates, and never as minutes.
- A situation no one has observed on a hospital's pages sends nothing and is recorded, until observation supports a rule for it.

## Considered options

- **One rule per hospital.** Rejected: every hospital would carry its own copy of caps, wording, recipients and lifecycle handling, and the family would get different behaviour per hospital, against the product's purpose of one familiar reminder across hospitals.
- **Keep a single "current number" for every hospital.** Rejected: it is the field that failed. It forces each reader to collapse rich signals into a number that does not mean queue position.

## Consequences

- Adding a hospital is a reader that fills the fields it can and a record of what it cannot. The reminder set it gets follows automatically.
- The rule must be tested per combination of present fields, not per hospital.
- Reading NTUH's per-clinic detail page becomes part of the hospital-access conditions recorded for #129.
