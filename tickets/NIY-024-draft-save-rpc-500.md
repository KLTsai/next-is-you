# NIY-024: Fix draft-save HTTP 500 across Worker and Durable Object RPC

Status: Open

## Goal

Make saving an existing draft through `PATCH /api/organizer/visits/{id}` complete successfully instead of returning HTTP 500 when the Worker calls the Durable Object.

## Scope

- Replace the reproduced tuple argument crossing the Worker-to-Durable-Object RPC boundary with JSON/RPC-compatible primitive arguments and a stable request shape.
- Preserve organizer authorization, CSRF checks, draft validation, and typed error responses.
- Add a local Wrangler integration regression that traverses the real local Worker/Durable Object binding.

## Acceptance criteria

- The local Wrangler integration creates a synthetic draft, sends an authorized `PATCH /api/organizer/visits/{id}`, and receives the documented successful draft response rather than HTTP 500.
- The same test verifies the updated values persist and can be read back through the organizer flow.
- Invalid JSON, missing required fields, invalid lifecycle state, failed authorization, and invalid CSRF continue to return the existing typed client/error responses rather than an internal server error.
- The regression exercises the actual local Worker/DO binding, not only an in-process mock or direct repository call.

## Dependencies

NIY-008 for local acceptance/integration infrastructure and NIY-010 for the organizer draft route and lifecycle contract.

## Out of scope

- Unrelated Worker/DO methods, API redesign, lifecycle changes, provider integrations, live Wrangler environments, deployment, secrets, and real patient data.
