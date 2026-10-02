# NIY-020 local manual acceptance

Use only the local NIY-006 test binding, its synthetic recipient, fake hospital observation source, and fake LINE transport. Do not use patient data, real LINE accounts, live hospital access, credentials, or deployment.

Start the local test app using the **Complete local service rehearsal** setup in [README.md](../README.md). This journey uses `wrangler.niy006.test.jsonc` and stays on loopback.

## Draft and correction

1. Sign in with **本機合成測試登入**. Expected: the reminder form and synthetic recipient list appear. The login is provided only by the local test binding.
2. Create a draft using a future date, **臺大醫院總院**, department `SYN`, clinic `SYN-1`, session `afternoon`, patient number `85`, and **Synthetic recipient**. Expected: the form says that creating a draft does not start monitoring or send notifications. After saving, the list shows **草稿**, `掛號序號 85`, and the API supplied source link; no hospital request occurs.
3. Under setup, confirm **已儲存草稿** shows the current count and starts collapsed. Use the keyboard or mouse on **展開草稿** and **收合草稿**; the control's expanded state must track visibility. Expected: draft cards, including the visible synthetic patient number, remain unchanged when hidden and shown.
4. Choose **修正草稿**. Expected: date, hospital, department, clinic, session, and selected recipient are prefilled from the visit projection, and the selected draft's saved patient number `85` is fetched through the authorized correction flow and prefilled.
5. Change the department to `UNSAVED`, then select **重新整理**. Expected: the unsaved value remains in the form and the list still shows the saved department `SYN`.
6. Choose **取消修正**. Expected: the form returns to new-draft mode, the unsaved value is gone, and the saved visit remains unchanged.
7. Edit again, select `evening`, keep the prefilled synthetic patient number `85`, then select **儲存草稿**. Expected: the list shows **晚診（evening）** and the saved-change message says to recheck and start. Saving updates a draft only; it does not start monitoring.
8. Observe the session field's note. The three codes are accepted by the current API, not a clinic/date availability list. Do not infer that morning, afternoon, or evening is actually offered. The [NIY-021 findings summary](../research/NIY-021-findings-summary.md) records the evidence and follow-up gate.

## Recheck, start, and stop

1. With the fake observation unavailable, select **重新檢查並開始提醒**. Expected: a pending recheck indicator appears, the service returns the unavailable error, and the visit remains **草稿**.
2. Set the fake source to a trusted synthetic observation using the local test route from the [rehearsal guide](LOCAL-REHEARSAL.md#start-one-fake-reminder-and-duplicate-ticks). Select **重新檢查並開始提醒** again. Expected: the API confirms activation and the list changes to **監控中**. Check the patient-number row during active and stopped states using the same guide.
3. While active, verify **停止提醒** is visible and the copy explains that confirmed Stop ends future checks and notifications. Select it. Expected: the button shows a pending state while the request is in flight; the UI does not say the visit is stopped until the API projection reports **已停止**. If the request fails, the visit remains active and the error is shown.
4. After **已停止**, verify the Stop button is gone. Select **修正後重新檢查**. Expected: the correction form is clearly labeled, existing projected settings and recipient remain selected, and saving returns the same visit with edited values to **已儲存草稿**. Its stopped card leaves the reminder list; the draft must be checked again before Start.
5. Start that saved draft with a trusted synthetic observation. Expected: it leaves **已儲存草稿** and appears exactly once in the active reminder list, with its patient number still visible.

The local fake LINE request log may be inspected through the documented NIY-006 test snapshot. It must contain only synthetic recipient data. The checklist does not assert handset delivery.
