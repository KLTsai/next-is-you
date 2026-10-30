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
| `CLOUDFLARE_API_TOKEN` | GitHub Env secret | Authenticates the production deploy workflow against Cloudflare | GitHub Settings -> Environments -> production | Scope: Workers Scripts Edit, D1 Edit, Account Settings Read. Rotate when a maintainer leaves. |
| `CLOUDFLARE_ACCOUNT_ID` | GitHub Env secret | Target account for the deploy workflow | GitHub Settings -> Environments -> production | Identifier, not a credential. Rotate only on account change. |
| `LINE_LOGIN_CHANNEL_SECRET` | Cloudflare Worker secret | LINE Login OAuth client secret | `pywrangler secret put` | Rotate immediately if LINE Developers console is compromised. |
| `SESSION_SIGNING_SECRET` | Cloudflare Worker secret | HMAC key for session cookies and signed tokens | `pywrangler secret put` | At least 32 UTF-8 bytes. Rotating this invalidates all live sessions. |
| `ORGANIZER_LINE_SUBJECTS` | Cloudflare Worker secret | Comma-separated LINE subject IDs allowed to sign in as organizers | `pywrangler secret put` | Treated as a secret because membership is sensitive, not because it is a credential. |
| `LINE_CHANNEL_ACCESS_TOKEN` | Cloudflare Worker secret | LINE Messaging API push credential | `pywrangler secret put` | Only required when real sending is enabled. Blank for the held HTTPS bootstrap. |

Non-secret variables live under `vars` in `wrangler.production.jsonc` and are
visible: `NIY_ENVIRONMENT`, `NIY006_LOCAL_TEST_MODE`, `LINE_LOGIN_CHANNEL_ID`,
`LINE_LOGIN_REDIRECT_URI`.

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

## Change log

Record every rotation here so the next maintainer knows which secret was
touched and why. Keep entries terse; no values.

| Date | Secret | Action | Reason |
| --- | --- | --- | --- |
| 2026-10-30 | - | inventory first published | - |

## Rules

- Never commit a value to this repository.
- Never paste a value into Claude or any other chat agent.
- Never log a value to Cloudflare logs or `console.log`.
- Never pass a value through GitHub Actions env or inputs.
- If a value is suspected to have leaked, rotate it the same day and record
  it in the change log above.
