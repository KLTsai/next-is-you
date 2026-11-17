# Hospital schedule and queue progress survey

Research date: 2026-11-17 (Tuesday), pages opened between about 14:40 and 15:10 Taipei time, during the afternoon session.

Question: how do large Taiwan hospitals publish (a) their outpatient clinic schedule (門診表 / 門診時刻表) and (b) live clinic queue progress (看診進度 / 叫號進度), how do the two identify a clinic, and does the three-tier model in [docs/ADDING-A-HOSPITAL.md](../docs/ADDING-A-HOSPITAL.md) fit?

## Method

- 15 hospitals, primary sources only: each hospital's own website and registration system, its own footer and terms, `robots.txt`, and official government pages. Third-party apps, blogs and news were not used.
- Each page was opened in an ordinary browser session a small number of times (3 to 7 page loads per hospital), choosing one department and one session where the page required a choice. No crawling, polling, bulk download, or endpoint probing. One schedule PDF (Mackay) and one 29-row government open-data CSV (NHI medical centers) were opened.
- No patient identifier, ID number, birthday or chart number was entered anywhere. Where a page asked for one, the survey stopped there.
- Individual queue numbers and doctor names were visible on public pages but are not recorded here. This file describes fields, not values.

Every finding carries one of three labels:

- **[observed]** - seen rendered on the official page on 2026-11-17.
- **[stated]** - the official page says so in its own text; not independently checked.
- **[not observed]** - could not be reached, rendered, or was behind a gate.

## Evidence limits

- **Reachability is not adapter readiness.** A page that loaded once in a browser says nothing about a stable request contract, rate tolerance, or behaviour from a server-side client.
- **Nothing here establishes freshness.** No displayed number was observed changing. Stated refresh intervals describe page refresh, not how current a clinic's number is.
- **Nothing here authorizes building a scraper.** Access terms are quoted as written and not interpreted. Several sites carry a no-reproduction statement, and one `robots.txt` names AI user agents as disallowed (see 三軍總醫院).
- **One department, one session, one afternoon per hospital.** Matching confidence is about whether a recognisable shared identifier exists, not whether exact matching would be unambiguous across a hospital.
- **"How far ahead" was read from registration pages.** What those pages show is the booking horizon. It is not proof that no schedule exists beyond it.
- **Sample bias.** 14 of 15 are medical centers; only 臺北市立聯合醫院 represents regional-level campuses. Smaller hospitals and clinics are not covered.
- The follow-up gate in [NIY-021-findings-summary.md](NIY-021-findings-summary.md) still applies: no poller, scraper or production adapter on the basis of this survey.

Conduct disclosures:

- 三軍總醫院's `robots.txt` was read only after four of its pages had been opened. It disallows a list of AI user agents (including `ClaudeBot`, `anthropic-ai`, `Claude-Web`) and declares `ai-train=no`. The browser session did not identify as any of them. No further request was made to that site after reading the file. Whether an agent-driven browser falls under those entries is a decision for the captain, not for this file.
- Mackay's schedule-by-department flow sits behind a notice page with a "本人已知悉，繼續掛號" button. The session's permission policy declined that click, so it was not made.
- On Shin Kong, a department information dialog (an age note with a 確定 button) was dismissed to see the schedule.
- Three progress pages auto-refresh (Mackay 30 s, 臺中榮總 60 s, 花蓮慈濟 15 s). Each was left within seconds; at most one automatic refresh may have fired.

## Summary table

Tier 1 = schedule and current number both public. Tier 2 = current number only. Tier 3 = neither.

| Hospital | Schedule format | Publication rule | Progress available | Matchable | Tier | Confidence |
| --- | --- | --- | --- | --- | --- | --- |
| 臺大醫院 (NTUH) | Server-rendered HTML, by department | Rolling 14 days, opens at midnight [stated] | Yes, by department and session | Room + doctor (already used by the repo reader) | 1 | High |
| 臺北榮總 | Server-rendered HTML by department, plus monthly PDF | Rolling 27 days ahead [stated]; PDF per month | Yes, by department and session | Four-digit room number + doctor on both | 1 | High |
| 林口長庚 | Server-rendered HTML, by department | "一個月內" [stated]; four weekly ranges, 29 days [observed] | Yes, by department and session | Department + doctor + session only; progress shows an area, not a room | 1 | Medium |
| 高雄長庚 | Same system as 林口長庚 [not observed directly] | Not observed | Page structure observed, no rows seen | Not observed | 1 (inferred) | Low |
| 馬偕 (台北) | PDF weekly template [observed]; date-based web view behind a notice gate [not observed] | Not observed | Yes, by department and session | Room number + doctor, across a PDF and an HTML page | 1 for today only | Medium-low |
| 國泰 (總院) | HTML weekly template by department; dental as PDF | Booking 30 days, day 30 opens at 00:30 or 08:00 by campus [stated] | Yes, keyed by room code | Three-digit room code + doctor on both | 1 for today only | Medium |
| 三軍總醫院 | Server-rendered HTML, by department | Six calendar-week tabs from Monday of the current week [observed] | Yes, whole campus on one page | Department + doctor + session only; schedule has no room | 1 | Medium |
| 新光 | Single-page app, by department; separate periodic PDF issues | Four weekly ranges, 28 days [observed]; PDF issued monthly or bimonthly | Yes, by department (single-page app) | Same building + room string + doctor on both | 1 | Medium-high |
| 亞東 | Server-rendered HTML by department; monthly PDF | "三個月" [stated]; 14 calendar-week ranges [observed] | Yes, by department and session, or by doctor name | Department + doctor + session only; schedule has no room | 1 | Medium |
| 臺北市立聯合醫院 (仁愛) | Server-rendered HTML, by campus and department | "28天內" [stated]; two 2-week tabs [observed] | Yes, one page per clinic, linked from today's schedule cell | Joined by the site's own link (campus, date, session, department, room, doctor) | 1 | Medium-high |
| 中國醫藥大學附設醫院 | HTML weekly template by department; monthly PDF; date-level view [not observed] | Monthly PDF; date-level rule not observed | Only by room number or patient identifier; no roster; results [not observed] | Not observed | 2 | Low |
| 臺中榮總 | Public: monthly PDF only. Date-based view behind identity verification | Monthly PDF, current and previous month | Yes, by department and session | Not observed on the schedule side (PDF not opened) | 1 for today only | Medium |
| 成大醫院 | Server-rendered HTML, by department | Six weekly ranges, 42 days [observed] | Yes, department, then clinic, then detail | Four-character clinic code + doctor on both | 1 | High |
| 高雄醫學大學附設醫院 | Server-rendered HTML, by sub-department, month grid per clinic | Rolling 91 days, opens 22:00 the night before [stated] | Yes, by department group and session | Clinic name ("N診") + doctor on both | 1 | Medium-high |
| 花蓮慈濟 | Server-rendered HTML, by department | Last open date printed on the page, rolls at 00:00 [stated]; 35 days ahead on the research date | Yes, roster by campus and session, then one page per clinic | Floor + room number + doctor on both | 1 | Medium-high |

Counts: 10 fit Tier 1 with both sides observed; 1 more (高雄長庚) is Tier 1 by inference from a shared system; 3 (馬偕, 國泰, 臺中榮總) are Tier 1 only in the sense that today's roster can be read off the progress page, with no date-based public schedule observed; 1 (中國醫藥大學附設醫院) is closest to Tier 2 and fits it poorly; none are Tier 3.

## Per-hospital notes

### 臺大醫院 (NTUH, 臺北總院)

- Schedule: <https://reg.ntuh.gov.tw/WebReg/WebReg/RegDeptSchedule?vhospCode=T0&showBlock=A&vDeptCode=OPH&realSubDeptCode=showAll>. Server-rendered HTML, by department with sub-specialty filters. [observed] The page showed a date range of 11/17 to 12/1 and "Open for next two weeks only". [stated] "Schedule from midnight on 14 days before consultation". The page rendered in English because the browser asked for English; field labels change with the browser language. Fields and status markers are documented from earlier captures in [docs/NTUH-READER.md](../docs/NTUH-READER.md) and were not re-derived today. No login or CAPTCHA to view. [observed]
- Progress: <https://www.ntuh.gov.tw/ntuh/ClininCurrentLight.action> and <https://registration.ntuh.gov.tw/WebReg/WebReg/ClinicCurrentLightNo?vHospCode=T0>. Selectors for campus (seven), department and session (上午 / 下午 / 夜間). [observed] "實際看診順序依現場燈號為準，畫面每分鐘更新一次。" [stated] Card fields are in the repo doc; no rows were opened today.
- Matching: the repo reader already matches on room + doctor (+ clinic type). The schedule's 診別 vocabulary differs from the progress card's clinic type (repo doc).
- Access terms: footer of www.ntuh.gov.tw, "醫療機構網際網路資訊管理辦法聲明：禁止任何網際網路服務業者轉錄本網路資訊之內容供人點閱。 但以網路搜尋或超連結方式，進入本醫療機構之網址（域）直接點閱者，不在此限。" Footer of reg.ntuh.gov.tw, "國立臺灣大學醫學院附設醫院所有，未經授權禁止轉載。" [stated] `robots.txt` on www.ntuh.gov.tw: `User-agent: *` / `Allow: /`. The two registration hosts return 404 for `robots.txt`. [observed]
- Tier 1, high confidence. Schedule and progress live on different hosts.

### 臺北榮民總醫院

- Schedule: <https://www6.vghtpe.gov.tw/reg/sectList.do?type=return> then `opdTimetable.do` per department. Server-rendered HTML. One table per session (早上門診 08:30-12:00, 下午門診 13:30-17:00, and so on); rows are rooms ("第 NNNN 診", four digits), columns are dates; cells hold the doctor and a status (已逾掛號時間, 額滿, 請假休診, 額滿關診). First page "門診表 11/17 - 11/30", then "前往第三週-第27天". [observed] "預約27天內門診，如：8/1可預約8/28(含)前門診"; "如前一日21:30以後診次狀態仍顯示「額滿」，表示醫師未請假且未關診". [stated] Viewing needs no login; a CAPTCHA and identity form sit below the table for booking only. [observed]
- Second schedule channel: <https://www6.vghtpe.gov.tw/reg/downloadOpdTable.do> offers "115年11月門診表" and "115年10月門診表" as PDF. [observed, PDFs not opened]
- Progress: <https://www6.vghtpe.gov.tw/reg/realTime.do?type=realtime>, titled 當日看診進度查詢 (today only). By department, with 上午診 / 下午診 / 夜間診 tabs. Per clinic: department + four-digit room, doctor, location (building and floor), 目前叫號, 預計下一號, 已叫最大號, a (順號) marker, 最後更新 time, and non-numeric states such as 請假休診. Telemedicine clinics (通訊診療 / 視訊通訊診療) appear as rows. A separate 其他叫號 group lists pharmacy, blood draw, X-ray, chemotherapy, injection and examination queues. [observed] No refresh interval stated on the page read.
- Matching: the same four-digit room number and doctor appear on both, and both use the same department code in their links. High confidence for the one department checked.
- Access terms: no terms seen on the registration pages read; `robots.txt` returns 404. [observed]
- Tier 1, high confidence. Two parallel schedule channels with different release rules.

### 林口長庚紀念醫院

- Schedule: <https://register.cgmh.org.tw/Register_WEEK/3> then `Department_WEEK/3/<codes>`. Server-rendered HTML, by department. Rows are dates, columns are 上午 / 下午 / 晚間. Each entry is a five-character code followed by the doctor and markers: (額滿), (停診), (無視訊), 初診 / 初診可掛, 超過掛號開放時間. The meaning of the five-character code is not labelled on the page. Four weekly ranges, 2026-11-17 to 2026-12-15. [observed] "點選院區、科別後，即可看見該科看診醫師一個月內門診時間之列表。實體紙本門診時刻表，請親至各分院相關服務櫃台索取。" [stated] A 門診表下載 PDF link exists per campus. [observed, not opened] No login or CAPTCHA to view.
- Progress: <https://register.cgmh.org.tw/Progress/3>. Two modes: 科別查詢 (department + 上午診 / 下午診 / 晚間) and 輸入身份資料 (patient identity, not used). Result columns: 掛號科別, 看診位置, 醫師名, 目前看診號碼, 下一個看診號碼, 下二個看診號碼, with a page timestamp. 看診位置 is a building, floor and area, not a room number. Values can carry a 過號 prefix. [observed] "因每位醫師看診進度不一，故看診進度(即目前診間已看診之診號)僅為參考之用。" [stated] The app 長庚e指通 is advertised as also showing 看診進度. [stated]
- Matching: department + doctor + session. No room number on the progress row, and the schedule's five-character code does not appear on the progress row. Medium confidence.
- Access terms: footer "長庚醫療財團法人 所有,未經授權,禁止轉載." [stated] `robots.txt` returns 404.
- Tier 1, medium confidence. One site serves about fifteen campuses and partner hospitals, selected by a campus code.

### 高雄長庚紀念醫院

- Same site and page templates as 林口長庚, campus code 8. Progress page <https://register.cgmh.org.tw/Progress/8> loaded with the same form and the same column headers, but showed no rows before a department was chosen; no query was submitted. [observed] Schedule page for this campus was not opened. [not observed]
- Tier 1 by inference only, low confidence.

### 馬偕紀念醫院 (台北院區)

- Schedule, PDF: <https://www.mmh.org.tw/downloadregdoc.php> links 台北馬偕門診表, 淡水馬偕門診表 and 馬偕兒醫門診表 at fixed PDF paths. The Taipei PDF page read is a weekly template: department, 時段 (上午 / 下午), 樓別 (building and floor), 診間 (room number), then 星期一 to 星期六 columns holding the doctor and a four-digit code, with symbols for appointment-only and specialty clinics and footnoted specific dates for clinics that run only on some dates. No month or effective period was visible on that page. [observed, one page]
- Schedule, web: `find_division.php` redirects to a notice page (`register_info.php`) that requires pressing "本人已知悉，繼續掛號". Not pressed. Date-based schedule, horizon and markers: [not observed].
- Progress: <https://www.mmh.org.tw/progress.php> (campus, department, session) leading to `progressstatus.php`. Columns: 位置 (building and floor), 診別 (department abbreviation + room number), 醫師, 目前看診號, 未看診人數. A separate 抽血進度 tab exists. [observed] "本查詢頁面每30秒自動更新"; "[已停診]：表示醫師暫時離開診間或已結束看診。"; "醫師若未顯示：表示醫師尚未開始看診或已結束看診超過一小時。"; "目前看診號僅供參考". [stated]
- Matching: room number + doctor appear in both the PDF and the progress table, but the PDF page and the progress table checked were for different departments. Medium-low confidence.
- Access terms: "本網站內容為馬偕紀念醫院所有，未經許可請勿轉載。" [stated] `robots.txt`: only `User-agent: Googlebot` / `allow: /`. [observed]
- Tier 1 for today's roster; no date-based public schedule observed.

### 國泰綜合醫院 (總院)

- Schedule: <https://reg.cgh.org.tw/tw/reg/TimeTable.jsp>. Campus and department selectors, then one table per session with rows by 診室 (three-digit room code) and columns 星期一 to 星期日 holding the doctor. A weekly template, no dates. Dental and integrated-care timetables are separate PDFs. [observed] "本表僅供參考，一切仍以本院當月印製之「門診時間表」為準。若醫師臨時因故未能應診，本院將適時調派醫師應診". [stated]
- Booking horizon: <https://reg.cgh.org.tw/tw/reg/main.jsp>, "網路預約第30日(20261217)開放掛號時間：總院：上午00：30起，新竹國泰：上午08：00起，汐止國泰：上午00：30起，內湖國泰：上午00：30起。" [stated] The date-based booking view was not opened. [not observed]
- Progress: <https://reg.cgh.org.tw/tw/reg/RealTimeTable.jsp>. Selectors for 院區, 時段 and 診室. The room list for a campus and session shows "room code + doctor" for the whole campus, not by department, and marks substitutes inline as "原醫師(某某代診)". The result shows 目前看診序號 and a list headed 尚未就診病人號碼. [observed] "欲查詢診室代號，請點選「網路掛號」。"; "本資訊僅供參考之用，實際看診序號仍以診間前之看診燈號為準。" [stated] No refresh interval stated.
- Matching: three-digit room code + doctor on both. Medium confidence; the timetable is a template, so a date still has to be assumed from the weekday.
- Access terms: "本網站內容為國泰綜合醫院所有，未經許可請勿轉載". [stated] `robots.txt` URL returns an HTML page, not a robots file. [observed]
- Tier 1 for today's roster; date-based schedule not observed.

### 三軍總醫院 (內湖院區)

- Schedule: <https://www2.ndmutsgh.edu.tw/NewWebReg/> then `Register/Doctors` per department. Server-rendered HTML. Six tabs, 本週 to 下五週, each a Monday-to-Sunday table; rows are sessions with clock times, columns are dates; cells hold the doctor, a time range and notes (教學診, 請現場掛號, combined-clinic notes). Past sessions today read "此時段門診已結束". No room number in the schedule cells. [observed] "「請現場掛號」表示預約名額已滿目前有當日現場號". [stated] The horizon rule is not stated on the pages read. No login or CAPTCHA to view. A 門診時刻表 link points to a separate page. [not opened]
- Progress: <https://www2.ndmutsgh.edu.tw/NumberStatus/>. One page for a whole campus (內湖院區 / 汀州院區 / 台北門診中心), with tabs 看診進度, 抽血檢驗, 批價掛號/檢查報到, 領藥, 手術進度 and sessions 上午診 / 下午診 / 夜診. Grouped by department; each card shows doctor, 診室 number, a current number and "下：" (next). [observed] No refresh interval stated.
- Matching: department + doctor + session only, because the schedule carries no room. Medium confidence.
- Access terms: footer "© 2026 三軍總醫院 禁止任何網際網路服務業者轉錄其網路資訊之內容供人點閱". [stated] `robots.txt`: `User-agent: *` with `Content-Signal: search=yes,ai-train=no,use=reference` and `Allow: /`, then `Disallow: /` for a list of named agents including `ClaudeBot`, `anthropic-ai`, `Claude-Web`, `GPTBot`, `CCBot`, `Google-Extended`; a comment block states "ANY RESTRICTIONS EXPRESSED VIA CONTENT SIGNALS ARE EXPRESS RESERVATIONS OF RIGHTS". [observed] See the conduct disclosure above.
- Tier 1, medium confidence. The domain redirected from `ndmctsgh.edu.tw` to `ndmutsgh.edu.tw`.

### 新光吳火獅紀念醫院

- Schedule: <https://reg.skh.org.tw/skh_regis/#/register/step>. Single-page app; content appears only after scripts run. By department, in weekly ranges; four ranges offered, 2026-11-17 to 2026-12-14. Each entry shows session, doctor, 已預約人數, building, a room string (building + room number 診 + floor) , free-text notes, and a status (掛號, 止掛 / 停止掛號, 約診 / 限醫師約診, 停診, 滿號). [observed] No login or CAPTCHA to view; a department note dialog had to be dismissed.
- Second schedule channel: <https://www.skh.org.tw/skh/f4cb322c15.html> lists "新光醫訊及門診時刻表" issues, some monthly (115年10月, 115年09月) and some bimonthly (115年11-12月, 115年07-08月), each posted around the start of its period. [observed, issues not opened]
- Progress: <https://reg.skh.org.tw/skh_regis/#/register/progress>. Tabs 看診進度, 領藥進度, 檢驗(抽血)進度, 批價掛號進度, 住院櫃台進度. After choosing a department, rows for today showed: session, doctor with a staff code, 診間 (the same building + room string as the schedule), 目前進度 with a (過號) or (順號) marker, 下一號 with (順號) or (無人報到), or the state 即將開始看診. [observed] This is new relative to NIY-021, which saw no rows. "本服務僅供民眾查詢當日掛號看診之診間進度，實際看診順序仍以現場作業為主。"; "目前看診進度不含過號插號"; "看診進度若未顯示，表示該科未開診或該門診為預約制。" [stated] No refresh interval stated.
- Matching: identical room string and doctor name on both. Medium-high confidence for the one department checked.
- Access terms: "網站內容為新光醫院所有未經許可 請勿任意轉載". [stated] `robots.txt`: `Disallow: /skh_resource/` with `Allow` lines for css, js, jpg, png and pdf under it. [observed]
- Tier 1, medium-high confidence.

### 亞東紀念醫院

- Schedule: <https://www.femh.org.tw/webregs/fregister.aspx> then `RegSec1.aspx?ID=<code>`. Server-rendered HTML, by department. Week selector with 14 Monday-to-Sunday ranges, 2026-11-16 to 2027-02-21; rows are 上午 / 下午 / 晚上, columns are dates; cells hold the doctor (substitutes written "某某-代診") and 網 / 現 badges, with a legend for 可網路掛號 and 網路掛號額滿. No room in the schedule cells. [observed] "網路掛號可預約期間為三個月"; "部份科別、醫師看診時間不同或採約診型式(未開放網路掛號)，請參閱門診時刻表。" [stated] No login or CAPTCHA to view.
- Second schedule channel: <https://www.femh.org.tw/document/opd_main.aspx> embeds one monthly PDF (`opd/202611.pdf`). [observed, not opened]
- Progress: <https://www.femh.org.tw/visit/visit.aspx?Action=9>. Department + session, or a doctor-name search; sibling tabs for 抽血, 領藥 and 麻醉諮詢 progress. Result columns: 看診日期, 時段, 看診科別, 診間 (a letter + digits code), 看診醫師 (substitutes written "某某代診"), 掛號人數, 下一號, 目前看診號, plus a 詳細進度 link. [observed] No refresh interval stated.
- Matching: department + doctor + session; the room code exists only on the progress side. Both sides use the same department code in their URLs. Medium confidence.
- Access terms: none seen beyond a privacy policy link; `robots.txt` returns 404. [observed]
- Tier 1, medium confidence.

### 臺北市立聯合醫院 (仁愛院區)

- Schedule: <https://webreg.tpech.gov.tw/> then `RegOnline1_1.aspx?ZCode=<campus>` and `RegOnline1_2.aspx` per department. Server-rendered HTML. Two tabs (一、二周 / 三、四周), each a pair of 7-day tables with ROC-calendar dates (115/11/17 ...); rows 上午 / 下午 / 夜間; cells hold the doctor, a booked count in brackets, and notes such as (預約號已額滿), (某某請假), (請於HH:MM前到診). No room in the cells. [observed] "網路掛號 ... 預約天數 28天內". [stated] No login or CAPTCHA to view.
- Progress: for today's cells only, the schedule cell itself carries a link "(看診進度及未看診人數)" to `RegOnline3_1_2.aspx`, whose parameters name campus, date, session, department, room and doctor. The page shows 看診日期, 院區, 科別, 午別, 診間, 醫師, 目前診號. The one clinic opened was in the state 未開診 with "該診間目前無看診進度資料！！". [observed] "此看診資訊僅提供參考 , 實際進度仍以現場看診狀況為準。" [stated] An active clinic's row was not seen. [not observed]
- Matching: the site joins schedule and progress itself through that link. Medium-high confidence.
- Access terms: none seen on the pages read; `robots.txt` returns 404. [observed]
- Tier 1, medium-high confidence. 25 campuses and outpatient departments share the site.

### 中國醫藥大學附設醫院

- Schedule: <https://www.cmuh.cmu.edu.tw/OnlineAppointment/AppointmentByDivision> (choose 初診 or 複診) then `DymSchedule?table=<code>`. Server-rendered HTML weekly template: rows are sessions with clock times, columns 星期一 to 星期日, cells are doctor names with markers such as (約診). The department's location is in the page title; no room per doctor. [observed] "本表內若有異動，以當月各科醫師排班表及門診公告為準，本表僅提供參考，若醫師臨時請假，未能應診者，將安排其他醫師代理". [stated] A monthly PDF "11月全院門診時間表" is linked. [observed, not opened; its path is under `/FileUploads/`, which `robots.txt` disallows] The per-doctor page that should list dates rendered no date rows in this session. Date-level schedule and horizon: [not observed].
- Progress: <https://www.cmuh.cmu.edu.tw/OnlineAppointment/ClinicQuery>. Three lookups: by chart / ID number + birthday; by room number ("請輸入診間號碼(★共3~4位英數字)") + session; and an examination-time lookup by patient identifier. There is no department roster to browse. [observed] "本功能目前僅提供當時段有掛號的民眾查詢門診就診狀態，查詢所得資料僅供參考，實際請以診間叫號為準。" [stated] No lookup was submitted; result fields are [not observed].
- Matching: [not observed]. The public schedule read carries no room number, and the progress lookup needs one.
- Access terms: footer "本網站內容屬中國醫藥大學附設醫院所有，一切內容僅供使用者在網站線上閱讀，禁止以任何形式儲存、散佈或重製部分或全部內容". [stated] `robots.txt`: `Disallow: /` for several named crawlers, `User-agent: *` / `Disallow: /FileUploads/`, and `Crawl-delay: 10`. [observed]
- Closest to Tier 2, low confidence. The number is reachable only for someone who already knows a room number, and the page describes itself as for patients registered in the current session.

### 臺中榮民總醫院

- Schedule, public: <https://www.vghtc.gov.tw/CL/7201> lists "115年10月時刻表" and "115年11月時刻表" as PDFs on a separate host. A news item announces the monthly 門診手冊 including 休診 information. [observed, PDFs not opened]
- Schedule, date-based: <https://register.vghtc.gov.tw/register/regEntrance.jsp>, "請選擇「初診掛號」或「複診掛號」進行身份驗證". Stopped there. [not observed]
- Progress: <https://www.vghtc.gov.tw/OutpatientProcess/5986>. Tabs 門診看診進度, 門診領藥進度, 門診抽血進度; lookup by 診間號, 病歷號 or 身分證號, or by a department list that also contains examination rooms under 其他進度查詢. Per clinic: department, 診間 (four digits), 醫師, 目前看診號次, 過號看診號, 已報到待看診人次, 最末號, and a free-text clinic notice. Session tabs 上午 / 下午 / 晚上 and a 更新時間 stamp. [observed] "每60秒自動刷新". [stated]
- Matching: [not observed] on the schedule side.
- Access terms: <https://www.vghtc.gov.tw/CP/4126> 政府網站資料開放宣告, "臺中榮民總醫院網站上刊載之所有資料與素材，其得受著作權保護之範圍，採政府資料開放授權條款-第1版，以無償、非專屬，得再授權之方式提供公眾使用 ... 然使用時，應註明出處。" The same site's footer reads "本網站內容為臺中榮民總醫院所有，未經允許請勿任意轉載、複製或做商業用途". [stated, both] `robots.txt` returns 404.
- Tier 1 for today's roster; the only public schedule seen is a monthly PDF.

### 成大醫院

- Schedule: <https://tandem.hosp.ncku.edu.tw/Tandem/Department/List/Clinic> then a per-department page. Server-rendered HTML. Six weekly ranges with ROC dates, 115/11/17 to 115/12/28; rows are 科診 (a four-character clinic code), columns are dates split into 上午 / 下午; cells hold the doctor and a status: (預約額滿), (停診), (當天不受理現場掛號), teaching-clinic notes, and "轉掛<另一家醫院>" entries for clinics held at another hospital. [observed] The horizon rule is not stated on the pages read. No login or CAPTCHA to view. Department URLs carry opaque tokens, and the site first rendered in English until the language link was used.
- Progress: <https://tandem.hosp.ncku.edu.tw/Tandem/Department/List/Progress>. Three steps: department; a list of today's clinics per session (科診代碼, 科診名稱 such as 一診, 醫師); then a detail page with 日期 and session, clinic and doctor, 診間號 (three digits), 目前叫號 (or the state 結束看診), 已看完診人數, 尚未看診人數, and 所有燈號狀態, a list of every appointment number with a state such as 已看診 or 未報到. [observed] "看診進度一覽（以實際現場燈號為準）". [stated] No refresh interval stated.
- Matching: clinic code + doctor on both. High confidence for the one department checked. The 診間號 on the detail page is a different identifier from the clinic code.
- Access terms: footer "禁止網路服務業者轉錄本院網路資訊內容". [stated] `robots.txt` returns 404.
- Tier 1, high confidence.

### 高雄醫學大學附設中和紀念醫院

- Schedule: <https://www.kmuh.org.tw/Web/WebRegistration/Registration/Index> then department group, sub-department and `RegSchedule`. Server-rendered HTML. One block per clinic: "科診： <科名>N診 (four-digit code)　地點： <building, floor, area>", then a Sunday-to-Saturday month grid for the chosen session tab (上午診 / 下午診 / 夜間診) with a 下個月 control; cells hold the date, doctor and markers such as (休診). [observed] "本院自2026/4/21起，門診預約掛號天數調整為91天。在您欲看診日期之前91天的夜間 22:00起，開始接受掛號作業。" and "可掛號日期： 2026/11/17 (今日) ~ 2027/02/16". [stated] No login or CAPTCHA to view. A 門診表 link points to a PDF. [not opened]
- Progress: <https://www.kmuh.org.tw/Web/WebRegistration/OPDSeq/ProcessMain?lang=tw>. Department group + session; 看診日期 is today. Each card: clinic name (sub-department + "N診"), 醫師, 代診醫師 as a separate field, and a number or a state (休診, 先報到先看診). A second tab 其他相關進度 covers 抽血 and 領藥. [observed] No refresh interval stated.
- Matching: clinic name + doctor on both. Medium-high confidence. Clinic numerals were printed in both half-width and full-width digits on the progress page.
- Access terms: home page footer carries the statutory no-reproduction statement and "版權所有翻印必究". [stated] `robots.txt` returns 404.
- Tier 1, medium-high confidence.

### 花蓮慈濟醫院

- Schedule: <https://hlapp.tzuchi.com.tw/tchw/opdreg/SecList_HL.aspx>; departments are form buttons leading to `OpdTimeShow.aspx`. Server-rendered HTML. Rows are 看診日 (month-day and weekday), columns 上午 / 下午 / 夜間; cells hold the doctor, a room string (floor + "第NNN診") and notes such as (額滿且無當日現場掛號名額). For the department opened, the first row was the day after the research date although the same weekday appeared in later weeks. [observed] "今日開放掛號日期至 115年 12月 22日 自00:00起開放掛號". [stated] No login or CAPTCHA to view.
- Progress: <https://hlapp.tzuchi.com.tw/tchw/opdreg/opdstatus/loginstatus.aspx?DShospital=HLWSopd>. Method one is a chart-number lookup (not used). Method two is a roster for the chosen campus and session (早上 / 下午 / 晚上): 科別, 診察室, 醫師. The roster includes telemedicine entries named after the doctor (某某遠距), dialysis units, and a duty-doctor placeholder. Each row opens a clinic page with 科別, 醫師, 診間, 已結束看診 count, 等待人數, 掛號人數, 平均看診時間, 時段, 最近更新 time, 現在看診號碼 and 下一個看診號. [observed] "因民眾報到時間不一或預約沒來，跳號看診無法避免。"; "平均看診時間僅供參考". [stated] The clinic page carries a 15-second meta refresh. [observed]
- Matching: floor + room number + doctor on both. Medium-high confidence.
- Access terms: home page footer carries the statutory no-reproduction statement. [stated] `robots.txt` on the registration host returns 404.
- Tier 1, medium-high confidence. Nine Tzu Chi campuses share the system through a campus selector.

## Access terms across the sample

- The no-reproduction sentence several hospitals print comes from 醫療機構網際網路資訊管理辦法 第4條: "前條網路資訊之首頁，應以明顯文字，聲明禁止任何網際網路服務業者轉錄其網路資訊之內容供人點閱。但以網路搜尋或超連結方式，進入醫療機構之網址（域）直接點閱者，不在此限。" (<https://law.moj.gov.tw/LawClass/LawAll.aspx?PCode=L0020165>, amended 民國104年11月03日). [stated] Seen in that form or close to it at 臺大, 三總, 成大, 高醫 and 花蓮慈濟.
- Plain copyright notices ("未經許可請勿轉載" and variants): 馬偕, 國泰, 新光, 長庚, 臺中榮總.
- Stricter wording: 中國醫藥大學附設醫院 (online reading only; no storing, distributing or reproducing).
- More permissive wording: 臺中榮總's open-data declaration (政府資料開放授權條款-第1版, attribution required), alongside its footer notice.
- `robots.txt` that says something beyond allow-all: 三總 (AI agents disallowed, content signals), 中國附醫 (`Crawl-delay: 10`, `/FileUploads/` disallowed), 新光 (`/skh_resource/` disallowed except static file types).
- No page read contained terms that mention automated access to queue progress specifically.

## National and municipal sources

- **NHI open data, 健保特約醫事機構-醫學中心** (<https://data.gov.tw/dataset/39280>, 衛生福利部中央健康保險署; sibling datasets for 區域醫院 39281, 地區醫院 39282, 診所 39283). Fields: 醫事機構代碼, 醫事機構名稱, 醫事機構種類, 電話, 地址, 分區業務組, 特約類別, 服務項目, 診療科別, 終止合約或歇業日期, 固定看診時段, 備註, 縣市別代碼, 合約起日. Updated daily, CSV, 政府資料開放授權條款-第1版. [stated] In the downloaded CSV (29 rows), 固定看診時段 is one string of 21 institution-level flags, each weekday × 上午 / 下午 / 晚上 marked 看診 or 休診, and 備註 is free text. [observed] It holds no doctor, room, department session, date, or queue number. It cannot replace a per-hospital schedule and carries no live progress.
- **NHI institution search and 全民健保行動快易通 app.** An MOHW release (<https://www.mohw.gov.tw/fp-16-19098-1.html>, 2016) describes querying an institution's opening sessions by county, department and session; another (<https://www.mohw.gov.tw/cp-2630-18895-1.html>, 2016) lists the app's functions without any outpatient queue feature. [stated] The current NHI app page and the 健康保險資料開放服務 portal could not be opened (403 and a name-resolution failure). A live outpatient queue feature in the app is [not observed].
- **急診即時訊息** (<https://mohw.gov.tw/cp-16-81763-1.html>, 2025; NHI query page <https://info.nhi.gov.tw/INAE4000/INAE4001S01>). Emergency-department waiting counts for 重度級急救責任醫院, also in the NHI app. [stated] Emergency only; not outpatient clinic progress.
- **Municipal open data for city hospitals.** 新北市立聯合醫院_門診進度查詢 (板橋院區) (<https://data.gov.tw/dataset/127995>, 新北市政府衛生局; 三重院區 at 127996): fields deptid, deptname, opdtimeid, roomid, roomname, roomlocation, doctorname, subdoctorname, callednumber_seqno, calledmaxnumber_seqno, waitcount_person, regcount_person, memo_remark; update frequency "每5分"; CSV and an API; 政府資料開放授權條款-第1版. [stated; the data itself was not downloaded] This is live queue progress published as licensed open data, for a hospital outside this sample.
- 臺北市立聯合醫院門診進度查詢 on data.taipei (<https://data.taipei/dataset/detail?id=8ee49ff0-600b-4e5a-81b2-41f712c5c801>): fields 序號, 縣市代碼, 行政區, 院區, 機構地址, 機構電話, 查詢網址. [stated] It is a list of query-page links per campus, not live data.
- A 高雄市立聯合醫院 看診進度 dataset appeared in search results but its page returned 404. [not observed]
- No national source was found that carries per-doctor schedules or live outpatient progress across hospitals.

## Not observed

- 馬偕: date-based web schedule (notice gate not passed).
- 臺中榮總: date-based schedule (identity verification); contents of the monthly PDF.
- 中國醫藥大學附設醫院: date-level schedule (per-doctor page rendered no dates); any progress result (needs a room number or patient identifier).
- 高雄長庚: schedule page; any progress row.
- 臺北市立聯合醫院: an active clinic's progress row.
- 國泰: the date-based booking view.
- PDFs at 臺北榮總, 亞東, 新光, 高醫, 長庚 and 中國附醫 were listed but not opened.
- Progress available only inside a mobile app: not observed at any hospital in the sample; every hospital that advertises an app also has a web page.
- Freshness of any number, at any hospital.

## What the three-tier model misses

Each case below was observed or stated on an official page on 2026-11-17; the source is the hospital section above.

1. **"Schedule" is two different things.** Today's roster (which doctors and rooms are consulting now) can be read from the progress page at most hospitals, while a date-based future schedule is a separate question. 臺中榮總 has a rich progress roster but its only public schedule is a monthly PDF; 馬偕 and 國泰 are similar. The Tier 1 definition in the repo covers the first meaning; the future-date picker needs the second.
2. **Schedule published only as PDF, or with the PDF as the stated authority.** 臺中榮總 (PDF only in public), 馬偕 (PDF; web view gated), 國泰 ("以本院當月印製之「門診時間表」為準"), 中國附醫 ("以當月各科醫師排班表及門診公告為準").
3. **Schedule is a weekday template, not a list of dates.** 國泰 TimeTable, 中國附醫 DymSchedule, 馬偕 PDF (with date exceptions only in footnotes). A date has to be inferred from the weekday.
4. **Fixed periodic releases alongside or instead of a rolling window.** Monthly PDFs at 臺北榮總, 亞東, 臺中榮總, 中國附醫; 新光's 醫訊 issues are sometimes monthly and sometimes bimonthly.
5. **The horizon is not a single last date.** It rolls at a clock time that differs by hospital and by campus (臺大 midnight; 國泰 00:30 for three campuses and 08:00 for 新竹; 高醫 22:00 the night before; 花蓮慈濟 00:00). Some windows are aligned to calendar weeks and include days already past (三總 from Monday of the current week, 亞東). Lengths seen: 14, 27 to 28, 28 to 29, 30, 35, 42, 91 days and about 3 months. 高醫 changed its length by announcement in 2026. Several sites print ROC-calendar dates (聯醫, 成大, 花蓮慈濟).
6. **Today's rows on the schedule degrade during the day.** 三總 replaces finished sessions with "此時段門診已結束"; 臺北榮總 marks 已逾掛號時間; 花蓮慈濟 showed no row for the research date. A same-day check against the schedule can fail for a clinic that is running.
7. **Progress keyed by room, with no browsable roster.** 中國附醫 needs a room number or a patient identifier and says the function is for patients registered in the current session. 國泰 lists room codes for a whole campus with no department grouping.
8. **Progress row without a room number.** 林口長庚 shows a building area; 高醫 shows a clinic name. The (room, doctor, session) key does not exist on that side.
9. **Schedule row without a room number.** 三總, 亞東, 聯醫 and 中國附醫 show the room only on the progress side. The join has to be (department, doctor, session), and one doctor can appear in more than one department's schedule (三總 combined-clinic notes).
10. **Several number sequences per clinic.** Current, next, next-after-next (長庚); current, expected next, highest called (臺北榮總); current, skipped-number, last number, checked-in waiting count (臺中榮總); current plus a list of unseen numbers (國泰); a state for every appointment number (成大); waiting counts or registered counts (馬偕, 亞東, 花蓮慈濟). Which one means "the number being called" is labelled differently everywhere.
11. **The number field holds states, not only numbers.** 請假休診 (臺北榮總), 即將開始看診 (新光), 休診 and 先報到先看診 (高醫), 未開診 (聯醫), 結束看診 (成大), [已停診] and "醫師若未顯示" after one hour (馬偕), 過號 prefixes (長庚, 新光).
12. **Substitute doctors break doctor-name matching.** 高醫 has a separate 代診醫師 field; 國泰 writes "原醫師(某某代診)"; 亞東 writes "某某代診" on progress and "某某-代診" on the schedule.
13. **Rows that are not a doctor in a room.** Telemedicine clinics (臺北榮總 通訊診療, 花蓮慈濟 遠距), dialysis units and a duty-doctor placeholder (花蓮慈濟), clinics held at another hospital (成大 轉掛), appointment-only clinics that are scheduled but closed to web booking or absent from progress (亞東, 新光, 中國附醫).
14. **Non-clinic queues share the progress page.** Pharmacy, blood draw, cashier, examination and surgery progress at 臺北榮總, 三總, 新光, 亞東, 臺中榮總, 高醫 and 馬偕. A department list can contain examination rooms (臺中榮總 其他進度查詢).
15. **Schedule and progress on different systems.** Different hosts at 臺大, 臺中榮總 (progress on the main site, schedule as PDF on another host, booking on a third) and 新光 (app for booking and progress, main site for PDF issues); a PDF matched against HTML at 馬偕. Identifier vocabularies differ even where both exist (臺大 診別 versus clinic type; 成大 clinic code versus 診間號; 長庚 five-character code on the schedule only).
16. **A hospital is a group of campuses.** 聯醫 (25), 長庚 (about 15), 花蓮慈濟 (9), 臺大 (7), 國泰 (4), 三總 (3), 馬偕. Rules can differ per campus inside one site (國泰 opening times).
17. **Gates that are neither login nor CAPTCHA.** A notice acknowledgement before the schedule (馬偕), identity verification before the schedule (臺中榮總), a "registered patients" condition on progress (中國附醫).
18. **Presentation depends on the client.** 臺大 and 成大 served English labels to an English-preferring browser; 新光 renders nothing without scripts; 花蓮慈濟 departments are form posts, and 成大 department links are opaque tokens.
19. **Refresh behaviour varies and is mostly unstated.** Stated: 臺大 1 minute, 馬偕 30 seconds, 臺中榮總 60 seconds; 花蓮慈濟's clinic page reloads every 15 seconds. The other nine state nothing.
20. **Access terms have no place in the model.** The tiers ask whether data is public, not what the site says about reuse. The sample ranges from an open-data declaration (臺中榮總) through the statutory no-reproduction statement to "online reading only" (中國附醫) and a `robots.txt` that disallows AI agents (三總).
21. **A fourth kind of source exists.** 新北市立聯合醫院 publishes queue progress as licensed open data with an API and a stated 5-minute update. The model has no tier for "officially published for reuse", which is a stronger footing than any page in this sample.
