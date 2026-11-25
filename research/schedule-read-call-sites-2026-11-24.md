# Clinic schedule read: call sites, hosts and blast radius (for #188)

Read-only map of `main` at 27b9841, 2026-11-24. Labels: **Observed** (read from code or docs, cited file:line), **Inference** (my reasoning), **Unconfirmed** (no source settles it). Paths are relative to the repo root.

**Update 2026-11-25:** 內科 now measures 7.68 M characters (485 clinics), and 外科部 at 3.95 M is also over the cap (#205, #243). The reader's schedule host `registration.ntuh.gov.tw` was confirmed to serve the page on 2026-11-25; earlier captures used `reg.ntuh.gov.tw`.

## 1. The one fetch-and-parse function

Every schedule read goes through one chain in `src/next_is_you/ntuh_reader.py`:

- `_future_schedule_rows` (705-738): optional 60 s memo keyed `(department, Taipei today)` (only when `memo_at` is passed, 717-722; only an `ok` result is stored, 731-737), then `asyncio.wait_for(self._fetch_schedule_rows(...), REQUEST_TIMEOUT_SECONDS=10)` (722-726). `TimeoutError` becomes `"timeout"`, any `Exception` becomes `"no_observation"` (727-730).
- `_fetch_schedule_rows` (897-910): one GET of `schedule_url(dept)` (271-280, `realSubDeptCode=showAll`, whole department), `_transport_failure(page, max_body_chars=MAX_SCHEDULE_BODY_CHARS)` (907), then `parse_schedule(page.body, today)` (910).
- `WorkersFetcher.__call__` (1714-1736): `str(await response.text())` (1734), so the whole body is buffered as a JS string and copied into a Python `str` before any size check.
- `_transport_failure` (1637-1655): the 3.5M-char cap (`MAX_SCHEDULE_BODY_CHARS`, 129) is checked only after the full download (1653) and reports `("invalid", "schema_drift")`.
- `parse_schedule` (544-560): one synchronous `HTMLParser.feed(html)` + `close()` over the whole page via `_ScheduleCollector` (399+), which also keeps every text node in `collector.text` (415) for `_page_status` (555). Returns `"ok"` whenever at least one row was collected (557-559); there is no completeness check.

Scope gate: only `SUPPORTED_DEPARTMENT = "OPH"` (80) reaches the fetch; any other department answers `scope_mismatch` before contacting NTUH (`list_clinics` 688-692, `match_clinic` 750-754). The registry offers only 眼科 (`hospital_registry.py:119-120`). So 內科 (6.9M) and 骨科 cannot reach the parse today; they become reachable with #180.

Date gate: the schedule page is read only for a visit date in `[today+1, today+14]`. Today uses the light table (`list_clinics` 696-697 -> `_list_today_roster` 829-853; `match_clinic` 768-790), past dates and dates past +14 answer without a request (693-707, 755-766).

The visit-day monitoring read (`observe` / `_read`, 659-662, 971+) never reads the schedule page. Its list rechecks (`LIST_RECHECK_INTERVAL`, 122, 1242-1252) and doctor/substitute handling (`_identify`, 627-648) use `DeptLightTable` (`_read_light_table`, 1436-1454) and the detail page.

## 2. Where it is called

There are exactly three callers of `_future_schedule_rows` (grep: `ntuh_reader.py:804`, `:865`, plus the alarm path through `match_clinic`). All three run in the same Durable Object.

### Host common to all three

- Worker entry: `wrangler.jsonc:4` `main: src/worker.py`; DO class `SystemSendGate` with SQLite storage (`wrangler.jsonc:24-37`); Cron `*/5 * * * *` (`wrangler.jsonc:35`).
- Every caller uses one named instance: `getByName("next-is-you-system")` for HTTP routes (`src/worker.py:1120-1131`) and for the Cron watchdog (`src/worker.py:1217`). So the picker, Start, Stop, the alarm tick and LINE sending all run in the single `SystemSendGate` instance, therefore in one isolate and on one event loop (**Inference** from the DO model: one instance lives in one isolate at a time).
- Reader construction: `_hospital_reader()` (`send_gate.py:801-809`) builds a new `RegistryHospitalReader` on every call, which builds a new `NtuhProgressReader` (`hospital_registry.py:203-214`, `102-108`). So the 60 s memo lives only for one call chain: shared across drafts inside one tick, never across ticks, pickers or Starts.
- Today no deployed environment reaches any schedule read: `_hospital_reader()` returns `None` unless `local_test_mode` (`send_gate.py:803-804`, `1184-1186`), the tick returns before `prepare_tick` outside local-test (`send_gate.py:132-134`), and Staging and Production set `NIY006_LOCAL_TEST_MODE=0` (`wrangler.staging.jsonc:48-49`, `wrangler.production.jsonc:48-49`). The schedule is read only in local-test/rehearsal with `NTUH_READER_ENABLED=1` (`send_gate.py:805-808`; `docs/NTUH-READER.md:9`). The Staging criterion of #188 therefore depends on #142 turning the reader on.

### 2a. Clinic picker (future date)

- Entry: HTTP `GET /api/organizer/hospitals/{hospital}/clinics` (`src/worker.py:481-502`) -> DO RPC `SystemSendGate.list_clinics` (`send_gate.py:811-862`) -> `RegistryHospitalReader.list_clinics` (`hospital_registry.py:185-192`) -> `NtuhProgressReader.list_clinics` (`ntuh_reader.py:669-703`) -> `_list_future_schedule` (855-895) -> `_future_schedule_rows(dept, today)` with no memo (865).
- Invocation: its own DO RPC invocation (own CPU accounting per `research/workers-free-cpu-limit-2026-11-21.md:10, 80`), plus the calling Worker HTTP invocation that awaits it.
- Lock: none. `list_clinics` does not take `self._lock` (`send_gate.py:811-862`), so it can interleave with a running tick at any `await` (fetch, D1, storage).
- Failure today:
  - Slow fetch (I/O): up to 10 s wall, then `timeout` (`ntuh_reader.py:722-728`); picker gets `available: false` and falls back to manual entry (`docs/NTUH-READER.md:119`). Nothing stored.
  - Over 3.5M chars: downloaded fully, then `schema_drift` (1653), same fallback.
  - Python exception in parse: `ValueError`/`AssertionError` -> `schema_drift` (548-551); any other `Exception` -> `no_observation` (729-730).
  - CPU overrun: `CpuLimitExceeded` is a `BaseException` (`research/workers-free-cpu-limit-2026-11-21.md:11, 56, 67`), not caught by `except Exception` (729) nor in `send_gate.list_clinics` nor in the route (`worker.py:498-502` has no try), so the RPC fails and the HTTP route errors (**Inference**: a 500 or 1102, not the manual-entry fallback).
  - Partial data: any page that yields at least one row is `ok` (557-559). Rows for the picked date are filtered (867-873); a truncated page lists fewer clinics, or `no_observation` if none for that date (874-875). The organizer sees an incomplete dropdown with no signal.
  - Effect on other jobs: no lock, so the tick is not blocked by waiting. But the parse is synchronous CPU on the same event loop: while it runs, nothing else in the object runs (**Inference**). If the isolate is terminated for CPU or for the 128 MB memory limit, an in-flight tick in the same isolate dies with it (**Inference, Unconfirmed**: no source read here says whether a CPU kill of one DO invocation resets the whole object; memory is per isolate).

### 2b. Start of a future-dated draft (pre-flight)

- Entry: HTTP `POST /api/organizer/visits/{visit_id}/start` (`src/worker.py:569-599`) -> DO RPC `start_visit` (`send_gate.py:271-294`) -> `_start_visit` under `self._lock` (296-297) -> `_preflight_validate` (352-357, 466-564) -> `reader.match_clinic` (494-503) -> `NtuhProgressReader.match_clinic` (740-827) -> `_future_schedule_rows(dept, today, memo_at=now)` (804-806).
- Only for full-schedule hospitals (`send_gate.py:345-358`) and only when the visit date is after today (same-day uses the light table, `ntuh_reader.py:768`).
- Invocation: its own DO RPC invocation, but it holds `self._lock` for the whole fetch and parse.
- Failure today:
  - Slow fetch: up to 10 s holding `_lock`; then `UNAVAILABLE/timeout` -> `set_source_read(unavailable, timeout)` and `schedule_unavailable` (`send_gate.py:541-553`). Draft stays a draft.
  - Too large or parse error: `schema_drift` -> `schedule_unavailable` (541-553).
  - CPU overrun: `CpuLimitExceeded` escapes `_start_visit`; the `async with self._lock` releases on unwind (**Inference**), nothing is written because `repository.start` comes after (362-369), and the route has no try (`worker.py:577`), so the organizer gets an error rather than a refusal code (**Inference**).
  - Partial data: if the clinic's row is in the missing part but other live rows for that date exist, `NOT_SCHEDULED` (823-827) -> `set_source_read(scope_mismatch)` and `doctor_not_scheduled` (`send_gate.py:513-517`). A false refusal plus a false organizer-attention flag on the draft. If no rows for that date, `UNAVAILABLE/no_observation` -> `schedule_unavailable`.
  - Effect on other jobs: while Start holds `_lock`, the alarm tick waits at `send_gate.py:115` (whole tick: lifecycle, reads, sends) and Stop waits at `send_gate.py:213`. Pending LINE sends wait at `send_gate.py:137`. Delay is up to the fetch timeout plus parse (wall time; DO wall time is not the CPU limit). Start is refused before any read while another visit is active or stopping (`has_other_running_visit`, `send_gate.py:304-307`), so Start's schedule read never delays a running visit's read; it can only delay lifecycle chores, the sweep and leftover LINE retries.

### 2c. Daily recheck (pre-flight sweep) inside the alarm tick

- Entry: DO alarm `SystemSendGate.alarm` (`send_gate.py:76-77`) -> `alarm_tick` (79-90; sets the next alarm first, 5 min, then 1 min if a visit is running, 87-89) -> `scheduled_tick` (107-110) -> `_scheduled_tick` under `self._lock` (112-115) -> `run_lifecycle` (129) -> `prepare_tick` (135) -> `_preflight_sweep` first (`scheduler.py:115`, 279-352) -> `RegistryHospitalReader.match_clinic` -> `NtuhProgressReader.match_clinic` -> `_future_schedule_rows(..., memo_at=now)` (`ntuh_reader.py:804-806`). The Cron (`worker.py:1210-1225`) only calls `ensure_alarm` (`send_gate.py:92-99`) and never reaches the schedule. Local-test controls can also run it: `/__niy006_test/tick` and `/__niy006_test/alarm` (`worker.py:907-911`).
- Which drafts: every `draft` with `visit_date > today` not yet checked today, ordered by hospital and department (`persistence.py:994-1016`), so drafts of one department are adjacent and share the in-tick memo (one fetch per department per tick while reads succeed).
- Same tick, after the sweep, in this order, all in the same alarm invocation:
  1. Running-visit reads: `active_schedule_rows` and, per visit, `self._hospital.observe(...)` (`scheduler.py:122-147`), which reads the light table and detail page and does doctor-change/substitute/card-missing handling (`ntuh_reader.py:971+`, `docs/NTUH-READER.md:46`); then `set_source_read`, `evaluate_alerts`, `commit_near_reminders` or `unavailable` reminders (`scheduler.py:184-261`).
  2. LINE sending: for each queued or retryable event, a separate `async with self._lock` round with hold and ledger checks and `scheduler.send_event` (`send_gate.py:136-174`; `scheduler.py:354-423`), then `finalize_stopping` (171-174).
  Lifecycle chores (`run_lifecycle`: recover in-flight, finalize stops, expire visits, erasures, draft deletion, `scheduler.py:89-108`) run before the sweep, so they are not starved by it.
- Failure today:
  - Slow fetch: up to 10 s per department before the visit read starts (wall time, holding `_lock`). The visit's `sample_time` is taken after (`scheduler.py:135`), so its freshness is unaffected; Stop and Start wait on `_lock` meanwhile.
  - Too large, timeout, parse error, transport error: `UNAVAILABLE` with a reason in `_SWEEP_TRANSIENT_REASONS` (`scheduler.py:31-33`: `no_observation`, `access_denied`, `timeout`, `schema_drift`) -> `continue` without `mark_preflight_checked` (317-319). The draft stays unchanged, and the visit read in the same tick still happens. But the draft is not marked, so it is due again on the next tick (`persistence.py:1011-1012`), and failures are not memoized (`ntuh_reader.py:731`). So a failing department is fetched again every tick: every 1 minute while a visit is running, every 5 minutes otherwise (`send_gate.py:63-64`).
  - Doc/code drift: `scheduler.py:29-30, 286-287` and `docs/NTUH-READER.md:124` say a failed sweep read retries "on the next Taipei day"; the code retries on the next tick.
  - Raised exception in `match_clinic`: caught per draft (`scheduler.py:310-315`), same `continue`.
  - CPU overrun: `CpuLimitExceeded` (a `BaseException`) passes both `except Exception` (`ntuh_reader.py:729`, `scheduler.py:312`) and leaves `_scheduled_tick`. The running visit's read, its reminders and every LINE send of that tick never run. Because the draft was not marked, the next tick reads the same schedule again first and dies the same way, so a schedule that consistently overruns starves the running visit and all LINE sending until the draft leaves the sweep (Start, deletion, or its date arriving). The alarm chain survives because the next alarm was set before the tick (`send_gate.py:83-89`, ADR 0005). Whether Cloudflare's at-least-once alarm retry (backoff from 2 s, up to 6 retries, `research/workers-free-cpu-limit-2026-11-21.md:99`) also re-fires the failed alarm on top of the one already set is **Unconfirmed**. A kill between D1 writes of the sweep (`set_source_read` then `mark_preflight_checked`, `scheduler.py:341-350`) leaves that draft half updated but not marked, so it is redone (idempotent for these writes, **Inference**). A kill after `run_lifecycle` but before `_save_ledger` at `send_gate.py:130` cannot happen from the sweep, since the sweep starts after that save.
  - Memory overrun (128 MB per isolate): same outcome as a CPU kill for this tick (**Inference**). The research note measured about 110 MB of CPython allocations for the full 內科 parse; on top of the JS copy of the body (`ntuh_reader.py:1734`) that is near or over the limit (**Inference**).
  - Partial data: an `ok` page with the draft's row missing but other live rows that date -> `NOT_SCHEDULED` -> `set_source_read(scope_mismatch)`, counted as mismatched and marked checked for the day (`scheduler.py:344-351`). The organizer sees a false "no longer scheduled" signal; it is not retried until the next Taipei day. A partial `ok` is also memoized for 60 s and reused by every later draft of that department in the tick (`ntuh_reader.py:731-737`). A missing date block gives `no_observation` (transient, retried next tick).
  - Pause/stop: `stop_visit` (`send_gate.py:196-222`) takes `_stop_transition_lock` and, for an in-flight send, returns `stopping` without `_lock` (198-209); otherwise it waits on `_lock` (211) behind the whole sweep. A CPU kill of the tick releases the lock only by isolate termination (**Inference**), so Stop then lands on a fresh object.

## 3. Summary table

| Read | Entry | DO / lock | Runs in same invocation | If slow | If too large / throws | If CPU or memory kill | If partial |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Picker, future date | HTTP GET clinics -> RPC `list_clinics` (`worker.py:481-502`, `send_gate.py:811`) | `next-is-you-system`, no lock | Nothing else; shares isolate and event loop with a concurrent tick | `timeout` after 10 s, manual entry | `schema_drift` / `no_observation`, manual entry | Unhandled error to organizer; may take down a concurrent tick in the same isolate (Unconfirmed) | Incomplete dropdown, no signal |
| Start, future draft | HTTP POST start -> RPC `start_visit` (`worker.py:569`, `send_gate.py:271`) | same, holds `_lock` | Start only; blocks tick, Stop and sends while held | `schedule_unavailable`; tick and Stop wait | `schedule_unavailable`, draft unchanged | Unhandled error, nothing stored | False `doctor_not_scheduled` and draft flagged |
| Daily recheck | DO alarm -> `_scheduled_tick` -> `prepare_tick` -> `_preflight_sweep` (`send_gate.py:76-135`, `scheduler.py:115, 279`) | same, holds `_lock` | Lifecycle (before), running-visit read and doctor-change handling, reminders, LINE sends, stop finalization (after) | Visit read delayed, Stop waits | Draft unchanged, visit read still runs, but refetched every tick | Visit read and LINE sends lost this tick and every following tick while the draft is due | False mismatch flag, marked checked for the day |

## 4. Points that bear on the two designs in the research note

- One streamed read in the existing invocations keeps all three call sites as they are; the CPU per invocation stays the whole parse. For the recheck it still sits in front of the visit read in the same alarm invocation (`scheduler.py:115` before `:122`), which is the case the #188 acceptance criterion "a running visit's read in the same tick still happens" is about.
- Storing the page in DO SQLite and scanning one slice per alarm step needs a completeness marker: today any non-empty row list is `ok` (`ntuh_reader.py:557-559`), and a partial `ok` produces false `NOT_SCHEDULED` in both Start and the sweep. The picker and Start are synchronous HTTP requests, so they cannot wait for later alarm steps; they would need to read an already complete stored scan or refuse as unavailable.
- Moving the recheck out of the visit tick removes the starvation path: today a failing or overrunning sweep is retried every tick and always runs first.
- The 60 s memo is per reader object and a reader is rebuilt per call (`send_gate.py:806`), so the picker, Start and the sweep never share a fetched page today.
- The size cap is applied after a full download into memory (`ntuh_reader.py:1734`, `1653`), so it limits parse cost, not download memory.
