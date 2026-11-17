---
status: accepted
---

# The hospital list lives in code, and the database does not enumerate hospitals

`migrations/0001_initial.sql` limited `visits.hospital` with `CHECK (hospital IN ('ntuh-main', 'shin-kong-taipei'))`. SQLite and D1 cannot alter a CHECK constraint, so registering any third hospital meant rebuilding the `visits` table, the table that holds every stored reminder, and a rebuild can lose rows if it goes wrong.

We decided on 2026-11-17, while specifying #45 and #95, that:

- The list of hospitals lives in code, in `src/next_is_you/hospital_registry.py`. A hospital is usable only because a reader exists for it. A database row would not make it usable, and two lists can disagree.
- The database does not enumerate hospitals. Whether a stored hospital id is valid is decided by the registry. Every write path that accepts a hospital id validates it against the registry and rejects an unknown id with no write. An id the registry does not know, found in storage, reads as unavailable and sends nothing.
- Clinic schedules are never stored. They are read live from the hospital and discarded.
- A hospital is retired by keeping its registry entry and removing its reader, never by deleting the entry. Stored reminders then keep a display name and fail closed.

Migration `0007_visits_hospital_unconstrained.sql` rebuilds `visits` without the CHECK. Issue #107 carries the scope and acceptance, and #95 the original problem.

## Considered options

- **A `hospitals` table with a foreign key from `visits`.** Rejected: it adds a second list that must agree with the registry, and a row would not make a hospital usable because only a reader does. Adding a hospital would still need a data migration, and a missing row would block writes for a hospital the code already supports.
- **Keep the CHECK and rebuild `visits` for each new hospital.** Rejected: every new hospital would put every stored reminder at risk in a table rebuild, which is the cost this decision exists to remove.

## Consequences

- Adding a hospital is a reader module and one registry entry. It needs no migration and no enum edit.
- The registry is the only authority on hospital ids, so the API and the send gate must validate against it. The test that an unknown id is rejected with no write guards this.
- Removing a registry entry orphans stored visits, so the rule is to retire a hospital by removing its reader and keeping the entry.
- Rows already stored keep their ids. A migration that rebuilds `visits` must copy the dependent `visit_recipients` and `outbound_events` rows aside first, because dropping `visits` cascades to them.
