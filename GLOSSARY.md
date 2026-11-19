# Next is you

The language used to build and deliver Next is you, a reminder service for hospital clinic queues.

## Language

### People

**Organizer**:
The person who sets up reminders: signs in with LINE, invites recipients, drafts a visit, and presses Start and Stop. Only LINE accounts the captain has allowed can be organizers.
_Avoid_: Owner, user, manager

**Recipient**:
A family member who accepted an invitation and agreed to receive reminders on LINE. An organizer may also be a recipient with the same LINE account.
_Avoid_: Member, subscriber, audience

**Live pilot**:
The first time a deployed copy of the product really reads the hospital and sends a reminder to a handset, with the captain as organizer and recipient, before any family member is invited.
_Avoid_: Launch, go-live, beta

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

### Sending

**Send hold**:
The temporary rule, in force until the live pilot, that a deployed copy of the product sends no reminder, reads no hospital and calls no LINE. Once the pre-live gates pass it is removed from production for good, not toggled. Expired data is still cleaned up under it.
_Avoid_: Configuration hold, production hold, send-gate hold

**Recovery hold**:
A stop on all sending that the system enters when it cannot prove what it has sent, or that the captain sets by hand before a restore or rollback. It lasts until the captain releases it after reconciling, and while it holds only expired drafts are deleted.
_Avoid_: Reconciliation hold, operator hold

### Delivery

**Captain**:
The one person who decides what is accepted into the product and which version reaches production. Everyone else, human or agent, proposes. Also the one who operates production, including setting and releasing holds.
_Avoid_: Admin, release manager, owner, operator

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

**Restore**:
Returning a database, its data and its schema together, to how it was at an earlier moment. Everything written after that moment is lost, so only the captain decides it. It is separate from a rollback, which returns code only.
_Avoid_: Rollback, undo, revert

**Restore point**:
The recorded moment a restore can return a database to, written down on the captain's instruction just before a version that changes the database is put into production.
_Avoid_: Backup, snapshot, checkpoint
