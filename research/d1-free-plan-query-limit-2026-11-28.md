# D1 queries per invocation on the Workers Free plan

Research for issue #278 (one reminder tick can exceed D1's per-invocation query limit).
Researched 2026-11-28. Sources are Cloudflare primary documentation only. Quotes are verbatim from the fetched pages; the `dateModified` shown is from each page's structured data.

## Short answer

1. The D1 platform limits page states the Free limit directly as 50 queries per Worker invocation (1000 on Paid). The Workers limits page separately lists 50 Free "subrequests per invocation" and 1,000 Free "subrequests to internal services". The two pages are not reconciled for D1 anywhere in the docs we could read.
2. A `db.batch()` call counts as a single query against the per-invocation limit, per the D1 limits page.
3. Nothing in the official pages says whether a Durable Object invocation gets its own budget, whether Worker-to-Durable-Object calls count against the Worker's, or whether Python Workers differ. These stay unconfirmed.

## Claims, with sources

### D1 limit is 50 queries per invocation on Free

- Source: https://developers.cloudflare.com/d1/platform/limits/ (dateModified 2026-11-20)
- Table row: "Queries per Worker invocation (read subrequest limits) | 1000 (Workers Paid) / 50 (Free)"
- Error text on the same page: "issuing 2,000 individual queries in one invocation fails with `Too many API requests by single Worker invocation`."

### Workers subrequest limits (the other number)

- Source: https://developers.cloudflare.com/workers/platform/limits/ (dateModified 2026-11-25)
- Definition: "A subrequest is any request a Worker makes using the Fetch API or to Cloudflare services like R2, KV, or D1."
- Table row: "Subrequests per invocation | 50 | 10,000 (up to 10M)" (Free | Paid)
- Table row: "Subrequests to internal services | 1,000 | Matches configured limit (default 10,000)" (Free | Paid)
- Account plan table row: "Subrequests | 50/request | 10,000/request"
- The page does not define or list which services count as "internal services". D1 is named only in the subrequest definition above.

### Where the two pages disagree or leave a gap

- The Workers page defines D1 calls as subrequests and lists a 1,000 Free limit for "internal services". The D1 page gives 50 Free for queries per invocation and labels the row "(read subrequest limits)". The D1 page does not say which Workers row it refers to, and the Workers page does not say D1 is an "internal service".
- Reading the D1 page as authoritative for D1 (it is the product-specific page and names the exact error) gives 50. Whether the platform actually enforces 50 or 1,000 for D1 on Free is not settled by the docs text and needs a live test (see Unconfirmed).
- No changelog entry explains the "internal services" row (see Changelogs).

### Does batch() count as one query?

- Source: https://developers.cloudflare.com/d1/platform/limits/ (dateModified 2026-11-20)
- "The Queries per Worker invocation limit is an exception: a `db.batch()` call counts as a single query against it, not one query per statement."
- "For example, a batch containing 2,000 statements executes in a single Worker invocation, while issuing 2,000 individual queries in one invocation fails with `Too many API requests by single Worker invocation`."
- Other per-query limits still apply per statement: "Limits for individual queries (listed above) apply to each individual statement contained within a batch statement."
- Batch semantics: https://developers.cloudflare.com/d1/worker-api/d1-database/ (dateModified 2026-06-22): "Batched statements are SQL transactions." and "If a statement in the sequence fails, then an error is returned for that specific statement, and it aborts or rolls back the entire sequence." That page has no sentence about counting against invocation limits.

### Durable Object invocation budget, and Worker-to-DO calls

Not stated by any page read.

- https://developers.cloudflare.com/workers/platform/limits/ : no text on whether subrequests made by a Durable Object or by a called Worker count against the caller. The only related sentences are about connections: "The runtime measures simultaneous open connections from the top-level request." and "Workers triggered via Service bindings share the same connection limit."
- https://developers.cloudflare.com/durable-objects/platform/limits/ (dateModified 2026-11-13): does not use the term subrequest and does not mention D1. It says "Durable Objects are a special kind of Worker", so Workers limits plausibly apply, but it does not state a per-invocation subrequest budget. On CPU: "Each incoming HTTP request or WebSocket message resets the remaining available CPU time to 30 seconds."
- https://developers.cloudflare.com/durable-objects/platform/pricing/ (dateModified 2026-11-13): billing only. "Every RPC method call on a Durable Objects stub is its own RPC session and therefore a single billed request." This is billing of requests, not the subrequest budget. Free plan request cap there: "100,000 / day".
- Conclusion: the docs do not say that a Durable Object's own invocation has a fresh D1 budget, and do not say whether the stub call from a Worker counts as a subrequest toward the Worker's limit. Unconfirmed.

### Python Workers

- https://developers.cloudflare.com/workers/languages/python/ (dateModified 2026-09-17): no text about limits, subrequests, or differences from JavaScript Workers. D1 and Durable Objects appear only in a list of bindings.
- https://developers.cloudflare.com/workers/platform/limits/ does not mention Python Workers.
- No documented difference found. Absence of text is not confirmation that behavior is identical.

### Changelogs

- https://developers.cloudflare.com/workers/platform/changelog/ : no entry on subrequest limits, the Free 1,000 internal-services limit, D1 per-invocation queries, Durable Object subrequests, or Python limits.
- https://developers.cloudflare.com/d1/platform/changelog/ : no entry on queries per invocation, subrequest limits, or batch counting.
- https://developers.cloudflare.com/d1/platform/pricing/ (dateModified 2026-10-30): no text on per-invocation queries. It covers daily rows read and written only.

### Cloudflare docs source repository

- The cloudflare/cloudflare-docs source for `src/content/docs/workers/platform/limits.mdx` was read through the repository's rendered page. It carried the same table rows and sentences as the published page, with no extra text on internal services, Durable Objects, or Python. The D1 and Durable Objects limits sources were read only through the published pages, so repository history and inline comments were not checked.

## Unconfirmed (needs a live test on a Free account)

1. Whether D1 on Free is actually cut off at 50 queries or at 1,000 (the two pages differ). Test: a Worker issuing N sequential `prepare().run()` calls; find where `Too many API requests by single Worker invocation` appears.
2. Whether `batch()` of many statements really counts as 1 in practice (documented, not tested here).
3. Whether a Durable Object invocation started by a Worker has its own D1 budget, and whether the Worker's stub call counts toward the Worker's limit. Test: a Worker runs 49 D1 queries plus a DO call that itself runs 50, and see which call fails.
4. Whether a Python Worker has the same limits. Test: repeat 1 from a Python Worker.
5. What "internal services" means in the Workers limits table.

## Live test on a Free account (2026-11-28, local integration against a real Cloudflare account)

Method: a temporary JavaScript Worker with a Durable Object (SQLite class) and an empty D1 database, run on an account with no paid subscription (the subscriptions API returned an empty list). Each probe ran N sequential `SELECT ?` queries inside one request. Both temporary resources were deleted afterward. No repository, staging, or production resource was touched.

| Probe | Result |
|---|---|
| Worker, 51 and 200 sequential queries | all succeeded |
| Worker, 1,001 sequential queries | 1,000 succeeded, then `Too many API requests by single Worker invocation` |
| Worker, one `db.batch()` of 1,001 statements | succeeded, counted as one query |
| Durable Object, 200 sequential queries | all succeeded |
| Durable Object, 1,001 sequential queries | 1,000 succeeded, then the same error |
| Worker making 1,001 Durable Object calls, one query each | 1,000 succeeded, then the same error |
| Worker 700 queries plus Durable Object 700 queries, one request | both succeeded |

Conclusion: on this Free account the effective limit was 1,000 D1 queries per invocation, not 50. The Workers limits page figure (1,000 internal subrequests) matched; the D1 limits page figure (50) did not. A Durable Object invocation has its own budget of 1,000.

Python Workers were measured separately, see the next section.

## Python Worker result (2026-11-28, local integration against a real Cloudflare account)

Method: a temporary Python Worker (`compatibility_date` 2026-09-25, `python_workers` flag, vendored with `uv run pywrangler sync`, deployed with `pywrangler deploy`) and an empty D1 database, on the same Free account. Both were deleted afterward and no longer list. No repository, staging, or production resource was touched. The first deployment attempts failed because the hand-written project did not run `pywrangler sync`, and `pywrangler` needs uv 0.13.4 or newer.

| Probe | Result |
|---|---|
| 51 and 200 sequential `SELECT ?` | all succeeded |
| 1,001 sequential `SELECT ?` | 1,000 succeeded, then `Too many API requests by single Worker invocation` |
| One `db.batch()` of 1,001 statements | succeeded (the very first cold request returned Cloudflare error 1102; the retry and smaller batches succeeded) |

Conclusion: the Python runtime has the same 1,000 per invocation limit as the JavaScript Worker, and a batch counts as one query.
