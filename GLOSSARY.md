# Next is you

The language used to build and deliver Next is you, a reminder service for hospital clinic queues.

## Language

### People

**Organizer**:
The person who sets up reminders: signs in with LINE, invites recipients, drafts a visit, and presses Start and Stop. Only LINE accounts the captain has allowed can be organizers, and every organizer sees and manages every visit and recipient. Each organizer is told on LINE about every visit's problems, once they are a friend of the environment's official account. Shown to users as 設定者.
_Avoid_: Owner, user, manager, 管理者

**Recipient**:
A family member who accepted an invitation and agreed to receive reminders on LINE. Every organizer is also a recipient with the same LINE account, without an invitation: signing in as an organizer counts as agreeing. Like any recipient, an organizer gets reminders only for the visits they are added to. On a visit, the recipients chosen for it are shown to users as 通知對象.
_Avoid_: Member, subscriber, audience, 成員

**Recipient list**:
Every recipient, whether they accepted an organizer's invitation or are an organizer: the people the organizer chooses a visit's recipients from. Removing someone from it removes them from every visit, while removing a recipient from one visit leaves them on the list. An organizer who removes themselves has withdrawn and stays off it after later sign-ins. Shown to users as 通知名單.
_Avoid_: Member list, family list, 家庭成員, 成員管理

**Pending invitee**:
Someone who signed in with LINE from an invitation but has not pressed 確認加入 yet. Not a recipient: nothing is sent to them and the organizer's list does not show them. A new invitation always works for them. They can confirm only while that sign-in lasts (four hours); after that they are erased.
_Avoid_: Pending recipient, inactive recipient

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
A job an organizer sets up and sends off: follow one clinic's progress on one day for one patient number, and tell the chosen recipients on LINE when to check in, when the number has been passed, and when the patient's turn comes close. It starts as a draft, runs once the organizer presses Start, and ends when the organizer stops it, the patient number leaves the hospital's list, the clinic ends, or its day is over. An ended visit is final: to follow the clinic again, the organizer sets up a new visit. A visit the hospital confirms cannot happen as set up is taken back by the system and returned as a draft for the organizer to correct. Its recipients are fixed at the first Start: the organizer can remove them, but no one can be added. When the organizer removes every recipient of a started visit, the system ends it, and the organizer sets up a new visit to tell anyone else. Shown to users as 叫號追蹤, counted with 筆; where the screen already makes clear that this is what is meant, as in 這筆追蹤, 停止追蹤, 追蹤中 or 修正已停止的追蹤, it may be shortened to 追蹤.
_Avoid_: Watch, reminder setting, appointment, 提醒, 看診提醒, 監聽工作, 監控, stopped or expired as a visit's state (a visit that has stopped running is ended; why is its end reason)

**End reason**:
Why a visit ended, one of: the organizer stopped it, the patient number left the hospital's list, the clinic ended, every recipient was removed, or its day is over. Each reason has its own sentence on the organizer's page, so the organizer can tell a normal end from a mistake. No end reason lets the visit be reopened. A visit sent back to draft because the hospital confirmed a mismatch has not ended and has no end reason; it carries a reason under needs attention instead.
_Avoid_: Stop reason, status, closing code

**Patient**:
The person who is seen at the clinic. A patient need not be an organizer or a recipient, and the product never stores who they are, only their patient number.
_Avoid_: User, member, 病患資料

**Patient number**:
The number a patient was given for one clinic on one day, which the clinic calls. Shown to users as 看診號碼.
_Avoid_: Ticket, queue number, 燈號 (alone)

**Current light**:
The number a clinic is showing as now being called. It is not the front of the queue: patients sent away for tests and patients who missed their call come back in between. In a clinic that sees patients in check-in order it is the patient number being seen, and says nothing about who comes next. A blank light means only that no number is shown now: before the first call, between calls, or after the clinic ended. Shown to users as 目前燈號.
_Avoid_: Called number, current number, progress

**Highest called**:
The highest patient number a clinic is known to have called. A hospital's page may show a number labelled 已叫最大號, but that number is only the highest called when the page itself proves it was called: it is being seen, or it is no longer listed. Otherwise there is no highest called, whatever the page labels it; at NTUH, outside 眼科 the labelled number is usually one of the called next numbers and may not have been called yet. The same rule holds for every hospital and department. Shown to users as 已叫最大號.
_Avoid_: Max number, current light

**Called in this session**:
Whether a clinic has called a number since its session started. A hospital's page can keep the numbers of an earlier session, so a current light on it alone does not say so. Before the session opens, the clinic's page already exists, with a blank light and its list of patient numbers.
_Avoid_: Started, open, active

**Clinic ended**:
The product's own judgment that a clinic has finished its session: after it has called in this session, the hospital's page has shown nothing new for an hour of readable pages. Hospitals never say so themselves, and a blank light alone does not mean it. Time when the page cannot be read does not count. Shown to users as 門診看起來已結束.
_Avoid_: Finished, closed, blank, 完診

**Clinic memory**:
What the reader has learnt from today's pages about one clinic, the same for every visit on that clinic: whether it has called in this session, its highest called so far, when its page last changed, its last known check-in position. Kept for the day only. Facts about one patient are reminder memory, never clinic memory. Not shown to users.
_Avoid_: Reader state, clinic timeline, entry

**Reminder memory**:
What the reminder rules remember about one visit's patient between reads, such as the patient's previous own status or whether the patient number was ever seen. It reads clinic memory's answers and never works them out again. Not shown to users.
_Avoid_: Visit state, alert state

**Check in**:
A patient telling the clinic they have arrived, by card or at the desk. Some clinics see patients in the order they checked in instead of by patient number. Shown to users as 報到.
_Avoid_: Arrive, register, 掛號

**Passed**:
A patient number whose call came while the patient had not checked in. The patient must check in at once to be seen. Shown to users as 過號.
_Avoid_: Skipped, missed, expired

**Called next**:
The few numbers a hospital lists as about to be called, when it says so (up to three at NTUH, where outside 眼科 the first is usually the current light itself). A number listed there is about to be called, whatever its place by number. Shown to users as 預計叫號.
_Avoid_: Next number, queue

**People ahead**:
The product's estimate of how many checked-in patients will be seen before the patient, made from what the hospital shows. Always an estimate, written as 約 N 人, never as minutes: patients who were passed or sent for tests can come back in front.
_Avoid_: Position, wait time, queue length

**Needs attention**:
A mark on a visit telling the organizers that the visit has a problem only an organizer can resolve, with the reason and what to do next. A visit can carry several reasons at once. Shown to users as 需要處理.
_Avoid_: Organizer attention, warning, alert

**Confirmed mismatch**:
A problem the hospital's own pages state outright: the clinic is not scheduled or is cancelled that day, or the doctor is unambiguously in another room or session. The system returns the visit to draft for the organizer to correct; the visit has not ended, and reminders not yet confirmed as sent are cancelled. Anything less than certain is an unconfirmed problem instead. Shown to users as 院方確認不符.
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
The system checking, once a day, that each visit that has not happened yet still matches what the hospital publishes, and on the visit day itself, before the clinic opens, that the visit's clinic is there. When the hospital's page cannot be read, it tries again a few times later the same day before leaving it to the next day. Covers drafts and running visits. Shown to users as 每日複查.
_Avoid_: Pre-flight sweep, preflight, sweep

### Sending

**LINE message**:
Any message the system sends someone on LINE: a reminder, an unavailable message, an organizer notice, or an alert to the captain. A send interruption stops all of them except the alert to the captain. Shown to users as LINE 通知.
_Avoid_: Push, alert, notification, 提醒

**Reminder**:
A LINE message telling one recipient, from what the hospital's page shows, where the patient stands in the clinic's queue and what to do now: check in, walk to the clinic, wait at its door, or ask at the desk. There are eight kinds, and each is sent to a recipient at most once per visit. When several kinds become due in one read, only the most urgent is sent; the others are skipped, which counts as sent, so they are never sent later. Shown to users as 進度通知.
_Avoid_: Alert, notification, near reminder, 提醒, 叫號通知

**Reminder cap**:
At most eight reminders and unavailable messages together, per recipient and visit. Skipped reminders, retries of the same message and organizer notices do not count. It is a safety limit: a visit's normal course stays below it. Not shown to users.
_Avoid_: Message limit, quota (LINE's monthly allowance is a different limit)

**Organizer notice**:
A LINE message telling every organizer about one needs-attention reason on one visit: a first notice when the reason is found, a final notice if it is still unresolved shortly before the visit, or a recovery notice when a site problem it reported has cleared. At most two per visit and reason, for the visit's whole life. It is not a reminder and does not count toward the reminder cap; a send interruption stops it. Not named to users.
_Avoid_: Push, re-notify, organizer alert, notice (alone)

**Live**:
A deployed environment that reads real hospitals and sends real LINE reminders. Each environment starts not live and is made live once, after its own pre-live gates pass, and is never made not live again; to stop sending, use a send interruption. Expired data is cleaned up either way. Shown to users as 已開通 and 未開通.
_Avoid_: Send hold, configuration hold, production hold, go-live

**Pre-live read**:
The one exception to "not live reads no hospital": the captain starts a single, time-boxed read of one real hospital page, either one progress page or one clinic schedule page, to measure the environment's cost before it is made live. It belongs to no visit, sends no message, keeps nothing for organizers, and must be started again to repeat.
_Avoid_: Test read, probe, dry run

**Send record**:
What the system keeps about each running visit and each message it has sent or is sending, and relies on to decide what to send next. Only the system's own steps change it. Shown to users as 發送紀錄.
_Avoid_: Ledger, 帳本

**Send interruption**:
A stop on all sending in one environment. The system enters it when its send record was changed by something outside its own control, such as a restore or a migration, or when it could not write down the result of a send; the captain can also set it by hand before a restore or rollback. Only the captain ends it, by resuming sending after checking. Visits keep their state through it: it pauses them, it does not stop them. A LINE request whose outcome is merely unknown is retried, not interrupted. Shown to users as LINE 通知暫停發送.
_Avoid_: Recovery hold, reconciliation hold, safety stop, brake

**Resume sending**:
The captain ending a send interruption once they have checked what happened. Running visits that are still valid carry on; it never brings back an ended visit. Shown to users as 恢復發送 LINE 通知.
_Avoid_: Release, unhold, end interruption

**Reading stop**:
A stop on reading one hospital in one environment, because the hospital refused to be read or sent the reading elsewhere. A refusal holds until the captain clears it, after checking; a redirect holds until the day ends. It is not a send interruption: sending goes on for other hospitals, and clearing one never ends the other. Shown to users as <醫院>暫停讀取, cleared with 恢復讀取<醫院>.
_Avoid_: Source stop, hospital block, refusal (alone)

**Paused service**:
A send interruption or a reading stop, as the organizer page lists them together. Shown to users as 暫停中的服務.
_Avoid_: Notice, outage

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
