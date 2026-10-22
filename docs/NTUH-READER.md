# NTUH first-hospital reader (Issue #20)

Supported scope: NTU Hospital main campus (branch `T0`), department ophthalmology (`OPH`), afternoon session of the current day, read from the official public registration progress list (`reg.ntuh.gov.tw`). Morning session hours are unverified and outside the evidenced scope; morning requests return `scope_mismatch` without a source read. Other departments, the evening session, other dates, and Shin Kong also stay explicitly unavailable. Evidence: Issue #17 report; the owner approved scheduled reads for family-internal, non-commercial use at one read every 2 to 3 minutes.

**Validation status: fixture and local integration only. Live hospital behavior is unverified.** No test or CI run contacts the hospital. Source evidence is not LINE acceptance or handset delivery.

## Enabling

The reader is off by default. `NTUH_READER_ENABLED=1` enables it only in local-test/rehearsal mode. Production does not read the live hospital or activate reminders until the Issue #22 pilot; Start reports the source unavailable, scheduled ticks remain held, and scheduler status reports the reader unavailable. A trustworthy observation means the fetched source read is fresh, matches the configured supported scope and has one unambiguous positive current number. The source list does not label department or session, so the configured OPH afternoon scope is not confirmed by the returned row. Trust does not mean the number is accurate against the room's physical light; that accuracy is unverified. Live behavior remains unverified.

## Entering the clinic

The reminder form has no doctor or room fields, so the NTUH clinic code carries them as `room/doctor/clinic type`, for example `11/Hsiao-Sang Chu/Dr. Appt.`, with department code `OPH`. Each part must equal the list row (compared ignoring case, spaces and punctuation). The doctor name is taken from the list view because the detail page does not show it. Any other shape is rejected as a scope mismatch without a request.

## Reading rules

- Match: room, doctor and clinic type must all equal one list row. Zero rows or several rows never produce a number. The current number is never inferred from neighbors, "Expected Call Number" is never read, and the page's "Last updated" is ignored (it is render time).
- Blank current light means no data, never zero. `0` or non-numeric text is invalid data.
- Freshness is the time the reader fetched the page. An observation older than 2 minutes cannot start a reminder or support a scheduled alert. A usable read is not evidence of physical-light accuracy; no accuracy claim is made.
- Cadence: the one-minute cron only offers a chance to read. Each clinic has independent cadence and retries, with no more than one read per clinic every 2 minutes. Repeated reads for the same clinic in one tick share its result; different clinics read independently. Transient Durable Object state retains only the matched row for that clinic (room, doctor, clinic type and current number), or its failure outcome; unrelated rows and raw responses are discarded. State is pruned daily. Cross-clinic read sharing may be considered as a future optimization outside Issue #20.
- Window: supported afternoon reads happen 13:30 to 16:30 plus 10 minutes either side. Morning hours are unverified and outside the evidenced scope, so morning requests fail with `scope_mismatch` before any read.
- Failures: a timeout, HTTP 408/429/5xx or other transport error retries after 1, then 2, then 4 minutes (capped), honoring `Retry-After` up to 10 minutes. A challenge or CAPTCHA marker, HTTP 401/403/451, or any redirect stops reading that source for the day and shows "來源拒絕讀取". Nothing bypasses, solves or works around a challenge, and requests are plain GETs without cookies.
- Unusable reads inside the window feed the existing unavailable alert (third consecutive unusable read, once per recipient). Skipped ticks, the time before the window and the clinic ending are not unusable reads.
- End of session: a blank number with the doctor row present is temporary no data. After the session end, the doctor row being gone marks the clinic as ended: reading stops, no unavailable alert is sent, and the reminder shows "來源沒有可用資料" until it expires at the normal cutoff.

## Source evidence and known gaps

The exact request construction, `https://reg.ntuh.gov.tw/WebReg/WebReg/ClinicCurrentLightNo?vHospCode=T0`, is derived from manual observation and is **not live-verified**. It carries no department or session selectors. The default list's department and session are unverified, and its returned rows do not label either; OPH and the requested afternoon session are enforced only by supported-scope checks and the time window. Morning session hours are unverified and outside the evidenced scope. The list's column headers and English or Chinese doctor rendering are taken from the evidence's field description, not from a captured page. A different header fails closed as `schema_drift`. Accuracy against the room's physical indicator is unproven. The existing organizer progress link uses `registration.ntuh.gov.tw`, while the evidence read `reg.ntuh.gov.tw`.

## Recovery

- Unavailable with a timeout, no observation or no result: wait; the reader retries by itself inside the session. Start again after the reason clears.
- Access refused: do not retry by hand around it. Open the official page in a browser to see what changed. The block lasts for that day's session.
- Scope mismatch or schema drift: correct the department and clinic code, or update the parser after a fresh manual check of the page.
