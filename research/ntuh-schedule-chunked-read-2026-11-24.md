# Reading a large NTUH clinic schedule in parts on the Workers Free plan

Research completed 2026-11-24. Question, for [#188](https://github.com/KLTsai/next-is-you/issues/188): can the NTUH `RegDeptSchedule` page, measured at 6.9 million characters for 內科 (`MED`) on 2026-11-22 (over the reader's `MAX_SCHEDULE_BODY_CHARS` of 3.5 million), be read completely within the Workers Free plan limits by reading it in parts (streaming, chunking, or splitting across invocations, possibly in parallel)? The captain cares most about data completeness and accepts some loss of efficiency.

Scope and method: primary sources only, namely developers.cloudflare.com (pages read 2026-11-24 through their `index.md` form), pyodide.org, docs.python.org, RFC 9110, and the `workers-runtime-sdk` 1.9.1 copy vendored in `python_modules/workers/` (upstream [cloudflare/workers-py](https://github.com/cloudflare/workers-py)). It builds on [`workers-free-cpu-limit-2026-11-21.md`](workers-free-cpu-limit-2026-11-21.md) and [`ci-gates-and-cloudflare-usage-2026-11-24.md`](ci-gates-and-cloudflare-usage-2026-11-24.md) and does not repeat their sources unless a claim depends on them. NTUH evidence comes only from captures already in `research/private/source-evidence/`; the live site was not contacted. Nothing was deployed and no Cloudflare API was called.

Labels: **Source** (what a primary source says), **Observed** (read from this repository or its captures), **Measured, fixture** (run on the captain's Mac in CPython 3 against the captured pages; not a Workers or Free-plan measurement), **Inference** (my reasoning), **Unverified** (no source settles it). This is supporting evidence for #188, not implementation authority; adopt anything from it through a GitHub issue first.

## Answer

- **Yes, a complete read is feasible on Free, but chunking alone does not make it fit.** Total CPU does not shrink when a page is read in parts; only the CPU per invocation does. The binding limits are, in order: **CPU per invocation** (10 ms, of which the Durable Object alarm's own overhead already takes 3 to 8 ms), then **memory** (128 MB per isolate; the current full-page parse peaks at about 110 MB of Python allocations for 內科 in CPython), and not subrequests (50 per invocation) or response size (no limit).
- **One HTTP response cannot be consumed across invocations.** Cloudflare binds streams and response bodies to the request context that created them. So "split one read across invocations" means either (a) several smaller GETs, one per invocation, or (b) one GET whose body is stored in Durable Object storage and parsed in later invocations.
- **Streaming is usable from a Python Worker.** `response.body` is a JavaScript `ReadableStream`, and the Python SDK itself iterates one with `async for` and `to_bytes()`. `HTMLParser.feed()` is incremental. On all three fixtures, feeding the page in 64 KiB chunks gives exactly the same clinics as one `feed`.
- **The cheapest large win is not chunking but what is parsed.** About 83 to 85% of each schedule page is per-card modal dialogs that the parser never uses, and about 78% of the 內科 page is white space. Dropping the modals before `HTMLParser` leaves the same 439 / 129 / 118 clinics and cuts the 內科 parse from about 155 ms to about 25 ms (fixture, CPython). A regex scan of the card fields finds all 439 cards in about 3 ms (fixture, CPython). Local workerd ran a related parser about 4 to 5 times slower than CPython in #170, so none of these CPython figures prove a fit.
- **For completeness, prefer one `showAll` GET over per-sub-department GETs.** One response is one consistent snapshot of every clinic. The captures show sub-department pages do not obviously add up to `showAll`: ophthalmology has a `一般眼科` page (02) plus seven more sub-department links, and the `showAll` page was larger than page 02; orthopedics lists a `不分科` (01) link that no card names. Per-session narrowing (`ampmCode` 1 or 2) has no evening option, so it could drop 夜間門診 clinics.
- **No sign of HTTP Range support.** No capture recorded response headers, and the page is a dynamic ASP.NET page behind an Imperva Incapsula script. RFC 9110 lets any server ignore `Range`. Do not plan on it.
- **Recommended shape, if one invocation does not fit after the parse is made cheaper:** read the `showAll` page in one Durable Object invocation without converting it to Python text, store the bytes in the Durable Object's SQLite storage, and let the existing alarm chain (ADR 0005) scan a bounded slice per step, one day block or a fixed byte window, carrying a small parser state between steps. Every step then has a CPU cost bounded by the slice, not by the page, so a page twice as large stays readable. The costs are latency (seconds, many alarm steps), more Durable Object requests and SQLite rows, and resumable state to get right. Whether the fetch step itself fits in 10 ms is the first thing to measure.

---

## 1. Free plan limits that apply

| Limit | Free value | What it means here | Source |
| --- | --- | --- | --- |
| CPU per HTTP request and per Cron Trigger | 10 ms | The Worker invocations | [Workers limits](https://developers.cloudflare.com/workers/platform/limits/) |
| CPU counts I/O wait? | No: "Waiting on network requests (such as fetch() calls, KV reads, or database queries) does not count toward CPU time." | Time waiting for NTUH's bytes is free; handling the bytes is not | [Workers limits](https://developers.cloudflare.com/workers/platform/limits/) |
| CPU per Durable Object invocation (request, RPC, alarm) | Stated inconsistently: the FAQ says Durable Objects "have the same per invocation CPU limits as any Workers do", then gives a 30 second default "per Durable Objects invocation (HTTP request, WebSocket message, or Alarm)"; the table has no plan split | Plan for 10 ms per alarm, as ADR 0005 and #188 already do | [DO limits](https://developers.cloudflare.com/durable-objects/platform/limits/) |
| Enforcement | "built-in flexibility" for infrequent overruns; termination when "consistently" over; outcome `exceededCpu` | An overrun is not certain to fail, but cannot be relied on | [Workers limits](https://developers.cloudflare.com/workers/platform/limits/), via the [2026-11-21 note](workers-free-cpu-limit-2026-11-21.md) |
| Memory per isolate | 128 MB; when exceeded the runtime "lets in-flight requests complete and creates a new isolate for subsequent requests" | Shared with the Pyodide runtime itself | [Workers limits](https://developers.cloudflare.com/workers/platform/limits/) |
| Memory error on stream reads | "Memory limit would be exceeded before EOF": "Trying to read a stream or buffer that would take you over the memory limit" | Buffering the whole body (`text()`) is where this can fire | [Errors](https://developers.cloudflare.com/workers/observability/errors/) |
| Subrequests per invocation | 50; "any request a Worker makes using the Fetch API or to Cloudflare services" | Ten sub-department GETs fit easily | [Workers limits](https://developers.cloudflare.com/workers/platform/limits/) |
| Simultaneous connections | "up to six connections simultaneously waiting for response headers" | Caps parallel GETs inside one invocation | [Workers limits](https://developers.cloudflare.com/workers/platform/limits/) |
| Response body size | "Cloudflare does not enforce response body size limits." No separate limit is given for a fetched response body | Size alone is not a platform limit; the 3.5 M cap is the project's own | [Workers limits](https://developers.cloudflare.com/workers/platform/limits/) |
| Wall time | Cron: 15 minutes; DO alarm handler: 15 minutes; queue consumer: 15 minutes | Waiting on a slow NTUH response is not the problem | [Workers limits](https://developers.cloudflare.com/workers/platform/limits/), [DO limits](https://developers.cloudflare.com/durable-objects/platform/limits/) |
| DO daily (Free) | 100,000 requests ("HTTP requests, RPC sessions, WebSocket messages, and alarm invocations"), 13,000 GB-s, 5 million SQLite rows read, 100,000 rows written, 5 GB stored | Budget for extra alarm steps and stored pages | [DO pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/) |
| DO SQLite value size | "Maximum string, `BLOB` or table row size" 8 MB | A 7.2 MB page fits in one row today, with little headroom; slices across rows avoid the cap | [DO limits](https://developers.cloudflare.com/durable-objects/platform/limits/) |
| I/O objects across invocations | "I/O objects (such as streams, request/response bodies, and others) created in the context of one request handler" cannot be used from another; "these objects are tied to the specific request they were created in" | A response stream cannot be paused in one alarm and resumed in the next | [Errors](https://developers.cloudflare.com/workers/observability/errors/) |

**Observed.** The current reader (`src/next_is_you/ntuh_reader.py`): `WorkersFetcher.__call__` does `str(await response.text())` (the whole body becomes one JavaScript string, then one Python `str`); `_fetch_schedule_rows` rejects a body over `MAX_SCHEDULE_BODY_CHARS = 3_500_000` as `schema_drift`; `parse_schedule` feeds the whole string to `_ScheduleCollector(HTMLParser)` in one call, and the collector keeps every text run in `self.text` so `_page_status` can scan `" ".join(...)` for challenge and denial markers. The scheduler tick runs in the `SystemSendGate` Durable Object alarm (ADR 0005), so the relevant budget is a Durable Object alarm invocation.

## 2. Streaming a response body, from Python

**Source** ([Streams](https://developers.cloudflare.com/workers/runtime-apis/streams/)): "Use the Streams API to avoid buffering large requests or responses in memory." "This enables you to parse extremely large request or response bodies within a Worker's 128 MB memory limit." "This is faster than buffering the entire payload into memory."

**Source** ([ReadableStreamDefaultReader](https://developers.cloudflare.com/workers/runtime-apis/streams/readablestreamdefaultreader/)): `read()` is "A promise that returns the next available chunk of data being passed through the reader queue"; `cancel()` "Cancels the stream", and unread data is lost.

**Source** (Python SDK, vendored `python_modules/workers/response.py` line 29): `FetchResponse.body` "Returns the body as a JavaScript ReadableStream from the JavaScript Response instance." `python_modules/workers/asgi.py` lines 212 to 217 iterate a request body stream in Python with `async for data in req.body:` and convert each chunk with `data.to_bytes()`.

**Source** ([Pyodide type conversions](https://pyodide.org/en/stable/usage/type-conversions.html)): a proxied JavaScript object supports `aiter(proxy)` (`x[Symbol.asyncIterator]()`) and `anext(proxy)`; "JavaScript ArrayBuffer and TypedArray objects are proxied into Python". ([Pyodide FFI API](https://pyodide.org/en/stable/usage/api/python-api/ffi.html#pyodide.ffi.JsBuffer.to_bytes)): `JsBuffer.to_bytes` "Copies the data once."

**Source** ([html.parser](https://docs.python.org/3/library/html.parser.html)): `feed(data)`: "It is processed insofar as it consists of complete elements; incomplete data is buffered until more data is fed or close() is called."

**Not found.** Cloudflare's [Encoding](https://developers.cloudflare.com/workers/runtime-apis/encoding/) page documents only a UTF-8 `TextDecoder`, and no Workers page I read mentions `TextDecoderStream`. It is not needed: Python's incremental UTF-8 decoder (`codecs.getincrementaldecoder("utf-8")`) handles a multi-byte character split across chunks.

**Measured, fixture.** `_ScheduleCollector` fed in 64 KiB slices of the decoded text produced exactly the same rows as a single `feed` on all three captures (內科 439, 骨科 129, 眼科 sub 02 118).

**Inference.** A streamed read in Python is: `async for chunk in response.body` (or a `getReader()` loop), `chunk.to_bytes()`, incremental UTF-8 decode, then either feed the parser or drop regions before feeding it. Streaming removes the two full-size copies (JavaScript string and Python `str`) and lets the reader keep only what it needs, so it is the fix for memory. It does **not** remove CPU: every byte still crosses the FFI once and is scanned at least once in the same invocation, plus a per-chunk await. Chunk size is chosen by the runtime, not documented, so the per-chunk overhead is **Unverified**.

## 3. Do Python Workers change these limits?

**Source.** No Cloudflare page gives Python Workers different CPU or memory limits ([How Python Workers work](https://developers.cloudflare.com/workers/languages/python/how-python-workers-work/)). Top-level imports run at deploy time and are snapshotted, so they are not per-request work (same page).

**Observed** (`docs/HTTPS-SERVICE.md`, #162 and #170). On Staging the Durable Object tick cost 3 to 8 ms of CPU per invocation before any hospital read. In local workerd a 52 KB detail-page parse cost about 3.0 to 3.8 ms, while CPython parsed the detail pages in 0.44 to 0.85 ms each.

**Inference.** Pyodide parsing was roughly 4 to 5 times slower than CPython in that one comparison. The budget left for the schedule work inside one alarm step is therefore about 2 to 7 ms of Pyodide CPU, which is on the order of 0.5 to 1.5 ms of CPython time. Every CPython figure in section 6 has to be read against that, and only a workerd or Staging measurement settles it.

## 4. Ways to split one read across invocations on Free

| Mechanism | Free availability and limits | Fit for a schedule read | Source |
| --- | --- | --- | --- |
| **Durable Object alarm chain** (already used, ADR 0005) | One alarm per object; handler can set the next; at-least-once with retries "starting at a 2 second delay"; each alarm is a DO request (100,000 a day) | Best fit. Each step does one bounded piece and sets the next alarm about a second out. Needs resumable state and must tolerate a repeated step | [Alarms](https://developers.cloudflare.com/durable-objects/api/alarms/), [DO pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/) |
| **RPC to other Durable Objects** (for example one reader object per department) | Each RPC session is its own DO request and invocation | Gives parallelism across objects, each with its own CPU accounting. Adds objects and coordination; total CPU grows | [DO pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/) |
| **Workflows** | Free: 10 ms CPU per step, 1,024 steps, 100 concurrent instances, 50 subrequests per request, step result at most 1 MiB, 100 MB persisted state per instance. Python entrypoints are supported with the `python_workflows` flag | Steps retry and persist results, which suits a resumable read. A step cannot return the raw 7 MB page (1 MiB cap); it would return parsed rows. A new deploy unit and binding for this project | [Workflows limits](https://developers.cloudflare.com/workflows/reference/limits/), [Python Workflows](https://developers.cloudflare.com/workflows/python/) |
| **Queues** | Has a Workers Free column: 10,000 operations a day, retention fixed at 24 hours. Message size 128 KB. Consumer CPU is given as 30 seconds by default with no plan split (the same ambiguity as Durable Objects) | Messages can carry a sub-department or a slice offset, not the page. Adds a producer and consumer | [Queues pricing](https://developers.cloudflare.com/queues/platform/pricing/), [Queues limits](https://developers.cloudflare.com/queues/platform/limits/) |
| **Service bindings / self-calls** | "A single request has a maximum of 32 Worker invocations"; each call "counts toward your subrequest limit"; "both Workers run on the same thread" by default. Whether the callee has its own 10 ms is not stated | Possible for a JavaScript extractor Worker (HTMLRewriter), at the cost of a second language. Each call is also a Worker request against the 100,000 a day | [Service bindings](https://developers.cloudflare.com/workers/runtime-apis/bindings/service-bindings/) |
| **Cron Triggers** | 10 ms CPU, 15 minutes wall, 5 per account | Not a splitting tool; already only a watchdog here | [Workers limits](https://developers.cloudflare.com/workers/platform/limits/) |

**Inference, on parallelism.** Parallel invocations shorten wall time; they do not lower CPU per invocation or in total. Within one Durable Object there is one thread, so parallel `fetch()` calls overlap waiting, not parsing. Because the captain ranks completeness over speed, sequential alarm steps on the existing object are the simplest path; parallel objects or Workflows are only worth it if the picker's latency becomes the problem.

## 5. What the NTUH captures say about narrowing a read

All **Observed** from `research/private/source-evidence/` (no live request).

**Range requests.** No capture recorded response headers. The capture scripts (`raw/ntuh-2026-11-20/scripts/req.sh`, `raw/ntuh-2026-11-23/scripts/capture.py`) save bodies only, and the request logs (`reqlog3.txt` and the other `reqlog.txt` files) record status and byte counts only. So there is no `Accept-Ranges` evidence either way. The page embeds an obfuscated script that sets `incap_ses` digest cookies (an Imperva Incapsula front end), and the page itself is generated per request. **Source** ([RFC 9110 section 14.2](https://www.rfc-editor.org/rfc/rfc9110#section-14.2)): "A server MAY ignore the Range header field." **Inference:** even if honored, each range would make the server render the whole page again. Range is not a basis for a design; testing it would need a deliberate, owner-approved request.

**Query and form parameters on the `showAll` page (內科, 2026-11-22).**

- Sub-department links, GET: `RegDeptSchedule?vHospCode=T0&showBlock=A&vDeptCode=MED&ampmCode=A&realSubDeptCode=NN` for NN = 02 to 11 (一般內科, 心臟血管科, 胃腸肝膽科, 腎臟科, 胸腔科, 感染科, 血液腫瘤科, 代謝內分泌科, 免疫風濕過敏科, 整合醫學科). These ten names are exactly the ten sub-department names on the page's 439 cards (`sub-spec` text before `|`), split 87 / 85 / 64 / 59 / 51 / 26 / 24 / 23 / 18 / 2. The largest sub-department holds about 20% of the cards.
- An advanced-search form `RegDeptScheduleForm` (POST, with `__RequestVerificationToken`) has hidden fields `vHospCode`, `showBlock`, `vDeptCode`, `realSubDeptCode=showAll`, `ampmCode=A`, `clinicQuota=All`. Its buttons set `ampmCode` to `A` (全天門診), `1` (上午門診) or `2` (下午門診), and `clinicQuota` to `All`, `NotFirst` or `First`. There is **no evening option**.
- The doctor and clinic-name dropdowns call `scheduleFilterBySpecificName(...)` and similar functions in `regDeptAndFormUI.js`, which was not captured; they are probably client-side filters over the full page (**Unverified**).
- No date, week or day parameter appears. `showBlock` has A, B, E and F tabs; only A (the active 14-day window) is understood.

**Other captures.** 眼科: page 02 (`一般眼科`, 118 cards) links `showAll` (門診全覽) and sub-departments 03 to 09 (青光眼科, 角膜科, 視網膜科, and others); page 01 returned the `查無此醫師` placeholder (37 K characters). The earlier evidence note records `showAll` at 2.2 MB against 1.9 MB for page 02, so 眼科 clinics exist outside page 02. 骨科 `showAll` links 01 (不分科), 02, 03, 04, 07, 10 and 11, while its 129 cards name only six sub-departments and never 不分科. All captures have 0 夜間門診 sessions.

**Inference, completeness of per-sub-department reads.**

- Whether the union of sub-department pages equals `showAll` is **Unverified**. A card may appear on two pages (duplicates are harmless if deduplicated on `(date, session, room, doctor)`). A clinic filed under a sub-department with no link, or under a link that renders the placeholder, would be missed silently. The 骨科 不分科 link and the 眼科 page-02-versus-`showAll` difference are reasons to doubt that the union is complete.
- `ampmCode=1/2` might halve a page, but it is only seen as a POST form value and a value embedded in GET links (`ampmCode=A`); whether a GET with `1` is honored is **Unverified**, and it offers no evening value. It must not replace `A` while the reader supports evening sessions (#183).
- Several GETs per read also multiply requests to NTUH. The owner approved scheduled reads at a stated cadence for progress pages (`docs/NTUH-READER.md`); ten schedule GETs per 內科 read is a change the captain should weigh against the source access rules (`docs/ADDING-A-HOSPITAL.md`).

## 6. Fixture measurements (CPython, captain's Mac, not Free-plan)

**Measured, fixture.** Median of five runs, using the repository's `parse_schedule` and `_ScheduleCollector` unchanged; "same rows" compares the full row tuples with the unmodified parse.

| Page | Characters | Full parse | Modals | After dropping modals | + collapsing white space | Regex card scan | Per-day pieces |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 內科 `MED` showAll, 2026-11-22 | 6,904,737 | 152 to 155 ms, 439 rows | 439 modals, 85% of characters, about 13 K characters each | 951,936 chars; strip 12 ms; parse 25 ms; same rows | 341,728 chars; parse 20 ms; same rows | 439 cards in 3.2 ms | 10 day blocks of 0.60 to 0.78 M chars; parsed separately they give the same 439 rows; slowest 17 ms |
| 骨科 `ORTH` showAll, 2026-11-23 | 2,049,780 | 47 ms, 129 rows | 83% | 320,096 chars; strip 3.5 ms; parse 9 ms; same rows | 122,812 chars; parse 7 ms; same rows | 129 cards in 1.0 ms | 11 blocks; same rows; slowest 4.5 ms |
| 眼科 `OPH` sub 02, 2026-11-03 | 1,883,149 | 44 to 48 ms, 118 rows | 82% | 303,970 chars; strip 3.3 ms; parse 8.5 ms; same rows | 115,636 chars; parse 7 ms; same rows | 118 cards in 0.9 ms | 11 blocks; same rows; slowest 5.3 ms |

Further fixture facts:

- Collapsing white space alone (without dropping modals) leaves 1.66 M characters for 內科 and only cuts the parse from 155 to 110 ms, because the cost is in tags, not spaces.
- UTF-8 decoding the 7.2 MB 內科 body costs about 1.5 ms in CPython.
- **Memory:** decoding plus `parse_schedule` on the 內科 page peaked at about 110 MB of Python allocations (`tracemalloc`), and about 32 MB for 骨科. The decoded 內科 `str` alone is about 14 MB because the page contains CJK characters. The collector's `self.text` list holds every text run of the page, most of it white space between tags, and is then joined into one string.
- The modal strip used plain `str.find` on `<div class="modal modal-lg fade"` and ended each modal at the next card wrapper, session header or day block. It is a sketch, not a proposal for the exact markers.

**Inference.**

- At the observed 4 to 5 times Pyodide slowdown, the full 內科 parse would be several hundred ms, far over 10 ms, and even the modal-stripped parse (about 25 ms CPython) would be around 100 ms. Day blocks alone (17 ms CPython at worst) would still be about 70 ms each. A per-step budget of a few ms means **either a much cheaper extractor or much smaller slices**, or both.
- A regex scan over the card markers is about 50 times cheaper than `HTMLParser` on the same page in CPython. It would need the same fail-closed checks (challenge and denial markers, a day and session for every card, card count against the number of `doctor-tag` buttons) to keep completeness.
- In the Worker, 110 MB of Python allocations on top of the Pyodide runtime, the JavaScript string copy and any other object in the isolate would very likely exceed 128 MB. **The 3.5 M cap is today also a memory guard, and memory, not only CPU, rules out the current whole-page approach for 內科.**

## 7. What binds, and the approaches compared

**What binds (Inference from sections 1 to 6).**

1. **CPU per invocation** binds first, everywhere. Network wait is free; FFI copying, decoding, scanning and parsing are not. The alarm's own 3 to 8 ms leaves little.
2. **Memory** binds for whole-page reads of 內科-sized pages. Streaming with early discard fixes it.
3. **Subrequests** (50) and **connections** (6) do not bind for any plan considered here. **Response size** is not limited by the platform.
4. **Daily quotas** (100,000 DO requests, 100,000 SQLite rows written) do not bind for once-a-day rechecks and occasional picker reads, even at tens of steps per read. They are shared with the scheduler, so #192's budget should count the steps.

**Approaches, ranked by completeness.**

| Approach | Completeness | Per-invocation CPU | Memory | Other trade-offs |
| --- | --- | --- | --- | --- |
| **A. One `showAll` GET, streamed, with modals and white space dropped on the fly and a cheap extractor, all in one invocation** | Full: one consistent snapshot, same rows as today on all fixtures | Lowest total; fits only if FFI copying plus scanning 7.2 MB stays under the remaining budget (**Unverified**, likely tight for 內科) | Small: keeps only cards | Simplest; no new state. Fails as a whole if it does not fit, and the size grows with the department |
| **B. One `showAll` GET stored as bytes in DO SQLite, then scanned in bounded slices over successive alarm steps** | Full: one snapshot; slices carry parser state, and the fixtures show day blocks parse independently with identical rows | Bounded by slice size, independent of page size; the fetch-and-store step must be measured | Small per step | Latency of many steps (seconds to a minute) for the picker; resumable state, at-least-once alarm repeats and a stale or partial stored page must be handled; storage rows and up to 8 MB per value; the stored copy is source HTML of a public page and should be deleted after the read |
| **C. One GET per sub-department, one per alarm step** | **At risk:** union with `showAll` unproven (眼科 and 骨科 evidence above); pages fetched at different moments | Smaller (內科 largest about 20% of `showAll`), still over budget with `HTMLParser` | Smaller | Up to 10 times more requests to NTUH per read; needs the sub-department list (read from the page's own links) and a fallback when a link renders the placeholder |
| **D. Narrow by `ampmCode` 1 and 2** | **At risk:** no evening option; GET support unverified | About half | About half | Doubles requests; conflicts with #183 evening support |
| **E. HTTP Range** | Unknown | n/a | n/a | No evidence the server supports it; RFC 9110 allows ignoring it |
| **F. Parallel reader objects or Workflows steps over B or C** | Same as the approach underneath | Same per step | Same | Shorter wall time, more moving parts; useful only if the picker's wait matters |

**How to keep B complete (Inference).**

- Fail closed on the whole read: if any slice fails or the stored page is missing, the read is unreadable and the draft stays unchanged (#188's failure criterion). Never publish partial rows.
- Verify that every `doctor-tag` button produced a row (439 buttons and 442 `doctor-tag` class occurrences in the 內科 page, so the check must count buttons, not the class string), that the scan ended at the page's end marker, and that challenge and denial markers were checked over the whole page, slice by slice.
- Cut slices at a safe boundary (a day block or card wrapper) found within a bounded window, or persist the incremental scanner's carry (current date and session, an incomplete tag tail, and the partial card).
- Tie stored bytes and progress to one read id and one fetch time; a repeated alarm resumes or restarts, never mixes two fetches.

**Inference, cost of the fetch step in B.** A body taken with `await response.arrayBuffer()` stays in JavaScript; Python holds a proxy. If the Durable Object's SQL API accepts that buffer (or slices of it) as a BLOB parameter, the bytes never enter the Python heap and the step's CPU is the runtime's copy plus the storage write. Whether the Python-to-JavaScript storage call passes the buffer without a copy, and how much CPU writing 7 MB to SQLite costs, are **Unverified**.

## Recommendation

1. **Measure before choosing, in local workerd and then Staging** (#188 already requires the Staging figure). In one Durable Object alarm, separately: (a) `response.text()` plus conversion to Python for the 內科 fixture served locally; (b) streaming the same body with `to_bytes()` and discarding it; (c) (b) plus the modal and white-space drop and a regex card scan; (d) `arrayBuffer()` stored to SQLite without entering Python. These four numbers decide between approaches A and B.
2. **Whatever the shape, change what is parsed:** drop the modals and stop keeping every text run. That fixes memory and removes most of the work, keeps the same rows on all fixtures, and is a prerequisite for both A and B.
3. **If (c) fits in the alarm budget with margin, use A** and raise or remove the character cap in favour of a streamed byte cap and a memory-safe reader.
4. **If not, use B** on the existing alarm chain (ADR 0005 already names "each alarm does one bounded step and then schedules the next about a second later" as the path for more work), with fixed-size or day-block slices and the completeness checks above.
5. **Avoid C and D as the primary read** while completeness ranks first. If they are ever needed, prove first, from one owner-approved capture of every sub-department page next to `showAll` on the same day, that the union matches card for card.
6. Parallelism (F) only if the picker's wait time becomes the problem.

## Open questions that need a measurement

- CPU of `response.text()` and of converting a 6.9 M character JavaScript string to Python, in workerd and on Staging.
- CPU per streamed chunk (`async for` plus `to_bytes()`), and the chunk sizes the runtime delivers for a 7 MB fetched body.
- Pyodide's slowdown for `re` scanning and `str.find` compared with CPython (the 4 to 5 times figure comes from `HTMLParser` only).
- Peak isolate memory of the current reader on the 內科 page in workerd, and the Python Worker's baseline memory with this project's snapshot. Whether several Durable Objects share one isolate's 128 MB.
- Whether a Python Durable Object can pass a JavaScript `ArrayBuffer` to `ctx.storage.sql.exec` as a BLOB without copying through Python, and the CPU of writing and reading 7 MB in SQLite storage.
- Whether NTUH honors `Range`, `ampmCode=1/2` on GET, and whether sub-department pages add up to `showAll` (each needs a deliberate, owner-approved request; none was made).
- Whether the Free plan's Durable Object and queue consumer CPU limit is 10 ms or the documented 30 second default (the docs disagree), and the size of the "built-in flexibility".
- Whether the Workers runtime requests and transparently decompresses a gzip response from NTUH, and whether that decompression is counted as the invocation's CPU (the captures were taken without `Accept-Encoding`, so their byte counts are uncompressed).

## Sources

All accessed 2026-11-24.

- Cloudflare Workers: [Limits](https://developers.cloudflare.com/workers/platform/limits/), [Errors](https://developers.cloudflare.com/workers/observability/errors/), [Streams](https://developers.cloudflare.com/workers/runtime-apis/streams/), [ReadableStreamDefaultReader](https://developers.cloudflare.com/workers/runtime-apis/streams/readablestreamdefaultreader/), [TransformStream](https://developers.cloudflare.com/workers/runtime-apis/streams/transformstream/), [Encoding](https://developers.cloudflare.com/workers/runtime-apis/encoding/), [Service bindings](https://developers.cloudflare.com/workers/runtime-apis/bindings/service-bindings/), [Python FFI](https://developers.cloudflare.com/workers/languages/python/ffi/), [How Python Workers work](https://developers.cloudflare.com/workers/languages/python/how-python-workers-work/).
- Durable Objects: [Limits](https://developers.cloudflare.com/durable-objects/platform/limits/), [Pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/), [Alarms](https://developers.cloudflare.com/durable-objects/api/alarms/).
- Workflows: [Limits](https://developers.cloudflare.com/workflows/reference/limits/), [Python Workflows](https://developers.cloudflare.com/workflows/python/). Queues: [Pricing](https://developers.cloudflare.com/queues/platform/pricing/), [Limits](https://developers.cloudflare.com/queues/platform/limits/).
- Pyodide: [Type conversions](https://pyodide.org/en/stable/usage/type-conversions.html), [FFI API](https://pyodide.org/en/stable/usage/api/python-api/ffi.html). Python: [html.parser](https://docs.python.org/3/library/html.parser.html). HTTP: [RFC 9110 section 14, Range requests](https://www.rfc-editor.org/rfc/rfc9110#section-14).
- Vendored `workers-runtime-sdk` 1.9.1: `python_modules/workers/response.py`, `python_modules/workers/asgi.py` (upstream [cloudflare/workers-py](https://github.com/cloudflare/workers-py)).
- Project: [`src/next_is_you/ntuh_reader.py`](../src/next_is_you/ntuh_reader.py), [`docs/NTUH-READER.md`](../docs/NTUH-READER.md), [`docs/HTTPS-SERVICE.md`](../docs/HTTPS-SERVICE.md), [`docs/adr/0005-scheduler-tick-runs-from-a-durable-object-alarm.md`](../docs/adr/0005-scheduler-tick-runs-from-a-durable-object-alarm.md), [`wrangler.jsonc`](../wrangler.jsonc), `research/private/source-evidence/ntuh-schedule-2026-11-03.md` and the `raw/` captures and request logs named above.
