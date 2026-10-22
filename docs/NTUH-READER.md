# NTUH first-hospital reader (Issue #20)

Supported scope: NTU Hospital main campus (branch `T0`), department ophthalmology (`OPH`), morning or afternoon session of the current day, read from the official public registration progress list (`reg.ntuh.gov.tw`). Everything else stays explicitly unavailable: other departments, the evening session, other dates, and Shin Kong. Evidence: Issue #17 report; the owner approved scheduled reads for family-internal, non-commercial use at one read every 2 to 3 minutes.

**Validation status: fixture and local integration only. Live hospital behavior is unverified.** No test or CI run contacts the hospital. Source evidence is not LINE acceptance or handset delivery.

## Enabling

The reader is off by default. Start and scheduled checks use it only when the Worker has `NTUH_READER_ENABLED=1`; otherwise Start reports the source as unavailable, as before. The production hold is separate and unchanged: scheduled ticks stay held outside the local rehearsal. The observed default list does not expose a verified department or session, so fetched numbers are never marked trustworthy or reported as verified-accurate. The flag is a deliberate enablement gate while that source scope remains unverified.

## Entering the clinic

The reminder form has no doctor or room fields, so the NTUH clinic code carries them as `room/doctor/clinic type`, for example `11/Hsiao-Sang Chu/Dr. Appt.`, with department code `OPH`. Each part must equal the list row (compared ignoring case, spaces and punctuation). The doctor name is taken from the list view because the detail page does not show it. Any other shape is rejected as a scope mismatch without a request.

## Reading rules

- Match: room, doctor and clinic type must all equal one list row. Zero rows or several rows never produce a number. The current number is never inferred from neighbors, "Expected Call Number" is never read, and the page's "Last updated" is ignored (it is render time).
- Blank current light means no data, never zero. `0` or non-numeric text is invalid data.
- Freshness is the time the reader fetched the page. An observation older than 2 minutes cannot start a reminder. Since the default list's department and session are unverified, its number is also marked untrusted and cannot start a reminder or be used as a verified-accurate number.
- Cadence: the one-minute cron only offers a chance to read. The reader skips unless 2 minutes passed since the last read of the same source, and visits in one tick share one read. Reader state lives in Durable Object storage.
- Window: reads happen only inside the session (afternoon 13:30 to 16:30, morning 08:30 to 12:30) plus 10 minutes either side. The morning hours are an assumption; confirm them against the official schedule.
- Failures: a timeout, HTTP 408/429/5xx or other transport error retries after 1, then 2, then 4 minutes (capped), honoring `Retry-After` up to 10 minutes. A challenge or CAPTCHA marker, HTTP 401/403/451, or any redirect stops reading that source for the day and shows "來源拒絕讀取". Nothing bypasses, solves or works around a challenge, and requests are plain GETs without cookies.
- Unusable reads inside the window feed the existing unavailable alert (third consecutive unusable read, once per recipient). Skipped ticks, the time before the window and the clinic ending are not unusable reads.
- End of session: a blank number with the doctor row present is temporary no data. After the session end, the doctor row being gone marks the clinic as ended: reading stops, no unavailable alert is sent, and the reminder shows "來源沒有可用資料" until it expires at the normal cutoff.

## Source evidence and known gaps

The exact request construction, `https://reg.ntuh.gov.tw/WebReg/WebReg/ClinicCurrentLightNo?vHospCode=T0`, is derived from manual observation and is **not live-verified**. It carries no department or session selectors. The default list's department and session are unverified, and its returned rows do not label either; OPH and the requested session are enforced only by supported-scope checks and the time window. The list's column headers and English or Chinese doctor rendering are taken from the evidence's field description, not from a captured page. A different header fails closed as `schema_drift`. Accuracy against the room's physical indicator is unproven. The existing organizer progress link uses `registration.ntuh.gov.tw`, while the evidence read `reg.ntuh.gov.tw`.

## Recovery

- Unavailable with a timeout, no observation or no result: wait; the reader retries by itself inside the session. Start again after the reason clears.
- Access refused: do not retry by hand around it. Open the official page in a browser to see what changed. The block lasts for that day's session.
- Scope mismatch or schema drift: correct the department and clinic code, or update the parser after a fresh manual check of the page.
