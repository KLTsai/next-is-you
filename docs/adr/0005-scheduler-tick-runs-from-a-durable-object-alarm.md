---
status: accepted
---

# The scheduler tick runs from a Durable Object alarm

Until #170 a Cloudflare Cron fired every minute, and the Python Worker's `scheduled` handler awaited `SystemSendGate.scheduled_tick()` over RPC. On the Free plan every invocation has about 10 ms of CPU. #162 measured the held Staging tick and found the Worker invocation alone took 5-27 ms (median 14, 11 of 15 over 10 ms). Cloudflare terminates a Worker that overruns consistently. Its RPC lifecycle docs say that when a calling Worker's execution context ends, the Durable Object call it was awaiting can be cancelled. The tick makes several separate D1 writes, so a cancelled tick can leave D1 and the ledger out of step, and the recovery hold then freezes all sending until the captain reconciles.

We decided on 2026-11-21, in the #170 grilling, that the tick runs only from the `SystemSendGate` Durable Object's own alarm. No caller is left that can disconnect. The alarm handler sets the next alarm first and only then runs the tick: 1 minute out while any visit is `active` or `stopping`, and 5 minutes out otherwise so that lifecycle chores still run. `start_visit` also sets a 1-minute alarm. The Cron drops to every 5 minutes and becomes a watchdog. The Worker calls only `ensure_alarm()`, which restores a missing alarm and never runs the tick. An overrun or termination of that Worker invocation therefore cannot interrupt a tick.

## Considered options

- **Keep the minute Cron calling the tick.** Rejected. Worker startup alone overruns the limit, and a terminated caller can cancel the tick mid-write.
- **Alarm schedules its successor after the tick.** Rejected. A tick killed before it reaches that step breaks the alarm chain, and reminders stop until the watchdog runs, up to 5 minutes later. Setting the next alarm first bounds the gap at 1 minute.
- **A JavaScript Cron Worker.** Kept as the fallback only. It means a second deploy unit, and it is not needed once the Cron cannot reach the tick.

## Consequences

- The CPU budget that matters is the Durable Object invocation. #170 acceptance requires every Durable Object invocation, alarm included, to be at or below 10 ms. The watchdog Worker may occasionally run over, and that is harmless.
- Alarms are at-least-once and may fire twice. The gate lock and the outbound retry key must keep a repeated alarm from sending twice.
- With no active visit, the Durable Object still wakes every 5 minutes, which is 288 Durable Object invocations a day. A visit started days ahead is `active` and keeps the 1-minute alarm until its day. This is accepted for simplicity.
- If a tick with several visits running exceeds 10 ms, each alarm will do one bounded step, such as chores, one clinic read or one send, and then immediately schedule the next step. This is adopted only if measurement shows it is needed.
- A tick interrupted between D1 writes inside the Durable Object still triggers the recovery hold. Keeping the tick small (#170 items 2 and 3) is what prevents that, not this decision.
- Prototype: branch `prototype/170-alarm-tick`, `src/next_is_you/send_gate_alarm.prototype.html`.
