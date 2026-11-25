# Pre-live checklist

An environment is made **live** once, after its own gates below pass, and is
never made not live again (`GLOSSARY.md`). Staging goes live first. Production
goes live only after every Staging gate has passed. Decided in the #129
grilling (2026-11-19/20).

## How an environment is made live

Each environment's live state is `vars.NIY_LIVE` in its own committed config,
`wrangler.staging.jsonc` or `wrangler.production.jsonc` (#237). It is `"false"`
until that environment's gates below pass. No dashboard variable or secret
decides it, and every deploy writes the committed value.

1. Open a pull request that sets `"NIY_LIVE": "true"` in that environment's
   config and adds `"LINE_BOT_BASIC_ID"`, the bot basic ID of the environment's
   own Official Account (LINE Developers console, Messaging API tab, for example
   `@123abcde`). A test refuses a live config without it.
2. The captain merges it. Staging deploys it on its own. Production gets it when
   the captain promotes the first version that carries it.
3. On the status endpoint (`/api/organizer/scheduler/status`), `live` is `true`
   and `line_unavailable_reason` is `null`. While it names a reason, nothing is
   read or sent: `line_token_missing` (no `LINE_CHANNEL_ACCESS_TOKEN` secret),
   `line_token_other_account` (the token belongs to another Official Account,
   such as the other environment's), `line_account_not_committed` (no
   `LINE_BOT_BASIC_ID`) or `line_account_unverified` (LINE did not say which
   account the token belongs to; asked again on the next tick).

**It cannot be undone.** Once live, the environment reads the hospital and sends
LINE messages together. To stop sending, use a send interruption. The promote
guard and the Staging deploy refuse any version older than the environment's
first live one (`scripts/delivery_state.py live-check`), so a rollback cannot
make it not live again. Rolling back past that point is not possible through
Promote or CI. Two paths outside them are not guarded and must not be used for
this: Cloudflare's native rollback ([CI-CD.md](CI-CD.md#rollback)), and editing
`NIY_LIVE` in the Cloudflare dashboard, which lasts until the next deploy writes
the committed value back.

Use [HTTPS-SERVICE.md](HTTPS-SERVICE.md) for provisioning and the interruption
procedures, and [CI-CD.md](CI-CD.md) for deployment and rollback. This checklist
owns the gates for making an environment live. Tick a gate only with a pointer
to its evidence and its label (fixture/mock, local integration, deployed, live
provider).

## Before Staging goes live

Staging is used by the captain alone. No family member is invited to it.

- [x] #134: an invitee who does not confirm within a minute is no longer deleted.
  Evidence: PR #161; live provider on Staging, 2026-11-22 (#134).
- [x] #135: a visit started before its day sends on the visit day. Evidence: PR
  #158, fixture/mock; migration 0008 rehearsed on Staging, deployed, 2026-11-21
  (#135). Its organizer-page criterion moved to #154.
- [ ] #136: the new reminder rules, with the clinic and patient number in every
  message. Its first step, the CPU measurements, is done (#162, #170).
- [ ] The held tick's CPU on Staging, measured again after #163 is deployed (it adds
  a cleanup of reader state to every tick): every Durable Object invocation stays
  at or below 10 ms under `wrangler tail`. Last measured 5 to 9 ms. Evidence label
  deployed.
- [ ] #179: a refusal stops the whole hospital, and Start and the picker follow it.
- [x] #181: scheduled reads begin one hour before the session's published start.
  Evidence: PR #194, fixture/mock (#181).
- [ ] #188: a clinic schedule read stays within the Free plan's 10 ms and the reader's
  size limit, for the picker, Start and the daily recheck.
- [ ] #192: an open organizer page stays within the Free plan's daily limits
  around the clock, for Staging and Production together.
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
- [ ] #139: the agreed words on screen. Here because #160, and through it #142,
  builds on its texts.
- [ ] #142: the live switch, captain-only interrupt and resume (the banner's
  恢復發送 LINE 通知 button), the interruption alert and the last tick time.
- [x] Hospital access rules are written in
  [ADDING-A-HOSPITAL.md](ADDING-A-HOSPITAL.md#source-access-rules). The
  hospital is not contacted. Evidence: that section, as amended by #181
  (2026-11-23); what the rules require of the reader is built by #179.
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
  earlier pipeline run, which also puts that version on Staging. A run from
  before Staging went live is refused instead.

## Before Production goes live

- [ ] Every Staging gate above has passed.
- [ ] #22, the live pilot on Staging, evidence label live provider:
  - Claude Code on the captain's Mac drives the captain's own account through at
    least 3 visits on real NTUH clinics, morning and afternoon, with a patient
    number chosen ahead of the highest called. Only one visit runs at a time
    (#172), so the 3 visits go one after another: stop each before starting the
    next, and record CPU and request headroom for each run.
  - At least one visit uses a real appointment (the captain's, or a consenting
    relative's with the captain as the only recipient), so the "about 8" and
    "about 5 people ahead" reminders are seen. The captain chose an
    ophthalmology appointment with a different doctor (#180, 2026-11-23).
  - At the real appointment, the page's current light is compared with the room's
    light at least once, with the result recorded and no number kept.
  - If a detail link stops working, what it answered (status, and for a redirect
    whether it stays on the same host and path) is recorded before its rule changes.
  - If the real appointment does not show both reminders, #22 is verified again
    on an appointment in 內科 `MED` or 骨科 `ORTH` (#180), because ophthalmology
    can call too far out of number order to show them. A 內科 fallback cannot be
    read until #188 lands: its clinic schedule page (7.68 million characters on
    2026-11-25) is over the reader's cap and reads as unavailable. 骨科 fits. In
    both, 已叫最大號 is the last of 預計叫號 rather than the last number called
    (`docs/NTUH-READER.md`), so "ahead of the highest called" means something
    else there.
  - Edge cases (passed, check-in order, unavailable source, number gone from the
    list) are covered by fixtures.
- [ ] #131: the security baseline, grilled after #22 passes and finished before
  Production goes live, because release day invites family members.
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
