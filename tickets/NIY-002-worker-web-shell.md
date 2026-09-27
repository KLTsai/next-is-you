# NIY-002: Python Worker and local web shell

Status: Done (local acceptance passed)

## Implementation notes

- `src/worker.py` registers `/api/healthz` before the local static fallback and serves built assets from `dist`; Cloudflare requests use the configured `ASSETS` binding.
- `npm run dev:local` builds the Vite UI and starts Uvicorn on loopback, keeping the UI and API on one local origin without deployment.
- Worker regression tests cover route order, local health, and same-origin UI and asset responses. The local smoke check also exercised the actual Vite build through Uvicorn.
- Browser output and the committed Wrangler configuration were inspected for secrets and patient values; the configured D1 ID is an all-zero placeholder.

## Goal

Create the FastAPI-based Python Worker entrypoint and same-origin static asset path, with a small Vite-built TypeScript frontend and a local-only development command.

## Acceptance criteria

- The Worker serves API routes before static assets and has a local health endpoint.
- The UI is served from the Worker origin after a Vite build.
- No secret or patient value is included in browser code or committed example configuration.
- Local smoke tests use the local runtime only and do not deploy.

## Dependencies

NIY-001.
