# NTUH first-hospital reader (Issue #20)

Supported scope: NTU Hospital main campus (branch `T0`), department ophthalmology (`OPH`), afternoon session of the current day, read from the official public registration progress list on `registration.ntuh.gov.tw`. Morning session hours are unverified and outside the evidenced scope; morning requests return `scope_mismatch` without a source read. Other departments, the evening session, other dates, and Shin Kong also stay explicitly unavailable. Evidence: Issue #17 report, plus the 2026-10-29 read that captured the request contract and the fragment's markup; the owner approved scheduled reads for family-internal, non-commercial use at one read every 2 to 3 minutes.

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
- Cadence: the one-minute cron only offers a chance to read. Each clinic has independent cadence and retries, with no more than one read per clinic every 2 minutes. Repeated reads for the same clinic in one tick share its result; different clinics read independently. Transient Durable Object state retains only the matched row for that clinic (room, doctor, clinic type and current number), or its failure outcome; unrelated rows and raw responses are discarded. State is pruned daily. Cross-clinic read sharing may be considered as a future optimization outside Issue #20.
- Window: supported afternoon reads happen 13:30 to 16:30 plus 10 minutes either side. Morning hours are unverified and outside the evidenced scope, so morning requests fail with `scope_mismatch` before any read.
- Failures: a timeout, HTTP 408/429/5xx or other transport error retries after 1, then 2, then 4 minutes (capped), honoring `Retry-After` up to 10 minutes. A challenge or CAPTCHA marker, HTTP 401/403/451, or any redirect on either request stops reading that source for the day and shows "來源拒絕讀取". A selector page without a token fails closed as `schema_drift` and the POST is never sent. Nothing bypasses, solves or works around a challenge; the only cookies sent back are the ones that read's own selector request received, and none are kept between reads.
- Unusable reads inside the window feed the existing unavailable alert (third consecutive unusable read, once per recipient). Skipped ticks, the time before the window and the clinic ending are not unusable reads.
- End of session: a blank number with the doctor's card present is temporary no data. After the session end, the card being gone marks the clinic as ended: reading stops, no unavailable alert is sent, and the reminder shows "來源沒有可用資料" until it expires at the normal cutoff. This is a bound, not a source signal - see the known gaps below.

## Source evidence and known gaps

The request contract and the card markup above were captured on 2026-10-29 with two plain requests against the owner's host, and the parser reads that captured page correctly (`research/private/source-evidence/ntuh-oph-clinic-end-2026-10-29.md`). What remains unverified is the reader's own behavior against the live source: no test, CI run or deployment has issued these requests from the Worker, and the fixtures below are synthetic pages shaped from the captured markup. Markup that does not produce a complete card fails closed as `schema_drift`. Accuracy against the room's physical indicator is unproven.

The same evidence rules out two things the reader must not start doing:

- **A listed card does not mean the clinic is consulting.** Cards appear as soon as a session is scheduled for the day, hours before it starts, and were still listed after the nominal session end. Card presence says the clinic is scheduled for the requested session, nothing more.
- **The current light is the number most recently called, not a queue position.** It can jump to any checked-in number: a 44-number backward move was observed within the same session. Nothing may read it as "how far the clinic has got".

No source field marks a clinic as finished. The list has none, and the detail page was not observed publishing one either, so the reader still has no end-of-clinic signal; the session window, the 23:59 Taipei cutoff and organizer Stop remain the only bounds.

## Recovery

- Unavailable with a timeout, no observation or no result: wait; the reader retries by itself inside the session. Start again after the reason clears.
- Access refused: do not retry by hand around it. Open the official page in a browser to see what changed. The block lasts for that day's session.
- Scope mismatch or schema drift: correct the department and clinic code, or update the parser after a fresh manual check of the page.
