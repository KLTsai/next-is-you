# NIY-021 hospital session and freshness findings

This note records the NIY-021 conclusion supplied to the NIY-020 worker on 2026-09-29. The original NIY-021 report was not present in this worktree or the task inbox; this summary preserves the findings provided for this task and does not replace the original report.

## Findings provided

- NTUH claims that its page updates every minute. The observations did not establish that the displayed current number is fresh.
- The observed SKH department had no clinic progress row, and SKH published no clinic-progress update interval.
- Public entry points alone do not validate live clinic-number freshness.

## Follow-up gate

Keep dynamic session options and saved patient-number prefill deferred. Do not expand NIY-020's API scope. Any API or source follow-up must wait for manual observations during active clinic sessions: at least two observations per hospital, including a displayed source timestamp where available.
