# Durable Object concurrency, alarms, and Free plan limits for a large schedule read

Researched 2026-11-24. Sources: developers.cloudflare.com and the workerd source (cloudflare/workerd `main` at commit 583a3b0275d574421f5f51ce0f6644cf26e92cf7). Every claim cites its URL. Where the docs say nothing, this file says so. Do not read silence as a guarantee.

Notes on the workerd source: workerd is the open-source runtime. Its local alarm scheduler (`src/workerd/server/alarm-scheduler.c++`) shares its retry constants with the production `WorkerInterface` (`ALARM_RETRY_*` in `worker-interface.h`). Production Cloudflare runs its own alarm manager on top of these, so treat source-level details as strong evidence of how it works, not as a documented contract.

## 1. Durable Object concurrency

- An object runs one thread with cooperative multitasking: "Durable Objects are single-threaded and cooperatively multi-tasked, just like code running in a web browser." - https://developers.cloudflare.com/durable-objects/concepts/what-are-durable-objects/
- Input gates: "Input gates block new events (incoming requests, fetch responses) while synchronous JavaScript execution is in progress." - https://developers.cloudflare.com/durable-objects/best-practices/rules-of-durable-objects/
- Output gates: "Output gates hold outgoing network messages (responses, fetch requests) until pending storage writes complete." - same URL.
- In workerd, the input gate is held while storage operations are outstanding. It blocks "all incoming I/O events of any type ... including ... responses to subrequests, timer events, input streams". The output gate is held while confirmed writes are still being flushed. - https://github.com/cloudflare/workerd/blob/main/src/workerd/io/io-gate.h (header comment, lines 6-21)
- **Awaiting a network fetch lets other events interleave:** "Awaiting async operations like fetch() or KV storage methods opens the input gate, allowing other requests to interleave." Also: "Non-storage I/O like fetch() or writing to R2 allows other requests to interleave, which can cause race conditions". - https://developers.cloudflare.com/durable-objects/best-practices/rules-of-durable-objects/
- **Does a long alarm or fetch block other requests?**
  - While the alarm handler is *awaiting* the network (headers, or each chunk of a streamed body), other requests and RPCs to the same object can run. It does not block them.
  - While the handler runs *synchronous* CPU work (for example parsing or hashing a 7 MB buffer), nothing else in that object runs. The input gate blocks new events. Other objects that share the isolate are also delayed: "Only one thread can execute JavaScript in that isolate at a time, so synchronous work in one object can delay others sharing it." - https://developers.cloudflare.com/durable-objects/concepts/what-are-durable-objects/
  - `blockConcurrencyWhile()` "guarantees that no other events are processed until the provided callback completes". Wrapping the fetch in it would block all other requests for the full network time. The docs say to reserve it "for initialization and migrations, not regular request handling". - https://developers.cloudflare.com/durable-objects/best-practices/rules-of-durable-objects/
  - Requests can pile up: "too many requests being queued due to slow or excessive I/O" is listed as a source of infrastructure exceptions. - https://developers.cloudflare.com/durable-objects/best-practices/error-handling/
- Alarm dedup in workerd: "An alarm must not be canceled once it is running, UNLESS the whole actor is shut down." Also: "If we are asked to schedule an alarm while one is running, we wait for the running alarm to" finish. - https://github.com/cloudflare/workerd/blob/main/src/workerd/io/worker-entrypoint.c++ (`runAlarmImpl`, around lines 987-994)

Design implication: interleaving during `await` means monitoring requests can run in the middle of a schedule read in the same object. Any in-memory "read in progress" state must tolerate that. CPU-heavy parsing of the whole page in one synchronous block stalls the object.

## 2. Alarms

- One alarm per object: "Each Durable Object is able to schedule a single alarm at a time by calling `setAlarm()`." - https://developers.cloudflare.com/durable-objects/api/alarms/
- Overwrite: "If you call `setAlarm` when there is already one scheduled, it will override the existing alarm." - same URL.
- Alarms do not repeat: "Alarms do not repeat automatically", so you call setAlarm() again for each run. Also: "In rare cases, alarms may fire more than once." - https://developers.cloudflare.com/durable-objects/best-practices/rules-of-durable-objects/
- At-least-once: "Alarms have guaranteed at-least-once execution and are retried automatically when the `alarm()` handler throws." - https://developers.cloudflare.com/durable-objects/api/alarms/
- Retry policy: exponential backoff starting at 2 seconds, up to 6 retries. `alarmInfo.retryCount` is "The number of times this alarm event has been retried." After the retries run out, the alarm does not run again until the next `setAlarm`. The docs recommend catching exceptions and scheduling a new alarm before returning. - https://developers.cloudflare.com/durable-objects/api/alarms/
- Source detail: `ALARM_RETRY_START_SECONDS = 2` and `ALARM_RETRY_MAX_TRIES = 6`. - https://github.com/cloudflare/workerd/blob/main/src/workerd/io/worker-interface.h (lines 153-154)
  - The delay is `2 << backoff` seconds (2, 4, 8, 16, 32, 64 s) plus up to 25% jitter (`RETRY_JITTER_FACTOR = 0.25`).
  - Only user-caused failures count toward the 6 (`retryCountsAgainstLimit`). Internal errors retry without counting, with backoff capped at `RETRY_BACKOFF_MAX = 9` (about 17 min).
  - If a new alarm was queued while the old one ran, the failed alarm is not retried. The queued one runs instead.
  - After the counted retries run out, the alarm is abandoned (`abandonAlarm`). An outcome of `ABORTED` is also abandoned, not retried.
  - Sources: https://github.com/cloudflare/workerd/blob/main/src/workerd/server/alarm-scheduler.h (lines 50-66) and https://github.com/cloudflare/workerd/blob/main/src/workerd/server/alarm-scheduler.c++ (lines 195-295)
- Wall time: an alarm handler is limited to 15 minutes. - https://developers.cloudflare.com/durable-objects/platform/limits/ and https://developers.cloudflare.com/workers/platform/limits/ (workerd also defaults to "15 minutes" when the alarm timeout is invalid: https://github.com/cloudflare/workerd/blob/main/src/workerd/io/worker-entrypoint.c++ around line 1057)
- **An alarm that exceeds CPU or memory limits:**
  - Docs: when the object exceeds its CPU or memory limits, the caller gets an infrastructure exception (with `.remote` set). - https://developers.cloudflare.com/durable-objects/best-practices/error-handling/
  - Docs: "If you consume more than 30 seconds of compute between incoming network requests, there is a heightened chance that the individual Durable Object is evicted and reset." - https://developers.cloudflare.com/durable-objects/platform/limits/ (footnote 4)
  - Source: when limits are exceeded, the object's whole IoContext aborts. `IoContext` calls `abortWhen(makeLimitsPromise())` "to abort when limits expire". "For actors, there is one IoContext per actor, and each incoming request to the actor creates a new IncomingRequest." So a CPU or memory overrun during the alarm aborts every in-flight request to that object, not only the alarm. - https://github.com/cloudflare/workerd/blob/main/src/workerd/io/io-context.c++ (lines 251-296) and https://github.com/cloudflare/workerd/blob/main/src/workerd/io/io-context.h (lines 1625-1635)
  - Is the alarm retried after an overrun? The docs do not say. In the source, a limit overrun becomes the alarm's event outcome (for example `EXCEEDED_CPU`). It goes through the same `retry`/`retryCountsAgainstLimit` path as a thrown exception. The hibernate handler uses the same "Classifies a failed handler run like a failed alarm" logic (https://github.com/cloudflare/workerd/blob/main/src/workerd/io/worker.c++ around line 5103). Assume it is retried, up to 6 counted times. A read that overruns deterministically will burn every retry and then be abandoned. Not documented: plan for it, do not rely on it.

## 3. Other in-flight work when one request exceeds CPU (1102) or memory

- Error 1102: "Worker exceeded [CPU time limit]." Exceeding memory is a separate metric: "Worker exceeded the memory limit during execution." - https://developers.cloudflare.com/workers/observability/errors/
- Buffering a body that would exceed memory throws "Memory limit would be exceeded before EOF". - https://developers.cloudflare.com/workers/observability/errors/ and https://developers.cloudflare.com/workers/platform/limits/
- Memory is per isolate: "This limit is per-isolate, not per-invocation. A single isolate can handle many concurrent requests." The limit is 128 MB "including the JavaScript heap and WebAssembly allocations". - https://developers.cloudflare.com/workers/platform/limits/
  - Python Workers run on Pyodide (WebAssembly), so the interpreter heap counts toward the same 128 MB. That is an inference from "WebAssembly allocations".
- When memory is exceeded (stateless Workers): "When an isolate exceeds 128 MB, the Workers runtime lets in-flight requests complete" "and creates a new isolate for subsequent requests." "During extremely high load, the runtime may cancel some incoming requests to maintain stability." - https://developers.cloudflare.com/workers/platform/limits/
- Durable Objects: "Memory is measured per isolate (which can host multiple Durable Objects), not per object." "A given instance of a Durable Object may share global memory with other instances defined in the same Worker code." - https://developers.cloudflare.com/durable-objects/reference/in-memory-state/
  - So a 6.9 MB body held in several copies (raw bytes, decoded str, Python and JS copies across the FFI) adds to memory pressure for every object in that isolate.
- Same Durable Object: the whole per-object IoContext aborts on a limit overrun (see section 2). Every in-flight request to that object fails. Callers get an exception, and "Many exceptions leave the DurableObjectStub in a "broken" state", "such that all attempts to send additional requests will just fail immediately with the original exception". Create a new stub after such an error. - https://developers.cloudflare.com/durable-objects/best-practices/error-handling/
- For stateless (non-DO) requests, the docs do not say whether a CPU overrun in one request affects other requests in the same isolate. In workerd each stateless request has its own IoContext ("For stateless requests, there is only ever one IncomingRequest per IoContext"), so the abort is scoped to that request. - https://github.com/cloudflare/workerd/blob/main/src/workerd/io/io-context.h (lines 1628-1630)

## 4. Durable Object SQLite storage on the Free plan

- Free plan: only SQLite-backed Durable Objects. - https://developers.cloudflare.com/durable-objects/platform/limits/
- Max string, BLOB, or table row size: **8 MB**. Key-value API: "Key and value combined cannot exceed 8 MB". - same URL.
  - A 6.9 MB page fits in one row, with only about 1.1 MB of headroom. Chunked rows (for example 1 MB each) are safer if the page grows.
- Max SQL statement length: 100 KB. Bound parameters per query: 100. Columns per table: 100. - same URL.
  - Pass the bytes as a bound parameter, never inlined into SQL text.
- Storage per account on Free: 5 GB total. - same URL and https://developers.cloudflare.com/durable-objects/platform/pricing/
- Storage per object: the limits table says 10 GB with no plan split, but the FAQ on the same page says "10 GB on Workers Paid, or 1 GB on the Free plan". Use 1 GB as the Free plan bound. - https://developers.cloudflare.com/durable-objects/platform/limits/
- Free plan daily limits: rows read 5 million/day, rows written 100,000/day, reset at 00:00 UTC. "further operations of that type will fail with an error" once exceeded. - https://developers.cloudflare.com/durable-objects/platform/pricing/
- How rows are counted: by row, not by bytes. `rowsWritten` on the cursor is the billed value. "When writing data, every row update of an index counts as an additional row." - https://developers.cloudflare.com/durable-objects/api/sqlite-storage-api/
  - Each `setAlarm()` is billed as one row written. Deletes count as rows written. - https://developers.cloudflare.com/durable-objects/platform/pricing/
- **Cost of ~7 MB per day per department** (derived from the rules above):
  - One-row write: 1 row written, plus 1 per secondary index. Chunked at 1 MB: about 7 rows, plus index rows. Deleting yesterday's copy costs the same again.
  - For D departments, that is about 2 x 7 x D rows/day in the chunked, replace-daily case (for 30 departments, about 420 rows/day). This is far below the 100,000/day cap.
  - Storage: about 7 MB x D if replaced daily (30 departments is about 210 MB). That is well under 5 GB. Keeping history: 5 GB / 7 MB is about 730 department-days.
  - Bytes are not metered on Free, only rows and total stored data. On Paid, SQLite storage billing starts with a target date of January 7, 2026. - https://developers.cloudflare.com/durable-objects/platform/pricing/

## 5. Free plan daily limits a multi-step read would use

- Durable Objects on Free (https://developers.cloudflare.com/durable-objects/platform/pricing/):
  - Requests: 100,000/day.
  - Duration: 13,000 GB-s/day.
  - Rows read: 5M/day. Rows written: 100,000/day.
  - Stored data: 5 GB.
  - Reset at 00:00 UTC.
- What counts as a request: the Paid row says requests "Includes HTTP requests, RPC sessions, WebSocket messages, and alarm invocations". The Free row does not repeat this, so assume alarms count on Free too. Each RPC session is one request. - https://developers.cloudflare.com/durable-objects/platform/pricing/
- Duration: wall-clock time, and "Each Durable Object is billed for 128 MB of memory, regardless of actual usage". "Pending I/O operations keep an object in memory for up to 15 minutes each." Idle objects that can hibernate are not billed. - same URL.
  - 13,000 GB-s / 0.125 GB = 104,000 object-seconds/day, about 28.9 object-hours. One object kept awake all day uses about 10,800 GB-s (83% of the cap). A slow streamed read keeps the object awake (and billed) for its whole wall time.
- Workers Free (https://developers.cloudflare.com/workers/platform/limits/):
  - 100,000 requests/day ("resetting at midnight UTC"). Exceeding it returns Error 1027.
  - 10 ms CPU per HTTP request.
  - 50 external subrequests per invocation, and 1,000 subrequests to internal services.
  - "Each subrequest in a redirect chain counts against this limit."
- Durable Object CPU: the DO limits page gives "30 seconds (default) / configurable to 5 minutes of active CPU time". "Each incoming HTTP request or WebSocket message resets the remaining available CPU time to 30 seconds." - https://developers.cloudflare.com/durable-objects/platform/limits/
  - Neither the DO limits page nor the pricing page says whether the Workers Free 10 ms CPU limit applies to Durable Objects. Treat this as unverified and measure it on the live Free account.
  - CPU time excludes waiting: "Waiting on network requests (such as fetch() calls, KV reads, or database queries) does not count toward CPU time." - https://developers.cloudflare.com/workers/platform/limits/
- **Cost of an N-step read** (derived from the rules above):
  - N alarm invocations, which are N DO requests.
  - N `setAlarm` calls, which are N rows written.
  - Chunk rows written, plus index rows.
  - N or more external subrequests, each within the 50-per-invocation cap.
  - Duration billed for the wall time of each step.
  - Even with N = 50 per department per day across 30 departments, that is 1,500 requests: small against 100,000/day. Duration is the budget most likely to matter, because a 30 s streamed step per department per day is about 3.75 GB-s each.

## 6. Separate Durable Object instances: parallelism and failure isolation

- Separate objects let work run in parallel: "This enables parallelism: operations on different children can happen concurrently". Each one "gets its own single-threaded execution environment with private storage". - https://developers.cloudflare.com/durable-objects/best-practices/rules-of-durable-objects/
- Storage is isolated: "A Durable Object's attached storage is private to its unique instance and cannot be accessed by other objects." - https://developers.cloudflare.com/durable-objects/concepts/what-are-durable-objects/
- Each object has its own alarm (one per object). A schedule-reader object can therefore run its own step alarms without overwriting the monitoring object's alarm. - https://developers.cloudflare.com/durable-objects/api/alarms/
- Each object has its own IoContext, input/output gates, and abort scope. A CPU or memory abort in the reader object fails that object's requests, not the monitoring object's. - https://github.com/cloudflare/workerd/blob/main/src/workerd/io/io-context.h (lines 1628-1630) and https://github.com/cloudflare/workerd/blob/main/src/workerd/io/io-context.c++ (lines 251-296)
- **Isolation is not complete:**
  - Same isolate: "Multiple instances of the same Durable Object class can share an isolate". Synchronous work in one can delay the others. - https://developers.cloudflare.com/durable-objects/concepts/what-are-durable-objects/
  - Shared memory: "Memory is measured per isolate (which can host multiple Durable Objects), not per object." Objects "may share global memory with other instances defined in the same Worker code". - https://developers.cloudflare.com/durable-objects/reference/in-memory-state/
  - So a memory blowup in the reader object can push the shared isolate over 128 MB. The docs do not say whether that only replaces the isolate or also aborts other objects' in-flight requests.
  - Giving the reader its own class does not appear in the docs as an isolation guarantee either. Each class is still code "defined in the same Worker code".
  - Strong failure isolation needs the reader in a separate Worker script, reached through a service binding. The docs do not state this directly; it follows from the per-isolate memory rule.
- Account-wide Free plan quotas (requests, duration, rows, storage) are shared by all objects. - https://developers.cloudflare.com/durable-objects/platform/pricing/

## Open questions (not answered by primary docs)

1. Does the Workers Free 10 ms CPU limit apply to Durable Object alarms and requests, or do DOs get 30 s on Free?
2. When an alarm overruns CPU or memory, is it officially retried (and does it count toward the 6)? The source suggests yes. The docs do not say.
3. When a shared isolate exceeds 128 MB, are other Durable Objects in it aborted, or allowed to finish?
4. Do alarm invocations count toward the Free plan 100,000/day DO requests? This is explicit only for Paid.
5. The Free plan per-object storage cap: 10 GB (table) vs 1 GB (FAQ).
