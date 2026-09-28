# NIY-009: Runtime configuration and secrets management

Status: Open

## Goal

Make the application's runtime configuration explicit, make root `.env` values usable in the supported local run path, and keep local values separate from production Worker secrets and bindings.

## Current evidence and ownership

- `src/worker.py` reads LINE Login settings from the Worker request environment: `LINE_LOGIN_CHANNEL_ID`, `LINE_LOGIN_CHANNEL_SECRET`, `LINE_LOGIN_REDIRECT_URI`, `SESSION_SIGNING_SECRET`, and `ORGANIZER_LINE_SUBJECTS`.
- `src/next_is_you/send_gate.py` reads `LINE_CHANNEL_ACCESS_TOKEN` and `NIY006_LOCAL_TEST_MODE` from the Worker environment. `ASSETS`, `DB`, and `SEND_GATE` are platform bindings configured by Wrangler, not values currently loaded from `.env`.
- `.env_template` currently names only `LINE_CHANNEL_ACCESS_TOKEN` and `NIY006_LOCAL_TEST_MODE`. `.gitignore` ignores `.env`, `.env.*`, `.dev.vars`, and `.dev.vars.*`; `.env_template` remains trackable.
- `npm run dev:local` starts Uvicorn without an env-file option. The app reads request-scoped Worker bindings and does not load process environment variables, so copying `.env_template` to `.env` does not currently configure that launch path.
- NIY-006 owns scheduler/outbox behavior and its local test harness, including the test-only mode and push-token checks already recorded there. Its ticket body says `Complete`, while the ticket index says `Open`; this ticket owns the broader application configuration catalog and local configuration workflow without changing NIY-006's recorded scope or status.

## Configuration inventory

| Name | Purpose | Handling |
| --- | --- | --- |
| `LINE_LOGIN_CHANNEL_ID` | LINE Login channel identifier | Local configuration; production Worker variable |
| `LINE_LOGIN_CHANNEL_SECRET` | LINE Login credential | Local-only value in `.env`; production Worker secret |
| `LINE_LOGIN_REDIRECT_URI` | LINE Login callback URI | Local configuration; production Worker variable |
| `SESSION_SIGNING_SECRET` | Signs application sessions and login transactions | Local-only value in `.env`; production Worker secret; at least 32 UTF-8 bytes |
| `ORGANIZER_LINE_SUBJECTS` | Comma-separated organizer allowlist | Local configuration; production value provisioned outside tracked files and handled as sensitive operational data |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API push credential | Local-only value in `.env`; production Worker secret |
| `NIY006_LOCAL_TEST_MODE` | Enables NIY-006's local synthetic scheduler/test routes | Test-only Wrangler variable; never a production setting |

The `ASSETS`, `DB`, and `SEND_GATE` bindings are supplied by Wrangler configuration. Document their local and production roles separately from `.env` values. Do not put binding objects, real database identifiers, or credentials in the environment template.

## Acceptance criteria

- `.env_template` lists every runtime environment name above, gives safe descriptions or non-secret placeholders only, and leaves credential values blank. It does not contain real or fabricated credentials.
- The documented local launch path explicitly loads the repository-root `.env` when present and maps its values to the same application settings used by the Worker. Missing local values fail closed and do not silently enable real LINE sends or test-only routes.
- Local setup documents which settings are needed for each feature, how `.env` is loaded, and that developers must not commit or share `.env` values. No `.env` file is added to the repository.
- `.env` and `.env.*` remain ignored while `.env_template` remains tracked; `.dev.vars` remains ignored for Wrangler workflows. Checks cover `.env`, `.env.local`, and `.env.example` without adding real values.
- Production secrets (`LINE_LOGIN_CHANNEL_SECRET`, `SESSION_SIGNING_SECRET`, and `LINE_CHANNEL_ACCESS_TOKEN`) are configured through Cloudflare Worker secrets, not checked-in files or Wrangler plaintext vars. Non-secret production settings and the organizer allowlist are provisioned outside tracked files. Local `.env` values are never treated as production values.
- `NIY006_LOCAL_TEST_MODE` remains isolated to the local test Wrangler config and cannot turn on test controls or fake transport in production.
- Local configuration checks prove the selected launch path receives settings and bindings as documented without contacting LINE, deploying, or logging secret values.

## Related tickets

- [NIY-005: LINE identity and targeted delivery](NIY-005-line-integration.md) owns LINE Login and recipient behavior.
- [NIY-006: Scheduler, outbox, and send coordination](NIY-006-scheduler-outbox.md) owns send coordination and the local test harness.
- [NIY-015: Repository structure review and disposition](NIY-015-repository-structure-review.md) records the broader repository inventory and cleanup decisions.
