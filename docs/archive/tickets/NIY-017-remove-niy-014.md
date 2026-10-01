# NIY-017: Remove the unrelated NIY-014 ticket

Status: Complete

## Goal

Remove NIY-014, which was opened for research navigation unrelated to the core app, while preserving useful independent research navigation and the valid repository-organization review in NIY-015.

## Conflict checks

- Confirm no other ticket depends on NIY-014 or requires its work.
- Keep NIY-015 open and intact as the repository-organization review; remove only its mistaken related-ticket link to NIY-014.
- Keep `research/README.md` as an independent navigation page. Its useful links and privacy boundary do not require NIY-014 to remain a ticket.
- Preserve `research/private/`, archives, caches, app code, secrets, and all unrelated paths.

## Acceptance criteria

- Delete `tickets/NIY-014-research-navigation.md` and remove its row from `tickets/README.md`.
- Remove the stale NIY-014 related-ticket link from `tickets/NIY-015-repository-structure-review.md` without changing NIY-015's status, requirements, or decisions.
- Correct NIY-014-specific claims in `tickets/REPOSITORY-STRUCTURE-INVENTORY.md`: retain the `research/` keep recommendation while describing the tracked README directly, and remove the row for the deleted NIY-014 ticket.
- Leave `research/README.md` and private or archived material unchanged.
- Check the ticket graph and all tracked NIY-014 references. The only remaining mention is this historical removal rationale in NIY-017.
- Run relevant Markdown and link checks and `git diff --check`.
