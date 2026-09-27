# NIY-002: Python Worker and local web shell

Status: In progress

## Goal

Create the FastAPI-based Python Worker entrypoint and same-origin static asset path, with a small Vite-built TypeScript frontend and a local-only development command.

## Acceptance criteria

- The Worker serves API routes before static assets and has a local health endpoint.
- The UI is served from the Worker origin after a Vite build.
- No secret or patient value is included in browser code or committed example configuration.
- Local smoke tests use the local runtime only and do not deploy.

## Dependencies

NIY-001.
