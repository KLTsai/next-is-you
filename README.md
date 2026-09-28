# Next is you

Next is you is a new application project.

This repository is maintained in English.
More details will be added as the product direction takes shape.

## Local Worker

Install the Python development dependencies with `uv sync --group dev` and the frontend dependencies with `npm ci`. Copy `.env_template` to the repository-root `.env`, then fill only the values needed for local work. `npm run dev:local` builds the Vite UI, loads that `.env` when present, and serves the FastAPI app at `http://127.0.0.1:8787`. It binds to loopback and does not deploy. The loader never prints configuration values. Do not commit or share `.env`.

For local LINE Login configuration, set `LINE_LOGIN_CHANNEL_ID`, `LINE_LOGIN_CHANNEL_SECRET`, `LINE_LOGIN_REDIRECT_URI`, and a `SESSION_SIGNING_SECRET` of at least 32 UTF-8 bytes. Set `ORGANIZER_LINE_SUBJECTS` to the comma-separated LINE subject IDs authorized as organizers. Missing or invalid settings leave login unavailable. The plain Uvicorn launch has no Cloudflare bindings, so database-backed features and scheduler sends remain unavailable; `LINE_CHANNEL_ACCESS_TOKEN` alone cannot enable sending. `NIY006_LOCAL_TEST_MODE` is ignored by this launch path. Use the separate `wrangler.niy006.test.jsonc` only for the NIY-006 local test harness.

Production uses Cloudflare Worker configuration. Store `LINE_LOGIN_CHANNEL_SECRET`, `SESSION_SIGNING_SECRET`, and `LINE_CHANNEL_ACCESS_TOKEN` as Worker secrets. Provision `LINE_LOGIN_CHANNEL_ID`, `LINE_LOGIN_REDIRECT_URI`, and `ORGANIZER_LINE_SUBJECTS` through the deployment environment outside tracked files; treat the organizer allowlist as sensitive operational data. Configure `ASSETS`, `DB`, and `SEND_GATE` as Wrangler platform bindings, not `.env` entries. Never use local `.env` values as production configuration, and never enable `NIY006_LOCAL_TEST_MODE` in production.
