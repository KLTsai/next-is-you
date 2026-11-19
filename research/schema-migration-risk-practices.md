# Schema migration risk: how teams judge and contain it

Research completed 2026-11-19. Scope: how real-world teams classify the risk of database schema changes, review and lint them, rehearse them, take restore points, and choose between rollback and roll-forward; what a solo operator can adopt cheaply; and the SQLite and Cloudflare D1 details that change the answers for this project. Primary sources only: official docs, first-party engineering guides, tool docs, and original posts by well-known authors. Each claim is labelled **Source** (what the source says) or **Inference** (my reasoning). Nothing was run against any remote database. This is supporting evidence, not implementation authority; adopt anything from it through a GitHub issue first.

Project context used for the inference parts: [docs/CI-CD.md](../docs/CI-CD.md) says Promote "applies production migrations, deploys production, and then publishes the GitHub Release", that "migrations are forward-only: once one has applied it stays applied", and that "Rollback restores code only". Production holds very little data.

## Summary of answers

1. **Risk classes.** Tool vendors converge on three classes: additive (new table, nullable column), destructive (drop table or column: data loss), and backward-incompatible (rename, type change: old code breaks). A fourth, data-dependent, covers changes that can fail only on real data (new `NOT NULL`, new `UNIQUE`). On SQLite, a table rebuild is its own class, because it drops and recreates a table that other tables may point at.
2. **Expand/contract** (Fowler's "parallel change") is the standard way to make a backward-incompatible change safe: add the new shape, move code over, remove the old shape in a later release. GitLab and `strong_migrations` both prescribe this for dropping and renaming columns.
3. **Review and lint.** GitLab requires a dedicated database review for any schema change, with a reviewer checklist. Linters (`strong_migrations`, Squawk, Atlas) encode the risk classes as rules. Squawk is Postgres-only; Atlas has a small SQLite set; none of them knows D1's transaction rules.
4. **Rehearsal.** GitLab runs every migration against a clone of the production database before merge. Cloudflare documents exporting a D1 database "for local development or testing".
5. **Restore points.** D1 Time Travel is always on, with 30 days (Paid) or 7 days (Free) of point-in-time restore, but restore "overwrites the database in place" and cannot yet fork a copy. The useful habit is to record the bookmark or timestamp right before applying.
6. **Rollback vs roll-forward.** GitLab.com rolls forward in production and keeps `down` methods mostly for development. Fowler and Sadalage found reverse migrations not "cost effective". Redgate's Flyway docs say undo scripts are no substitute for "a proper, well tested, backup and restore strategy". Forward-only plus a restore point plus backward-compatible schema is the mainstream answer.
7. **SQLite/D1 trap.** D1 runs every migration inside a transaction, so `PRAGMA foreign_keys=OFF` (step 1 of SQLite's 12-step rebuild) has no effect. With foreign keys on, `DROP TABLE` on a parent table runs an implicit `DELETE`, which fires `ON DELETE CASCADE` on child tables. A rebuild of a parent table in D1 can therefore silently delete child rows.

---

## 1. Risk classification and expand/contract

### 1.1 Classes used by lint tools

**Source** ([Atlas lint analyzers](https://atlasgo.io/lint/analyzers)):

- Destructive: DS102 "A destructive change is reported when a table is dropped, posing a risk of data loss." DS103 "A destructive change is reported when a non-virtual column is dropped, posing a risk of data loss."
- Data-dependent: MF103 "Adding a non-nullable column to a table might fail in case the table is not empty." MF104 "Modifying nullable column to non-nullable might fail in case it contains NULL values." MF101 "Adding a unique index to a table might fail in case one of the indexed columns contain duplicate entries."
- Backward-incompatible: BC102 "Renaming a column is a backward-incompatible change that can cause errors during deployment (migration)". BC101 says the same for tables.
- SQLite-specific: LT101, "Modifying a nullable column to non-nullable without a `DEFAULT` value", with suggested fixes that recreate the table and copy rows.

**Source** ([strong_migrations README](https://github.com/ankane/strong_migrations)): the gem "Detects potentially dangerous operations" and "Prevents them from running by default". Its list includes removing a column, changing a column's type, renaming a column or table, adding foreign keys and check constraints, executing SQL directly, and backfilling data. "Renaming a column that's in use will cause errors in your application." Executing raw SQL "cannot be inspected" and is blocked until wrapped in `safety_assured`.

**Source** ([Rails migrations guide](https://guides.rubyonrails.org/active_record_migrations.html)): a migration can be "just plain irreversible; for example, it might destroy some data", in which case `down` raises `ActiveRecord::IrreversibleMigration`.

**Source** ([GitLab migration style guide](https://docs.gitlab.com/development/migration_style_guide/)): "some data migrations can't be reversed because we lose information about the state of the database before the migration."

**Inference.** A usable classification for this project, from lowest to highest risk:

| Class | Examples | What can go wrong | Can code rollback still work? |
| --- | --- | --- | --- |
| Additive | `CREATE TABLE`, `ADD COLUMN` nullable or with a constant default, `CREATE INDEX` | Almost nothing; old code ignores the new shape | Yes |
| Data-dependent | add `NOT NULL`, add `UNIQUE`, new `CHECK` | Fails on existing rows that staging did not have | Yes, if it applied |
| Backward-incompatible | rename column or table, change meaning of a value | Old code (and the code running during deploy) breaks | No, unless done as expand/contract |
| Destructive or data-bearing | `DROP TABLE`, `DROP COLUMN`, `UPDATE`/`DELETE` backfills | Data is gone; only a restore brings it back | Code may run, but data does not return |
| SQLite table rebuild | 12-step rebuild to change a constraint or column type | Everything above, plus foreign key side effects (section 7) | Depends on what changed |

### 1.2 Expand/contract (parallel change)

**Source** ([Martin Fowler, ParallelChange](https://martinfowler.com/bliki/ParallelChange.html)): "Parallel change, also known as expand and contract, is a pattern to implement backward-incompatible changes to an interface in a safe manner, by breaking the change into three distinct phases: expand, migrate, and contract." "In the expand phase you augment the interface to support both the old and the new versions." Then "you perform the contract phase to remove the old version". And: "Most database refactorings follow the parallel change pattern, where the migrate phase is the transition period between the original and the new schema".

**Source** ([Fowler and Sadalage, Evolutionary Database Design](https://martinfowler.com/articles/evodb.html)): changes that break existing access code are "destructive changes"; teams handle them with "a period of time when the database supports both the old access pattern and the new ones simultaneously". "Our usual rule is to make each database change as small as possible".

**Source** ([GitLab, Avoiding downtime in migrations](https://docs.gitlab.com/development/database/avoiding_downtime_in_migrations/)): dropping a column takes "three steps in three releases": "first, ignore the column (release M), then, drop it in the next release (release M+1)", then remove the ignore rule. The reason: "running GitLab processes expect these columns to exist", and "an application might continue to use the old column names during or after a database migration."

**Source** ([strong_migrations README](https://github.com/ankane/strong_migrations)): for a rename, create a new column, write to both, backfill, move reads, stop writing to the old column, then drop it.

**Inference.** Expand/contract is what makes "Rollback restores code only" safe: after the expand step, the previous version still works against the new schema. The contract step is the only destructive one, and it can wait until nobody would roll back past it.

## 2. Review checklists

**Source** ([GitLab database review guidelines](https://docs.gitlab.com/development/database_review/)): review is required for "Changes that touch the schema or perform data migrations". Reviewers "must review the output of both migrating (`db:migrate`) and rolling back (`db:rollback`)". For data migrations the author must describe how changes could be reverted if the migration is not reversible, label data deletion `~data-deletion`, and describe user impact of an error. The reviewer checklist includes checking that the testing job on a production clone passes, that the schema dump "contains only changes related to migrations in this merge request", that migrations run in a transaction, and migration timing.

**Source** ([GitLab migration style guide](https://docs.gitlab.com/development/migration_style_guide/)): "Your migration must be reversible." "In your migration, add a comment describing how the reversibility of the migration was tested." Irreversible migrations still need a `down` that is a no-op with a comment explaining why. "Migrations always must be written in such a way to avoid downtime." Regular migrations should take 3 minutes or less.

**Inference.** The parts of GitLab's checklist that do not depend on scale are: name the risk class, say what happens to data, say what happens if code is rolled back, and show the migration actually ran. The timing and lock rules are about large Postgres tables and do not apply here.

## 3. Automated linting

**Source** ([Squawk docs](https://squawkhq.com/docs/)): "a linter for Postgres migrations". Example rules: `constraint-missing-not-valid`, `disallowed-unique-constraint`. The docs do not mention SQLite.

**Source** ([Atlas lint analyzers](https://atlasgo.io/lint/analyzers)): the DS, MF and BC analyzers above, plus one SQLite check (LT101).

**Source** ([strong_migrations README](https://github.com/ankane/strong_migrations)): Rails-only; it inspects Active Record migration calls, not plain SQL files.

**Inference.** None of these fits a folder of plain `.sql` files run by Wrangler on D1 without adopting a new toolchain: Squawk is Postgres, `strong_migrations` is Rails, and Atlas would need its own migration directory format and still would not know D1's transaction and foreign key behavior (section 7). The rules themselves are short. A grep-level check in the existing `scripts/check_migrations.py` for `DROP TABLE`, `DROP COLUMN`, `RENAME`, `DELETE`, `UPDATE`, and `PRAGMA` would flag the same classes, and the review then decides.

## 4. Rehearsal on production-like data

**Source** ([GitLab database review guidelines](https://docs.gitlab.com/development/database_review/)): the author triggers `db:gitlabcom-database-testing`, which "runs migrations on a Database Lab clone and posts runtimes, warnings, and size changes to the MR."

**Source** ([Cloudflare D1, import and export data](https://developers.cloudflare.com/d1/best-practices/import-export-data/)): `npx wrangler d1 export <database_name> --remote --output=./database.sql` exports a database; you can export one table, or only schema or only data. You might export "for local development or testing". "A running export will block other database requests." Export does not work with virtual tables.

**Source** ([Cloudflare D1, local development](https://developers.cloudflare.com/d1/best-practices/local-development/)): local D1 runs "the same version of D1 as Cloudflare runs globally", and "Migrations can be run locally as part of your CI/CD setup by passing the `--local` flag", for example `wrangler d1 migrations apply your-database --local`.

**Source** ([Fowler and Sadalage](https://martinfowler.com/articles/evodb.html)): sample data "also allows to test our migrations as we alter the schema of the database", and "you should try to introduce real data from the very first iteration of your project".

**Inference.** This project already rehearses every migration on staging D1 before Promote ([CI-CD.md](../docs/CI-CD.md): "the check on staging is the last point where stopping costs nothing"). What staging does not prove is that production's rows satisfy a data-dependent change, or that a rebuild preserves child rows. For a destructive or rebuild migration, a local rehearsal on a production export answers that in minutes. The export contains real user data, so it must stay outside the repository and be deleted afterwards ([AGENTS.md](../AGENTS.md): "never put credentials or patient data in repository artifacts"). A schema-only export is safe to keep and confirms production's schema matches what the migration assumes.

## 5. Backups and restore points

**Source** ([D1 Time Travel](https://developers.cloudflare.com/d1/reference/time-travel/)): Time Travel is "D1's approach to backups and point-in-time-recovery". "It is always on." Restore goes back "up to 30 days in the past (Workers Paid plan) or 7 days (Workers Free plan)". Get a bookmark with `wrangler d1 time-travel info YOUR_DATABASE` (add `--timestamp` for a past point). Restore with `wrangler d1 time-travel restore YOUR_DATABASE --timestamp=UNIX_TIMESTAMP` or `--bookmark=`. Restoring "overwrites the database in place"; in-flight queries are cancelled. "The restore operation will return a bookmark that allows you to undo and revert the database." "Time Travel does not yet allow you to clone or fork an existing database to a new copy."

**Source** ([Wrangler D1 commands](https://developers.cloudflare.com/workers/wrangler/commands/d1/)): for `d1 migrations apply`, "If applying a migration results in an error, this migration will be rolled back", and "After applying, a backup will be captured." In CI the confirmation prompt is skipped but "the backup will still be captured."

**Source** ([GitLab migration style guide](https://docs.gitlab.com/development/migration_style_guide/)): "On GitLab Self-Managed, we advise users to restore the backup which was created before the upgrade process started."

**Source** ([Flyway, undo migrations](https://documentation.red-gate.com/fd/undo-migrations-273973334.html)): recommends "a proper, well tested, backup and restore strategy".

**Inference.**

- Who takes the backup: on D1 nobody has to; Time Travel records continuously. What is missing is the restore point's identity. Recording the bookmark (or Unix timestamp) right before Promote turns "restore to roughly when?" into one command.
- A restore is all-or-nothing for the whole database. It also discards every write made after the bookmark (reminders sent, settings changed). So restore is for data loss, not for a schema that merely does not match old code; for the latter, roll forward.
- Because Time Travel cannot fork, there is no documented way to restore into a scratch database and inspect it first. A local export before the Promote fills that gap when a migration is destructive.

## 6. Rollback vs roll-forward

**Source** ([GitLab migration style guide](https://docs.gitlab.com/development/migration_style_guide/)): "On GitLab production environments, if a problem occurs, a roll-forward strategy is used instead of rolling back migrations using `db:rollback`." "The `down` method is used primarily in the development environment."

**Source** ([Fowler and Sadalage](https://martinfowler.com/articles/evodb.html)): on reverse migrations, "We haven't found this to be cost effective and beneficial enough to try all the time." The main approach is to keep the database working with both old and new application versions during a transition.

**Source** ([Flyway, undo migrations](https://documentation.red-gate.com/fd/undo-migrations-273973334.html)): "you should take care if you have destructive changes (drop, delete, truncate etc) in your deployment"; "failed versioned migrations on databases without DDL transactions may require a different approach"; and instead "maintain backwards compatibility between the DB and all versions of the code currently deployed in production".

**Source** ([Django migrations](https://docs.djangoproject.com/en/5.2/topics/migrations/)): "A migration is irreversible if it contains any irreversible operations. Attempting to reverse such migrations will raise `IrreversibleError`".

**Source** ([Cloudflare D1 migrations](https://developers.cloudflare.com/d1/reference/migrations/)): the documented commands are create, list, and apply; there is no down migration.

**Inference.** Why forward-only wins: a down migration cannot restore dropped data, is rarely exercised so it is the least tested code at the worst moment, and D1 does not support one anyway. The working pattern is three parts: (1) keep each migration backward-compatible with the version before it, so code rollback is safe; (2) when something is wrong, write a new forward migration; (3) keep a restore point for the case where data was lost. This is the policy [CI-CD.md](../docs/CI-CD.md) already describes; what it does not yet have is a per-migration statement of which class the migration is and therefore whether code rollback past it is safe.

## 7. SQLite and D1 specifics

### 7.1 What SQLite's ALTER TABLE can do

**Source** ([SQLite ALTER TABLE](https://www.sqlite.org/lang_altertable.html)): "it can be renamed; a column can be renamed; a column can be added to it; or a column can be dropped from it." `ADD COLUMN` restrictions include: "The column may not have a PRIMARY KEY or UNIQUE constraint", "If a NOT NULL constraint is specified, then the column must have a default value other than NULL", and a `REFERENCES` column with foreign keys enabled "must have a default value of NULL". `DROP COLUMN` fails if the column is a primary key, unique, indexed, in a foreign key, or "appears in a trigger or view".

Anything else (changing a constraint, a type, a `CHECK`, a foreign key) needs a table rebuild.

### 7.2 The 12-step rebuild

**Source** ([SQLite ALTER TABLE, section 7](https://www.sqlite.org/lang_altertable.html)), verbatim steps:

1. "If foreign key constraints are enabled, disable them using PRAGMA foreign_keys=OFF."
2. "Start a transaction."
3. "Remember the format of all indexes, triggers, and views associated with table X."
4. "Use CREATE TABLE to construct a new table "new_X" that is in the desired revised format of table X."
5. "Transfer content from X into new_X using a statement like: INSERT INTO new_X SELECT ... FROM X."
6. "Drop the old table X: DROP TABLE X."
7. "Change the name of new_X to X using: ALTER TABLE new_X RENAME TO X."
8. Recreate indexes, triggers, and views.
9. Drop and recreate views affected by the change.
10. "If foreign key constraints were originally enabled then run PRAGMA foreign_key_check to verify that the schema change did not break any foreign key constraints."
11. "Commit the transaction started in step 2."
12. "If foreign keys constraints were originally enabled, reenable them now."

And: "Caution: Take care to follow the procedure above precisely." Renaming the old table first and then creating the new one "might corrupt references to that table in triggers, views, and foreign key constraints."

**Source** ([Django migrations](https://docs.djangoproject.com/en/5.2/topics/migrations/)): Django emulates SQLite alterations by creating a new table, copying, dropping, and renaming, and warns "it can be slow and occasionally buggy".

### 7.3 Foreign keys during a rebuild, and why D1 is different

**Source** ([SQLite foreign keys](https://www.sqlite.org/foreignkeys.html)): "It is not possible to enable or disable foreign key constraints in the middle of a multi-statement transaction ... Attempting to do so does not return an error; it simply has no effect." And: "If foreign key constraints are enabled when it is prepared, the DROP TABLE command performs an implicit DELETE to remove all rows from the table before dropping it. The implicit DELETE does not cause any SQL triggers to fire, but may invoke foreign key actions or constraint violations."

**Source** ([D1 foreign keys](https://developers.cloudflare.com/d1/sql-api/foreign-keys/)): "By default, D1 enforces that foreign key constraints are valid within all queries and migrations." "Because D1 runs every query inside an implicit transaction, user queries cannot change this during a query or migration." `PRAGMA defer_foreign_keys = on` "allows you to violate foreign key constraints temporarily (until the end of the current transaction)".

**Source** ([D1 migrations](https://developers.cloudflare.com/d1/reference/migrations/)): "When applying a migration, you may need to temporarily disable foreign key constraints", using `PRAGMA defer_foreign_keys = true`.

**Source** ([SQLite PRAGMA](https://www.sqlite.org/pragma.html)): with `defer_foreign_keys` on, "enforcement of all foreign key constraints is delayed until the outermost transaction is committed." It "is automatically switched off at each COMMIT or ROLLBACK". Caution: setting it to 0 "resets the internal foreign-key tracking state ... so that it becomes possible to commit the current transaction even if there are foreign key violations."

**Source** ([SQLite foreign keys](https://www.sqlite.org/foreignkeys.html)): when a parent row is deleted the sequence includes "Perform any required foreign key actions"; only `RESTRICT` is singled out as acting immediately "Even if the foreign key constraint it is attached to is deferred".

**Inference.**

- Step 1 of the 12-step procedure cannot be done in D1. `defer_foreign_keys` is the documented substitute, and it defers the constraint check only.
- If the table being rebuilt is the parent of a child table with `ON DELETE CASCADE` or `ON DELETE SET NULL`, step 6 (`DROP TABLE X`) deletes or nulls the child rows, deferral or not, and the migration commits cleanly. Staging with few or no child rows will not show it. This is the single highest-risk migration shape for this project.
- Rebuilding a child table (one that only holds `REFERENCES`) is much safer: dropping it fires no actions on others, and with `defer_foreign_keys` the copy can be checked by `PRAGMA foreign_key_check` before commit.
- For a parent-table rebuild, options are to rebuild the children in the same migration (copy them out and back), to avoid the rebuild by an expand/contract alternative (new table plus a later switch), or at minimum to rehearse on a production export and compare child row counts before and after.

## 8. Lightweight process for a solo operator

**Source** ([DORA, streamlining change approval](https://dora.dev/capabilities/streamlining-change-approval/)): heavyweight external approval has "a negative impact on software delivery performance", and "no evidence was found to support the hypothesis that a more formal, external review process was associated with lower change fail rates". The recommended substitute is review at check-in "supplemented by automation to detect, prevent, and correct bad changes early".

**Source** ([Fowler and Sadalage](https://martinfowler.com/articles/evodb.html)): "make each database change as small as possible"; developers consult DBAs on significant schema changes, and "the DBA has to make herself approachable and available".

**Source** ([GitLab migration style guide](https://docs.gitlab.com/development/migration_style_guide/)): the reversibility note lives as "a comment" in the migration itself.

**Inference.** The cheap equivalent of GitLab's review is a header comment in each migration file that states its risk class and its rollback consequence, written by the author (often an agent) and read by the captain before merge and again before Promote. The "DBA" role can be a fixed question list rather than a person.

---

## What fits this project

Proportionate to one captain, D1, forward-only migrations, little production data:

1. **A risk header in every migration file.** Three lines at the top: class (additive, data-dependent, incompatible, destructive, rebuild), "code rollback to the previous version is safe: yes/no, because ...", and "data that can be lost: none / ...". Cost: a minute per migration; optionally a check in `scripts/check_migrations.py` that the header exists. It makes the existing Rollback step ("read them, and roll back only if the earlier code works") a read of three lines.
2. **A grep-level danger flag in the existing migration check.** Flag `DROP TABLE`, `DROP COLUMN`, `RENAME`, `DELETE`, `UPDATE`, and `PRAGMA` so that the class in the header cannot be silently wrong, and require the header to say destructive or rebuild when they appear. Cost: tens of lines in a script that already exists; no new tool.
3. **Expand/contract for anything incompatible.** Split renames, drops, and rebuilds into an additive migration now and a contract migration in a later version, so the version in production minus one always runs on the current schema. Cost: one extra small PR and release per such change.
4. **Record a Time Travel bookmark before every Promote that applies a migration.** Run `wrangler d1 time-travel info <db>` (read-only) and keep the bookmark in the Promote run summary or the release notes. Cost: one command; zero storage cost since Time Travel is always on. Remember restore overwrites everything after it, so it is for data loss only.
5. **For destructive or parent-table rebuild migrations only, a local rehearsal on a production export.** Export to a path outside the repo, `migrations apply --local` against it, compare row counts of the table and its child tables, then delete the export. Cost: about ten minutes, a few times a year. It is the only check that catches the cascade trap in section 7.3.

What to skip, and why:

- **Down migrations.** D1 has none, they cannot bring back dropped data, and GitLab and Fowler both report they are not worth it in production.
- **Squawk, `strong_migrations`, Atlas lint.** Wrong engine or wrong framework, and none models D1's implicit transaction. A grep in the existing check covers the same rule classes.
- **A production-clone rehearsal for every migration.** Staging already applies every migration first; additive migrations gain nothing from real rows. Reserve the export rehearsal for the destructive and rebuild classes.
- **Separate manual backups or exports as the main safety net.** Time Travel already provides 7 to 30 days of point-in-time restore; a copied export of real user data is a privacy liability to keep around.
- **Lock, timing, and batching rules** (GitLab's 3-minute limit, concurrent indexes). They exist for large Postgres tables; production here is tiny.

## What issue #111 adopted

The captain's decisions (2026-11-19) differ from the list above in three places. The procedure itself lives in [docs/CI-CD.md](../docs/CI-CD.md#promoting-a-version-that-applies-migrations).

- **Rehearsal (item 5).** No production export is copied anywhere: it would put LINE identifiers on a laptop. Staging is restored with Time Travel to before the migration, seeded with synthetic rows that cover every shape, and CI applies the migration; every row is then compared. The trigger is wider than item 5: `data-dependent` migrations are rehearsed too, because equal counts cannot catch a wrong transformation.
- **Header (item 1).** Required from `0008` on; `0001` to `0007` stay unedited, because applied migrations are never edited.
- **Restore point (item 4).** Recorded by hand as a release PR comment (time, bookmark, per-table counts), not by the Promote workflow.
