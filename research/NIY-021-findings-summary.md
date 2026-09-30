# NIY-021: NTUH and Shin Kong public progress source findings

Research completed 2026-09-29; official progress entry points rechecked for reachability on 2026-09-30. This tracked summary condenses the detailed manual browser report maintained by Firstmate at `/Users/kun/projects/firstmate/data/next-is-you-niy-021-public-source-check-20260929/report.md`. The detailed report is supporting evidence and is not part of this repository.

## Findings

| Hospital | Official public entry point and observed path | What the public page exposed | Assessment for a future live adapter |
| --- | --- | --- | --- |
| NTUH Main | [NTUH Clinic Current Light page](https://www.ntuh.gov.tw/ntuh/ClininCurrentLight.action); the page defaults to Main Hospital and offers campus, department, and session selection. The [official registration progress page](https://registration.ntuh.gov.tw/WebReg/WebReg/ClinicCurrentLightNo?vHospCode=T0) identifies Taipei Main Hospital (`T0`) and offers department and Morning / Afternoon / Evening selections. Both URLs loaded in a manual browser check on 2026-09-30. | The report observed a clinic detail view with room, current light, highest called number, expected call number, and light status fields. A source timestamp appeared on the detail sample. NTUH says its screen updates every minute. | **Unverified.** Page timestamps changed once per minute, but the observations did not establish freshness of a current clinic number. The detail sample was not reached through the public selection flow, and its `ServiceIDSE` value is undocumented. Do not treat it as a stable query route. |
| Taipei Shin Kong | The [official registration home](https://www.skh.org.tw/skh_regis/) links to [看診/各項進度查詢](https://reg.skh.org.tw/skh_regis/#/register/progress). The progress route and home both loaded in a manual browser check on 2026-09-30. | The report selected a department and observed its date, clinic hours, and instructions. That department showed no clinic progress row; no doctor, room, or current clinic number could be confirmed. The page says missing progress can mean the clinic has not opened or is appointment-only. Other service progress panels are not outpatient clinic progress. | **Unverified.** The public entry point is reachable, but this observation did not show matchable current outpatient progress. No clinic-progress refresh interval was found, and freshness remains unknown. |

The 2026-09-30 check was limited to opening the official entry point URLs in a normal browser. It did not repeat queue observations or establish that either hospital's displayed numbers are fresh. Reachability is not evidence of a stable interface or adapter readiness.

## Access and freshness limits

- The 2026-09-29 report records no login or CAPTCHA at the observed public pages. It used low-impact manual browser inspection and did not enter patient identifiers or retain individual queue numbers.
- NTUH's minute-update statement and changing page timestamp describe page updates, not demonstrated changes in an active clinic's displayed number. Its public detailed sample timestamp also did not provide a sufficient pair of observations across a full update interval.
- Shin Kong's observed department had no clinic progress to compare. A timestamp on pharmacy, laboratory, billing, or inpatient panels does not establish outpatient progress freshness.
- Absence of a progress row is not zero. The report does not support calculating an ETA from number differences.
- The report reviewed public app descriptions only as secondary leads. They do not make a third-party app an authoritative source or authorize reproducing undocumented access behavior.

## Follow-up gate

Do not add a poller, scraper, or production adapter based on these findings. Any later source or API work must first record at least two manual observations per hospital during active clinic sessions, including a source timestamp where available, and determine whether the same public clinic can be matched. Keep freshness unknown until that evidence exists. Dynamic session availability remains deferred; the current session labels do not confirm clinic/date availability.

## Detailed report

The detailed report includes the source-by-source browser observations, secondary app documentation, timestamps, access path notes, and remaining questions: `/Users/kun/projects/firstmate/data/next-is-you-niy-021-public-source-check-20260929/report.md` (Firstmate local data, not tracked here).
