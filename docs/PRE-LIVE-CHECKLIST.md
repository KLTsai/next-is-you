# Pre-live checklist

An environment is made **live** once, after its own gates below pass, and is
never made not live again (`GLOSSARY.md`). Staging goes live first. Production
goes live only after every Staging gate has passed. Decided in the #129
grilling (2026-11-19/20).

Use [HTTPS-SERVICE.md](HTTPS-SERVICE.md) for provisioning and the interruption
procedures, and [CI-CD.md](CI-CD.md) for deployment and rollback. This checklist
owns the gates for making an environment live. Tick a gate only with a pointer
to its evidence and its label (fixture/mock, local integration, deployed, live
provider).

## Before Staging goes live

Staging is used by the captain alone. No family member is invited to it.

- [ ] #134: an invitee who does not confirm within a minute is no longer deleted.
- [ ] #135: a visit started before its day sends on the visit day.
- [ ] #136: the new reminder rules, with the clinic and patient number in every
  message. Its first step, the CPU measurements, is done (#162, #170).
- [ ] The held tick's CPU on Staging, measured again after #163 is deployed (it adds
  a cleanup of reader state to every tick): every Durable Object invocation stays
  at or below 10 ms under `wrangler tail`. Last measured 5 to 9 ms. Evidence label
  deployed.
- [ ] #179: a refusal stops the whole hospital, and Start and the picker follow it.
- [ ] #181: scheduled reads begin one hour before the session's published start.
- [ ] #188: a clinic schedule read stays within the Free plan's 10 ms and the reader's
  size limit, for the picker, Start and the daily recheck.
- [ ] #163's CPU condition ([HTTPS-SERVICE.md](HTTPS-SERVICE.md), #170 verdict),
  evidence label live provider: before Staging's reading is turned on for use, one
  synthetic visit reads a real NTUH detail page under `wrangler tail`, and every
  Durable Object invocation stays at or below 10 ms, including the one that finds
  the card on the list and the 30-minute list check. If one does not, stop and
  bring the choice to the captain. Staging reads no hospital until it is live, so
  the captain allows this one read before Staging is live: run by the captain,
  time-boxed, one page, no LINE message (2026-11-22, #142).
- [ ] #137: at most 5 retries of an unknown LINE outcome, and the monthly-limit
  `429` handled.
- [ ] #138: a visit ends when its clinic ends.
- [ ] #130: the real reason a Start or daily recheck fails (built through #144
  and its slices).
- [ ] #142: the live switch, captain-only interrupt and resume (the banner's
  恢復發送 LINE 通知 button), the interruption alert and the last tick time.
- [ ] Hospital access rules are written in
  [ADDING-A-HOSPITAL.md](ADDING-A-HOSPITAL.md#source-access-rules). The
  hospital is not contacted.
- [ ] Staging has its own LINE provider, Official Account, Login channel (in
  Developing mode, with the captain as a tester) and Messaging API channel
  ([ADR 0004](adr/0004-staging-has-its-own-line-provider.md)). Its organizer
  allowlist and captain LINE ID are set for that provider.
- [ ] **Restore rehearsal on Staging**, evidence label deployed. It starts from a
  send gate that already holds state and a manual interruption, as production's
  has since 2026-10-27:
  1. an interruption alert reaches the captain;
  2. the captain resumes sending;
  3. a restore point is recorded;
  4. a synthetic visit is created;
  5. D1 is restored with Time Travel;
  6. sending is interrupted automatically, a second alert arrives, and the
     captain resumes again;
  7. a visit is stopped and its deletion 48 hours later is confirmed.
- [ ] **Organizer page walkthrough on Staging**, evidence label live provider.
  By hand on desktop Chrome, iPhone Safari and Android Chrome: real devices, not
  emulation, which cannot reproduce Safari scrolling or the on-screen keyboard
  resizing the page. Stop a visit while a send is in flight, so the page repaints
  every second while the visit is stopping. A send can settle within seconds:
  repeat until every step was done while a visit was stopping. On each device:
  1. type in the member label and in every visit form field, with the on-screen
     keyboard open on the phones: no character or cursor position is lost, and a
     date typed to the end comes out whole;
  2. scroll slowly, by wheel on desktop and by touch on the phones, with each
     field focused: the page is never pulled back;
  3. scroll until the focused field is off screen and wait 3 seconds: the page
     does not move;
  4. open the date calendar and a dropdown, and wait 5 seconds: each stays open;
  5. on a phone, type Chinese with the input method in use (bopomofo): another
     candidate can still be picked after 5 seconds.

  Record for each: browser and version, device and OS version, date.
- [ ] Only NTUH Main (`ntuh-main`) is offered.

## While Staging is live

- On days when visits are watched for evidence, pause automatic deployment
  (`STAGING_DEPLOY_PAUSED`, [CI-CD.md](CI-CD.md)), so no merge restarts the
  Worker mid-visit.
- The staging deploy records a D1 restore point before it applies migrations.
- Before each run, the captain checks the month's remaining messages in LINE
  Official Account Manager. The free plan allows 200 a month per official
  account.
- After each run, the one who ran it reads the Worker's log for
  `ntuh_unobserved_situation` the same day, and writes what was seen on #136 with no
  clinic, doctor or number. Nothing else tells anyone.
- Every merge to `main` reaches a live Staging. A production rollback re-runs an
  earlier pipeline run, which also puts that version on Staging.

## Before Production goes live

- [ ] Every Staging gate above has passed.
- [ ] #22, the live pilot on Staging, evidence label live provider:
  - Claude Code on the captain's Mac drives the captain's own account through at
    least 3 visits on real NTUH clinics, morning and afternoon, with a patient
    number chosen ahead of the highest called. Only one visit runs at a time
    (#172), so the 3 visits go one after another: stop each before starting the
    next, and record CPU and request headroom for each run.
  - At least one visit uses a real appointment (the captain's, or a consenting
    relative's with the captain as the only recipient), so the "about 8" and "about 5 people ahead" reminders are seen.
  - At the real appointment, the page's current light is compared with the room's
    light at least once, with the result recorded and no number kept.
  - If a detail link stops working, what it answered (status, and for a redirect
    whether it stays on the same host and path) is recorded before its rule changes.
  - At least one visit is in a department whose calls follow number order
    (#180), because ophthalmology calls too far out of order to show every reminder.
  - Edge cases (passed, check-in order, unavailable source, number gone from the
    list) are covered by fixtures.
- [ ] #131: the security baseline, grilled after #22 passes and finished before
  Production goes live, because release day invites family members.
- [ ] #139: the agreed words on screen.
- [ ] Production's LINE setup: its Official Account and Messaging API channel
  under the same provider as its Login channel, the Login channel Published, and
  Staging's callback removed from it.
- [ ] Production configuration: secrets, captain LINE ID, organizer allowlist,
  HTTPS callback, and local test mode off, checked without exposing values in
  logs or repository files ([SECRETS.md](SECRETS.md)).
- [ ] **Organizer page walkthrough on Production**, evidence label live provider:
  the Staging walkthrough repeated with the Production setup and a real LINE
  sign-in. Record the same: browser and version, device and OS version, date.
- [ ] A one-page guide for the family in Traditional Chinese: add the official
  account as a friend, accept the invitation, and what reminders look like.

## Release day for Production

1. Record a restore point if the version applies migrations (#111).
2. Promote.
3. The captain checks production's send interruption (in place since
   2026-10-27) on the organizer page banner and resumes sending with
   恢復發送 LINE 通知.
4. The captain sets up the first visit with themself as a recipient and
   confirms it reaches the handset.
5. The captain invites family members as recipients. The captain stays the only
   organizer; family members become organizers only after #140.

## Known limitations

- Nothing alerts anyone when the Worker itself stops running. The status page
  shows the last scheduler run time, but a family member who notices missing
  reminders has usually already missed the call.
- A doctor change after the clinic has called is not noticed (`docs/NTUH-READER.md`).
- If the reader's state is lost while a clinic is calling, the clinic reads as not
  started until the page moves or its card shows a number.
- Until #183, an evening visit gets no progress reminder. NTUH Main's clinic
  schedule shows no evening clinic (#180), so it does not hold back Staging
  (captain, 2026-11-22).
- There is no backup outside Cloudflare. D1 Time Travel (7 days) is the only
  restore path, and it does not roll back the send gate Durable Object, so any
  restore is followed by a send interruption.
- The browser tests (`tests/test_organizer_page.py`, `tests/test_background_repaint.py`)
  run in Chromium and cannot show how a real phone behaves. The page waits for an
  open calendar or dropdown only where the browser reports it open (`:open`), and
  an input method is simulated, not real: both are checked by hand in the
  walkthrough above.
