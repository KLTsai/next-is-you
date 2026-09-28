# NIY-010: Organizer API

Status: Open

## Goal

Provide the organizer API used by the settings UI to manage eligible family recipients and visit lifecycle state. Compose the existing identity, persistence, hospital observation, and serialized send-gate behavior without exposing sensitive provider or transport data.

## Scope

- Add organizer-authenticated endpoints to list currently eligible recipients and to list visits with a settings-ready status projection. The projection includes only the visit's clinic/date/session scope, selected recipient display data, lifecycle state, latest safe observation summary/check time, latest source-read status and reason, and notification outcome summary needed by the UI. Include the hospital source URL only when supplied by the selected hospital adapter/catalog; never accept or echo a caller-provided URL.
- Add draft creation and correction operations. Validate selected recipients as currently eligible and opted in. Draft edits may change the intended clinic/date/session and selection according to the lifecycle rules; they do not start monitoring or send notifications.
- Persist the latest source-read status and reason as bounded enums for the UI when the current observation schema cannot provide them. Status values are `usable`, `unavailable`, `stale`, `untrusted`, `scope_mismatch`, and `invalid`; reason values are `none`, `no_observation`, `timeout`, `stale_sample`, `untrusted_source`, `scope_mismatch`, `empty_result`, `schema_drift`, `access_denied`, `ambiguous_match`, and `invalid_data`. Store no raw response body or free-form error text. Allow only the minimal migration required for this metadata.
- Add a Start operation mediated by the NIY-006 serialized gate. Before activation, require a fresh, trusted observation whose clinic/date/session exactly matches the requested visit scope. Fail closed when no verified observation is available. Freeze the eligible recipient roster at the first successful Start, as defined by NIY-003/006.
- Add gate-mediated Stop integration using the existing lifecycle and gate behavior, exposing a confirmed stopped result only after the close operation has taken effect under NIY-006 semantics.
- Add correction for a stopped series by updating its watch while preserving the same logical visit ID and existing one-alert caps. Do not offer a correction path that resets notification history or silently creates a new logical visit.
- Return typed, safe errors for unavailable observations, stale observations, scope mismatch, ineligible recipients, and invalid lifecycle state. Do not expose raw hospital responses, LINE subjects or tokens, retry keys, or unfiltered exception details.
- Require the existing signed organizer session, recheck the current organizer allowlist on mutations, and enforce the signed session's CSRF token on every state-changing route. Do not add an alternate production authentication path.
- Preserve NIY-003/NIY-006 Taipei cutoff behavior at 23:59:00 on the visit day and the 48-hour deletion semantics for drafts and terminal visit/notification records.
- Provide a synthetic organizer session fixture for local browser acceptance only when the explicit NIY-006 local test configuration is enabled. Pair it with a fake hospital observation source and fake LINE transport. Prove the fixture is unavailable outside that explicit configuration and that production LINE Login, organizer allowlist enforcement, signed sessions, and CSRF behavior remain unchanged.

## Acceptance criteria

- An authenticated organizer can retrieve eligible recipients and a list of visits with the status and notification projection required by NIY-007, including the latest source-read status/reason and selected hospital's trusted source URL from its adapter/catalog. No endpoint accepts an arbitrary URL for this projection. Responses contain no provider payloads, identity subjects, credentials, retry keys, or exception internals.
- Persisted source-read status and reason use only the enumerated values in this ticket. The minimal migration, if needed, stores only this bounded metadata and does not add raw response or free-form exception fields.
- An organizer can create and edit a draft and can correct a stopped series. Correction retains the original logical visit ID and cannot reset per-recipient `near` or `unavailable` alert uniqueness/caps.
- Start cannot activate a visit unless the gate accepts a fresh, trusted observation for the exact clinic/date/session scope and freezes the eligible roster. Unavailable, stale, untrusted, or mismatched observations leave the visit a draft and produce the corresponding typed error.
- Stop is mediated by the NIY-006 gate and reports success only in accordance with its close/settlement contract. No API path bypasses the gate to start a LINE request or confirm Stop.
- State-changing requests reject missing/invalid CSRF tokens, non-organizer sessions, and organizers no longer present in the current allowlist. Production LINE Login and organizer session issuance retain NIY-005 behavior.
- Taipei cutoff and 48-hour deletion boundaries remain enforced through the API lifecycle.
- Automated route and lifecycle tests cover authorization, CSRF, typed errors, roster freeze, correction identity and caps, gate ordering, cutoff, and deletion boundaries.
- Local browser acceptance uses an isolated synthetic organizer/session fixture, fake hospital observation, and fake LINE transport. Tests prove the fixture cannot be enabled outside the explicit NIY-006 local test configuration and does not alter production authentication behavior.

## Out of scope

- NIY-004 live hospital transport and independent source freshness verification. Existing parsers/fixtures do not establish a verified live source; production Start remains unavailable unless the exact-scope observation is fresh and trusted.
- Real LINE calls, changes to LINE Login or recipient enrollment, and deployment.
- A browser-callable or manual endpoint that directly triggers arbitrary LINE sends or bypasses gate ordering. Automatic LINE notifications remain part of the product and continue to be triggered internally by the NIY-006 scheduler/outbox/gate when its conditions are met. This ticket uses fake LINE transport for local acceptance only and makes no live LINE calls; it does not remove or change automatic production notification behavior.
- Schema changes beyond the minimal migration for bounded latest source-read status/reason metadata, and any runtime configuration changes.

## Dependencies

NIY-001 through NIY-006, and NIY-009 for configuration boundaries. NIY-004 live transport/freshness verification remains a separate pre-live dependency for production Start.
