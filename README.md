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

For the API-backed browser journey, install dependencies with `npm ci` and `uv sync --group dev`, then build with `npm run build`. Start the local Worker with `uv run pywrangler dev --local --config wrangler.niy006.test.jsonc`; this config supplies local D1, a SQLite Durable Object, a fake hospital reader, fake LINE transport, and the explicit test-only session fixture. Open `http://127.0.0.1:8787`. The Wrangler path binds locally and does not deploy. Do not add `.env` credentials.

Expected local result:

1. Click **本機合成測試登入**. It succeeds only because this local config enables `NIY006_LOCAL_TEST_MODE`; it does not call LINE.
2. Set the fake source to a trusted number well outside the alert window, then seed an active synthetic visit for the Stop journey. Both operations affect only local test bindings:

   ```sh
   curl --fail-with-body -X POST http://127.0.0.1:8787/__niy006_test/observation \
     -H 'content-type: application/json' \
     --data '{"current_number":70,"trustworthy":true}'

   curl --fail-with-body -X POST http://127.0.0.1:8787/__niy006_test/seed \
     -H 'content-type: application/json' \
     --data "{\"visit_id\":\"niy007-stop-demo\",\"recipient_id\":\"niy007-family\",\"visit_day\":\"$(date -u -v+1d +%F)\",\"patient_number\":85,\"now\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
   ```

   Return to the browser and select **重新整理**. The visit should show **監控中**, the synthetic recipient, source status, and notification summary. Select **停止提醒**; it should show the pending stop state, then **已停止** after the API confirms closure. The configured fake number is 15 numbers from its target, so scheduled checks do not create an alert.
3. Clear the fake observation, then create a draft using the listed **Synthetic recipient**, a future visit date, hospital **臺大醫院總院**, department `SYN`, clinic `SYN-1`, session `afternoon`, and synthetic patient number `85`. These values are local test data. The form does not offer guessed clinic/session choices; use only the source values supplied for your test. The API-backed draft should appear with its recipient, the NTUH official source link, and **來源 unavailable**. The link is a static official reference; it does not mean the app has read or verified current hospital data.
4. Select **檢查資料並開始**. The route should return the typed unavailable error, keep the visit in **草稿**, and show the source reason. Configure a fresh trusted synthetic observation at `70` and try Start again:

   ```sh
   curl --fail-with-body -X POST http://127.0.0.1:8787/__niy006_test/observation \
     -H 'content-type: application/json' \
     --data '{"current_number":null,"trustworthy":false}'

   curl --fail-with-body -X POST http://127.0.0.1:8787/__niy006_test/observation \
     -H 'content-type: application/json' \
     --data '{"current_number":70,"trustworthy":true}'
   ```

   After setting the observation, select **檢查資料並開始** again. The route checks freshness, trust, and exact visit scope; only its successful response changes the visit to **監控中**. The UI does not call a hospital.

5. Select **停止提醒** on that active visit and verify the stopping and stopped states. On a stopped visit, **修正後重新檢查** keeps the same logical visit ID and the eligible existing recipient set.

The visit list shows the server-owned official source link for NTUH Main or Taipei Shin Kong when present in the visit projection. Shin Kong's link is its verified official registration portal, not a verified direct progress-query route. A missing link is shown as unavailable and is never made clickable. These static links make no hospital requests and do not imply freshness. The session field accepts only the domain's canonical values and does not display generic session options because there is no clinic/date-specific directory. Enter only a session code supplied by the hospital. The standard `npm run dev:local` path has no D1 or send-gate bindings; use it only to inspect the unauthenticated shell and unavailable-service behavior.

The current runner has `uv 0.11.32`, while `pywrangler` requires `uv 0.12.3` or newer, so the local browser journey could not be run in this environment. There is no browser automation dependency in the repository; use the manual browser steps above when the local Wrangler runtime is available.

Run `npm run test:ui` for the focused lifecycle gate checks, `uv run pytest -q` for the full local Python suite, and `npm run build` for the frontend build. These commands do not contact hospitals or LINE and do not deploy.
