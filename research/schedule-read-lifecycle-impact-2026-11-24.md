# Clinic schedule read (#188): what options A and B do to each visit situation

Written 2026-11-24. Read only: from code at `27b9841` (main), tests, `docs/NTUH-READER.md`, `GLOSSARY.md`, ADR 0005, `docs/HTTPS-SERVICE.md`, and issues #188, #130, #144, #148, #150, #172, #179, #192. The live hospital was not contacted, nothing was run against Cloudflare, and no test was run. Labels: **Code** (read from source), **Doc** (stated in a repo doc or issue), **Inference** (my reasoning).

- **Option A:** one streamed GET of `showAll`, with the unused modal markup (and white space) dropped before parsing, all in one invocation.
- **Option B:** one GET whose bytes are stored in Durable Object SQLite. Later alarm steps each scan one slice. The whole read fails if the clinic count does not match.

## 0. Facts that decide most of the answers

1. **Only days 1 to 14 ahead read the clinic schedule page.** On the visit day the picker and Start use the light table (`DeptLightTable`), not `RegDeptSchedule` (**Code**: `ntuh_reader.py` `list_clinics` and `match_clinic` branch on `days_ahead == 0` to `_list_today_roster`). Visit-day monitoring reads the light table and the detail page. Neither A nor B touches anything that happens on the visit day itself.
2. **No family LINE message depends directly on a schedule read.** Only `near` and `unavailable` exist (`migrations/0008...sql` CHECK, `scheduler.py` `_MESSAGES`), and #130 decides "nothing before the visit day" for the family. Families are affected only indirectly: (a) when a schedule read in the same tick costs a running visit its read or delays its send, and (b) when a wrong schedule answer flags or (after #148) stops a visit that is in fact fine.
3. **Where the schedule page is read today (Code):**
   - Picker: `GET /api/organizer/hospitals/{h}/clinics` -> `SystemSendGate.list_clinics` RPC (not under the gate lock) -> `_list_future_schedule`. The browser shows a spinner (`正在向院方讀取該日門診排班…`) and keeps Save disabled until the answer arrives. It has no client timeout. A thrown error becomes `no_observation`, and the form drops to manual entry (`frontend/src/main.ts` `maybeFetchRoster`, `rosterPending`).
   - Start of a future visit: `start_visit` -> `_preflight_validate` -> `match_clinic`, run inside `async with self._lock`, the same lock the tick holds. Start answers synchronously with `active` or an error code.
   - Daily recheck: `OutboxScheduler.prepare_tick` calls `_preflight_sweep` **first**, before it reads any running visit. The sweep and the visit read share one alarm invocation, under the gate lock. LINE sends happen after `prepare_tick`, in the same alarm.
4. **The reader is built new for every call** (`_hospital_reader()` returns a new `RegistryHospitalReader`). So `_schedule_memo` (60 s) is shared only inside one tick or one call. Nothing is shared between a picker read, a Start and the sweep.
5. **A failed sweep read is retried on the next tick, not the next day.** **Code:** on a transient reason (`no_observation`, `access_denied`, `timeout`, `schema_drift`) or an exception, `_preflight_sweep` does `continue` without `mark_preflight_checked`, so `drafts_due_for_preflight_sweep` returns the draft again at the next alarm (1 minute while any visit is running, 5 minutes otherwise). A failed read is never memoized (`test_a_failed_schedule_read_is_not_remembered`), so in one tick every draft of that department fetches again. `docs/NTUH-READER.md` ("Daily sweep") and the comment on `_SWEEP_TRANSIENT_REASONS` both say "retries the next day". This is doc/code drift, and it matters for both options (see S9 and S12).
6. **Today a 內科 page is fully downloaded and converted before it is refused.** `WorkersFetcher` does `str(await response.text())`, and only then does `_transport_failure` compare against `MAX_SCHEDULE_BODY_CHARS`. Every refused read pays the full CPU and memory cost.
7. **The schedule read has no completeness check.** `parse_schedule` returns `ok` when it finds any rows and no challenge marker. No end marker or `doctor-tag` count is checked (**Code**: `_ScheduleCollector`, `parse_schedule`). A 200 page cut short today reads as "ok" with fewer rows.
8. **One running visit at a time** (#172, `has_other_running_visit`). A visit started days ahead is `active` and holds that place. Any number of drafts can exist, and the sweep covers them all. #148 (open) extends the daily recheck to running future visits.
9. **The ledger covers non-draft visits** (`scheduler_ledger_digest` reads `WHERE state != 'draft'`). A tick killed after a write to a running visit, but before `_save_ledger`, causes `d1_ledger_mismatch` -> recovery hold -> send interruption (ADR 0005, Consequences). Sweep writes to drafts are outside the ledger today. #148's writes to running visits would be inside it.
10. **A deployed environment is held today.** `local_test_mode` gates every hospital read, so all of this is about Staging once it is live (#142) and about #180 adding 內科 and 骨科. Today only 眼科 (`OPH`) is offered.

## 1. Situation by situation

Each entry gives: current behavior; risk under A; risk under B; what the organizer and the family would see; tests that cover it today.

### S1. Organizer picks a clinic (picker, a day 1 to 14 ahead)

- **Current.** One synchronous GET plus parse inside the picker RPC. Spinner until it answers. A failure becomes manual entry (`degradeNotice`), or after #150 a draft whose clinic is still to be chosen. 內科 is refused as `schema_drift` (over 3.5 M chars) after a full download.
- **A.** The latency stays about what it is now: one NTUH round trip plus a parse that should be much cheaper. Risk: if the streamed parse still runs over 10 ms CPU, the RPC may be terminated (`exceededCpu`). The browser's `listClinics` then throws, and the organizer silently gets manual entry or "clinic to be chosen" instead of a list. No family impact.
- **B.** **Noticeable latency.** The answer is ready only after every slice is scanned. From the research note's numbers (regex extractor about 3 ms CPython for all of 內科, about 4 to 5 times that in Pyodide; HTMLParser after dropping modals about 25 ms CPython), and with alarm steps about 1 s apart plus 3 to 8 ms of alarm overhead each, that is roughly 3 to 8 steps (a few seconds) with a cheap extractor, or 20 to 60 steps (20 s to over a minute) with HTMLParser (**Inference**). An alarm retry starts at a 2 s delay and adds to this. Today's picker has no pending state that survives a reload, and no timeout. The HTTP request would either hang that long or need a new "reading, come back" protocol with polling, which adds Worker and DO requests against #192's budget. If the organizer changes the date, the same department's page serves all 14 days, so a stored read could answer the new date instantly. That is an upside of B, but only if the stored read is reused across requests, which A could also do with a memo.
- **Organizer sees.** A: unchanged. B: a spinner for seconds to a minute, or a new "still reading" state. Family: nothing.
- **Tests.** `test_ntuh_reader.py`: `test_list_clinics_future_date_filters_schedule_and_drops_cancelled`, `..._reports_no_observation_when_cancelled_only`, `..._timeout_degrades_without_crashing`, `test_future_roster_labels_and_details_match_the_schedule_cards`, `test_list_clinics_rejects_date_beyond_schedule_window`, `test_list_clinics_rejects_past_date_without_fetching`, `test_gate_roster_wire_carries_label_and_details`, `test_gate_roster_is_held_without_the_reader`. Browser: `test_local_acceptance_hospital_fallbacks.py::test_failed_clinic_schedule_read_falls_back_to_manual_entry`. Frontend: `setup-form.test.js` (clinic inside or outside the returned schedule). **Not covered:** the loading state or its duration, a large page, a slow multi-step answer.

### S2. Start (visit 1 to 14 days ahead)

- **Current.** Under the gate lock, `match_clinic` does one GET plus parse. Then `active` (future visits need no live observation) or a typed refusal: `doctor_not_scheduled`, `schedule_unavailable`, `visit_date_out_of_schedule_window`, `observation_invalid`, and so on. While Start holds the lock, a tick and a Stop wait behind it for the whole NTUH round trip (up to the 10 s budget).
- **A.** Same shape. If the read overruns the CPU limit and Start's RPC is cut, the browser gets a failure. Start is all-or-nothing before `repository.start`, so no half-started visit is left. The organizer sees an error and can press Start again.
- **B.** **Start can no longer answer synchronously from a fresh read.** Either (a) Start returns a new pending state ("checking the clinic schedule"), the organizer waits seconds to a minute, and the frontend must poll and handle refresh, navigating away and a draft edited meanwhile (a stale edit: the read finishes for the old clinic code); or (b) Start trusts a stored read from earlier (the picker's or the sweep's). Then a cancellation (停診) posted between that read and Start goes unseen until the next daily recheck, and for a running visit that recheck only exists once #148 lands. The steps must not hold the gate lock across alarms, or ticks and Stop are blocked for the whole read.
- **Organizer sees.** A: unchanged. B: a pending Start, a new lifecycle state, with its own success, failure and cancel outcomes (AGENTS.md: lifecycle UI must define them). Family: nothing, since nothing is sent before the visit day.
- **Tests.** `test_ntuh_reader.py`: `test_preflight_blocks_start_when_date_is_out_of_schedule_window`, `..._when_doctor_not_scheduled`, `..._when_schedule_source_is_unreachable`, `test_future_date_start_transitions_to_active_without_an_observation`, `test_start_on_an_earlier_day_degrades_to_schedule_unavailable`, `test_preflight_resolve_rewrites_clinic_code_for_same_day_schedule_sourced_draft`. `test_start_match_outcomes.py` (every match outcome, all cancelled, unparseable code). `test_organizer_api.py::test_start_refusal_for_unpublished_day_carries_end_date_and_release_time`. **Not covered:** Start with a large or slow page, Start racing a draft edit.

### S3. Start on the visit day

- **Current.** Uses the light table and `observe_for_start`. No schedule page is read.
- **A and B.** No effect.
- **Tests.** `test_visit_day_matching.py` (same-day Start cases), `test_ntuh_reader.py::test_a_schedule_form_clinic_code_reads_the_visit_day_card`.

### S4. Active monitoring: progress reminders and the near reminder

- **Current.** Reads only the light table and the detail page. But in the same alarm, `_preflight_sweep` runs **before** the visit read and before the sends. If drafts are due, each GET (10 s budget each, not memoized on failure) delays the visit read and its near reminder by the wall time. If CPU is exceeded during the sweep, the whole alarm is lost: no visit read, no send that tick. Because the draft is not marked checked (fact 5), the next tick repeats the same expensive read. **Inference:** with a 內科 draft and a running visit, every tick could overrun at the sweep step, and the running visit could go unread for as long as that lasts. The family would get no near reminder. Once three reads count as unusable, the unavailable message would fire, but only if the visit read is reached at all. A skipped tick does not count as unusable, so possibly not even that.
- **A.** A cuts the CPU, but the sweep still sits in front of the visit read in the same invocation. #188's acceptance criterion "a running visit's read in the same tick still happens" needs a reorder (visit reads and sends first, recheck last) or a separate step. That is true under A too.
- **B.** The slices run in their own alarm steps, so the running visit's read gets its own invocation, which meets that criterion by construction. New risk: the Durable Object has **one** alarm. Scan steps about 1 s apart and the 1-minute tick share it, so the handler must choose per step. If scan steps take priority, or each step also runs the full tick, the visit's 2-minute cadence can slip and the near reminder comes late. If each step runs the full tick, per-step CPU is tick plus slice, which defeats B. The steps need an explicit rule that the visit read and its sends go first.
- **Family sees.** Current or A without a reorder: late or missing near reminders on a day when a draft recheck is due. B done carelessly: reminders late by the steps queued ahead of them. Organizer: nothing new.
- **Tests.** Visit-day reminder logic: `test_visit_day_matching.py::test_a_visit_started_three_days_ahead_reaches_a_near_reminder`, `test_ntuh_reader.py::test_scheduled_checks_repeat_near_alerts_as_the_number_moves`, `test_reminder_kinds.py`, `test_scheduler_outbox.py`. **Not covered:** a tick with a due draft recheck and a running visit together, or a slow or failing sweep in front of a visit read.

### S5. LINE notification sent or not sent

- **Current.** Sends are made after `prepare_tick` in the same alarm, each under the lock, with ledger checks. A sweep that delays or kills `prepare_tick` delays or drops that tick's sends. Queued events are retried on later ticks (`retryable_events`), so a dropped tick delays a send rather than losing it, as long as the event was created. A near reminder whose read never happened is never created.
- **A.** Same as S4. A duplicate is unlikely: retry keys and the outbox are unchanged.
- **B.** Alarms are at-least-once. A repeated scan step must be idempotent. Today the sweep writes only `set_source_read` and `mark_preflight_checked`, which are idempotent. Once #130 adds organizer LINE pushes on a confirmed mismatch, a repeated final step could push twice unless the push goes through the outbox with a retry key. A partial result (S7) must never reach a push.
- **Who sees.** Family: a late send (current and A), or none for a near reminder that was never created. Organizer, after #130: a possible duplicate push under B if steps are not idempotent.
- **Tests.** `test_scheduler_outbox.py`, `test_line_push.py`, `test_delivery_state.py`. **Not covered:** sends in a tick whose sweep is slow or fails.

### S6. Pause or interruption (send interruption, recovery hold, not live)

- **Current.** On a recovery hold, or when not in local test mode, the tick returns before `prepare_tick`, so no sweep and no visit reads. Start refuses with `scheduler_held` when the ledger does not match. The picker is **not** gated by a hold. It reads whenever a reader exists. A tick killed between ledger-covered writes **causes** a send interruption (ADR 0005).
- **A.** No change. One more reason to keep the recheck's writes to running visits (#148) out of an invocation that can overrun: an overrun after a write to a running visit and before `_save_ledger` would put the whole environment into a send interruption.
- **B.** If scan steps run inside the alarm path that returns early on a hold, a picker read waiting on steps never finishes while sending is interrupted, and the organizer sees an endless spinner (no client timeout). Decide whether reading for the picker continues during an interruption (it sends nothing) or fails fast with a reason. Stored pages must also be dropped or expired across a long interruption. A page stored before the hold must not answer after it.
- **Organizer sees.** B: possibly a hung picker or Start during an interruption. Family: no change (nothing is sent during an interruption anyway).
- **Tests.** `test_held_service.py`, `test_held_service_runtime.py`, `test_gate_roster_is_held_without_the_reader`. **Not covered:** the picker during a recovery hold.

### S7. Doctor or clinic mismatch (not scheduled, cancelled, moved)

- **Current.** `match_clinic` gives `NOT_SCHEDULED` when the visit's day has live rows but none match. It gives `CANCELLED` for 停診 or 颱風停診. Start refuses with `doctor_not_scheduled`. The sweep sets `scope_mismatch` on the draft (needs attention). After #148, a running future visit is stopped and returned to draft.
- **Partial read (both options), the most misleading case.** Day blocks are in order. A page cut short in the middle of a day keeps that day's earlier cards and loses the rest. The day still "has live rows", so a clinic in the lost tail reads as `NOT_SCHEDULED`. That is a **confirmed mismatch** (`GLOSSARY.md`: the hospital "states outright"), when the hospital stated nothing of the kind. Today: Start refused, or the draft flagged "院方門診表上，這天沒有這位醫師". After #148: a correct running visit is stopped and sent back to draft, and the organizer may cancel a real appointment. Cut-off days lose every card, and `not live` gives `no_observation`, which is safe.
  - A: a stream that ends early must be failure, not "ok". Needs an end-of-page marker, a `doctor-tag` button count equal to the rows, and a byte or char cap that refuses rather than truncates. Today none of this exists (fact 7).
  - B: the same checks, plus every slice from one fetch (one read id). A missing or failed slice fails the whole read. A step that ran twice must not add rows twice. Note that "the clinic count matches" is not enough on its own: on a page truncated before it was stored, the button count of what is there matches its rows. The end marker must be checked too.
- **Organizer sees.** A wrong "not on the schedule" or "cancelled" if completeness is not enforced. Family: after #148, a visit wrongly stopped, so no reminders on the day.
- **Tests.** `test_ntuh_match_clinic.py` (session, room and doctor matching, cancelled, typhoon, other session not scheduled), `test_preflight_sweep.py` (`..._flags_a_draft_whose_doctor_is_no_longer_scheduled`, `..._is_cancelled_in_schedule`), `test_start_match_outcomes.py`. **Not covered:** a truncated or incomplete page, a count mismatch, an end marker.

### S8. Clinic not found

- **Before the visit day.** The picker has no rows for the date: `no_observation`, and the form drops to manual entry (to "clinic to be chosen" after #150). The same partial-read risk as S7 applies. A date cut off by truncation looks like "the hospital list could not be read". That is safe but wrong in its reason, and with B a stale stored page (S10) could also lack a newly published day.
- **On the visit day** (`card_not_found`, light table): not affected by A or B.
- **Tests.** `test_list_clinics_future_date_reports_no_observation_when_cancelled_only`. Visit day: `test_visit_day_matching.py::test_an_unlisted_card_sends_nothing_before_the_session_start`, `..._counts_as_unusable_once_the_session_has_started`, `test_a_doctor_absent_on_the_day_needs_attention_with_the_reason`.

### S9. Daily recheck

- **Current.** It runs in every tick until each draft is marked for the day. Drafts of one department share a fetch only inside one tick and only on success. On failure it repeats every tick (fact 5), and on failure it also repeats per draft within the tick. Today's 內科 case: every tick, every 內科 draft downloads 6.9 M chars and is refused. That is CPU and memory each time, and one GET to NTUH per draft per minute while a visit runs, above the 2 to 3 minute rate the owner approved for progress pages (`docs/NTUH-READER.md`; `docs/ADDING-A-HOSPITAL.md` access rules) (**Inference** from code; no test pins it).
- **A.** Fixes size and memory. It still needs (a) to run after, or apart from, the running visit's read (S4), and (b) failure memoized for the day, or backed off, so that one failing department does not re-read every tick. That is what the docs already promise.
- **B.** The recheck becomes a multi-step job. A recheck started near 23:59 Taipei and finished after 00:00 mixes two days. `today` must be fixed at fetch time, and `_forget_other_days` must also drop stored pages and progress of other days. Several departments (OPH, MED, ORTH after #180) each need their own multi-step read: they either queue, which adds up their latency, or store pages side by side (8 MB per SQLite value, a 7.2 MB page leaves little room, so slice across rows). A picker read arriving mid-recheck for the same department should reuse that read, not start a second one.
- **Organizer sees.** Current: possibly nothing at all (the recheck never succeeds), and no "needs attention" for a real cancellation. A or B: the recheck result, once a day. Family: nothing before the visit day.
- **Tests.** `test_preflight_sweep.py` (still scheduled, no longer scheduled, cancelled, `test_sweep_is_a_noop_when_schedule_source_fails` (one tick only), idempotent within a day, again on the next day, window edge, unpublished then published, ignores today, `test_sweep_shares_one_fetch_across_drafts_of_the_same_group`, separate fetches across dates). `test_ntuh_match_clinic.py::test_matching_many_drafts_of_one_day_costs_the_hospital_one_request`, `test_a_failed_schedule_read_is_not_remembered`, `test_schedule_memo_keeps_only_the_current_day`. `test_current_number_only.py` (sweep skips current-number-only drafts). **Not covered:** retry cadence after a failure (doc says next day, code does next tick), running future visits (#148), a recheck spanning midnight.

### S10. Hospital page failing or stale

- **Failing (current).** Timeout, 5xx or no observation: transient, so Start gives `schedule_unavailable`, the picker drops to manual entry, and the sweep skips the draft (and retries next tick). A challenge, 401/403/451 or a redirect gives `access_denied`. #179 (open) will make that stop every read of the hospital, picker and Start included.
  - A: a new failure appears in the middle of the stream (connection reset after part of the body). It must map to `no_observation`, never to partial rows (S7). A challenge marker can sit anywhere, and `_page_status` today scans the joined text of the whole page. A streamed reader that drops modals must still scan all the text it drops for challenge and denial markers, or it may read a challenge page as an empty schedule. A byte cap replaces the char cap.
  - B: the fetch step can fail after storing part of the body. Every slice must come from one complete stored body. A refusal seen in any slice must stop the read and, after #179, the hospital, without later slices still being processed. A refusal found only at slice k means slices 1 to k-1 were already scanned, which is harmless if nothing is published before the end.
- **Stale.** Today every read is fresh: no cross-call cache, and the observation's freshness rule (2 minutes) applies only to visit-day progress. A has no stored copy, so no new staleness. B keeps a stored copy. Rows describe the fetch time, not the end of the scan. A stored page reused by a later Start or picker call can show yesterday's roster or miss a 停診 posted since. **Rule needed:** a maximum age, tie the read to its fetch time and Taipei day, and delete the stored page after the read (it is a public page, but the research note recommends deletion).
- **Organizer sees.** B with reuse: a roster or Start check that is older than it looks. A: unchanged.
- **Tests.** `test_a_source_failure_is_unavailable_with_its_reason`, `test_list_clinics_future_date_timeout_degrades_without_crashing`, `test_list_clinics_is_unavailable_when_a_session_is_denied` (light table), `test_preflight_blocks_start_when_schedule_source_is_unreachable`, `test_parse_schedule_returns_schema_drift_on_empty_markup`. **Not covered:** a challenge page as the schedule response, a mid-stream failure, a page over the cap.

### S11. Stop or cancel

- **Current.** `stop_visit` takes the gate lock (unless a send for that visit is in flight), so a Stop pressed during a tick waits for the tick to finish, sweep included. That can be several 10 s schedule timeouts when NTUH's `reg.` host is slow, and the organizer's Stop button spins that long. Editing a draft (`update_draft`) also waits on the lock.
- **A.** The same lock behavior. Shorter CPU, but the same network wait, so Stop is still delayed while a recheck GET is pending. Moving the recheck out of the locked section removes this.
- **B.** If each step holds the lock only briefly, Stop waits less. New cases: the organizer edits or deletes a draft whose read is in progress (B steps must check that the draft and its version still exist before writing a result). The organizer leaves the picker mid-read (the steps should stop or be shared, not run on at a cost). A Stop of a running visit while #148's multi-step recheck is mid-way must win: the recheck must not then "return it to draft" after the organizer already stopped it.
- **Tests.** `test_one_running_visit.py::test_start_succeeds_after_the_running_visit_is_stopped`, `test_scheduler_outbox.py` stop paths, `test_held_cleanup.py`. **Not covered:** Stop or a draft edit while a schedule read is in progress.

### S12. Two or more visits at once

- **Current.** Only one running visit (`another_visit_running`). A future-dated running visit holds the place until its day. Many drafts are allowed, and the recheck covers all of them in one tick.
- **A.** One department read per tick for all of its drafts (memo), but the read is repeated per draft and per tick on failure (S9). Several departments mean several full reads in one tick, which adds up CPU and wall time in front of the visit read.
- **B.** Several departments' multi-step reads either queue (latency adds up) or run interleaved (more state). When #172's limit is lifted, ADR 0005 already names "each alarm does one bounded step" as the path, so B's step machinery could be shared with per-visit steps. That is a long-term plus of B. But each extra kind of step competes for the one alarm, and the visit reads must stay first.
- **Organizer sees.** Current: `another_visit_running` on a second Start (unchanged by A or B). B: a picker for department X slower while department Y is being rechecked.
- **Tests.** `test_one_running_visit.py` (all four), `test_preflight_sweep.py::test_sweep_shares_one_fetch_across_drafts_of_the_same_group`, `test_sweep_separates_fetches_across_different_dates` (one memo key per department and day, so different dates of one department share one fetch).

### S13. A schedule read overlapping a monitoring tick

- **Picker vs tick (current).** The picker RPC is not under the lock and runs in the same Durable Object while a tick runs. Each has its own CPU budget, but they share the isolate's 128 MB. The current reader peaks at about 110 MB of Python allocations on 內科 (research note, CPython). A picker read of 內科 during a tick could exhaust memory and reset the isolate. Both in-flight requests are allowed to complete, but the cost falls on the visit's tick (**Inference**).
- **Start vs tick.** Serialized by the lock: one waits for the other (S11).
- **Sweep vs visit read.** Same invocation, sweep first (S4).
- **A.** Streaming keeps memory small, so the shared-isolate risk goes away. CPU stays per invocation. The sweep must still be moved behind, or away from, the visit read.
- **B.** Memory is small per step. Overlap moves into alarm scheduling: the scan steps and the visit tick share one alarm (S4). The picker's fetch step, if done in the picker RPC, overlaps a tick as it does today, but cheaply.
- **Tests.** None for any overlap. #188's criteria ask for one ("a running visit's read in the same tick still happens"; "a measurement, not an assumption, says whether the daily recheck and a running visit's read may share a tick").

### S14. Visit day boundary and expiry (for completeness)

- **Current.** `_forget_other_days` drops reader state of other days at the start of every tick. `expire_due_visits` closes visits at 23:59 Taipei. `match_clinic` and the sweep compute `today` from `now`.
- **A.** No new state.
- **B.** A stored page and its scan progress are new state of a day. They must be dropped by the same `forget_other_days` path. A scan that crosses midnight must use the fetch's `today` to resolve `MM/DD`, and the sweep must not mark a draft checked for a day it did not read.

## 2. Where B adds latency the organizer would notice

1. **Picker (S1):** seconds with a cheap extractor, up to about a minute with HTMLParser. It shows today as a spinner with Save disabled. This is the most visible cost.
2. **Start of a future visit (S2):** today immediate. Under B it is either pending for the same time, or answered from an older stored read (staleness instead of latency).
3. **Stop and draft edits (S11):** only if B's steps hold the gate lock. Otherwise B improves this.
4. **Near reminders (S4):** only if scan steps take the alarm ahead of the visit tick.

The daily recheck (S9) is not latency the organizer sees: it runs in the background, once a day.

## 3. Where a partial read could mislead

1. **A page cut in the middle of a day** reads as `NOT_SCHEDULED`, a confirmed mismatch, under either option, and **already today** (no completeness check). Start is refused, a draft is flagged, and after #148 a correct running visit would be stopped.
2. **B, the count check alone:** a body stored short gives a self-consistent count. The end marker and the size of the stored body must be checked as well.
3. **B, a mix of two fetches** (a repeated alarm after a re-fetch): rows from two moments. One read id per fetch.
4. **A or B, challenge markers inside dropped modal text:** a challenge or denial page could read as an empty or partial schedule if the marker scan skips what is dropped.
5. **B, a stale stored page** answering a later picker or Start call: a 停診 posted since is not seen.

## 4. Tests that would be needed (gaps found)

- Fixture/mock: a running visit's read and its near reminder still happen in a tick where the draft recheck's schedule read fails, times out, or is too large (#188 criterion 3).
- Fixture/mock: a sweep read that fails is retried when the doc says (next day, or backed off). Today the code retries every tick, and per draft within a tick.
- Fixture/mock: a truncated `showAll` page (cut in the middle of a day) is unreadable, never `NOT_SCHEDULED`. Same for a page over the cap and a page with a challenge marker inside modal markup.
- Fixture/mock, ADR 0006: the captured 內科, 骨科 and 眼科 pages as fixtures, the same clinic counts (439, 129, 118) before and after the change. Today's `tests/fixtures/hospitals/ntuh_oph_schedule.html` is an 8 KB synthetic page.
- B only: a repeated alarm step, a step after a draft edit or delete, a read across midnight, a read during a recovery hold, a picker request that arrives during a recheck of the same department.
- Browser (B only): the picker and Start pending states, with success, failure and give-up outcomes.

## 5. Bottom line for the choice

- Neither option changes anything on the visit day itself (light table and detail page), and neither sends a family message directly.
- Whichever option is chosen, three things are needed: run the daily recheck after, or apart from, the running visit's read; stop re-reading a failing department every tick; and add a completeness check so a short page can never become a confirmed mismatch. None of them depends on A or B.
- A keeps today's synchronous picker and Start. Its risk is only "does it fit in 10 ms", which is all-or-nothing and visible as a fall-back to manual entry or "clinic to be chosen".
- B always fits per step. It costs the organizer seconds to a minute on the picker and on Start, adds a new pending lifecycle state for Start, and brings new state to get right: alarm sharing with the tick, idempotent steps, the day boundary, staleness, and the hold path. Its advantages are that it separates the recheck from the visit read by construction, and that it builds the stepwise machinery ADR 0005 names for lifting #172.
