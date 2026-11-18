# Private HTTPS service: provisioning and operation (Issue #18)

> **This document provisions and operates an environment. It is not the
> deployment procedure for a change.** Ongoing deployment is owned by
> [docs/CI-CD.md](CI-CD.md): a commit reaches staging automatically after
> a green push to `main` (the `Deploy staging` job in
> `.github/workflows/ci.yml`, GitHub environment `staging`) and production
> through **Promote** (`.github/workflows/promote.yml`, GitHub environment
> `prod`), using the committed `wrangler.staging.jsonc` and
> `wrangler.production.jsonc`. Both environments accept deployments from branch
> `main` only. [docs/SECRETS.md](SECRETS.md) lists what each one holds.
>
> Do not hand-deploy production from a local `.wrangler.production.jsonc`. That
> file declares `LINE_LOGIN_REDIRECT_URI`, which commit `6a4af1c` deliberately
> removed from the committed config so the deployed value is preserved through
> `--keep-vars` instead. A hand deployment would overwrite the live value, and
> the account's `workers.dev` subdomain has since changed, so any older local
> copy carries a dead URL.

Sections are grouped by what they are for, because they are not all the same
kind of text:

| Section | Kind |
| --- | --- |
| [Scope and authorization](#scope-and-authorization), [Free plan and origin decision](#free-plan-and-origin-decision) | Decisions this environment rests on |
| [Local proof](#local-proof-before-any-remote-action), [Provisioning](#provisioning-a-fresh-environment), [Acceptance checks](#acceptance-checks) | Instructions, to follow in order |
| [Stop, failure recovery and rollback](#stop-failure-recovery-and-rollback) | Operational procedure for a running environment |
| [Recorded evidence](#recorded-evidence-for-the-owners-production-environment) | A dated log of one environment. Not an instruction |

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
The held bootstrap was deployed as recorded in
[Recorded evidence](#recorded-evidence-for-the-owners-production-environment);
see the [README status](../README.md#status) for the current user-facing state.
Deployment does not authorize live reads or reminder sends, and publication of
repository changes does not authorize a new deployment.

Non-goals: enabling sends, enabling the hospital reader in production before
the Issue #22 pilot, LINE or handset acceptance, paid resources, domain purchase,
another service/database, a storage rewrite, or a deployment automation layer.
The [NTUH reader guide](NTUH-READER.md) owns reader scope and behavior.

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
in this bootstrap. Full live workload/retention measurement belongs to acceptance criterion 6 of #22.

The Free plan is the proposed plan for this held bootstrap, not proven sufficient for
this Python/FastAPI app's deployed CPU, startup, memory, or workload. Check those
metrics after authorized deployment; a quota/startup failure is a stop condition,
not an invitation to enable Paid. The local dry run proves compilation only.
The 2026-10-03 native dry run with pywrangler 1.17.4 / Wrangler 4.147.0 reported
9,329.18 KiB total upload (2,305.70 KiB gzip), 1,018 modules and four asset files.
No deployed CPU, startup latency, memory, quota usage or provider measurements
are available. Local wall-clock test timing is not a Free-plan CPU measurement.

Proposed origin: `https://<approved-worker-name>.<owner-subdomain>.workers.dev`.
[Cloudflare documents](https://developers.cloudflare.com/workers/configuration/routing/workers-dev/)
that this origin is public, suitable for personal/hobby use, and recommends custom
domains for business-critical production. The static shell and health endpoint
are public; organizer data and mutations require an allowlisted LINE session and
mutations require CSRF. Recipient enrollment additionally requires an invitation,
friendship verification and consent. The owner must explicitly agree whether
this application-level privacy meets "private HTTPS." No domain purchase or
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

## Provisioning a fresh environment

These five steps create one environment from nothing. Every one of them needs
the account owner's explicit authorization: the selected account, the new D1
database and Worker/DO resources, the fixed origin and what privacy it is taken
to mean, Workers Free with no plan purchase, and an organizer subject supplied
privately. That subject belongs to the LINE provider used by this Login channel;
a display name is not an identifier, and the allowlist must not be broadened to
discover one.

The owner's own production environment was provisioned this way. What that run
established, and what it did not, is in
[Recorded evidence](#recorded-evidence-for-the-owners-production-environment).

1. Copy the template to the ignored repository-root `.wrangler.production.jsonc`.
   Set `name` to the approved unique Worker name, and `account_id` to the
   authorized account ID. Keep public routes disabled for initial setup. Never
   deploy a local or rehearsal config remotely. Name this explicit production
   config on every command; no named environment inherits test bindings. Local
   state and the new remote database are separate.
2. Authenticate with native Wrangler and create only the approved D1 database:

   ```sh
   uv run python -m pywrangler login
   uv run python -m pywrangler d1 create next-is-you-production --config .wrangler.production.jsonc
   ```

   Keep the returned resource ID private and replace the template's zero UUID
   with it in the ignored config. If another database name is chosen, use that
   exact name both in the config and in every command below. Stop if Wrangler
   selects another account or requests a plan upgrade. Do not accept resource
   auto-creation beyond the approved Worker, D1 and SQLite DO.
3. Build and dry-run the config first. Then apply migrations to the one approved
   remote database and deploy the service with the origin still disabled:

   ```sh
   uv run python -m pywrangler d1 migrations apply next-is-you-production --remote --config .wrangler.production.jsonc
   uv run python -m pywrangler deploy --config .wrangler.production.jsonc --keep-vars
   ```

   Deployment provisions `ASSETS`, `SEND_GATE`/`SystemSendGate` with SQLite
   storage, and the existing one-minute scheduled handler on this one Worker.
   No second service is needed. Missing auth settings deny login and protected
   APIs; every non-local-test runtime is held by code even if a push token exists.
4. Provision `LINE_LOGIN_CHANNEL_ID` and the exact approved
   `LINE_LOGIN_REDIRECT_URI` as this Worker's dashboard variables. Provision the
   three secrets through native masked interactive prompts or the dashboard's
   secret controls:

   ```sh
   uv run python -m pywrangler secret put LINE_LOGIN_CHANNEL_SECRET --config .wrangler.production.jsonc
   uv run python -m pywrangler secret put SESSION_SIGNING_SECRET --config .wrangler.production.jsonc
   uv run python -m pywrangler secret put ORGANIZER_LINE_SUBJECTS --config .wrangler.production.jsonc
   ```

   Use an independently generated session signing secret of at least 32 UTF-8
   bytes. Paste values only into private masked controls, never into shell
   arguments, tracked files, logs, reports or chat. Do not provision
   `LINE_CHANNEL_ACCESS_TOKEN` for a held bootstrap. Root `.env` and local
   `.dev.vars` are not production provisioning sources. Keep
   `NIY_ENVIRONMENT=production` and `NIY006_LOCAL_TEST_MODE=0`; neither is a
   secret. [docs/SECRETS.md](SECRETS.md) is the inventory for both deployed
   environments.
5. Register the exact callback above in LINE Console, with an appropriate
   channel status or tester permission for the account that will sign in. Once
   the public-origin choice is agreed, set `workers_dev: true` in the ignored
   config and deploy again, keeping `preview_urls: false`. Record the exact URL
   Wrangler returns, the account and plan, resource IDs, deployed
   commit/version, migration versions and the time, privately.

## Acceptance checks

Run these against the live deployed origin once provisioning is complete. Daily
use needs only a browser; open the exact stable URL. Report fixture/mock,
genuine local, deployed, provider and handset results separately, and keep all
[pre-live gates](PRE-LIVE-CHECKLIST.md) open for later exercises: a successful
LINE Login proves nothing about reminder delivery.

1. **Origin and fail-closed API.** The current UI and its JS/CSS load over HTTPS
   from this same origin. `/api/healthz` returns
   `{"status":"ok","mode":"held-service"}`. An unauthenticated
   `POST /api/organizer/invitations` returns `401`, other logged-out organizer
   API calls are refused, and missing or invalid configuration returns `503`.
   The synthetic `/__niy006_test/organizer-session`, `/seed` and `/snapshot`
   routes return `404`, and no synthetic login button is rendered.
2. **LINE round trip.** Complete a real LINE login and reach organizer access,
   with the exact callback returning to this origin. Check that a second test
   account outside the allowlist gets `403`, and that a callback with missing
   state or code returns `401`. Do not add an unauthorized account to the
   allowlist. Do not capture callback codes, cookies, provider tokens or patient
   information in evidence.
3. **Recovery hold.** Set recovery hold through the authorized status API and
   confirm the status endpoint reports `held: true`, `configuration_hold: true`,
   `recovery_hold: true` and `hospital_reader_available: false`. The console
   snippet is in
   [Stop, failure recovery and rollback](#stop-failure-recovery-and-rollback).
   No production resume is allowed in this bootstrap, even with
   `{"reconciled":true}`. Do not call resume as an operational workaround.
4. **D1 persistence.** Prove it without synthetic login or consent: create one
   unused owner invitation through the existing API, discard its private URL,
   and record only the row count in private operator evidence. In the signed-in
   console:

   ```js
   console.log((await fetch('/api/organizer/invitations', {method: 'POST', headers: {'x-csrf-token': csrf}})).status); // 201
   ```

   Owner read-only query:

   ```sh
   uv run python -m pywrangler d1 execute next-is-you-production --remote --config wrangler.production.jsonc --command 'SELECT COUNT(*) AS total FROM invitations'
   ```

   Record that count before and after redeploying the same approved config and
   commit; only the comparison establishes survival across a deployment. Reload
   the same URL and check recovery hold is still true. Do not rename the Worker,
   DO class, binding or singleton, and do not replace D1.
5. **Cron and platform metrics.** Confirm Cron is configured and observe a
   successful held scheduled invocation using native Cloudflare metrics. Record
   HTTP and Cron CPU, startup errors, DO requests/duration/storage, and D1 rows
   read/written/storage and errors. Compare remaining account quota to the
   [Free-plan table](#free-plan-and-origin-decision). Do not dump request
   headers or private payloads into logs. A local scheduled hook is not deployed
   Cron proof. Production Start remains held and does not read the live hospital
   until the Issue #22 pilot; the [NTUH reader guide](NTUH-READER.md) owns the
   reader gate, and real consented recipient and Start/provider journeys remain
   gated by the pre-live checklist.

## Stop, failure recovery and rollback

For local foreground sessions Ctrl-C stops only that process; preserve its state
directory. On the deployed service closing the browser does not stop Cron. UI
**停止提醒** closes an active logical reminder only after confirmation; a request
already started may settle first. If Stop fails, retry and inspect the saved
state. It is not a retraction of an accepted LINE notification.

To hold the whole service, the signed-in owner sets recovery hold through the
authorized status API. These application actions use the current session's CSRF
cookie without displaying it:

```js
const csrf = decodeURIComponent(document.cookie.split('; ').find(v => v.startsWith('__Host-ny_csrf='))?.split('=').slice(1).join('=') ?? '');
const hold = await fetch('/api/organizer/scheduler/recovery-hold', {method: 'POST', headers: {'x-csrf-token': csrf}});
console.log(hold.status); // 204; otherwise stop and investigate
console.log(await (await fetch('/api/organizer/scheduler/status')).json());
// held: true, configuration_hold: true, recovery_hold: true,
// hospital_reader_available: false
```

The configuration hold is enforced by this version's code, and recovery hold is
stored separately in the named DO, so it survives Worker restarts. Set recovery
hold before any restore, code rollback or later live experiment and verify the
status API. If auth is broken, keep the held version deployed and fix only its
private settings.

To take the HTTP service offline, set `workers_dev: false`, keep
`preview_urls: false`, then deploy the same held code and config after owner
authorization. This disables public browsing, not Cron. To stop Cron too, set
this Worker's `triggers.crons` to `[]` and deploy. Preserve D1 and DO resources;
do not delete or clear any environment. When restoring the schedule or origin,
use the same IDs and name and verify both holds again.

[docs/CI-CD.md](CI-CD.md#rollback) owns the primary rollback procedure: run
**Promote** with an earlier version number, which restores a known deployed
commit's code only. The
native Wrangler commands below remain the emergency path for when Promote is
unusable. Before a change, record the last known-good
held version:

```sh
uv run python -m pywrangler deployments list --config wrangler.production.jsonc
uv run python -m pywrangler rollback <known-good-held-version-id> --config wrangler.production.jsonc
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

## Recorded evidence for the owner's production environment

This section is a record of one environment, the owner's production Worker. It
is not an instruction, and nothing here should be repeated by anyone setting up
their own copy.

**Provisioning.** Deployment history confirms an initial deploy on 2026-10-23,
three "Secret Change" events on 2026-10-27 matching the three required secrets,
and that the version live during the 2026-10-27/28 verification was from
2026-10-27. `wrangler secret list` confirmed `LINE_LOGIN_CHANNEL_SECRET`,
`ORGANIZER_LINE_SUBJECTS` and `SESSION_SIGNING_SECRET` are all provisioned
(names only; values were never read). Provisioning steps 1-5 are complete on
this evidence. The owner authorized the account, the resources, the fixed origin
and its privacy meaning, and Workers Free with no plan purchase, and supplied the
organizer subject privately. The allowlist was not broadened to discover that
identity, and no private account data was inspected during preparation or
verification.

**Acceptance**, run directly against the live deployed origin on 2026-10-27/28:

| Check | Result |
| --- | --- |
| 1 Origin and fail-closed API | **Partly confirmed.** UI and JS/CSS loaded over HTTPS from the same origin, `/api/healthz` returned `{"status":"ok","mode":"held-service"}`, an unauthenticated `POST /api/organizer/invitations` returned `401`, and `/__niy006_test/organizer-session` returned `404`. Other logged-out organizer responses, the `503` for missing or invalid configuration, the `/seed` and `/snapshot` routes and the synthetic login button were not exercised. |
| 2 LINE round trip | **Partly confirmed, 2026-10-27.** The owner completed a real LINE login and reached organizer access, and the exact callback returned to this origin. The `403` for an account outside the allowlist and the `401` for a callback with missing state or code were not exercised and remain unverified. |
| 3 Recovery hold | **Confirmed, 2026-10-27.** The owner set recovery hold and the status endpoint reported the four expected values. Not re-checked since that date. |
| 4 D1 persistence | **Partly confirmed, 2026-10-28.** The owner created one unused invitation through the existing API and a direct read-only query against the remote database returned the expected row count. The before/after-redeploy comparison was not repeated, though the service has been redeployed several times since with no indication of data loss. |
| 5 Cron and platform metrics | **Deferred, not run**, consistent with this issue's acceptance wording, which defers full live workload measurement to acceptance criterion 6 of #22. |

What this pass did not establish: survival of data across a deployment,
restored-backup consistency, and live notification deduplication. No deployed
CPU, startup latency, memory, quota usage or provider measurement exists for
this environment.

Taking the HTTP service offline, stopping Cron, and the native Wrangler rollback
commands have never been exercised here. A recorded stable URL and the deployed
evidence exist privately.
