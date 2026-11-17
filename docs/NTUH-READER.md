# NTUH first-hospital reader (Issue #20)

Supported scope: NTU Hospital main campus (branch `T0`), department ophthalmology (`OPH`), morning, afternoon or evening session of the day the owner entered, read from the official public registration progress list on `registration.ntuh.gov.tw`. Other departments, other dates, and Shin Kong stay explicitly unavailable. The session is the `AmpmCode` the reader sends, not a clock: there are no hardcoded session hours anywhere in this reader, so no session needs verified hours to be read. Evidence: Issue #17 report, plus the 2026-10-29 reads that captured the request contract, the fragment's markup and how a clinic starts and ends; the owner approved scheduled reads for family-internal, non-commercial use at one read every 2 to 3 minutes.

**Validation status: fixture and local integration only. Live hospital behavior is unverified.** No test or CI run contacts the hospital. Source evidence is not LINE acceptance or handset delivery.

## Enabling

The reader is off by default. `NTUH_READER_ENABLED=1` enables it only in local-test/rehearsal mode. Production does not read the live hospital or activate reminders until the Issue #22 pilot; Start reports the source unavailable, scheduled ticks remain held, and scheduler status reports the reader unavailable. A trustworthy observation means the fetched source read is fresh, matches the configured supported scope and has one unambiguous positive current number. The source list does not label department or session, so the configured OPH afternoon scope is not confirmed by the returned row. Trust does not mean the number is accurate against the room's physical light; that accuracy is unverified. Live behavior remains unverified.

## Entering the clinic

The reminder form has no doctor or room fields, so the NTUH clinic code carries them as `room/doctor/clinic type`, for example `11診/王小明/醫師約診`, with department code `OPH`. Each part must equal the clinic card (compared ignoring case, spaces and punctuation). The reader pins the source's Traditional Chinese rendering, because that is what the owner's registration slip says; the same page in English renders the same clinic as `Room 11 / Hsiao-Ming Wang / Dr. Appt.`, which would not match. Any other shape is rejected as a scope mismatch without a request.

## How a read is made

The site's own page does not put clinic rows in the progress page's HTML. One read is two requests:

1. `GET https://registration.ntuh.gov.tw/WebReg/WebReg/ClinicCurrentLightNo?vHospCode=T0` for the `__RequestVerificationToken` hidden input and the session cookies. No clinic rows come back here.
2. `POST https://registration.ntuh.gov.tw/WebReg/WebReg/DeptLightTable` with those cookies, `X-Requested-With: XMLHttpRequest`, and the form body `__RequestVerificationToken`, `vHospitalCode=T0`, `DeptCode`, `RegionCode=`, and `AmpmCode` (`1` morning, `2` afternoon, `3` evening). The reply is an HTML fragment of clinic cards.

Both requests send `Accept-Language: zh-TW` and the `Localization.CurrentUICulture=zh-TW` cookie, so the rendering stays Traditional Chinese whatever the server would otherwise negotiate. The pair shares one 10-second budget and never follows redirects. Because the department and the session are now request parameters, the returned cards are the ones for the department and session the owner entered, rather than whatever a default view would have returned.

A card looks like this, and the reader reads `room-number`, `clinic-doc-name`, `clinic-type`, `number` and `according-to-order` from it:

```html
<a href="/WebReg/WebReg/ClinicCurrentLightNoDetail?ServiceIDSE=..." class="open-link">
  <div class="room-number">11 診</div>
  <div class="row room-content g-0">
    <div class="col-7">
      <div class="clinic-doc-name">王小明</div>
      <div class="clinic-type">醫師約診</div>
    </div>
    <div class="col-5 align-items-stretch">
      <div class="number"> 025 </div>
      <div class="according-to-order pt-2"></div>
    </div>
  </div>
</a>
```

## Reading rules

- Match: room, doctor and clinic type must all equal one clinic card. Zero cards or several cards never produce a number. The current number is never inferred from neighbors, "Expected Call Number" is never read, and the fragment's "Last updated" is ignored (it is render time).
- Blank current light means no data, never zero. `0` or non-numeric text is invalid data. A card whose `according-to-order` says the clinic calls by check-in order reports no observation, because its number is not a called number.
- Freshness is the time the reader fetched the page. An observation older than 2 minutes cannot start a reminder or support a scheduled alert. A usable read is not evidence of physical-light accuracy; no accuracy claim is made.
- Watch window: reads happen on the day the owner entered and nowhere else; the scheduler's 23:59 Taipei cutoff closes the visit from above. Within that day the clinic's own number marks the window. A card that has never shown a number today has not started, which is not a failed read and sends no alert. The first valid number opens the watch. Once open, the number going blank - or the card vanishing - for two reads in a row ends it, and the clinic is not read again that day.
- Cadence: the one-minute cron only offers a chance to read. Each clinic has independent cadence and retries: one read every 5 minutes before the clinic has called anyone, and one every 2 minutes from the read that first sees a number. Repeated reads for the same clinic in one tick share its result; different clinics read independently. Transient Durable Object state retains only the matched card for that clinic (room, doctor, clinic type and current number), whether it has called today and how many blank reads are in the current run, or its failure outcome; unrelated cards and raw responses are discarded. State is pruned daily. Cross-clinic read sharing may be considered as a future optimization outside Issue #20.
- Failures: a timeout, HTTP 408/429/5xx or other transport error retries after 1, then 2, then 4 minutes (capped), honoring `Retry-After` up to 10 minutes. A challenge or CAPTCHA marker, HTTP 401/403/451, or any redirect on either request stops reading that source for the day and shows "來源拒絕讀取". A selector page without a token fails closed as `schema_drift` and the POST is never sent. Nothing bypasses, solves or works around a challenge; the only cookies sent back are the ones that read's own selector request received, and none are kept between reads.
- Unusable reads inside the watch feed the existing unavailable alert (third consecutive unusable read, once per recipient). Skipped ticks, a clinic that has not started and a clinic that has ended are not unusable reads. A clinic ending can never raise that alert on its own: two blank reads end the watch and three are needed to alert.
- End of clinic: the first blank read after the clinic has been calling is an unusable read, because a single blank may be the source hiccuping. The second one ends the watch: reading stops, no unavailable alert is sent, and the reminder shows "來源沒有可用資料" until it expires at the normal cutoff.
- If the reader's transient state is lost mid-clinic, the clinic reads as not yet started again. That keeps the watch open on a sparse cadence rather than declaring an end that was never observed.

## Source evidence and known gaps

The request contract and the card markup above were captured on 2026-10-29 with two plain requests against the owner's host, and the parser reads that captured page correctly (`research/private/source-evidence/ntuh-oph-clinic-end-2026-10-29.md`). What remains unverified is the reader's own behavior against the live source: no test, CI run or deployment has issued these requests from the Worker, and the fixtures below are synthetic pages shaped from the captured markup. Markup that does not produce a complete card fails closed as `schema_drift`. Accuracy against the room's physical indicator is unproven.

The same evidence rules out two things the reader must not start doing:

- **A listed card does not mean the clinic is consulting.** Cards appear as soon as a session is scheduled for the day, hours before it starts, and stay listed after the clinic has finished. Card presence says the clinic is scheduled for the requested session, nothing more, which is why the watch is keyed on the number rather than on the card.
- **The current light is the number most recently called, not a queue position.** It can jump to any checked-in number: a 44-number backward move was observed within the same session, when a doctor called a number that had been waiting since the start. Nothing may read it as "how far the clinic has got".

The start and end signals come from two clinics watched through their transition on 2026-10-29: both kept their card and blanked their number when they finished, while a clinic that had not started showed a blank number and a blank highest-called number on its detail page. That is one department on one morning. What it does not cover: whether a clinic can blank its number temporarily and resume, what a cancelled clinic looks like, and what happens in a room when its next session begins. The two-blank-reads rule is the margin left for the first of those.

## Future-date schedule reader (Issue #58)

The today-only `DeptLightTable` path above covers the live queue number. A separate reader, enabled by the same `NTUH_READER_ENABLED` flag, serves `list_clinics` for dates in the next 14 days against the dept-wide `RegDeptSchedule` page.

The pre-flight path answers one question only: for the chosen visit date, department and (session, room, doctor), is this clinic published on NTUH's own schedule? It does not read queue numbers, and the queue-side `DeptLightTable` reader keeps its today-only contract unchanged.

### How this read is made

One GET against `GET https://reg.ntuh.gov.tw/WebReg/WebReg/RegDeptSchedule?vhospCode=T0&showBlock=A&vDeptCode=<DeptCode>&realSubDeptCode=showAll`, with `Accept-Language: zh-TW` and `Localization.CurrentUICulture=zh-TW`. No token, no POST. The returned page lists every weekday in the active 14-day window with its sessions and per-doctor clinic cards. The parser pins the day-column `MM/DD` against the caller's Taipei today year, so a window that crosses December into January still resolves correctly.

Per clinic card the reader records `(visit_date, session, room, doctor, 診別, status)` from the schedule's own markup; the modal's 預約碼 is observed as evidence (`research/private/source-evidence/ntuh-schedule-2026-11-03.md`) but is not stored, since the visit-day card does not carry it.

### Match contract

Pre-flight matches on `(visit_date, session, room, doctor)` only. The schedule's `診別` vocabulary (`角膜`, `網膜`, `教學門診`, `葡萄膜炎`, `眼神經`, `眼整型`, …) is different from the visit-day card's `clinic_type` vocabulary (`醫師約診`, `特別門診`, `教學門診`, `日間手術`, `代診`), and the two sets overlap only on `教學門診`. The schedule's 診別 is kept on the draft until the moment its `visit_date` reaches today, at which point the Start-time path rewrites the stored `clinic_code` to the today-side `clinic_type` from `DeptLightTable`. After that rewrite the existing visit-day reader's `(room, doctor, clinic_type)` matcher keeps working unchanged.

### Status markers

Cards carry a status marker inside `<div class="tag"><div class="first-reg">...</div></div>`. The reader drops rows whose status is `停診` or `颱風停診` (the clinic will not run that day). Registration-restriction markers (`額滿`, `已逾當日掛號時間`, `代診不續掛`, `代診可續掛`, `僅存本院初診`, `本院初診`, `本科初診`, `本科複診`, `18:00開放`) leave the clinic running and keep the row in the roster, since a patient who already has a number is unaffected by registration-side limits.

Each listed clinic also carries a dropdown `label` (`room · doctor（session）`, for example `05 · 合成醫師乙（早診）`) and ordered `details`. Today's roster lists 診間, 醫師, 診別 and 時段 from the light-table card. A future day lists 診間, 醫師, 科別 (the text before the `|` in `.sub-spec`), 診別, 時段 and, when the card shows one, 狀態 (the status marker verbatim, which is where 額滿 and 代診 markers appear).

### Reason codes returned to the setup picker and Start

- `visit_date_past` - the chosen date is before Taipei today. Returned by both `list_clinics` and Start.
- `visit_date_out_of_schedule_window` - the chosen date is more than 14 days ahead, so the clinic schedule does not cover it yet. The reader answers without contacting NTUH and adds `schedule_end` (Taipei today plus 14 days) and `release_time` (00:00 Taipei, 14 days before the chosen date, per NTUH's "Schedule from midnight on 14 days before consultation"). The setup form shows the not-yet-published notice from these and degrades to manual entry.
- `scope_mismatch` - the hospital or department is outside the supported scope (not NTUH main or not OPH).
- `no_observation`, `access_denied`, `timeout`, `schema_drift` - transport or shape failures from the schedule page itself; the picker degrades to manual entry and Start fails closed as `schedule_unavailable`.
- `doctor_not_scheduled` - the schedule read succeeded, but no row for the chosen date matches on `(session, room, doctor)`. Only Start returns this; the picker catches it earlier by refusing a dropdown mismatch.

### Daily sweep (Issue #58, R1)

A once-per-Taipei-day sweep runs over every draft whose `visit_date` is after today and that has not been checked today, for hospitals that publish a clinic schedule. No day count bounds the query; the reader decides whether a day is published. Drafts of the same `(hospital, department)` share one schedule fetch. For each draft the sweep matches on `(session, room, doctor)`; a draft whose doctor is no longer on the schedule, or whose matching row has status `停診`/`颱風停診`, transitions to `scope_mismatch` and raises the standard organizer-attention signal. A schedule read that fails is a no-op this run; the sweep retries the next day. Drafts whose `visit_date` is today are handled by the Start-time resolve step, not the sweep. A day the hospital has not published yet marks the draft checked today and leaves its source-read status untouched, so the next Taipei day asks again; the reader answers that without contacting the hospital.

## Recovery

- Unavailable with a timeout, no observation or no result: wait; the reader retries by itself while the clinic is still calling. Start again after the reason clears.
- "來源沒有可用資料" all day with no reminder: the clinic never showed a number for the department, session and clinic code entered. Open the official page, pick the same department and session, and compare the card's room, doctor and clinic type against the draft; a session or a doctor that does not match is the usual cause, and the reader cannot tell that apart from a clinic that has not started.
- Access refused: do not retry by hand around it. Open the official page in a browser to see what changed. The block lasts for the rest of that day.
- Scope mismatch or schema drift: correct the department and clinic code, or update the parser after a fresh manual check of the page.
- `visit_date_out_of_schedule_window` on a draft: the chosen date is more than two weeks out. The draft is held; the daily sweep will validate it on the first sweep after the hospital publishes that day.
- `doctor_not_scheduled` or `schedule_unavailable` at Start: open the setup form, re-pick the doctor from the dropdown (now constrained to the schedule), or wait a few minutes and retry if the source was briefly down.
