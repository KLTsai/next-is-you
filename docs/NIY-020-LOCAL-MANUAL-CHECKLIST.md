# NIY-020 local manual acceptance

Use only the local NIY-006 test binding, its synthetic recipient, fake hospital observation source, and fake LINE transport. Do not use patient data, real LINE accounts, live hospital access, credentials, or deployment.

Start the local test app using the **Local UI acceptance (NIY-007)** setup in [README.md](../README.md). This journey uses `wrangler.niy006.test.jsonc` and stays on loopback.

## Draft and correction

1. Sign in with **本機合成測試登入**. Expected: the reminder form and synthetic recipient list appear. The login is provided only by the local test binding.
2. Create a draft using a future date, **臺大醫院總院**, department `SYN`, clinic `SYN-1`, session `afternoon`, patient number `85`, and **Synthetic recipient**. Expected: the form says that creating a draft does not start monitoring or send notifications. After saving, the list shows **草稿** and the API supplied source link; no hospital request occurs.
3. Choose **修正草稿**. Expected: date, hospital, department, clinic, session, and selected recipient are prefilled from the visit projection, and the selected draft's saved patient number `85` is fetched through the authorized correction flow and prefilled. The general visit list does not expose the patient number.
4. Change the department to `UNSAVED`, then select **重新整理**. Expected: the unsaved value remains in the form and the list still shows the saved department `SYN`.
5. Choose **取消修正**. Expected: the form returns to new-draft mode, the unsaved value is gone, and the saved visit remains unchanged.
6. Edit again, select `evening`, keep the prefilled synthetic patient number `85`, then select **儲存草稿**. Expected: the list shows **晚診（evening）** and the saved-change message says to recheck and start. Saving updates a draft only; it does not start monitoring.
7. Observe the session field's note. The three codes are accepted by the current API, not a clinic/date availability list. Do not infer that morning, afternoon, or evening is actually offered. The [NIY-021 findings summary](../research/NIY-021-findings-summary.md) records the evidence and follow-up gate.

## Recheck, start, and stop

1. With the fake observation unavailable, select **重新檢查並開始提醒**. Expected: a pending recheck indicator appears, the service returns the unavailable error, and the visit remains **草稿**.
2. Set the fake source to a trusted synthetic observation using the local test route from the README. Select **重新檢查並開始提醒** again. Expected: the API confirms activation and the list changes to **監控中**.
3. While active, verify **停止提醒** is visible and the copy explains that confirmed Stop ends future checks and notifications. Select it. Expected: the button shows a pending state while the request is in flight; the UI does not say the visit is stopped until the API projection reports **已停止**. If the request fails, the visit remains active and the error is shown.
4. After **已停止**, verify the Stop button is gone. Select **修正後重新檢查**. Expected: the correction form is clearly labeled, existing projected settings and recipient remain selected, and saving returns the same visit to **草稿** for a fresh Start check.

The local fake LINE request log may be inspected through the documented NIY-006 test snapshot. It must contain only synthetic recipient data. The checklist does not assert handset delivery.
