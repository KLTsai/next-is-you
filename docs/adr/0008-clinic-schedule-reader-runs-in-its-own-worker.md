---
status: accepted
---

# The clinic schedule reader runs in its own Worker

A clinic schedule page is large (NTUH 內科 was 7,684,379 characters on 2026-11-25) and is read by the clinic picker, by Start and by the daily recheck (#188). The Free plan gives each invocation 10 ms of CPU and each isolate 128 MB of memory, and no option on that plan raises either. So the read is done in bounded steps that keep no full page text in memory, and it runs in its own Durable Object, apart from `SystemSendGate`, which reads running visits and sends LINE messages (ADR 0005, ADR 0007).

We decided on 2026-11-25, in the #188 grilling, to put that Durable Object class in a separate Worker, one per environment, bound from the main Worker with a Durable Object binding that sets `script_name`. A second class inside the main Worker was the cheaper option and was rejected:

- **Memory.** workerd gives each script one isolate, so two classes in one Worker may share 128 MB. Cloudflare does not document what happens to other objects when that isolate runs out. A separate Worker has its own isolate, so a reader that runs out of memory cannot cost a family member a visit read or a reminder.
- **Deploys.** `code_update_strategy` applies to every class a Worker exports, so a release of either part would reset both. Separate Workers reset separately.
- **Rollback.** Adding a Durable Object class blocks rollback to earlier versions of the Worker that exports it. In its own Worker, that floor stays off the main Worker, which already has the live floor of #245.

A `script_name` binding, not a service binding or a stateless RPC entrypoint, because the reader keeps state and its own alarm between steps, and because the docs leave the callee's CPU and request counting of service bindings on the Free plan unstated.

## Consequences

- Each release deploys two Workers. CI deploys the reader first on Staging and in Promote, and the RPC interface between them stays backward compatible, because the two can run different versions for a while.
- The captain has two Workers per environment to look at. `docs/HTTPS-SERVICE.md` says which one to open for which symptom. Account-wide usage (`usage.yml`) covers both without changes.
- The live switch stays on the main Worker only. The reader has no public route and is reached only through the binding.
- Moving the class back into the main Worker later is possible but takes a Durable Object transfer across several deploys.
- Whether the isolation holds is checked on Staging by forcing the reader over its memory limit while a `SystemSendGate` tick runs (#188).

Research: `research/cloudflare-free-plan-separate-worker-2026-11-25.md`, `research/cloudflare-do-concurrency-2026-11-24.md`.
