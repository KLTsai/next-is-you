# Next is you

The language used to build and deliver Next is you, a reminder service for hospital clinic queues.

## Language

### People

**Organizer**:
The person who sets up reminders: signs in with LINE, invites recipients, drafts a visit, and presses Start and Stop. Only LINE accounts the captain has allowed can be organizers. Shown to users as 設定者.
_Avoid_: Owner, user, manager, 管理者

**Recipient**:
A family member who accepted an invitation and agreed to receive reminders on LINE. An organizer may also be a recipient with the same LINE account.
_Avoid_: Member, subscriber, audience

**Live pilot**:
The first time a deployed copy of the product really reads the hospital and sends a reminder to a handset: Staging, once made live, with the captain as its only organizer and recipient.
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

### Visits

**Visit**:
A job an organizer sets up and sends off: follow one clinic's progress on one day for one patient number, and tell the chosen recipients on LINE when to check in, when the number has been passed, and when the patient's turn comes close. It starts as a draft, runs once the organizer presses Start, and ends when it is stopped, the patient number leaves the hospital's list, the clinic ends, or its day is over. A visit the hospital confirms cannot happen as set up is stopped by the system and comes back as a draft for the organizer to correct. Shown to users as 叫號追蹤, counted as 一個.
_Avoid_: Watch, reminder setting, appointment, 看診提醒, 監聽工作

**Patient**:
The person who is seen at the clinic. A patient need not be an organizer or a recipient, and the product never stores who they are, only their patient number.
_Avoid_: User, member, 病患資料

**Patient number**:
The number a patient was given for one clinic on one day, which the clinic calls. Shown to users as 看診號碼.
_Avoid_: Ticket, queue number, 燈號 (alone)

**Current light**:
The number a clinic is showing as now being called. It is not the front of the queue: patients sent away for tests and patients who missed their call come back in between. Shown to users as 目前燈號.
_Avoid_: Called number, current number, progress

**Highest called**:
The largest number a clinic has called so far today. A patient number below it has had its call, whether or not the patient has been seen. Shown to users as 已叫最大號.
_Avoid_: Max number, current light

**Check in**:
A patient telling the clinic they have arrived, by card or at the desk. Some clinics see patients in the order they checked in instead of by patient number. Shown to users as 報到.
_Avoid_: Arrive, register, 掛號

**Passed**:
A patient number whose call came while the patient had not checked in. The patient must check in at once to be seen. Shown to users as 過號.
_Avoid_: Skipped, missed, expired

**Called next**:
The few numbers a hospital says it will call after the current one, when it says so. A number listed there is about to be called, whatever its place by number. Shown to users as 預計叫號.
_Avoid_: Next number, queue

**People ahead**:
The product's estimate of how many checked-in patients will be seen before the patient, made from what the hospital shows. Always an estimate, written as 約 N 人, never as minutes: patients who were passed or sent for tests can come back in front.
_Avoid_: Position, wait time, queue length

**Needs attention**:
A mark on a visit telling its organizer that the visit has a problem only they can resolve, with the reason and what to do next. A visit can carry several reasons at once. Shown to users as 需要處理.
_Avoid_: Organizer attention, warning, alert

**Confirmed mismatch**:
A problem the hospital's own pages state outright: the clinic is not scheduled or is cancelled that day, or the doctor is unambiguously in another room or session. The system stops the visit and returns it to draft. Anything less than certain is an unconfirmed problem instead. Shown to users as 院方確認不符.
_Avoid_: Setup problem, hard failure, invalid visit

**Unconfirmed problem**:
A problem the system cannot be sure of, such as the hospital's site being unreadable, the clinic missing from the day's list, or a substitute doctor. The visit keeps running and needs attention. Shown to users as 無法確認的問題.
_Avoid_: Source problem, soft failure, transient error

**Clinic to be chosen**:
A draft whose clinic has not been picked yet because the hospital's list could not be read or the day is not yet on the clinic schedule. It cannot be started until the organizer picks the clinic. Shown to users as 待選門診.
_Avoid_: Manual entry, incomplete draft, pending clinic

**Unavailable message**:
The one message a recipient gets on the visit day when the system cannot follow the clinic, naming the visit, the reason and what to do instead. Shown to users as 讀不到進度通知.
_Avoid_: Failure notice, error message

**Daily recheck**:
The system checking, once a day, that each visit that has not happened yet still matches what the hospital publishes, and on the visit day itself, before the clinic opens, that the visit's clinic is there. Covers drafts and running visits. Shown to users as 每日複查.
_Avoid_: Pre-flight sweep, preflight, sweep

### Sending

**Live**:
A deployed environment that reads real hospitals and sends real LINE reminders. Each environment starts not live and is made live once, after its own pre-live gates pass, and is never made not live again; to stop sending, use a send interruption. Expired data is cleaned up either way. Shown to users as 已開通 and 未開通.
_Avoid_: Send hold, configuration hold, production hold, go-live

**Send interruption**:
A stop on all sending in one environment. The system enters it when its record of what it has sent was changed by something outside its own control, such as a restore or a migration, or when it could not write down the result of a send; the captain can also set it by hand before a restore or rollback. Only the captain ends it, by resuming sending after checking. Visits keep their state through it: it pauses them, it does not stop them. A LINE request whose outcome is merely unknown is retried, not interrupted. Shown to users as LINE 通知暫停發送.
_Avoid_: Recovery hold, reconciliation hold, safety stop, brake

**Resume sending**:
The captain ending a send interruption once they have checked what happened. Running visits that are still valid carry on; it never brings back a stopped visit. Shown to users as 恢復發送 LINE 通知.
_Avoid_: Release, unhold, end interruption

### Delivery

**Captain**:
The one person who decides what is accepted into the product and which version reaches production. Everyone else, human or agent, proposes. Also the one who operates every deployed environment, including interrupting and resuming sending. Writing code does not make someone the captain. Shown to users as 服務負責人, or 負責人 for short.
_Avoid_: Admin, release manager, owner, operator, developer, 開發者

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
