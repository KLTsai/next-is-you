# Held HTTPS service preparation (Issue #18)

## Scope and authorization

[Issue #18](https://github.com/KLTsai/next-is-you/issues/18) owns this work.
Repository preparation covers an isolated native Wrangler production template,
fail-closed authentication and synthetic controls, a production send hold, and
local executable regression evidence. Observable checks are same-origin assets
and API, rejected synthetic requests, restricted organizer access, a production
hospital-reader hold that cannot Start, and a recovery hold that survives a
local Worker restart. The [NTUH reader guide](NTUH-READER.md) owns reader scope
and rehearsal behavior. Existing retry identity, deduplication, Stop ordering,
consent, cutoff, and recovery tests remain the behavior seams.

Dependencies are the owner's Cloudflare Free account/resource authorization,
agreed fixed HTTPS origin and privacy interpretation, private LINE configuration
and organizer subject, then separately authorized deployment/manual acceptance.
The held bootstrap was deployed as recorded in the owner evidence below; see
the [README status](../README.md#status) for the current user-facing state.
Deployment does not authorize live reads or reminder sends, and publication of
repository changes does not authorize a new deployment.

Non-goals: enabling sends, enabling the hospital reader in production before
the Issue #22 pilot, LINE or handset acceptance, paid resources, domain purchase,
another service/database, a storage rewrite, or a deployment automation layer.
The [NTUH reader guide](NTUH-READER.md) owns reader scope and behavior. Full
review, validation, documentation, lint, push, PR and CI are handed to
no-mistakes after the implementation commit.

## Free plan and origin decision

Zero added spend is required. As checked against official documentation on
2026-10-03, the required resource types exist on Workers Free:

| Resource | Free limits relevant to this bootstrap |
| --- | --- |
| Worker | 100,000 requests/day; 10 ms CPU per HTTP request and Cron invocation; 128 MB memory; 64 MiB bundle; five Cron triggers per account |
| D1 | 5 million rows read/day; 100,000 rows written/day; 5 GB account storage; 500 MB per database |
| SQLite DO | 100,000 requests/day; 13,000 GB-s duration/day; 5 million rows read/day; 100,000 rows written/day; 5 GB account storage |

Sources: [Workers limits](https://developers.cloudflare.com/workers/platform/limits/),
[D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/),
[D1 limits](https://developers.cloudflare.com/d1/platform/limits/), and
[DO pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/).
D1 and DO operations fail when their Free quotas are exhausted; these are
availability limits, not permission to upgrade. Account quotas include other
applications. One minute Cron means 1,440 invocations/day, each using the same
named gate. The production hold returns before scheduler preparation, hospital
access or LINE sends; it also defers scheduler cleanup. Do not store patient data
in this bootstrap. Full live workload/retention measurement belongs to ticket 08.

The Free plan is a candidate for this held bootstrap, not proven sufficient for
this Python/FastAPI app's deployed CPU, startup, memory, or workload. Check those
metrics after authorized deployment; a quota/startup failure is a stop condition,
not an invitation to enable Paid. The local dry run proves compilation only.
The 2026-10-03 native dry run with pywrangler 1.17.4 / Wrangler 4.147.0 reported
9,329.18 KiB total upload (2,305.70 KiB gzip), 1,018 modules and four asset files.
No deployed CPU, startup latency, memory, quota usage or provider measurements
are available. Local wall-clock test timing is not a Free-plan CPU measurement.

Candidate origin: `https://<approved-worker-name>.<owner-subdomain>.workers.dev`.
[Cloudflare documents](https://developers.cloudflare.com/workers/configuration/routing/workers-dev/)
that this origin is public, suitable for personal/hobby use, and recommends custom
domains for business-critical production. The static shell and health endpoint
are public; organizer data and mutations require an allowlisted LINE session and
mutations require CSRF. Recipient enrollment additionally requires an invitation,
friendship verification and consent. The owner must explicitly agree whether
this application-level privacy meets “private HTTPS.” No domain purchase or
additional Access service is assumed. If network-level privacy is required,
stop for a separate origin/access decision and callback rehearsal.

The current Login flow uses a browser redirect, not a provider-to-server webhook.
A publicly reachable HTTPS `workers.dev` callback has no inherent conflict with
that flow (inference from the existing code and the
[LINE web Login documentation](https://developers.line.biz/en/docs/line-login/integrate-line-login/)).
Actual LINE registration and round-trip success remain provider gates. The exact
callback, once the origin is approved, is:

`https://<approved-worker-name>.<owner-subdomain>.workers.dev/auth/line/callback`

Register that exact URL in LINE Developers Console > the correct LINE Login
channel > LINE Login > Callback URL. Enable the channel's Web app type. Use the
same URL in `LINE_LOGIN_REDIRECT_URI`, with no query, fragment or trailing slash.
The Worker rejects invalid callbacks and callbacks for a different request origin.
Keep the Worker name and account subdomain fixed; renaming either changes the URL.

## Local proof before any remote action

Install the locked dependencies using the [README developer guidance](../README.md#for-developers).
These commands change only local build/test state:

```sh
npm run build
npm run typecheck
uv run pytest -q tests/test_held_service.py tests/test_held_service_runtime.py tests/test_worker_startup.py
uv run python -m pywrangler deploy --dry-run --config wrangler.production.example.jsonc --outdir .wrangler/held-dry-run
```

`wrangler.production.example.jsonc` is a template, not an approved deployment
target. It has a placeholder D1 ID, production mode, synthetic mode disabled,
`workers_dev: false` and `preview_urls: false`. It keeps dashboard variables on
subsequent deployments. The existing SQLite class export provisions the native
DO class on deployment; do not add a legacy DO migration alongside `exports`.
The singleton name remains `next-is-you-system`.

Synthetic login, test controls and fake providers require both
`NIY_ENVIRONMENT=local-test` and `NIY006_LOCAL_TEST_MODE=1`, as configured in
`wrangler.niy006.test.jsonc`. Every other mode keeps sends held and the hospital
reader unavailable; a test flag alone cannot enable the rehearsal.

The runtime regression uses this production template with fixture credentials,
self-signed loopback HTTPS, real local D1/SQLite DO bindings, and current built
assets. It creates an invitation through the authorized API, sets recovery hold,
restarts the Worker with the same local state, reads the persisted DO hold, and
queries the original D1 invitation count. Fixture identity bypasses LINE solely
inside the test; production has no synthetic session route. Browser assertions
check the real login shell, same-origin assets and hidden synthetic login button.
The separate startup regression rejects synthetic controls even when the test
flag is mistakenly set with a production environment.

Fixture/mock tests additionally prove missing/invalid settings fail closed,
allowlist enforcement, production reader unavailability, refusal to resume
production, and no outbound event creation for an already active restored
fixture.
Existing scheduler tests cover retry keys, deduplication, Stop ordering,
withdrawal, cutoff and recovery reconciliation. This is genuine local integration
with fixture identity plus fixture/mock evidence. It is not deployed integration,
LINE provider acceptance or handset evidence.

## Owner setup (recorded completed 2026-10-27/28)

These steps were completed with the owner's explicit authorization of the selected
account, new D1 database and Worker/DO resources, the fixed origin/privacy meaning,
Workers Free with no plan purchase, and the organizer subject supplied privately.
The subject belongs to the LINE provider used by this Login channel; a display
name is not an identifier. The allowlist was not broadened to discover the
identity. No private account data was inspected during preparation or this
verification pass.

Deployment history confirms an initial 2026-10-23 deploy, three "Secret Change"
events on 2026-10-27 matching the three required secrets, and that the version
reported as live during the 2026-10-27/28 verification was from 2026-10-27.
`wrangler secret list` confirmed
`LINE_LOGIN_CHANNEL_SECRET`, `ORGANIZER_LINE_SUBJECTS`, and `SESSION_SIGNING_SECRET`
are all provisioned (names only; values were never read). Steps 1-5 below are
confirmed done on this evidence.

1. Locally copy the template to the ignored repository-root
   `.wrangler.production.jsonc`. Set `name` to the approved unique Worker name,
   and `account_id` to the authorized account ID. Keep public routes disabled
   for initial setup. Never deploy either local/rehearsal config remotely.
   Use this explicit production config on every command; no named environment
   inherits test bindings. Local state and the new remote database are separate.
2. The owner authenticated with native Wrangler and created only the approved D1
   database. Commands below are **completed; remote state changes already applied**:

   ```sh
   uv run python -m pywrangler login
   uv run python -m pywrangler d1 create next-is-you-production --config .wrangler.production.jsonc
   ```

   The returned resource ID was kept private and the template's zero UUID
   replaced with it in the ignored config. If the owner chose another database
   name, use that exact name both in the config and every command below. Stop if
   Wrangler selects another account or requests a plan upgrade. Do not accept
   resource auto-creation beyond the approved Worker, D1 and SQLite DO.
3. The config was built and dry-run first. Migrations were then applied to the
   one approved remote database and the service deployed with origin still
   disabled. Commands below are **completed; remote state changes already applied**:

   ```sh
   uv run python -m pywrangler d1 migrations apply next-is-you-production --remote --config .wrangler.production.jsonc
   uv run python -m pywrangler deploy --config .wrangler.production.jsonc --keep-vars
   ```

   Deployment provisions `ASSETS`, `SEND_GATE`/`SystemSendGate` with SQLite
   storage, and the existing one-minute scheduled handler on this one Worker.
   No second service is needed. Missing auth settings deny login and protected
   APIs; every non-local-test runtime is held by code even if a push token exists.
4. `LINE_LOGIN_CHANNEL_ID` and the exact approved `LINE_LOGIN_REDIRECT_URI` were
   provisioned using this Worker's dashboard variables. The following were
   provisioned using native masked interactive prompts or the dashboard's secret
   controls. Commands are **completed; remote secret/version changes already applied**:

   ```sh
   uv run python -m pywrangler secret put LINE_LOGIN_CHANNEL_SECRET --config .wrangler.production.jsonc
   uv run python -m pywrangler secret put SESSION_SIGNING_SECRET --config .wrangler.production.jsonc
   uv run python -m pywrangler secret put ORGANIZER_LINE_SUBJECTS --config .wrangler.production.jsonc
   ```

   An independently generated session signing secret of at least 32 UTF-8 bytes
   was used. Values were pasted only into private masked controls, never shell
   arguments, tracked files, logs, reports or chat. `LINE_CHANNEL_ACCESS_TOKEN`
   was not provisioned for this bootstrap. Root `.env` and local `.dev.vars` are
   not production provisioning sources. `NIY_ENVIRONMENT=production` and
   `NIY006_LOCAL_TEST_MODE=0` are kept; neither is a secret.
5. The owner registered the exact callback above in LINE Console (**completed**),
   with an appropriate channel status/tester permission for their account. After
   the agreed public-origin choice, `workers_dev: true` was set in the ignored
   config and deployed again (**completed**). `preview_urls: false` is kept.
   The exact URL Wrangler returned, account/plan, resource IDs, deployed
   commit/version, migration versions and time were recorded privately.

## Manual deployed acceptance (completed 2026-10-27/28, to the extent noted per step)

Daily use needs only a browser after owner setup. Open the exact stable URL.
This pass was run directly against the live deployed origin on 2026-10-27/28,
to the extent noted per step below:

1. **Confirmed on 2026-10-27/28.** Current UI and JS/CSS load over HTTPS from
   this same origin. `/api/healthz` returns `{"status":"ok","mode":"held-service"}`.
   Logged-out organizer APIs return `401` when auth is configured; missing/invalid
   config returns `503`. Synthetic controls such as POST
   `/__niy006_test/organizer-session`, `/seed` and `/snapshot` return `404`,
   even if a stray test flag exists. The synthetic login button's absence was
   not independently re-checked in this pass; it remains presumed true by the
   same code gate that previously verified it, but was not freshly confirmed.
2. **Confirmed on 2026-10-27: the owner completed a real LINE login and reached
   organizer access.** The exact callback returned to this origin, and only
   the approved subject gained organizer access. The two edge-case checks - an
   unauthorized second test account outside the allowlist getting `403`, and a
   callback with missing state/code returning `401` - were not exercised in
   this pass and remain unverified. Do not add an unauthorized account to the
   allowlist. Do not capture callback codes, cookies, provider tokens or
   patient information in evidence.
3. **Confirmed on 2026-10-27:** the owner set recovery hold through the
   authorized status API and the status endpoint reported the values below;
   this was not freshly re-checked after that date. In the signed-in browser
   console, inspect the existing authorized status API and establish recovery
   hold. These application actions use the current session's CSRF cookie
   without displaying it; re-run to re-verify:

   ```js
   const csrf = decodeURIComponent(document.cookie.split('; ').find(v => v.startsWith('__Host-ny_csrf='))?.split('=').slice(1).join('=') ?? '');
   const hold = await fetch('/api/organizer/scheduler/recovery-hold', {method: 'POST', headers: {'x-csrf-token': csrf}});
   console.log(hold.status); // 204; otherwise stop and investigate
   console.log(await (await fetch('/api/organizer/scheduler/status')).json());
   // held: true, configuration_hold: true, recovery_hold: true,
   // hospital_reader_available: false
   ```

   No production resume is allowed in this bootstrap, even with
   `{"reconciled":true}`. Do not call resume as an operational workaround.
4. **Confirmed on 2026-10-28 that invitations are genuinely stored on the
   remote D1 database:** the owner created one unused invitation through the
   existing API, and a direct read-only query against the remote database
   returned the expected row count. The specific before/after-redeploy
   comparison below was not repeated in this pass, though the service has
   already been redeployed multiple times historically with no indication of
   data loss. To prove D1 persistence without synthetic login/consent, create
   one unused owner invitation through the existing API, discard its private
   URL, and record only the database row count in private operator evidence.
   In the signed-in console, re-run to re-verify:

   ```js
   console.log((await fetch('/api/organizer/invitations', {method: 'POST', headers: {'x-csrf-token': csrf}})).status); // 201
   ```

   Owner read-only query, re-run to re-verify:

   ```sh
   uv run python -m pywrangler d1 execute next-is-you-production --remote --config .wrangler.production.jsonc --command 'SELECT COUNT(*) AS total FROM invitations'
   ```

   Record the count before/after redeploying the same approved config/commit
   to repeat that stronger comparison. Reload the same URL and check recovery
   hold is still true. The recorded query confirms invitation rows were stored
   in remote D1; the hold was reported by the status endpoint on 2026-10-27.
   Neither check establishes survival across a deployment. This pass did not
   establish restored-backup consistency or live notification deduplication.
   Do not rename the Worker, DO class, binding or singleton, or replace D1.
5. **Deferred - not run in this pass**, consistent with this issue's acceptance
   wording of deferring full live workload measurements to ticket 08. Confirm
   Cron is configured and observe a successful held scheduled invocation
   using native Cloudflare metrics. Record HTTP/Cron CPU, startup errors, DO
   requests/duration/storage and D1 rows read/written/storage and errors. Compare
   remaining account quota to the table above. Do not dump request headers or
   private payloads into logs. A local scheduled hook is not deployed Cron proof.
   Production Start remains held and does not read the live hospital until the
   Issue #22 pilot; the [NTUH reader guide](NTUH-READER.md) owns the reader gate.
   Real consented recipient and Start/provider journeys remain gated by the
   pre-live checklist.

The owner setup and acceptance pass above are complete to the extent marked
for each step as of 2026-10-27/28; a recorded stable URL and deployed evidence
exist privately. The LINE round-trip edge cases (step 2), the before/after-redeploy
D1 comparison (step 4), and the Cron/metrics check (step 5) remain unexercised
and are deferred, consistent with this issue's acceptance wording of deferring
full live workload measurements to ticket 08. Report fixture/mock, genuine
local, deployed, provider and handset results separately; LINE Login success
proves no reminder delivery. Keep all [pre-live gates](PRE-LIVE-CHECKLIST.md)
open for later exercises.

## Stop, failure recovery and rollback

For local foreground sessions Ctrl-C stops only that process; preserve its state
directory. On the deployed service closing the browser does not stop Cron. UI
**停止提醒** closes an active logical reminder only after confirmation; a request
already started may settle first. If Stop fails, retry and inspect the saved
state. It is not a retraction of an accepted LINE notification.

The configuration hold is enforced by this version's code, and recovery hold is
stored separately in the named DO. Set recovery hold before any restore, code
rollback or later live experiment and verify the status API. If auth is broken,
keep the held version deployed and fix only its private settings. To take the
HTTP service offline, set `workers_dev: false`, keep `preview_urls: false`,
then deploy the same held code/config after owner authorization (**remote
change; not performed in this pass**). This disables public browsing, not Cron.
To stop Cron too, set this Worker's `triggers.crons` to `[]` and deploy
(**remote change; not performed in this pass**). Preserve
D1 and DO resources; do not delete or clear any environment. When restoring the
schedule/origin, use the same IDs/name and verify both holds again.

Before a change, record the last known-good held version. Owner commands below
are generic rollback instructions, not yet exercised in this pass (list is a
remote read; rollback changes the deployment):

```sh
uv run python -m pywrangler deployments list --config .wrangler.production.jsonc
uv run python -m pywrangler rollback <known-good-held-version-id> --config .wrangler.production.jsonc
```

[Rollback](https://developers.cloudflare.com/workers/versions-and-deployments/rollbacks/)
selects the earlier Worker's code, assets and versioned bindings/settings; it
does not reverse D1 migrations or restore DO data. Routes and Cron triggers are
[managed separately](https://developers.cloudflare.com/workers/versions-and-deployments/deployment-management/)
and must be checked explicitly after rollback; rolling back does not undo an
operator's route or schedule shutdown. Roll back only to a version compatible
with the current schema and preserved SQLite class. Do not roll back to pre-hold/test-capable
code. If native rollback rejects a migration/storage/asset constraint, leave
sends held and deploy a forward fix; do not delete resources to force it.
Review settings after rollback and repeat the status, asset and persistence
checks. Unknown notification outcomes or a D1/DO ledger mismatch require private
reconciliation with preserved event IDs/retry keys before any future authorized
release. Enabling live sends requires a later accepted implementation and
provider/source gates; this task deliberately provides no production release
switch.
