# Deployed secrets inventory

Only secret **names** are tracked here. Values live in Cloudflare and never
appear in this repository, CI logs, or chat.

## Scope

This document covers both deployed Workers and the GitHub environments that
deploy them:

| Environment | Worker | Config | GitHub Environment |
| --- | --- | --- | --- |
| Production | `next-is-you-held` | `wrangler.production.jsonc` | `prod` |
| Staging | `next-is-you-staging` | `wrangler.staging.jsonc` | `staging` |

Each GitHub environment is used by exactly one workflow, and both are restricted
to deployments from branch `main`:

| GitHub Environment | Workflow and job | Runs when |
| --- | --- | --- |
| `staging` | `Deploy staging` job in `.github/workflows/ci.yml` | A push to `main` passes every gate, unless the push is documentation-only or `STAGING_DEPLOY_PAUSED` is `true`. |
| `prod` | `Deploy` job in `.github/workflows/promote.yml` | The captain dispatches Promote from `main` and the promote guard accepts the version. |

The other jobs (the gates, Release Please, and the promote guard) use no
environment and no Cloudflare credential; they run with the workflow's own
`GITHUB_TOKEN` only.

Local development reads from the untracked `.env` file described in
`.env_template`. `docs/CI-CD.md` owns how a commit reaches each Worker.

### What differs between the two environments

Staging and production share one LINE Login channel (`2011753957`), which is
what Issue #55 intends: each environment registers its own callback URL on that
channel rather than owning a separate channel.

- `LINE_LOGIN_CHANNEL_SECRET` is therefore **the same value** in both. It
  belongs to the shared channel.
- `SESSION_SIGNING_SECRET` must be a **different value** in each. This is the
  real isolation point: a session minted by one Worker cannot authenticate
  against the other, because each signs with its own key.
- `ORGANIZER_LINE_SUBJECTS` is normally **the same value** in both. A LINE
  subject is stable per provider, so the owner's subject is identical on the
  shared channel. Staging may narrow the list further if a staging-only
  organizer is wanted.
- `LINE_CHANNEL_ACCESS_TOKEN` is **absent in both**, and stays absent until
  Issue #22 authorizes a pilot. Its absence is a second layer, not the hold
  itself: `_held()` in `src/next_is_you/send_gate.py` returns true for every
  runtime that is not the local test mode, so providing this token would not
  release sends in either deployed environment.
- `LINE_LOGIN_REDIRECT_URI` differs because it embeds each Worker's own origin.

## Current inventory

`Holders` names which environments must carry the entry.

| Name | Kind | Holders | Purpose | Set via | Notes |
| --- | --- | --- | --- | --- | --- |
| `CLOUDFLARE_API_TOKEN` | GitHub Env secret | prod, staging | Authenticates `Deploy staging` (`ci.yml`) or Promote's `Deploy` job (`promote.yml`) against Cloudflare | GitHub Settings -> Environments -> the environment | Scope: Workers Scripts Edit, D1 Edit, Account Settings Read. Each environment holds its own token. Rotate when a maintainer leaves. |
| `CLOUDFLARE_ACCOUNT_ID` | GitHub Env secret | prod, staging | Target account for `Deploy staging` and Promote's `Deploy` job | GitHub Settings -> Environments -> the environment | Identifier, not a credential. No longer duplicated in `account_id` inside the committed `wrangler.*.jsonc` files; Wrangler reads it from this env var instead. Rotate only on account change. |
| `LINE_LOGIN_CHANNEL_SECRET` | Cloudflare Worker secret | both Workers | LINE Login OAuth client secret | `pywrangler secret put` | Same value in both, because both use the shared Login channel. Rotate immediately if LINE Developers console is compromised, and rotate it in both Workers together. |
| `SESSION_SIGNING_SECRET` | Cloudflare Worker secret | both Workers | HMAC key for session cookies and signed tokens | `pywrangler secret put` | At least 32 UTF-8 bytes. Must differ between staging and production. Rotating one invalidates that Worker's live sessions only. |
| `ORGANIZER_LINE_SUBJECTS` | Cloudflare Worker secret | both Workers | Comma-separated LINE subject IDs allowed to sign in as organizers | `pywrangler secret put` | Treated as a secret because membership is sensitive, not because it is a credential. Login returns `503 Organizer LINE Login is not configured` while this is unset, because `organizer_login_ready` in `src/worker.py` requires it. |
| `LINE_CHANNEL_ACCESS_TOKEN` | Cloudflare Worker secret | neither, by design | LINE Messaging API push credential | `pywrangler secret put` | Deliberately absent in both. Its absence is what holds reminder sends. Setting it anywhere requires Issue #22 authorization. |
| `LINE_LOGIN_REDIRECT_URI` | Cloudflare Worker var, set without committing it | both Workers | The LINE Login callback URL, which embeds the owner's Cloudflare `workers.dev` subdomain | `pywrangler deploy --var "LINE_LOGIN_REDIRECT_URI:<value>" --keep-vars` (one time per Worker) | Kept out of the repo because the value identifies the owner's Cloudflare account, not because it is a credential. `--keep-vars` on every later deploy preserves it even though it is absent from the config file. Each Worker holds its own origin. The URL must also be registered as a callback on the LINE Login channel, or login fails with `400 redirect_uri mismatch`. |
| `PROD_WORKER_URL`, `STAGING_WORKER_URL` | GitHub Actions repository variable (not a secret) | repository | Display-only deployed Worker URL used in `environment.url` and the run summary of `promote.yml` and `ci.yml` respectively | GitHub Settings -> Secrets and variables -> Actions, **Variables** tab | Not sensitive on its own, but kept out of workflow file text for the same reason as `LINE_LOGIN_REDIRECT_URI` above. |
| `STAGING_DEPLOY_PAUSED` | GitHub Actions repository variable (not a secret) | repository | Set to `true` (letter case is ignored; no other value pauses), pauses automatic staging deployment: `Deploy staging` is skipped and the run still succeeds | GitHub Settings -> Secrets and variables -> Actions, **Variables** tab | Absent means not paused. A value that is neither `true` nor `false` does not pause either; `npm run status` and the run page of a push to `main` warn about it. Read by `ci.yml`, by `npm run status`, and by the promote guard, which is handed it by `promote.yml` because a workflow token cannot read repository variables. See [docs/CI-CD.md](CI-CD.md#staging-follows-main). |

Non-secret variables committed directly in `wrangler.production.jsonc` /
`wrangler.staging.jsonc` under `vars`: `NIY_ENVIRONMENT`,
`NIY006_LOCAL_TEST_MODE`, `LINE_LOGIN_CHANNEL_ID` (a LINE OAuth client
identifier, not a secret by itself).

## How to work with the inventory

Every command below takes `--config wrangler.production.jsonc` or
`--config wrangler.staging.jsonc`. There is no default; always name the config,
so a staging intention never reaches production.

### List current names in Cloudflare

```sh
uv run python -m pywrangler secret list --config wrangler.staging.jsonc
```

Values are not returned. Only names.

### Read a deployed plain var

Plain vars are not secrets, so the live value can be read back. This is how to
confirm an environment's `LINE_LOGIN_REDIRECT_URI` without redeploying:

```sh
uv run python -m pywrangler versions list --config wrangler.staging.jsonc
uv run python -m pywrangler versions view <version-id> --config wrangler.staging.jsonc
```

The second command prints the bindings, including each plain var's value and
each secret's name.

### Add or update a secret

```sh
uv run python -m pywrangler secret put <NAME> --config wrangler.staging.jsonc
```

The command prompts for the value. The value is sent to Cloudflare over TLS
and is never written to the shell history buffer when run interactively.

### Remove a secret

```sh
uv run python -m pywrangler secret delete <NAME> --config wrangler.staging.jsonc
```

Only remove a name after the code no longer reads it; deployed code reading a
missing secret will fail at request time.

### Set a plain var without committing its value

For a value that is not a credential but should not appear in repository
text (for example `LINE_LOGIN_REDIRECT_URI`), deploy once with an inline
override instead of adding it to the `vars` block:

```sh
uv run python -m pywrangler deploy --config wrangler.production.jsonc --keep-vars \
  --var "LINE_LOGIN_REDIRECT_URI:<value>"
```

Because every deploy already runs with `--keep-vars`, later deploys that omit
this flag leave the value untouched on the live Worker; they only replace the
vars actually listed in the config file.

## Change log

Record every rotation here so the next maintainer knows which secret was
touched and why. Keep entries terse; no values.

| Date | Secret | Action | Reason |
| --- | --- | --- | --- |
| 2026-10-30 | - | inventory first published | - |
| 2026-11-03 | `account_id`, `LINE_LOGIN_REDIRECT_URI` | removed from committed `wrangler.*.jsonc`; deploy workflow URLs moved to repo variables | values identified the owner's Cloudflare subdomain in a repository meant to be shared publicly |
| 2026-11-14 | `LINE_LOGIN_CHANNEL_SECRET`, `SESSION_SIGNING_SECRET` | set on the staging Worker | staging had been deployed without any LINE configuration, so organizer login returned 503 |
| 2026-11-14 | - | inventory widened from production only to both deployed Workers and both GitHub environments | staging became a real deployment target under Issue #55 and had no documented inventory |
| 2026-11-15 | - | workflows and environment policies renamed in this inventory; `STAGING_DEPLOY_PAUSED` added | delivery was rebuilt (Issue #66, ADR 0001): staging deploys from `ci.yml` and production from `promote.yml`, both from branch `main` |

## Rules

- Never commit a value to this repository.
- Never paste a value into Claude or any other chat agent.
- Never log a value to Cloudflare logs or `console.log`.
- Never pass a value through GitHub Actions env or inputs.
- If a value is suspected to have leaked, rotate it the same day and record
  it in the change log above.
