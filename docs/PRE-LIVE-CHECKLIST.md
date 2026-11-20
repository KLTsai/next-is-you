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
  message. Its first step measures Staging's scheduler CPU and the parse time of
  a captured NTUH detail page against the Free plan's 10 ms per invocation.
- [ ] #137: at most 5 retries of an unknown LINE outcome, and the monthly-limit
  `429` handled.
- [ ] #138: a visit ends when its clinic ends.
- [ ] #130: the real reason a Start or daily recheck fails, and the invalid-visit
  rule the resume page lists.
- [ ] #142: the live switch, captain-only interrupt and resume, the resume page,
  the interruption alert and the last tick time.
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
- [ ] Only NTUH Main (`ntuh-main`) is offered.

## While Staging is live

- On days when visits are watched for evidence, pause automatic deployment
  (`STAGING_DEPLOY_PAUSED`, [CI-CD.md](CI-CD.md)), so no merge restarts the
  Worker mid-visit.
- The staging deploy records a D1 restore point before it applies migrations.
- Before each run, the captain checks the month's remaining messages in LINE
  Official Account Manager. The free plan allows 200 a month per official
  account.
- Every merge to `main` reaches a live Staging. A production rollback re-runs an
  earlier pipeline run, which also puts that version on Staging.

## Before Production goes live

- [ ] Every Staging gate above has passed.
- [ ] #22, the live pilot on Staging, evidence label live provider:
  - Claude Code on the captain's Mac drives the captain's own account through at
    least 3 visits on real NTUH clinics, morning and afternoon, with a patient
    number chosen ahead of the highest called. One run watches 3 visits at once
    and records CPU and request headroom.
  - At least one visit uses a real appointment (the captain's, or a consenting
    relative's), so the "about 8" and "about 3 people ahead" reminders are seen.
  - Edge cases (passed, check-in order, unavailable source, number gone from the
    list) are covered by fixtures.
- [ ] #131: the security baseline before the first family member is invited.
- [ ] #139: the agreed words on screen.
- [ ] Production's LINE setup: its Official Account and Messaging API channel
  under the same provider as its Login channel, the Login channel Published, and
  Staging's callback removed from it.
- [ ] Production configuration: secrets, captain LINE ID, organizer allowlist,
  HTTPS callback, and local test mode off, checked without exposing values in
  logs or repository files ([SECRETS.md](SECRETS.md)).
- [ ] A one-page guide for the family in Traditional Chinese: add the official
  account as a friend, accept the invitation, and what reminders look like.

## Release day for Production

1. Record a restore point if the version applies migrations (#111).
2. Promote.
3. The captain checks production's send interruption (in place since
   2026-10-27) on the resume page and resumes sending.
4. The captain sets up the first visit with themself as a recipient and
   confirms it reaches the handset.
5. The captain invites family members as recipients. The captain stays the only
   organizer; family members become organizers only after #140.

## Known limitations

- Nothing alerts anyone when the Worker itself stops running. The status page
  shows the last scheduler run time, but a family member who notices missing
  reminders has usually already missed the call.
- There is no backup outside Cloudflare. D1 Time Travel (7 days) is the only
  restore path, and it does not roll back the send gate Durable Object, so any
  restore is followed by a send interruption.
