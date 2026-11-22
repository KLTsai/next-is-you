---
status: accepted
---

# Readers report what they are sure of, and reminders decide from whichever facts are present

The first reminder rule read one number per clinic, NTUH's list-card current light, and sent a near reminder when it was 1-3 below the patient number. Live reads on 2026-11-20 showed that number is not the front of the queue: patients sent for tests and patients who were passed come back in between, so the light jumped 22 → 42 → 8 in one morning while the highest called stood at 25. Each hospital also exposes different signals: NTUH has the highest called and every remaining number's status, 長庚 the next two numbers, 中榮 the people waiting, 慈濟 a waiting count with a warning that numbers skip (`research/hospital-schedule-and-progress-survey.md`).

We decided on 2026-11-20, in the #136 grilling, that:

- Each hospital reader reports a progress observation in which every field is optional and present only when the source states it outright: current light, highest called, the patient number's own status (not checked in, checked in, check-in position, being seen, absent from the list), the clinic's check-in-order position, the numbers the source says it will call next (NTUH 預計叫號, 長庚's next and next-but-one), people waiting, and source flags. A reader never estimates a field the page does not show.
- The reminder rule is one hospital-neutral rule that chooses which reminders it can send from the fields present. A reminder whose facts a hospital cannot supply is never sent for that hospital. There is no per-hospital reminder rule.
- Estimates, such as "about N people ahead", are made by the rule from reported facts, are worded as estimates, and never as minutes.
- A situation no one has observed on a hospital's pages sends nothing and is recorded, until observation supports a rule for it.
- A session is not a situation: an evening session follows the same rule as a morning or an afternoon, and a hospital offers it only for a department whose evening page has been captured (captain, 2026-11-22, #183).
- The rule is the same for every department, room and doctor. A clinic that calls out of order is handled by the checked-in reminder telling the family that the call order can change and later reminders may come too late, not by a rule for that department (captain, 2026-11-21): on 2026-11-20 眼科 called so far out of number order that no people-ahead threshold warned in time, while 內科 followed it (`research/private/source-evidence/ntuh-progress-validation-2026-11-20.md`).

## Considered options

- **One rule per hospital.** Rejected: every hospital would carry its own copy of caps, wording, recipients and lifecycle handling, and the family would get different behaviour per hospital, against the product's purpose of one familiar reminder across hospitals.
- **Keep a single "current number" for every hospital.** Rejected: it is the field that failed. It forces each reader to collapse rich signals into a number that does not mean queue position.

## Consequences

- Adding a hospital is a reader that fills the fields it can and a record of what it cannot. The reminder set it gets follows automatically.
- The rule must be tested per combination of present fields, not per hospital.
- Reading NTUH's per-clinic detail page falls under the source access rules in `docs/ADDING-A-HOSPITAL.md`: the list to find the card's link, then the detail page at the reader's stated cadence, counted across every live environment. Amended by the captain on 2026-11-22 (#163): until the clinic calls, the list is read again every 30 minutes, because a card removed or given to a substitute doctor after the link was found could not be noticed otherwise. It is also read again when the link stops leading to the clinic's page. Amended again by the captain on 2026-11-22 (#181): scheduled reads of a clinic begin one hour before its session's published start, because reading through the night (about 220 reads before a morning clinic is an hour away) told the organizer nothing they could act on, and a refusal or an outage at night messaged the family. The organizer learns on the visit day that a card is missing, or that a substitute has it, from one hour before the published start; the captain accepts that. Start on the visit day still reads once. The observation also says whether the clinic has called in this session, the one fact a reader works out by comparing what the source showed at different times.
