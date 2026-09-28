# NIY-016: Trusted hospital progress links

Status: Complete (2026-09-28)

## Goal

Supply the NIY-010 visit projection with a server-owned official hospital link when a verified catalog entry exists, so NIY-007 can let the organizer open the selected hospital's source page.

## Verified official URLs and limits

- NTUH Main queue progress page: `https://registration.ntuh.gov.tw/WebReg/WebReg/ClinicCurrentLightNo?vHospCode=T0`.
- Taipei Shin Kong official registration portal: `https://reg.skh.org.tw/`. This is a verified official portal entry only; its direct progress-query route has not been verified.
- The refresh interval for either source is unknown. Do not infer or communicate a cadence.

These URLs are static allowlist values owned by the server. Use only the `ntuh-main` and `shin-kong-taipei` hospital identifiers. Do not accept a caller URL, redirect to a caller URL, fetch, scrape, poll, infer another endpoint, or claim source freshness from this catalog. Emit links only over HTTPS.

## Acceptance criteria

- The NIY-010 visit projection includes optional `source_url` only when the selected hospital is present in the server-side catalog.
- `ntuh-main` resolves exactly to the NTUH Main queue progress page above; `shin-kong-taipei` resolves exactly to the official portal above.
- Unsupported hospital identifiers produce no source URL.
- Caller-provided URLs are rejected or ignored and never reflected in the projection or used as a redirect target.
- URL selection is deterministic, HTTPS-only, and makes no network requests. The catalog does not establish freshness, reliability, or refresh cadence.
- Synthetic local tests cover both mappings, unsupported identifiers, and arbitrary URL non-reflection/rejection.

## Dependencies

NIY-010.

## Out of scope

- Verifying Shin Kong's direct progress-query route or refresh cadence.
- Hospital requests, scraping, polling, endpoint inference, freshness claims, UI redesign, live patient data, LINE calls, or deployment.
