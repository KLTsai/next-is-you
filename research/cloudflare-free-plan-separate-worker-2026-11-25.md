# A separate Worker for the clinic schedule read on the Workers Free plan

Researched 2026-11-25, for [#188](https://github.com/KLTsai/next-is-you/issues/188). Question: under the Workers Free plan, is (a)+(b) the best way to isolate the schedule read, compared with (b) alone or another option (Workflows, Queues, a Cron Trigger in a separate Worker)?

- (a) The schedule reader lives in a separate Worker script with its own Durable Object (DO) for step alarms. The main Worker calls it.
- (b) The per-step memory is bounded: stream the body, drop the unused modal markup, work in small steps across alarms, and store chunks in DO SQLite.

Sources: developers.cloudflare.com (pages read 2026-11-25 through their `index.md` form), the Cloudflare blog, and the cloudflare/workerd source on `main` at commit `6eb888c52f5b32b2afb3b862abc0c7e9ec997ca3`. Every claim cites its URL. Where the docs say nothing, this file says so. Do not read silence as a guarantee.

This builds on [`cloudflare-do-concurrency-2026-11-24.md`](cloudflare-do-concurrency-2026-11-24.md) and [`ntuh-schedule-chunked-read-2026-11-24.md`](ntuh-schedule-chunked-read-2026-11-24.md) and does not repeat their sources. Nothing was deployed and no Cloudflare API was called.

Labels: **Source** (a primary source says it), **Source code** (workerd says it; production Cloudflare runs extra closed code on top, so it is strong evidence, not a documented contract), **Observed** (read from this repository), **Inference** (my reasoning), **Not documented** (no primary source settles it).

## Answer

- **Yes, (a)+(b) is the best option, with one change to (a).** Put the reader DO class in its own Worker and bind it from the main Worker with a Durable Object binding that sets `script_name`. Do not use a stateless service binding or an RPC `WorkerEntrypoint`. Cloudflare's own guidance describes this pattern ("Split Workers by class family", "Bind across Workers with `script_name`"). It needs no service binding, so it avoids the service binding questions the docs leave open (callee CPU, the 100,000 requests/day count, cancellation when the caller ends).
- **(b) is required whatever else is chosen.** No layout raises the 10 ms CPU or the 128 MB memory per isolate. (a) only limits the blast radius when (b) is not enough. (b) is what makes the read fit.
- **What (a) adds over (b) alone:**
  - Memory isolation from the DO that reads visits and sends LINE messages. The docs only say that objects of the *same* class can share an isolate. In workerd each script gets its own isolate, so two classes in one script may share one.
  - Deploys are separate. A code update in one Worker does not reset the other Worker's objects.
  - No new rollback floor for the main Worker. Adding a DO class is a class lifecycle change, and Cloudflare blocks rollback to any version before one.
  - The reader can be a minimal Python Worker without the main app's imports, so its isolate starts with more free memory (Inference).
- **What (a) costs:**
  - Two more scripts: one reader each for Staging and Production, 4 of the 100 allowed.
  - Two deploys per release, which are not atomic. The reader goes first.
  - The RPC interface must stay forwards and backwards compatible.
  - The captain has two Workers per environment to look at.
  - No new Cron Trigger is needed (alarms drive the steps). No extra quota is used beyond the DO requests the steps already cost, because all Free daily limits are account-wide.
- **Workflows, Queues and a Cron Trigger are not better here.** Each runs with the same 10 ms CPU per invocation or step, so none of them removes the need for (b). Workflows has a 3,000 steps/day Free cap and a 1 MiB step result cap. Queues has 10,000 operations/day and 128 KB messages. A Cron Trigger is limited to 5 per account (2 already used) and cannot run fine-grained steps. The existing alarm chain (ADR 0005) already gives at-least-once steps with retries.

---

## 1. Isolates and memory

### Two different Worker scripts

- **Source:** "Each isolate's memory is completely isolated, so each piece of code is protected from other untrusted or user-written code on the runtime." - https://developers.cloudflare.com/workers/reference/how-workers-works/
- **Source:** the limit is per isolate. "Each isolate can consume up to 128 MB of memory, including the JavaScript heap and WebAssembly allocations. This limit is per-isolate, not per-invocation. A single isolate can handle many concurrent requests." - https://developers.cloudflare.com/workers/platform/limits/
- **Source code:** "each Script gets a V8 Isolate, while each Zone sharing that script gets a JavaScript context (global object)." - https://github.com/cloudflare/workerd/blob/6eb888c52f5b32b2afb3b862abc0c7e9ec997ca3/src/workerd/io/worker.h (lines 332-334)
- **Source:** many isolates share one OS process, and Free plan Workers are grouped into "cordons" by trust ("a customer who signs up for the Free plan will not be scheduled in the same process as an Enterprise customer"). Sharing a process is not sharing an isolate. - https://developers.cloudflare.com/workers/reference/security-model/
- **Not documented:** no developers.cloudflare.com page says in so many words that two scripts of one account never share an isolate or its 128 MB. The workerd comment and the "completely isolated" statement are the strongest evidence. **Inference:** two scripts have two isolates and two separate 128 MB budgets.

### Two DO classes in one script

- **Source:** "Multiple instances of the same Durable Object class can share an isolate. Only one thread can execute JavaScript in that isolate at a time, so synchronous work in one object can delay others sharing it." - https://developers.cloudflare.com/durable-objects/concepts/what-are-durable-objects/
- **Source:** "For most accounts, a Durable Object is typically the only Durable Object in its isolate. However, multiple instances of the same Durable Object class can share an isolate. Different object IDs do not guarantee separate isolates." Also: "Sharding can distribute work, but does not guarantee a separate isolate for each shard." - https://developers.cloudflare.com/durable-objects/best-practices/architecture-guidance/ (section "Shared isolates and event-loop contention")
- **Source:** "A single isolate can host multiple Durable Objects of the same class, along with the surrounding Worker code, and they all share that isolate's memory." - https://developers.cloudflare.com/durable-objects/observability/metrics-and-analytics/ (section "Memory usage")
- **Source:** "A given instance of a Durable Object may share global memory with other instances defined in the same Worker code." - https://developers.cloudflare.com/durable-objects/reference/in-memory-state/
- **Not documented:** whether objects of *different* classes in one script can share an isolate. The docs neither say so nor rule it out. **Source code + Inference:** in workerd a script maps to one isolate, and every DO class a script exports is part of that script. So in workerd two classes of one script do share an isolate. A second class in the main Worker (option (b) alone) is not a documented memory boundary. The 2026-11-24 research reached the same conclusion (its section 6).

### When one isolate exceeds its memory

- **Source:** "When an isolate exceeds 128 MB, the Workers runtime lets in-flight requests complete and creates a new isolate for subsequent requests. During extremely high load, the runtime may cancel some incoming requests to maintain stability." The outcome is `exceededMemory`, shown as "Exceeded Memory" under **Metrics > Errors > Invocation Statuses**. - https://developers.cloudflare.com/workers/platform/limits/
- **Source:** "When a Worker hits official limits or when resources are exceptionally tight on the machine the request is running on, the runtime will selectively evict isolates after their events are properly resolved." - https://developers.cloudflare.com/workers/reference/how-workers-works/
- **Source:** for DOs, an infrastructure exception "may also have the `.remote` property set to `True` -- for example, when the Durable Object exceeds its memory or CPU limits." - https://developers.cloudflare.com/durable-objects/best-practices/error-handling/
- **Source code:** `exitJs` "Returns true if the isolate has exceeded limits and become condemned." - https://github.com/cloudflare/workerd/blob/6eb888c52f5b32b2afb3b862abc0c7e9ec997ca3/src/workerd/io/limit-enforcer.h (line 75). Memory is a property of the isolate, so every object in a condemned isolate is affected.
- **Not documented:** what happens to the *other* DOs in a shared isolate when one object's work pushes it over 128 MB. They may finish ("lets in-flight requests complete"), may be cancelled ("may cancel some incoming requests"), or may be reset when the isolate is replaced. **Inference:** in (b) alone, a memory overrun in the reader can reach the `SystemSendGate` object if they share an isolate. In (a) it cannot, because they are in different scripts.

## 2. CPU

- **Source:** the Free plan CPU limit is "10 ms" per HTTP request and per Cron Trigger. The table lists no other invocation types. - https://developers.cloudflare.com/workers/platform/limits/
- **Source:** the pricing table gives Free "10 milliseconds of CPU time per invocation". - https://developers.cloudflare.com/workers/platform/pricing/
- **Source:** "Durable Objects are Worker scripts, and have the same per invocation CPU limits as any Workers do." The same FAQ gives "30 seconds" by default "per Durable Objects invocation (HTTP request, WebSocket message, or Alarm)", and the limits table has no plan split. - https://developers.cloudflare.com/durable-objects/platform/limits/
  - **Not documented:** whether a DO alarm on Free gets 10 ms or 30 s. This is still open, as in the 2026-11-24 notes. #188 and ADR 0005 plan for 10 ms.
- **Source:** "Each incoming HTTP request or WebSocket message resets the remaining available CPU time to 30 seconds." - https://developers.cloudflare.com/durable-objects/platform/limits/ (footnote 4). Each alarm is a separate invocation. So a reader DO in another script has its own per-invocation budget, separate from the `SystemSendGate` alarm (**Inference**, from "per invocation").
- **Source:** the same rule appears for Workflows ("Workflows are Worker scripts, and share the same per invocation CPU limits"; Free "Compute time per step" 10 ms) and for Queues ("Queue consumer Workers ... share the same per invocation CPU limits"). - https://developers.cloudflare.com/workflows/reference/limits/ and https://developers.cloudflare.com/queues/platform/limits/
- **Service bindings and callee CPU:**
  - **Source:** for billing, a Worker A to Worker B call through a service binding "is billed as: One request (for the initial invocation of Worker A); The total amount of CPU time used across both Worker A and Worker B". This section is marked "Only available on Workers Standard pricing". - https://developers.cloudflare.com/workers/platform/pricing/ (section "Service bindings")
  - **Not documented:** whether the Free 10 ms *limit* applies to the caller and callee separately or to their sum. The billing text adds the two CPU times. That is a billing statement on Standard, not a Free limit statement, so do not rely on a separate 10 ms for the callee.
  - **Inference:** this ambiguity is one reason to call the reader's DO (its own invocation) and not a stateless service binding.
- **Source:** "Each isolate has some built-in flexibility to allow for cases where your Worker infrequently runs over the configured limit. If your Worker starts hitting the limit consistently, its execution will be terminated". - https://developers.cloudflare.com/workers/platform/limits/

## 3. Service bindings, RPC, and cross-script DO bindings on Free

### Service bindings

- **Free availability, not documented:** the service bindings page does not mention a plan. It links to pricing, whose service-binding section is marked "Only available on Workers Standard pricing". That marker covers how calls are billed, not whether the feature exists. - https://developers.cloudflare.com/workers/runtime-apis/bindings/service-bindings/ and https://developers.cloudflare.com/workers/platform/pricing/
- **Daily requests, not documented for Free:** the pricing footnote says "Inbound requests to your Worker. Cloudflare does not bill for subrequests you make from your Worker." The service-binding section says Standard bills one request for A, not one for B. Neither says whether B's invocation counts toward the Free 100,000/day. - https://developers.cloudflare.com/workers/platform/pricing/
- **Limits:** - https://developers.cloudflare.com/workers/runtime-apis/bindings/service-bindings/
  - "Each request to a Worker via a Service binding counts toward your subrequest limit." That is 50 per invocation on Free, and "Subrequests to internal services" is 1,000 on Free (https://developers.cloudflare.com/workers/platform/limits/).
  - "A single request has a maximum of 32 Worker invocations, and each call to a Service binding counts towards this limit."
  - "Calling a service binding does not count towards simultaneous open connection limits". The limits page adds that "Workers triggered via Service bindings share the same connection limit" (https://developers.cloudflare.com/workers/platform/limits/).
- **Latency and thread:** "When you use Service Bindings, there is zero overhead or added latency. By default, both Workers run on the same thread of the same Cloudflare server. And when you enable Smart Placement, each Worker runs in the optimal location for overall performance." - same service bindings page.
  - **Inference:** "same thread" with "each Script gets a V8 Isolate" (section 1) means two isolates take turns on one thread. Memory is separate, but a long synchronous step in one can delay the other while they share the thread. The docs do not say whether a callee's CPU blocks the caller in a way that counts against it.
- **Cancellation:** "When the caller's execution context ends, the called Worker's RPC execution context is canceled". For work that must finish, "Send the job to Queues or start a Workflow". - same service bindings page. So a stateless reader behind a service binding cannot run a multi-step read on its own.
- **RPC payload:** "The maximum serialized RPC limit is 32 MiB. Consider using ReadableStream when returning more data." - https://developers.cloudflare.com/workers/runtime-apis/rpc/
- **Smart Placement:** it exists to put a back-end Worker near its data ("split your edge logic ... and back-end logic ... into separate Workers"). "Durable Objects provide automatic placement without configuration." - https://developers.cloudflare.com/workers/configuration/placement/. **Inference:** it does not matter here. The reader's work happens in its DO, which is placed by DO rules.

### Cross-script DO binding (the recommended form of (a))

- **Source:** a DO binding's `script_name` is "The name of the Worker where the Durable Object is defined, if it is external to this Worker." - https://developers.cloudflare.com/workers/wrangler/configuration/ (section "Durable Objects")
- **Source:** in "Split Workers by class family", Cloudflare says to "Group classes that change together ... into their own Worker", "Bind across Workers with `script_name`, so the API Worker can call a class it does not deploy", and "Keep RPC interfaces forwards and backwards compatible, because callers and objects now deploy independently". - https://developers.cloudflare.com/durable-objects/best-practices/architecture-guidance/
- **Source:** "Each RPC session is billed as one request to your Durable Object. Every RPC method call on a Durable Objects stub is its own RPC session and therefore a single billed request." The DO request row includes "alarm invocations". The Free plan allows 100,000 DO requests/day. - https://developers.cloudflare.com/durable-objects/platform/pricing/
- **Not documented:** whether a call from one script into another script's DO also counts as a Workers request toward the separate Workers 100,000/day. It costs DO requests either way.

## 4. Free plan account limits

All daily quotas below are per account. Splitting code into more scripts does not add quota, and every script draws from the same pool.

| Limit | Free value | Effect on (a) | Source |
| --- | --- | --- | --- |
| Workers per account | 100 | +2 scripts (Staging and Production readers) | https://developers.cloudflare.com/workers/platform/limits/ |
| DO classes per account | 100, "Identical to the Workers script limit" | +1 class per environment in both (a) and (b) | https://developers.cloudflare.com/durable-objects/platform/limits/ |
| DO namespaces | Not listed separately. A namespace is created per class through `exports` | Same as classes | https://developers.cloudflare.com/durable-objects/reference/durable-objects-migrations/ |
| Cron Triggers per account | 5 | 0 more if the reader uses alarms only. **Observed:** Staging and Production already use 2 (`wrangler.staging.jsonc`, `wrangler.production.jsonc`) | https://developers.cloudflare.com/workers/platform/limits/ |
| Workers requests | 100,000/day, reset at midnight UTC, Error 1027 when exceeded | Shared | https://developers.cloudflare.com/workers/platform/limits/ |
| DO requests | 100,000/day | Shared. Every alarm step and every cross-script RPC call counts | https://developers.cloudflare.com/durable-objects/platform/pricing/ |
| DO duration | 13,000 GB-s/day, each object billed at 128 MB | Shared | https://developers.cloudflare.com/durable-objects/platform/pricing/ |
| DO SQLite | 5 million rows read/day, 100,000 rows written/day, 5 GB storage per account | Shared | https://developers.cloudflare.com/durable-objects/platform/pricing/, https://developers.cloudflare.com/durable-objects/platform/limits/ |
| Workflows | Available on Free. Requests "shared with Workers requests", 10 ms CPU per invocation, 3,000 steps/day, 1 GB-month storage | Alternative only | https://developers.cloudflare.com/workflows/reference/pricing/ |
| Queues | Available on Free. 10,000 operations/day, retention fixed at 24 hours, 10,000 queues | Alternative only | https://developers.cloudflare.com/workers/platform/pricing/, https://developers.cloudflare.com/queues/platform/limits/ |
| Workers Logs | 200,000 log events/day, 3 days retention. "Beginning December 1, 2026, Workers Logs will use Cloudflare Observability pricing" | Shared. A second Worker adds its own invocation logs | https://developers.cloudflare.com/workers/platform/pricing/ |
| Worker startup time | 1 second per Worker | Each Worker checked on its own | https://developers.cloudflare.com/workers/platform/limits/ |

## 5. Python Workers specifics

- **Source:** "When you write a Python Worker, your code is interpreted directly by Pyodide, within a V8 isolate." At deploy time Cloudflare "executes the Worker entrypoint module and everything it imports at top level and then take a snapshot of the Worker's WebAssembly linear memory". "When a request comes in to your Worker, we load this snapshot and use it to bootstrap your Worker in an isolate". - https://developers.cloudflare.com/workers/languages/python/how-python-workers-work/
- **Source:** "This snapshot is specific to your Worker. It can't be shared". Package files are shared across Workers on a machine, but "Today, we're able to share these files across Workers, but copy them into each new isolate." "Pyodide itself is 6.4 MB". - https://blog.cloudflare.com/python-workers/
- **Source:** cold start: "without snapshots takes around 10 seconds", "With snapshots, it takes 1 second". The measured mean cold start for a Worker importing httpx, fastapi and pydantic is 1.027 s. - https://blog.cloudflare.com/python-workers-advancements/
- **Memory baseline: Not documented.** No primary source gives the resident memory of a Pyodide isolate. The 6.4 MB figure is a download size, not the heap.
- **Inference, does a second Python Worker double the cost?**
  - Yes for cold starts and for Pyodide memory in total: each script has its own isolate, Pyodide copy and snapshot.
  - It does not take memory from the main Worker. Each isolate has its own 128 MB.
  - It does not change DO duration billing, which charges 128 MB per object "regardless of actual usage" (https://developers.cloudflare.com/durable-objects/platform/pricing/).
  - A reader Worker that imports only the standard library and the reader module, not FastAPI and the app, should snapshot smaller and leave more of its 128 MB for the page.
- **No Python-only restriction found on service bindings, RPC or DOs:**
  - The service-binding RPC docs show a Python `WorkerEntrypoint` with an RPC method (https://developers.cloudflare.com/workers/runtime-apis/bindings/service-bindings/rpc/).
  - The Python overview lists DOs, service bindings, Workflows and Queues as available bindings (https://developers.cloudflare.com/workers/languages/python/).
  - Python Workflows need both `python_workflows` and `python_workers` flags (https://developers.cloudflare.com/workflows/python/).
  - **Observed:** this project already runs a Python SQLite DO (`SystemSendGate`, `wrangler.jsonc`).
  - **Not documented:** whether a Python DO can call a DO in another Python script through `script_name` without a Python-specific caveat. No page says it cannot. Measure it locally (`wrangler dev` with two configs) before committing.

## 6. Deploy and versioning across two Workers

- **Deploy order (service bindings):** "Workers using Service bindings are deployed separately." "the target Worker ... must be deployed first ... Otherwise ... deployment will fail, because Worker A declares a binding to Worker B, which does not yet exist." For changes: deploy B compatibly first, then A, then remove unused code. - https://developers.cloudflare.com/workers/runtime-apis/bindings/service-bindings/
  - **Not documented:** the same deploy-time check for a DO binding with `script_name`. **Inference:** assume it too fails or binds to nothing until the reader exists, and deploy the reader first.
- **One commit, two Workers:** nothing in the docs makes two Worker deploys atomic. Each `wrangler deploy` creates a version and deployment for that Worker only (https://developers.cloudflare.com/workers/versions-and-deployments/). **Inference:** CI deploys the reader, then the main Worker, from the same commit, and keeps the RPC interface compatible across one version in each direction.
- **Code updates and resets:**
  - **Source:** "`code_update_strategy` applies to every Durable Object class this Worker exports" and "you cannot set a different strategy for one class than another in the same Worker."
  - **Source:** "If a Durable Objects binding uses `script_name` to reference a class defined in a different Worker, that class's code updates are controlled by that other Worker's own `code_update_strategy`".
  - **Source:** the default is "deferred" for up to 300 s, after which an active object "resets and adopts the new code".
  - Sources: https://developers.cloudflare.com/durable-objects/deployments/durable-objects-code-updates/ and https://developers.cloudflare.com/durable-objects/best-practices/architecture-guidance/ ("If one Worker defines every class, a deploy can affect objects across all of those classes").
  - **Inference:** in (b) alone, every main Worker deploy can reset a reader that is mid-read, and a reader-only fix resets `SystemSendGate`. In (a) the two are independent.
- **Rollback:**
  - **Source:** rollback is per Worker and "Resources connected to your Worker ... will not be changed during a rollback".
  - **Source:** rollback "will not be allowed if: A Durable Object class lifecycle change (via `exports` or the legacy `migrations` array) has occurred between the version in the active deployment and the version selected to roll back to".
  - Sources: https://developers.cloudflare.com/workers/versions-and-deployments/rollbacks/ and https://developers.cloudflare.com/workers/versions-and-deployments/gradual-deployments/with-durable-objects/ ("Once a lifecycle change is deployed, rollbacks cannot take place to any version prior to the one that included the change").
  - **Inference:** (b) alone adds a new class to the main Worker's `exports`, which sets a new rollback floor for the main Worker at that release. **Observed:** the project already tracks a rollback floor (commit e55bba9, #245; `docs/CI-CD.md` section "Rollback"). In (a), the class lifecycle change happens in the new reader Worker. The main Worker only gains a binding, and binding changes are not on the list of rollback blockers (the list names DO class lifecycle changes and deleted R2, KV or queue resources).
- **Gradual deployments and versions:**
  - **Source:** "When one Worker calls another via a service binding, the two Workers may be at different points in their own gradual deployment." Version overrides can pin the downstream Worker, but "Version overrides only apply to `fetch()`-based service binding calls ... RPC calls do not support attaching headers." - https://developers.cloudflare.com/workers/versions-and-deployments/gradual-deployments/ and https://developers.cloudflare.com/workers/versions-and-deployments/version-overrides/
  - **Source:** for DOs, "each Durable Object is assigned a Worker version" per deployment. - https://developers.cloudflare.com/workers/versions-and-deployments/gradual-deployments/with-durable-objects/
  - **Observed:** the project deploys with plain `pywrangler deploy` (100%, `.github/workflows/ci.yml`, `promote.yml`), so gradual deployments are not in use.
- **Moving later is possible:** a DO namespace can be transferred to another Worker with `transferred` and `expecting-transfer` entries in a "multi-deploy flow" (four deploys recommended). - https://developers.cloudflare.com/durable-objects/reference/durable-objects-migrations/ (section "Transfer a Durable Object class between Workers"). **Inference:** starting with (b) alone does not lock the project in, but the move later costs four coordinated deploys, so it is cheaper to start with (a).

## 7. What the captain sees and manages

- **Source, per Worker in the dashboard:** Metrics (requests, errors with "Exceeded CPU Time Limits" and "Exceeded Memory", CPU time, duration, memory usage) is opened by selecting a Worker under **Workers & Pages** (https://developers.cloudflare.com/workers/observability/metrics-and-analytics/). Workers Logs: "In Overview, select your Worker. Select Observability" (https://developers.cloudflare.com/workers/observability/logs/workers-logs/). Real-time logs and `wrangler tail` are also per Worker, with "A maximum of 10 clients" per Worker (https://developers.cloudflare.com/workers/observability/logs/real-time-logs/).
- **Source:** DO logs "are aggregated by the script name and the Durable Object class name". So even in (b) alone, the reader class is told apart in logs. - https://developers.cloudflare.com/durable-objects/observability/metrics-and-analytics/
- **Source:** the DO memory chart "always reports the memory of the whole isolate, not an individual Durable Object". - same page. **Inference:** in (b) alone, the captain cannot tell from the chart whether the reader or the visit object used the memory. In (a), the reader Worker's memory chart shows only the reader.
- **Source:** Issues "groups related occurrences from the same Worker into one issue" and is enabled per Worker with `observability.issues.enabled`. - https://developers.cloudflare.com/workers/observability/issues/
- **Source:** observability is configured per Worker (`observability.enabled`, `head_sampling_rate`). - https://developers.cloudflare.com/workers/observability/logs/workers-logs/
- **Not documented:** any Free plan alert for approaching the daily request, DO or row quotas. **Observed:** the project's hourly `usage.yml` reads account-wide usage from GraphQL, filtered by account and date (`scripts/cloudflare_usage.py`), so it would include a reader Worker without changes.
- **Inference, captain workload:**
  - (a) doubles the places to look per environment: two Worker pages, two log views, two Issues lists.
  - The usage budget stays one account-wide view.
  - The deploy is still one CI pipeline, and Promote and Rollback would need to handle two Workers.
  - A page in `docs/HTTPS-SERVICE.md` should name both Workers and say which one to open for which symptom: picker or recheck failures go to the reader, visit reads and LINE sends go to the main Worker.

## 8. The other alternatives

- **Workflows (in the main or a separate Worker):**
  - Free: 10 ms CPU per step, 3,000 steps/day, 1 MiB per step result, 100 MB state per instance, 3 days retention, 100 concurrent instances. - https://developers.cloudflare.com/workflows/reference/limits/ and https://developers.cloudflare.com/workflows/reference/pricing/
  - Steps retry and persist results, which suits a resumable read. But a 7.7 MB page cannot be a step result, and the step cap is 3,000/day against 100,000 DO requests/day.
  - It is a new product for the captain to watch, Python needs the extra `python_workflows` flag, and the step code still runs in some Worker's isolate.
  - **Inference:** not better than DO alarms for this read. ADR 0005 already uses alarms, and they give per-object SQLite for the stored page.
- **Queues:**
  - Free: 10,000 operations/day, "it takes 3 operations to deliver a message", 128 KB per message, consumer CPU under the same per-invocation rule. - https://developers.cloudflare.com/workers/platform/pricing/ and https://developers.cloudflare.com/queues/platform/limits/
  - A message cannot carry the page, only a pointer to a chunk. **Inference:** this adds a product and a quota without removing anything.
- **Cron Trigger in a separate Worker:**
  - 10 ms CPU per Cron Trigger, 5 per account. - https://developers.cloudflare.com/workers/platform/limits/
  - **Inference:** useful only as a watchdog (as today). It cannot pace sub-minute steps, and it would use 2 of the 3 remaining triggers for Staging and Production.
- **Stateless reader behind a service binding or RPC entrypoint:**
  - The call is canceled when the caller's context ends, it cannot hold state between steps, and callee CPU and request counting on Free are not documented (section 3). **Inference:** worse than a cross-script DO.

## Comparison

| | (b) alone: second DO class in the main Worker | (a)+(b): reader DO class in its own Worker, bound with `script_name` | Workflows for the steps |
| --- | --- | --- | --- |
| Fits 10 ms CPU per step | Only through (b) | Only through (b) | Only through (b) (10 ms per step) |
| Memory isolation from visit reads and LINE sends | Not documented. workerd puts one script in one isolate, so classes may share 128 MB | Separate script, separate isolate (workerd source, "completely isolated") | Depends on which script holds the Workflow class |
| Reader memory headroom | Shares the main app's Pyodide snapshot and imports | Minimal reader snapshot (Inference) | As the hosting script |
| Deploy resets | Every deploy can reset both classes (one `code_update_strategy`) | Independent | As the hosting script |
| Main Worker rollback floor | New floor at the release that adds the class | None in the main Worker (binding only) | New floor if the class is added to the main Worker |
| Extra Free quota used | DO requests and rows for steps | Same, plus one DO request per cross-script call | Up to 3,000 steps/day; Workers requests shared |
| Scripts and crons | +0 scripts, +0 crons | +2 scripts (of 100), +0 crons | +0 or +2 scripts |
| Deploy steps per release | 1 | 2, reader first, interface kept compatible | 1 or 2 |
| Captain's views per environment | 1 Worker | 2 Workers | 1 Worker plus Workflows pages |
| How well the docs cover it | Isolate sharing across classes not documented | Cloudflare's own "Split Workers by class family" pattern | Documented, tighter caps |

## Recommendation

**Do (a)+(b), with (a) built as a separate Python Worker that exports the reader DO class, bound from the main Worker by a DO binding with `script_name`, not a service binding.**

Reasons:

1. **Completeness and visit safety come first (#188 decisions 1 and 2).** Only a separate script gives the visit-reading object a memory boundary that does not depend on undocumented isolate placement. (b) alone relies on behavior the docs do not cover: whether two classes of one script share an isolate, and what happens to other objects when it is condemned.
2. **Deploys stay independent.** A reader fix does not reset `SystemSendGate`, and a main Worker release does not reset a read in progress (sections 6 and 7 sources).
3. **No new rollback floor for the main Worker,** which matters given the project's Promote and Rollback rules.
4. **The Free plan cost is small.** It adds 2 of 100 scripts and no cron, and all daily quotas are shared either way. The extra DO requests per read (one RPC call plus the alarm steps) are small against 100,000/day.
5. **(b) is still mandatory and comes first.** Measure per #188 "What to build" item 1. If the streamed, modal-dropping read fits in one alarm, the reader Worker runs one step. If not, it runs the stored-page, bounded-step chain.
6. **Keep the interface small and versioned:** request a read, then read the latest result. The two Workers deploy separately, and RPC calls cannot use version overrides.

Shape (Inference):

- The main Worker's picker handler, and the `SystemSendGate` for the daily recheck, call `READER.get(id_for(dept)).request_read(...)`. That call returns at once and the reader sets its own alarm.
- Results are read back with another RPC call, for example `latest_read(dept)`.
- The reader keeps its chunks, progress and last complete read in its own SQLite. It sends no LINE messages.
- CI deploys the reader before the main Worker in both the Staging and Promote jobs.

## Open questions that only a live measurement can answer

1. Does a DO alarm on the Free plan get 10 ms or 30 s of CPU, and how large is the "built-in flexibility"? (Carried over from 2026-11-24.)
2. The memory usage of the main Worker's isolate and of a minimal reader Worker's isolate on Staging, from each Worker's **Metrics > Memory usage** chart, before any page is read. Then the peak during a 內科 read with (b).
3. Whether a deliberate memory overrun in the reader (Staging only, synthetic page) leaves a concurrent `SystemSendGate` tick untouched in (a), and, for comparison, in (b) alone. This is the only way to see the undocumented isolate behavior.
4. Whether a Python DO can call a DO in another Python script through `script_name` with no Python-specific caveat, and the CPU and latency of that call (Workers Logs invocation logs show CPU and wall time per invocation).
5. What `pywrangler deploy` does when the main Worker's `script_name` binding names a reader that is not deployed yet. Does it fail at deploy or at call time?
6. Whether the cross-script DO RPC call also counts toward the Workers 100,000 requests/day, or only toward DO requests. Read it from the GraphQL usage after a known number of calls.
7. The reader Worker's `startup_time_ms` at deploy and its cold start, compared with the main Worker's.
8. The measurements already listed in #188 "What to build" item 1, which decide between one streamed step and the stored-page chain.

## Sources

All accessed 2026-11-25.

- Workers: [Limits](https://developers.cloudflare.com/workers/platform/limits/), [Pricing](https://developers.cloudflare.com/workers/platform/pricing/), [How Workers works](https://developers.cloudflare.com/workers/reference/how-workers-works/), [Security model](https://developers.cloudflare.com/workers/reference/security-model/), [Service bindings](https://developers.cloudflare.com/workers/runtime-apis/bindings/service-bindings/), [Service bindings RPC](https://developers.cloudflare.com/workers/runtime-apis/bindings/service-bindings/rpc/), [RPC](https://developers.cloudflare.com/workers/runtime-apis/rpc/), [Placement](https://developers.cloudflare.com/workers/configuration/placement/), [Wrangler configuration](https://developers.cloudflare.com/workers/wrangler/configuration/), [Versions and deployments](https://developers.cloudflare.com/workers/versions-and-deployments/), [Gradual deployments](https://developers.cloudflare.com/workers/versions-and-deployments/gradual-deployments/), [Gradual deployments with Durable Objects](https://developers.cloudflare.com/workers/versions-and-deployments/gradual-deployments/with-durable-objects/), [Version overrides](https://developers.cloudflare.com/workers/versions-and-deployments/version-overrides/), [Rollbacks](https://developers.cloudflare.com/workers/versions-and-deployments/rollbacks/), [Metrics and analytics](https://developers.cloudflare.com/workers/observability/metrics-and-analytics/), [Workers Logs](https://developers.cloudflare.com/workers/observability/logs/workers-logs/), [Real-time logs](https://developers.cloudflare.com/workers/observability/logs/real-time-logs/), [Issues](https://developers.cloudflare.com/workers/observability/issues/), [Errors](https://developers.cloudflare.com/workers/observability/errors/).
- Python Workers: [Overview](https://developers.cloudflare.com/workers/languages/python/), [How Python Workers work](https://developers.cloudflare.com/workers/languages/python/how-python-workers-work/), [Python Workflows](https://developers.cloudflare.com/workflows/python/).
- Durable Objects: [Limits](https://developers.cloudflare.com/durable-objects/platform/limits/), [Pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/), [What are Durable Objects](https://developers.cloudflare.com/durable-objects/concepts/what-are-durable-objects/), [Lifecycle](https://developers.cloudflare.com/durable-objects/concepts/durable-object-lifecycle/), [In-memory state](https://developers.cloudflare.com/durable-objects/reference/in-memory-state/), [Architecture guidance](https://developers.cloudflare.com/durable-objects/best-practices/architecture-guidance/), [Error handling](https://developers.cloudflare.com/durable-objects/best-practices/error-handling/), [Metrics and analytics](https://developers.cloudflare.com/durable-objects/observability/metrics-and-analytics/), [Code updates](https://developers.cloudflare.com/durable-objects/deployments/durable-objects-code-updates/), [Migrations and transfers](https://developers.cloudflare.com/durable-objects/reference/durable-objects-migrations/), [Changelog: Durable Objects on Workers Free plan](https://developers.cloudflare.com/changelog/post/2025-04-07-durable-objects-free-tier/).
- Workflows: [Limits](https://developers.cloudflare.com/workflows/reference/limits/), [Pricing](https://developers.cloudflare.com/workflows/reference/pricing/). Queues: [Limits](https://developers.cloudflare.com/queues/platform/limits/).
- Cloudflare blog: [Bringing Python to Workers using Pyodide and WebAssembly](https://blog.cloudflare.com/python-workers/), [Python Workers redux](https://blog.cloudflare.com/python-workers-advancements/).
- workerd at `6eb888c52f5b32b2afb3b862abc0c7e9ec997ca3`: [`src/workerd/io/worker.h`](https://github.com/cloudflare/workerd/blob/6eb888c52f5b32b2afb3b862abc0c7e9ec997ca3/src/workerd/io/worker.h), [`src/workerd/io/limit-enforcer.h`](https://github.com/cloudflare/workerd/blob/6eb888c52f5b32b2afb3b862abc0c7e9ec997ca3/src/workerd/io/limit-enforcer.h), [`src/workerd/io/io-context.h`](https://github.com/cloudflare/workerd/blob/6eb888c52f5b32b2afb3b862abc0c7e9ec997ca3/src/workerd/io/io-context.h).
- Project: `wrangler.jsonc`, `wrangler.staging.jsonc`, `.github/workflows/ci.yml`, `.github/workflows/promote.yml`, `scripts/cloudflare_usage.py`, `docs/CI-CD.md`, commit e55bba9 (#245).
