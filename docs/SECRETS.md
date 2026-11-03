# Production secrets inventory

Only secret **names** are tracked here. Values live in Cloudflare and never
appear in this repository, CI logs, or chat.

## Scope

This document covers the production Worker (`next-is-you-held`,
`wrangler.production.jsonc`). Local development reads from the untracked
`.env` file described in `.env_template`.

## Current inventory

| Name | Kind | Purpose | Set via | Notes |
| --- | --- | --- | --- | --- |
| `CLOUDFLARE_API_TOKEN` | GitHub Env secret | Authenticates the production deploy workflow against Cloudflare | GitHub Settings -> Environments -> prod | Scope: Workers Scripts Edit, D1 Edit, Account Settings Read. Rotate when a maintainer leaves. |
| `CLOUDFLARE_ACCOUNT_ID` | GitHub Env secret | Target account for the deploy workflow | GitHub Settings -> Environments -> prod | Identifier, not a credential. No longer duplicated in `account_id` inside the committed `wrangler.*.jsonc` files; Wrangler reads it from this env var instead. Rotate only on account change. |
| `LINE_LOGIN_CHANNEL_SECRET` | Cloudflare Worker secret | LINE Login OAuth client secret | `pywrangler secret put` | Rotate immediately if LINE Developers console is compromised. |
| `SESSION_SIGNING_SECRET` | Cloudflare Worker secret | HMAC key for session cookies and signed tokens | `pywrangler secret put` | At least 32 UTF-8 bytes. Rotating this invalidates all live sessions. |
| `ORGANIZER_LINE_SUBJECTS` | Cloudflare Worker secret | Comma-separated LINE subject IDs allowed to sign in as organizers | `pywrangler secret put` | Treated as a secret because membership is sensitive, not because it is a credential. |
| `LINE_CHANNEL_ACCESS_TOKEN` | Cloudflare Worker secret | LINE Messaging API push credential | `pywrangler secret put` | Only required when real sending is enabled. Blank for the held HTTPS bootstrap. |
| `LINE_LOGIN_REDIRECT_URI` | Cloudflare Worker var, set without committing it | The LINE Login callback URL, which embeds the owner's Cloudflare `workers.dev` subdomain | `pywrangler deploy --var "LINE_LOGIN_REDIRECT_URI:<value>" --keep-vars` (one time) | Kept out of the repo because the value identifies the owner's Cloudflare account, not because it is a credential. `--keep-vars` on every later deploy preserves it even though it is absent from the config file. |
| `PROD_WORKER_URL`, `STAGING_WORKER_URL` | GitHub Actions repository variable (not a secret) | Display-only deployed Worker URL used in the deploy workflows' `environment.url` and run summary | GitHub Settings -> Secrets and variables -> Actions -> Variables | Not sensitive on its own, but kept out of workflow file text for the same reason as `LINE_LOGIN_REDIRECT_URI` above. |

Non-secret variables committed directly in `wrangler.production.jsonc` /
`wrangler.staging.jsonc` under `vars`: `NIY_ENVIRONMENT`,
`NIY006_LOCAL_TEST_MODE`, `LINE_LOGIN_CHANNEL_ID` (a LINE OAuth client
identifier, not a secret by itself).

## How to work with the inventory

### List current names in Cloudflare

```sh
uv run python -m pywrangler secret list --config wrangler.production.jsonc
```

Values are not returned. Only names.

### Add or update a secret

```sh
uv run python -m pywrangler secret put <NAME> --config wrangler.production.jsonc
```

The command prompts for the value. The value is sent to Cloudflare over TLS
and is never written to the shell history buffer when run interactively.

### Remove a secret

```sh
uv run python -m pywrangler secret delete <NAME> --config wrangler.production.jsonc
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

## Rules

- Never commit a value to this repository.
- Never paste a value into Claude or any other chat agent.
- Never log a value to Cloudflare logs or `console.log`.
- Never pass a value through GitHub Actions env or inputs.
- If a value is suspected to have leaked, rotate it the same day and record
  it in the change log above.
