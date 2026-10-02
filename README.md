# Next is you

Next is you is a new application project.

This repository is maintained in English. Active work is tracked in [GitHub Issues](https://github.com/KLTsai/next-is-you/issues); see the [issue-tracker conventions](docs/agents/issue-tracker.md). Former local tickets are [archived historical records](docs/archive/tickets/README.md), not current work assignments. Their completion statements retain their original evidence limits.

## Local development entrypoints

Use the [supported toolchain and validated host details in the complete rehearsal guide](docs/LOCAL-REHEARSAL.md#first-time-preparation) before installing dependencies.

From a clean checkout, install the locked dependencies once:

```sh
npm ci
uv sync --group dev --locked
```

Choose an entrypoint:

- **Complete local service rehearsal:** run `npm run dev:rehearsal` and open <http://127.0.0.1:8787>. This is the recommended path for trying the UI with real local D1 and SQLite Durable Object bindings plus synthetic login and fake providers. It needs no credentials. Follow the [complete rehearsal guide](docs/LOCAL-REHEARSAL.md) for the first synthetic setup, draft, Start/Stop, fake send, duplicate tick, and restart journey.
- **Lightweight shell smoke:** run `npm run dev:local`, then open <http://127.0.0.1:8787>. This builds the UI and serves the Python ASGI app on loopback without Cloudflare bindings, D1, or Durable Objects. With the blank template, `curl -i http://127.0.0.1:8787/auth/line` should return `503`. Stop the foreground server with Ctrl-C. It does not exercise database features or reminder sends.

`npm run dev:rehearsal` builds current UI assets, applies pending local migrations, and serves the Worker in the foreground. It uses `.wrangler/manual-rehearsal` on every start. Stop it with Ctrl-C, then run the same command to continue with the same data and outbox. Do not delete that state or reset the database to repeat the journey. Unchanged dependencies are not reinstalled on repeat starts. Update dependencies only when intentionally changing a manifest or lockfile; use `npm install` for npm dependency changes and `uv lock` for Python dependency changes, review the lockfile diff, then repeat the locked setup commands and relevant checks.

### Optional private local development

The lightweight `dev:local` path can use your own local LINE Login settings. Copy [.env_template](.env_template) to the ignored repository-root `.env` and edit it locally; never put values in commands, logs, or repository files. This app reads the root `.env` for this path only; shell environment variables are not merged into its settings. Leave unused values blank. The loader excludes `NIY006_LOCAL_TEST_MODE` and does not print values. This path has no Cloudflare bindings, so a LINE access token cannot enable scheduler sends. Keep credentials on your machine and do not share the `.env` file.

For private local shell work, start `npm run dev:local` when needed and stop it with Ctrl-C when finished. It is a lightweight UI/login smoke, not the complete reminder service. The complete rehearsal does not read root `.env` and does not need real credentials. Its test-only mode comes from `wrangler.niy006.test.jsonc`; `ASSETS`, `DB`, and `SEND_GATE` are Wrangler platform bindings. For deployed Worker use, configure secrets and non-secret variables through the deployment environment, and provision the bindings there. Local `.env` is never a deployment source. See [NIY-009 runtime configuration decisions](docs/archive/tickets/NIY-009-runtime-configuration-secrets.md) and the [pre-live checklist](docs/PRE-LIVE-CHECKLIST.md) for ownership and live gates.

The [rehearsal guide](docs/LOCAL-REHEARSAL.md#first-time-preparation) explains the locked Worker runtime dependencies and generated tooling mirrors; project runtime dependencies are declared in `pyproject.toml` and locked in `uv.lock`.

## Validation and operations

The CI-equivalent deterministic checks are:

```sh
uv run playwright install chromium
uv run ruff format --check src tests
uv run ruff check src tests
npm run typecheck
npm run test:ui
npm run build
uv run python scripts/check_migrations.py
uv run pytest -q
git diff --check
```

These are fixture/mock and local automated evidence. `tests/test_local_acceptance.py` exercises organizer routes, SQLite, synthetic hospital observations, scheduled ticks, and fake LINE transport in process. Worker startup and draft RPC tests use local Wrangler bindings. They do not contact a live hospital or LINE, deploy, or prove handset delivery. See the [CI workflow](.github/workflows/ci.yml) for the automated gates. For tested UI steps and recovery, use the [local manual checklist](docs/NIY-020-LOCAL-MANUAL-CHECKLIST.md) and [complete rehearsal guide](docs/LOCAL-REHEARSAL.md). The [pre-live checklist](docs/PRE-LIVE-CHECKLIST.md) lists deployed integration, provider acceptance, and handset evidence still required.

Source research and evidence limits are indexed in [research/README.md](research/README.md), including the [NIY-021 findings summary](research/NIY-021-findings-summary.md). Historical implementation decisions and their owning current guides are indexed in [docs/archive/tickets/README.md](docs/archive/tickets/README.md).
