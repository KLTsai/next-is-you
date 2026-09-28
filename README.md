# Next is you

Next is you is a new application project.

This repository is maintained in English.
More details will be added as the product direction takes shape.

## Local Worker

Install the Python development dependencies with `uv sync --group dev` and the frontend dependencies with `npm ci`. Copy `.env_template` to the repository-root `.env`, then fill only the values needed for local work. For example, run `cp .env_template .env` and open it with `${EDITOR:-vi} .env`; do not put values in shell commands or terminal transcripts. `npm run dev:local` builds the Vite UI, loads that `.env` when present, and serves the FastAPI app at `http://127.0.0.1:8787`. It binds to loopback and does not deploy. The loader never prints configuration values. Do not commit or share `.env`.

For local LINE Login configuration, set `LINE_LOGIN_CHANNEL_ID`, `LINE_LOGIN_CHANNEL_SECRET`, `LINE_LOGIN_REDIRECT_URI`, and a `SESSION_SIGNING_SECRET` of at least 32 UTF-8 bytes. Set `ORGANIZER_LINE_SUBJECTS` to the comma-separated LINE subject IDs authorized as organizers. Missing or invalid settings leave login unavailable. The plain Uvicorn launch has no Cloudflare bindings, so database-backed features and scheduler sends remain unavailable; `LINE_CHANNEL_ACCESS_TOKEN` alone cannot enable sending. `NIY006_LOCAL_TEST_MODE` is ignored by this launch path. Use the separate `wrangler.niy006.test.jsonc` only for the NIY-006 local test harness.

To verify the fail-closed local setup without credentials, leave the copied template blank, start `npm run dev:local`, and in another terminal run `curl -i http://127.0.0.1:8787/auth/line`; the route should return `503`. Open `http://127.0.0.1:8787/` to check the built UI, then stop the server with Ctrl-C. For a configured local login, use only your own local values in `.env`; this standard Python launch has no Cloudflare bindings, and scheduler sends remain disabled. The local `.env` is ignored and may be kept on this machine; never commit or share it. Never paste credential values into commands, tickets, or logs.

Production uses Cloudflare Worker configuration. Store `LINE_LOGIN_CHANNEL_SECRET`, `SESSION_SIGNING_SECRET`, and `LINE_CHANNEL_ACCESS_TOKEN` as Worker secrets. Provision `LINE_LOGIN_CHANNEL_ID`, `LINE_LOGIN_REDIRECT_URI`, and `ORGANIZER_LINE_SUBJECTS` through the deployment environment outside tracked files; treat the organizer allowlist as sensitive operational data. Configure `ASSETS`, `DB`, and `SEND_GATE` as Wrangler platform bindings, not `.env` entries. Never use local `.env` values as production configuration, and never enable `NIY006_LOCAL_TEST_MODE` in production.

## Local UI acceptance (NIY-007)

Run `npm ci`, `uv sync --group dev`, then `npm run dev:local`. Open `http://127.0.0.1:8787`. This path binds to loopback and needs no `.env` for the UI. Do not add credentials for this check.

Expected local result:

1. The header reports that the local service is healthy. The clinic catalog reports unavailable because this runtime has no clinic-catalog or hospital-reading route.
2. Choose either supported hospital and a date, then select **建立草稿**. The status card shows a draft, missing clinic/session data, no source link, no recipient roster, no trusted observation, and no send result. Change hospital/date and create the draft again to check the correction flow.
3. **開始提醒** stays disabled. The UI requires a fresh (under two minutes), trusted observation that exactly matches hospital, date, department, clinic, and session, plus a selected recipient. Fixture adapter results are untrusted and cannot satisfy this gate.
4. No active visit can be created through the current local app: visit creation/listing, clinic choices, and a recipient roster are not exposed by the API, and the local runtime has no database or send gate. The Stop control is shown on an active visit and posts to the existing `/api/visits/{visit_id}/stop` route; it cannot be reached in this local setup until those backend capabilities are connected. When Stop is pending, the UI says it is stopping; on a failed request it restores the active state and offers another attempt.
5. The interface has distinct draft, active, stopping, stopped, source-unavailable, and terminal labels. Source unavailability leaves a visit as a draft and never enables Start.

Run `npm run test:ui` for the focused lifecycle gate checks, `uv run pytest -q` for the full local Python suite, and `npm run build` for the frontend build. These commands do not contact hospitals or LINE and do not deploy.
