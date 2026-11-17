# Next is you

The language used to build and deliver Next is you, a reminder service for hospital clinic queues.

## Language

### Hospitals

**Clinic schedule**:
What a hospital publishes about its outpatient clinics: which doctor consults in which room, in which session, on which day. Shown to users as 門診表. Always written in full, never as a bare "schedule".
_Avoid_: Schedule (alone), timetable, registration window, 掛號視窗

**Clinic schedule end date**:
The last day a hospital's clinic schedule currently covers. A visit after it cannot yet be checked against the hospital. Shown to users as 門診表最後一天.
_Avoid_: Schedule window, lookahead, schedule horizon, last schedulable date

**Clinic schedule release time**:
The moment a hospital says it will add a given day to its clinic schedule. Known only when the hospital states it publicly; otherwise it is unknown, never estimated. Shown to users as 門診表公布時間.
_Avoid_: Booking open time, registration open time

### Delivery

**Captain**:
The one person who decides what is accepted into the product and which version reaches production. Everyone else, human or agent, proposes.
_Avoid_: Admin, release manager

**Pipeline run**:
The single pass through the checks that one change starts, with whatever it goes on to deliver. Re-running it delivers that same change again.
_Avoid_: Build, CI job

**Gate**:
One named check in a pipeline run. A change moves forward only when every gate has passed.
_Avoid_: Step, stage

**Version**:
A named cut of the product: everything accepted up to one point, given a number by the captain's decision to ship it. A version may never reach production.
_Avoid_: Candidate, version candidate, build

**Release**:
A version the captain has put into production and announced.
_Avoid_: Candidate, deployment

**Staging**:
The private copy of the product that always shows the latest accepted work, where the captain checks a version before releasing it.
_Avoid_: Candidate environment, test site

**Reject**:
The captain's decision that a version checked on staging must not reach production. The fix ships as a later version.
_Avoid_: Rollback, revert

**Rollback**:
Returning production to an earlier version after a release has caused a problem. It restores code only; stored data and its schema stay as they are.
_Avoid_: Reject, undo
