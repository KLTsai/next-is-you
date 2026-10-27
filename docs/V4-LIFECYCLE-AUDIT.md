# V4 reminder lifecycle audit (issue #27)

Evidence level: local integration. The table distinguishes Chromium observations
from existing-test coverage and prior walkthroughs; each result records its
evidence. Browser observations used a real local Worker with D1 and SQLite Durable
Object bindings (`npm run dev:rehearsal`), the synthetic organizer login, the fake
hospital reader and fake LINE transport, in Chromium at 1280 px (desktop) and
390 px (mobile) widths. Nothing here contacts
LINE or a hospital, and nothing proves handset delivery or live source behavior
(issues #20 and #22 remain open gates). Rows marked "not executed" were not
exercised and are not reported as passing.

Base: `dada0a0` on `main` (includes the merged correction and draft-transition work).

## Checklist

| # | Step | Success | Pending | Failure | Cancel/Stop | Recovery | Result |
|---|------|---------|---------|---------|-------------|----------|--------|
| 1 | LINE sign-in | Synthetic login shows dashboard | button disabled while request runs | unauthenticated shows login with warning | n/a | reload re-reads session | Pass (synthetic login only). Real LINE login: not executed |
| 2 | Dashboard lists | Drafts list (collapsed, count) and reminder list (count, drafts excluded) | "連線檢查中" status | refresh warning keeps last list | n/a | 重新整理 | Pass |
| 3 | Create draft | "草稿已建立..." and draft count 1, no monitoring, no fake request | "儲存中…" | validation message, API error text | clear unsaved draft | re-submit | Pass |
| 4 | Edit draft and cancel | prefilled incl. patient number; cancel restores saved values | n/a | unsaved-change guard message | 取消修正 | n/a | Pass (covered by existing tests; draft edit walked in prior suites) |
| 5 | Start with failing source | stays 草稿 | "正在檢查可信院方觀察…" | reason text | n/a | restore source, Start again | FAIL then fixed: reason only in a page-top banner styled as success. Now shown on the draft card as an alert |
| 6 | Start with trusted source | same reminder becomes 監控中, leaves draft list | "重新檢查中…" | see 5 | n/a | n/a | Pass |
| 7 | Active card | status, patient number, current number, last checked, source status, recipients, notification summary | n/a | n/a | n/a | n/a | Pass |
| 8 | Near notice (fake send) | an accepted notice each time the called number moves inside the window (up to 20 per visit and recipient); summary counts every delivered notice, e.g. "共 1 則；已接受 1 則" after the first and "共 2 則；已接受 2 則" after a second move | n/a | n/a | n/a | a tick reading the same number creates no further event (covered by existing restart test and `test_duplicate_ticks_reading_the_same_number_create_one_near_event`) | Pass |
| 9 | Stop | 已停止 after confirmation, no later notices | button "停止中" + 停止中 badge | error stays active | n/a | retry | Pass (in-flight ordering covered by `test_rehearsal_stop_shows_stopping_while_fake_line_request_is_in_flight`) |
| 10 | Correct stopped reminder | same reminder returns to 草稿, recipients limited to existing | n/a | API error | cancel keeps stopped | n/a | Pass |
| 11 | Expiry (tick after 23:59 Taipei on appointment date) | 監控中 becomes 已結束, no notice | n/a | n/a | n/a | 修正後重新啟動 returns same reminder to draft | Pass |
| 12 | Recipient removal | allowed after start, last recipient locked, add not offered | "移除中…" | error text | n/a | n/a | Pass |
| 13 | Automatic deletion | drafts/expired 48 h after cutoff, stopped 48 h after Stop | n/a | n/a | n/a | n/a | Not executed in the browser (needs elapsed time). Covered by existing persistence and scheduler tests only |
| 14 | Mobile layout (390 px) | single column, full width actions, no horizontal scroll | n/a | n/a | n/a | n/a | Pass |
| 15 | Form field alignment | date and patient number inputs align | n/a | n/a | n/a | n/a | FAIL then fixed: date field was 13 px taller and its input sat 13 px lower |

## Defects fixed

1. Failed Start feedback (step 5). Regression:
   `tests/test_rehearsal.py::test_rehearsal_failed_start_explains_reason_on_the_draft_card_and_aligns_fields`
   (real Worker). The reason now renders as `role="alert"` on the draft card, is
   cleared when Start is retried or an edit is saved, and the draft stays 草稿.
2. Date input misalignment (step 15). Same test asserts equal height and top
   position of the date and patient-number inputs at 1280 px. Fixed with
   `align-content: start` and a fixed 48 px control height.

## Observed but not changed (suggested follow-ups)

- The top banner for every non-start error (stop, remove, save) uses the green
  success style; a warning style for errors would be clearer.
- A draft that was never checked shows "來源暫不可用 · 草稿" and "尚無院方觀察";
  "尚未檢查" would be more accurate wording.
- The unauthenticated first load logs two expected 401 console errors.
- Step 13 needs a time-controlled real-Worker test if browser-level proof is wanted.

## Synthetic rehearsal (separate state, port 8791)

```sh
NIY_REHEARSAL_STATE=.wrangler/audit27 NIY_REHEARSAL_PORT=8791 npm run dev:rehearsal
```

Then follow [LOCAL-REHEARSAL.md](LOCAL-REHEARSAL.md) with port 8791. Expected states:
seed leaves 監控中, Stop gives 已停止 (reminder list 1, drafts 0); creating a draft
gives drafts 1 and no fake request; Start with `{"current_number":null,"trustworthy":false}`
shows the alert on the card and stays 草稿; Start with `70` gives 監控中 and drafts 0;
observation `82` plus `GET /cdn-cgi/local/scheduled` or `POST /__niy006_test/tick`
gives 1 accepted notice; a tick with `now` after 23:59 Taipei on the appointment
date gives 已結束 and no new notice.

## Remaining manual, device and provider acceptance

Real LINE Login and handset delivery (#22), live hospital source behavior (#20),
and elapsed-time retention deletion remain outside this audit.
