# Complete local service rehearsal

This journey uses a real local Worker, D1 and SQLite Durable Object, with the
existing synthetic login, fake hospital reader and fake LINE transport. It does
not contact LINE or a hospital, deploy, or prove handset delivery. The lightweight
`dev:local` shell has no D1/DO and cannot replace this rehearsal.

## First-time preparation

From the repository root, use the CI toolchain: Node 24, Python 3.13, and uv
0.12.3. Vite 7.3.6 requires Node `^20.19.0` or `>=22.12.0`; Python packages
require Python 3.13 or newer. The complete rehearsal was also validated on
macOS Apple Silicon with Node 24.18.0, Python 3.14.6, and uv 0.12.19. CI runs
on Ubuntu; other local hosts have not been validated for this journey.

```sh
npm ci
uv sync --group dev --locked
```

For automated browser regressions only, also run `uv run playwright install chromium`.
No real credentials or environment template are needed for this journey.
`workers-py` 1.17.4 supplies `pywrangler`; `workers-runtime-sdk` 1.9.0 provides
the Worker runtime support. Worker commands prepare generated compatibility
modules in the ignored `python_modules/` mirror, with local tooling state in
`.venv-workers/`. These are generated from the locked project dependencies;
do not edit or delete them as routine setup.

To intentionally update dependencies, change the relevant manifest and use
`npm install` for npm dependencies or `uv lock` for Python dependencies. Review
the manifest and lockfile changes, then install with the locked commands above.
Do not run those installation commands again just to repeat an unchanged setup.

## Start and repeat

```sh
npm run dev:rehearsal
```

Open <http://127.0.0.1:8787>. The command builds current assets, applies pending
local migrations and serves in the foreground. Both migration and serving use
`.wrangler/manual-rehearsal`; repeating the command preserves the same dataset,
including D1 events and the DO's fake-request log. It does not reinstall Node
dependencies, seed recipients, or reset data. uv uses the existing locked environment
when dependencies are unchanged.

The rehearsal does not load the repository-root `.env`; see the [README's
developer guidance](../README.md#for-developers) for the current local
development entrypoints.

For an explicitly separate empty fixture dataset or a busy port, native settings
can be selected before starting:

```sh
NIY_REHEARSAL_STATE=.wrangler/my-rehearsal NIY_REHEARSAL_PORT=8788 npm run dev:rehearsal
```

Keep the same state location and port when restarting that journey. Adjust the
URLs below if using another port. Do not point this command at a live dataset.
The send gate's alarm drives each tick ([ADR 0005](adr/0005-scheduler-tick-runs-from-a-durable-object-alarm.md)).
Locally it fires on its own timer, as it does when deployed: every minute while a
visit is active or stopping, every 5 minutes otherwise. Wrangler does not run Cron
on a local timer. To run a tick right away, `POST /__niy006_test/alarm`. No extra
scheduler process is needed.

## Prepare the synthetic recipient once

A fresh dataset has no consented recipient. In a second terminal, use the existing
local controls to create the synthetic fixture and its setup visit:

```sh
curl --fail-with-body -X POST http://127.0.0.1:8787/__niy006_test/observation \
  -H 'content-type: application/json' \
  --data '{"current_number":70,"trustworthy":true}'

curl --fail-with-body -X POST http://127.0.0.1:8787/__niy006_test/seed \
  -H 'content-type: application/json' \
  --data "$(uv run python -c 'import json; from datetime import datetime, timedelta, timezone; now = datetime.now(timezone.utc); print(json.dumps({"visit_id": "rehearsal-setup", "recipient_id": "rehearsal-recipient", "visit_day": (now + timedelta(days=1)).date().isoformat(), "patient_number": 85, "now": now.isoformat()}))')"
```

Sign in with **本機合成測試登入**, then select **停止提醒** on the setup visit.
Expected: **監控中** becomes **已停止** after confirmation, and **Synthetic recipient**
is available in the form. No notification has been sent. This fixture is not real
consent or identity enrollment. Skip preparation on subsequent starts; do not
reseed or clear the outbox to repeat the journey.

## Save, edit and restart

1. In the UI, create a draft for tomorrow with **臺大醫院總院**, department `SYN`,
   clinic `SYN-1`, session `afternoon`, patient number `85` and **Synthetic recipient**.
   Expected: **已儲存草稿 1**, initially collapsed; saving does not start reminders.
   When expanded, the saved draft shows `掛號序號 85` with the hospital, department,
   clinic and session so the organizer can identify the draft. These are synthetic
   codes, not verified clinic availability.
2. Use **展開草稿**, then **修正草稿**. The authorized correction flow prefills `85`;
   the saved draft card also shows that synthetic number for organizer-only local
   identification. Change a value and use **取消修正**: saved values must stay
   unchanged. Edit again, save, and verify the saved result. **收合草稿** and
   **展開草稿** must preserve the draft and keyboard focus.
3. Press Ctrl-C in the service terminal and run `npm run dev:rehearsal` again.
   Reload the same URL; sign in again if the session expired. The same draft and
   edits remain. Do not prepare the recipient again or change the state location.

## Start, one fake reminder and duplicate ticks

To observe a failed Start, set the source unavailable:

```sh
curl --fail-with-body -X POST http://127.0.0.1:8787/__niy006_test/observation \
  -H 'content-type: application/json' \
  --data '{"current_number":null,"trustworthy":false}'
```

Select **重新檢查並開始提醒**. Expected: pending recheck, then an unavailable
reason shown as an alert on the draft card; state remains **草稿**. The alert
clears when Start is retried or after a draft edit is saved successfully. Restore
the trusted observation at `70` using the first control above, then Start again.
Expected: **監控中** after API confirmation.
The synthetic reader returns a fresh observation matching the visit scope; it
does not prove real hospital freshness.

For patient number `85`, set a near observation at `82` and run the alarm now:

```sh
curl --fail-with-body -X POST http://127.0.0.1:8787/__niy006_test/observation \
  -H 'content-type: application/json' \
  --data '{"current_number":82,"trustworthy":true}'
curl --fail-with-body -X POST http://127.0.0.1:8787/__niy006_test/alarm
curl --fail-with-body -X POST http://127.0.0.1:8787/__niy006_test/snapshot \
  -H 'content-type: application/json' --data '{}'
```

Expected for this first in-window read: one `near` event, `outcome: accepted`,
`attempt_count: 1`, and one fake `line_requests` entry with the same `retry_key`
and `outbox_persisted: true`. If the saved patient number changed, choose a trusted
current number 1-3 below it. The snapshot may include earlier events when reusing
a dataset; compare the selected visit/event rather than assuming the global
count always starts at zero.

The near reminder repeats as the called number moves inside the window (the 3
numbers before the patient number). Set the observation to `83`, invoke the hook,
and snapshot again: a second `near` event is created because the number moved
from `82` to `83`. Each move inside the window that reaches a number different
from the previous scheduled read sends another reminder (forward, backward, or
re-entering after leaving), up to 20 per visit and recipient; the target number
itself and numbers past it send none. Each reminder is its own event with its own
`retry_key`.

Invoke the same hook again at the same observed number. Stop the process with
Ctrl-C, restart with the same command, then invoke it again and inspect the
snapshot. Reading the same number creates no further event: the existing event
IDs, retry keys, outcomes, attempt counts and request history must remain,
without an additional request. Both D1 history and the DO fake-request log are
durable; a blank/reset request counter is not deduplication evidence. UI refresh
shows the saved lifecycle and notification summary.

Select **停止提醒**. Expected: pending stop, then **已停止** only after confirmation.
The stopped reminder card keeps the same `掛號序號` row as the saved draft.
Further ticks cannot begin a new request for that visit. A request that began
before Stop may settle before confirmation; Stop is not a retraction of it.

## Recovery and stopping

UI **停止提醒** closes a logical reminder. Ctrl-C stops the local service process;
it does not close active visits. A restarted active visit can be evaluated again,
while an already accepted logical event stays deduplicated.

If preparation/build/migrations fail, the command stops before serving. Fix the
reported prerequisite and repeat the same command. If the port is busy, stop
only your own foreground session or select another port. If Start fails, correct
the source control and recheck; do not assume failure means active. If Stop fails,
the visit remains active until the service confirms it: retry and inspect state.

For a recovery hold or unknown notification result, preserve the dataset and
retry identity and inspect the snapshot. Keep sending held until an authorized
operator has reconciled restored rows with notification history; the existing
organizer resume API requires explicit reconciliation confirmation. Stop this
local process while investigating. Do not clear D1/DO or blindly resume. Unknown
outcomes, bounded retries, both send/Stop orderings, authorization, consent,
withdrawal and recovery holds remain covered by the existing regression tests;
you need not provoke these faults or generate new data every manual run.

After 23:59 Taipei time on the appointment date, the next scheduled run expires
an Active reminder and sends no further notices. Before automatic cleanup, choose
**修正後重新啟動** on that expired reminder, update its date or appointment details,
and save. It returns to **已儲存草稿** as the same reminder; use
**重新檢查並開始提醒** to recheck the source before it can become **監控中**
again. Correction by itself must not add another `near` event. Confirmed
**停止提醒** ends monitoring and all later notifications; a notice already in
flight may settle before Stop is confirmed. After the first successful start,
existing recipients can be removed from the reminder card, but the frozen roster
cannot accept new recipients. At least one recipient must remain. When only one
remains, its Remove button is disabled because reminders need a recipient to keep
monitoring or restart later.

Drafts and expired reminders are cleaned up 48 hours after the appointment cutoff
at 23:59 Taipei time; stopped reminders are cleaned up 48 hours after Stop. A
genuinely new fixture journey can use an explicit separate state directory,
without deleting the old one. Live LINE, hospital access and deployment remain
separate [pre-live gates](PRE-LIVE-CHECKLIST.md).
