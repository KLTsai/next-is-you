# NIY-014: Research documentation navigation

Status: Open

## Goal

Give contributors one tracked starting point for active implementation tickets, local-only research material, and Firstmate-local investigation reports while keeping implementation authority and private evidence clearly separated.

## Acceptance criteria

- Add a tracked top-level `research/README.md` that links to the active implementation tickets and the tickets index.
- The README names the local-only current spec at `research/private/mvp-spec-review-2026-09-27-v2.md` and its supporting/archive index at `research/private/README.md`; it says these files exist only in the captain primary checkout and are ignored/untracked.
- The README lists these Firstmate-local reports by exact absolute path and says they are not part of this repository: `/Users/kun/projects/firstmate/data/next-is-you-spec-v2-ticket-provenance-2026-09-27/report.md` (spec provenance), `/Users/kun/projects/firstmate/data/next-is-you-preflight-tickets-2026-09-27/report.md` (ticket audit), and `/Users/kun/projects/firstmate/data/next-is-you-preflight-runtime-2026-09-27/report.md` (runtime).
- The README says implementation requirements and acceptance criteria are authoritative in the active implementation tickets; the local-only spec, archived material, and investigation reports are supporting evidence unless a ticket explicitly adopts a requirement.
- Do not copy private or patient-specific content into tracked files.
- Do not move, rename, edit, or delete existing private or archived files, change tracking/privacy boundaries, alter requirements, change ticket statuses, or edit existing tickets or dirty project files.
- Keep this ticket as the sole new navigation record besides the top-level research README; run only relevant local documentation checks.
