# NIY-006: Scheduler, outbox, and send coordination

Status: Complete

## Goal

Implement scheduled evaluation, durable event creation, retry-key reuse, and strict coordination among sends, Stop, recipient removal, withdrawal, and cutoff.

## Approved decisions and testable semantics

- Use one system-wide SQLite-backed Durable Object as the serialized gate for scheduled evaluation, LINE request starts, Stop, visit-recipient removal, recipient withdrawal, and recovery hold/resume. Do not shard by visit. The gate is the only path that may start a LINE request or confirm a close action.
- A close action takes effect in gate order. Once Stop, withdrawal, removal, cutoff, or a recovery hold is applied, no later LINE request for the closed visit or recipient can begin. A LINE request that began first may finish afterward. Stop or withdrawal is not confirmed until each already-started request has settled or is durably classified `unknown`, and no previous sender can start another request.
- Persist each recipient-specific `near` or `unavailable` event in D1 before its first request. A logical visit is the stable visit ID across corrections. Uniqueness is `(logical visit, recipient, event kind)`, so duplicate Cron ticks and corrected watches do not reset the one-alert cap. Creating a new attempt requires an explicit review and a new logical visit ID.
- Keep the same UUID retry key and the exact same recipient and message body for every retry of an uncertain event. LINE's documented retry-key window is 24 hours from the first request ([LINE retry guidance](https://developers.line.biz/en/docs/messaging-api/retrying-api-request/)). Retry only inside that window. After it expires, preserve the event as `unknown`, do not mint another key, and do not report delivery. An HTTP 2xx or retry-key 409 means API accepted, not handset delivery.
- Compare the injected current time with 23:59:00 Asia/Taipei on the visit day. A request may start before that instant; at or after it, the visit is closed to new requests. Draft deletion is due exactly 48 hours after that visit-day cutoff. Delete withdrawn recipient identity and associated visit/event rows after all of that recipient's in-flight requests settle or become unknown.
- A D1 restore uses a recovery hold stored in the Durable Object, outside D1. An authorized organizer must set the hold before starting a planned restore. The gate also compares a durable checkpoint of scheduler-relevant D1 state before each tick and send; a mismatch sets the hold before another request can begin. The hold persists across D1 restore and Worker restart. After the restore, sending stays disabled until a human has reconciled the restored D1 rows against notification history and explicitly resumes through the CSRF-protected organizer endpoint, which records the reconciled checkpoint.
- The Durable Object uses the SQLite backend supported on Workers Free. Cloudflare currently documents Free limits of 100,000 Durable Object requests and 13,000 GB-s per day; exceeding a Free limit causes further operations of that type to fail ([Cloudflare Durable Objects pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/)). This establishes plan compatibility, not production load headroom. A local test cannot prove deployed Cloudflare ordering, quota headroom, D1 restore operations, or LINE behavior.

## Acceptance criteria

- Local Python Worker + FastAPI + D1 + Durable Object + Cron composition tests use local bindings, synthetic D1 records, an injected clock, and fake hospital/LINE transports only.
- Duplicate scheduled ticks and corrected watches cannot create a second `near` or `unavailable` event for the same recipient and logical visit; a new logical visit ID is required for a reviewed new attempt.
- The outbox event exists before a fake LINE request begins. Restarting the invocation reuses the persisted retry key and exact payload for an uncertain event inside the 24-hour window. At and after expiry, an uncertain event remains unknown and no request is started.
- Race tests cover Stop, recipient withdrawal/removal, and send start in both orderings. If send start wins, the close waits for settlement or durable unknown classification. If close wins, the LINE transport is not called. Once close is confirmed, a later tick cannot start a request.
- Injected Taipei times immediately before, exactly at, and immediately after 23:59 verify the request-start boundary, including clock advancement during pre-request persistence. Draft expiry is verified at the 48-hour boundary.
- A restore-shaped test sets the DO recovery hold, restores D1 from an earlier snapshot, proves Cron and sends remain held across a Worker/DO restart, then reconciles the records and proves only explicit authenticated resume re-enables sends.
- `.env_template` is the only tracked environment template. It documents the NIY-006 keys `LINE_CHANNEL_ACCESS_TOKEN` and `NIY006_LOCAL_TEST_MODE` with blank placeholders and tells developers to copy it to local `.env` before filling values. Production supplies the LINE token as a Worker secret; the local test Wrangler config supplies the test-mode flag, and `SEND_GATE` is a Wrangler Durable Object binding. `.env` and `.env.*` remain ignored, `.env.example` is not trackable, and no real credentials are committed.
- Run the full Python suite, frontend build, local Worker/DO/Cron smoke and race tests, and `git diff --check`. Mark this ticket complete only when all pass. Production Cloudflare integration, quota/load headroom, D1 restore procedure, the NIY-004 hospital transport/freshness integration, and real LINE behavior remain unproven and must stay identified as such.

## Local validation

- `python -m pytest -q`: 96 passed.
- `npm run build`: passed.
- Local `pywrangler dev` used `wrangler.niy006.test.jsonc`, local D1, a SQLite Durable Object, synthetic records, injected times, and fake hospital/LINE transports. Worker, FastAPI, D1, DO, and Cron smoke passed. Duplicate tick and correction caps, Stop and withdrawal races, the Taipei cutoff, and a recovery hold surviving a local Worker restart were exercised.
- Unit-level gate tests cover uncertain retry-key reuse and expiry, invocation restart, draft expiry, D1 restore reconciliation, and authenticated explicit resume.
- The existing NIY-004 hospital modules are parsers without a verified live transport or freshness provider. Production has no hospital reader wired here and requires a separately configured LINE access token before any outbound request can run.
- `.env_template` contains blank placeholders only. `.env` and `.env.*` are ignored, and no local `.env` or real credential was used.
- Git ignore checks confirmed `.env` and `.env.example` are ignored and `.env_template` is the only tracked environment template.
- `git diff --check`: passed. No remote bindings or external hospital/LINE requests were used.

## Dependencies

NIY-003, NIY-004, and NIY-005.
